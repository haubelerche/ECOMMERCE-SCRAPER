import os
import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import requests
from dotenv import load_dotenv
from typing import List, Literal, Optional
import random

from supabase_client import SupabaseClient
from scraper.tiki_scraper import scrape_tiki
from scraper.tiki_category_scraper import (
    scrape_category,
    scrape_all_electronics,
    ELECTRONICS_CATEGORIES,
)

load_dotenv()

# Centralized CORS origins: can be overridden by env CORS_ORIGINS (comma-separated)
DEFAULT_CORS = "http://localhost:5173,https://insightlytics-chatbot.vercel.app"
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", DEFAULT_CORS).split(",") if o.strip()]

app = FastAPI()

# Add CORS middleware to allow frontend connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Supabase client for storing scraped reviews
try:
    supabase_client = SupabaseClient()
except Exception as e:
    print(f"⚠️ Warning: Supabase initialization failed: {e}")
    supabase_client = None

# LLM configurations
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL")  # Default Ollama port

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Make Gemini optional: try to import at startup, but don't fail if missing
try:
    import google.generativeai as genai  # type: ignore
    GENAI_AVAILABLE = True
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
except Exception as _e:  # ImportError or other misconfig
    GENAI_AVAILABLE = False
    genai = None  # type: ignore
    print(f"⚠️ google-generativeai not available; Gemini features disabled: {_e}")


# Pydantic models
class DBCredentials(BaseModel):
    db_user: str
    db_password: str
    db_host: str
    db_port: str | int  # Accept both string and integer
    db_name: str


class QueryRequest(BaseModel):
    question: str
    db_credentials: Optional[DBCredentials] = None
    llm_choice: Literal["openai", "gemini", "local"] = "openai"


class DBStructureRequest(BaseModel):
    db_credentials: Optional[DBCredentials] = None


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]
    db_credentials: Optional[DBCredentials] = None
    llm_choice: Literal["openai", "gemini", "local"] = "openai"


# LLM choice function
def choose_llm(llm_choice: str):
    if llm_choice == "openai":
        return nl_to_sql_openai
    elif llm_choice == "gemini":
        if not GENAI_AVAILABLE:
            raise HTTPException(status_code=503, detail="Gemini is unavailable on this deployment (missing google-generativeai)")
        return nl_to_sql_gemini
    elif llm_choice == "local":
        return nl_to_sql_local
    else:
        raise ValueError("Invalid LLM choice")


def get_default_db_credentials() -> DBCredentials:
    """Get database credentials from Supabase connection string"""
    supabase_url = os.getenv("SUPABASE_URL", "")
   
    if "supabase.co" in supabase_url:
        project_id = supabase_url.replace("https://", "").replace(".supabase.co", "")
        return DBCredentials(
            db_user=os.getenv("SUPABASE_DB_USER", "postgres"),
            db_password=os.getenv("SUPABASE_DB_PASSWORD", ""),
            db_host=f"db.{project_id}.supabase.co",
            db_port="5432",
            db_name=os.getenv("SUPABASE_DB_NAME", "postgres")
        )
    else:
        # Fallback to local PostgreSQL
        return DBCredentials(
            db_user="postgres",
            db_password="password",
            db_host="localhost",
            db_port="5432",
            db_name="products"
        )


# OpenAI function
def nl_to_sql_openai(question: str, table_info: str) -> str:
    prompt = f"""
    The sql code should not have ``` in beginning or end and sql word in output
    Given the following tables in a PostgreSQL database:

    {table_info}

    Convert the following natural language question to a SQL query:

    {question}

    Return only the SQL query, without any additional explanation.

    """

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a SQL expert. Convert natural language questions to SQL queries."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    return response.choices[0].message.content.strip()


def nl_to_sql_gemini(question: str, table_info: str) -> str:
    if not GENAI_AVAILABLE:
        raise HTTPException(status_code=503, detail="Gemini not installed on server")
    prompt = f"""
    Given the following tables in a PostgreSQL database, Also the sql code should not have ``` in beginning or end and sql word in output:

    {table_info}

    Convert the following natural language question to a SQL query:

    {question}

    Return only the SQL query, without any additional explanation.
    """

    # Choose a stable flash model (update if quota/model name changes)
    model = genai.GenerativeModel('gemini-1.5-flash')  # type: ignore
    response = model.generate_content(prompt)

    return response.text.strip()


# Local LLM function (using Ollama)
def nl_to_sql_local(question: str, table_info: str) -> str:
    prompt = f"""
    Given the following tables in a PostgreSQL database:

    {table_info}

    Convert the following natural language question to a SQL query:

    {question}

    Return only the SQL query, without any additional explanation.
    Also the sql code should not have ``` in beginning or end and sql word in output
    """

    response = requests.post(
        f"{LOCAL_LLM_URL}/v1/chat/completions",
        json={
            "model": "defog/sqlcoder-7b-2/sqlcoder-7b-q5_k_m.gguf",  # or any other model you have in Ollama
            "messages": [
                {
                    "role": "system",
                    "content": prompt
                }
            ]
            ,
            "stream": False
        }
    )
    response = response.json()
    print(response['choices'][0]['message']['content'])

    if response:
        return response['choices'][0]['message']['content'].strip()
    else:
        raise HTTPException(status_code=500, detail="Error in local LLM request")


def get_db_structure(db_credentials: DBCredentials = None):
    """Get database structure - returns actual schema from Supabase.
    
    Schema includes both reviews and products tables.
    """
    return {
        "reviews": [
            "review_id", "product_id", "rating", "title", "content", 
            "author", "review_date", "verified_purchase", "helpful_count", 
            "review_url", "inserted_at"
        ],
        "products": [
            "product_id", "product_name", "category"
        ]
    }


def execute_sql_query(query: str, db_credentials: DBCredentials = None):
    try:
        if not supabase_client:
            raise HTTPException(status_code=503, detail="Supabase client not initialized")
        
        # Clean the query
        query = query.strip().rstrip(';')
        print(f"🔍 Executing query: {query}")
        
        import re
        
        # Check if it's a SQL query
        if not re.search(r'SELECT\s+', query, re.IGNORECASE):
            return [{"message": "I'm ready to help! Ask me about Tiki products and I'll search the reviews for you."}]

        has_join = bool(re.search(r'\sJOIN\s', query, re.IGNORECASE))
        
        if has_join:
            # For JOIN queries: Use Supabase's foreign key expansion
            q = supabase_client.client.table("reviews").select("*, products(product_name, category)")
            
            # Check for EXACT match first (e.g., WHERE product_name = 'exact value')
            exact_match = re.search(r"WHERE\s+.*?product_name\s*=\s*'(.+?)'", query, re.IGNORECASE)
            
            if exact_match:
                # Exact match - use eq filter
                search_term = exact_match.group(1)
                print(f"🎯 Exact match search for: {search_term}")
                q = q.filter("products.product_name", "eq", search_term)
            else:
                # Check for ILIKE (fuzzy search)
                ilike_match = re.search(r"WHERE\s+.*?product_name\s+ILIKE\s+'%(.+?)%'", query, re.IGNORECASE)
                
                if ilike_match:
                    search_term = ilike_match.group(1)
                    print(f"🔎 Fuzzy search for: {search_term}")

                    q_exact = supabase_client.client.table("reviews").select("*, products(product_name, category)")
                    q_exact = q_exact.filter("products.product_name", "ilike", search_term)
                    result_exact = q_exact.limit(20).execute()
                    
                    if result_exact.data and len(result_exact.data) > 0:
                        # Found exact matches
                        print(f"Found {len(result_exact.data)} exact matches")
                        return result_exact.data
                    else:
                        # No exact match, use fuzzy search
                        print(f"⚠️ No exact match, using fuzzy search")
                        q = q.filter("products.product_name", "ilike", f"%{search_term}%")
            
            # Handle ORDER BY
            order_match = re.search(r'ORDER BY\s+(.+?)(?:\s+LIMIT|$)', query, re.IGNORECASE)
            if order_match:
                order_clause = order_match.group(1).strip()
                # Simple parsing: column_name ASC/DESC
                order_parts = order_clause.split()
                if len(order_parts) >= 1:
                    column = order_parts[0]
                    desc = len(order_parts) > 1 and order_parts[1].upper() == 'DESC'
                    q = q.order(column, desc=desc)
            
            # Handle LIMIT
            limit_match = re.search(r'LIMIT\s+(\d+)', query, re.IGNORECASE)
            if limit_match:
                limit = int(limit_match.group(1))
                q = q.limit(limit)
            else:
                q = q.limit(20)  # Default limit
            
            result = q.execute()
            data = result.data if hasattr(result, 'data') else []
            
        else:
            # Simple query without JOIN
            select_match = re.search(r'SELECT\s+(.+?)\s+FROM\s+(\w+)', query, re.IGNORECASE)
            if not select_match:
                return [{"message": "I couldn't understand that query. Try asking about specific products!"}]
            
            columns = select_match.group(1).strip()
            table = select_match.group(2).strip()
            
            # Build Supabase query
            if columns == '*':
                q = supabase_client.client.table(table).select("*")
            else:
                q = supabase_client.client.table(table).select(columns)
            
            # Parse WHERE clause
            where_match = re.search(r'WHERE\s+(.+?)(?:\s+LIMIT|\s+ORDER|$)', query, re.IGNORECASE | re.DOTALL)
            if where_match:
                where_clause = where_match.group(1).strip()
                
                # Handle exact match: column = 'value'
                eq_matches = re.findall(r"(\w+)\s*=\s*'(.+?)'", where_clause, re.IGNORECASE)
                for column, value in eq_matches:
                    q = q.eq(column, value)
                
                # Handle ILIKE: column ILIKE '%value%'
                ilike_matches = re.findall(r"(\w+)\s+ILIKE\s+'%(.+?)%'", where_clause, re.IGNORECASE)
                for column, value in ilike_matches:
                    q = q.ilike(column, f"%{value}%")
            
            # Handle LIMIT
            limit_match = re.search(r'LIMIT\s+(\d+)', query, re.IGNORECASE)
            if limit_match:
                limit = int(limit_match.group(1))
                q = q.limit(limit)
            
            result = q.execute()
            data = result.data if hasattr(result, 'data') else []
        
        if not data:
            return [{"message": "No reviews found matching your search. Try different keywords or ask about other products!"}]
        
        print(f"✅ Found {len(data)} results")
        return data
        
    except Exception as e:
        print(f"❌ Query execution error: {e}")
        import traceback
        traceback.print_exc()
        return [{"message": f"I had trouble searching. Error: {str(e)[:150]}"}]


def format_response_with_llm(sql_query: str, query_results: str, llm_choice: str) -> str:
    prompt = f"""
    Analyze the following query results and provide insights:

    Results: {query_results}

    Please provide a clear and concise analysis of the data. Focus on key trends, patterns, or notable information in the results. Use markdown formatting to structure your response, including:

    - Headers for main sections
    - Bullet points or numbered lists for key points
    - Bold or italic text for emphasis
    - Code blocks for any numerical data or examples

    Your analysis should be informative and easy to understand for someone looking at this data.
    """

    if llm_choice == "openai":
        formatted_response = format_response_openai(prompt)
    elif llm_choice == "gemini":
        formatted_response = format_response_gemini(prompt)
    elif llm_choice == "local":
        formatted_response = format_response_local(prompt)
    else:
        raise ValueError("Invalid LLM choice")

    # Add the SQL query at the end without displaying it in the chat
    formatted_response += f"\n\n[SQL_QUERY]{sql_query}[/SQL_QUERY]"

    return formatted_response


def format_response_openai(prompt: str) -> str:
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system",
             "content": "You are a data analyst providing insights on query results. Use markdown formatting in your responses."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )
    return response.choices[0].message.content.strip()


def format_response_gemini(prompt: str) -> str:
    if not GENAI_AVAILABLE:
        raise HTTPException(status_code=503, detail="Gemini not installed on server")
    model = genai.GenerativeModel('gemini-1.5-flash')  # type: ignore
    response = model.generate_content(prompt)
    return response.text.strip()


def format_response_local(prompt: str) -> str:
    response = requests.post(
        f"{LOCAL_LLM_URL}/v1/chat/completions",
        json={
            "model": "defog/sqlcoder-7b-2/sqlcoder-7b-q5_k_m.gguf",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a data analyst providing insights on query results. Use markdown formatting in your responses."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "stream": False
        }
    )
    response_json = response.json()
    return response_json['choices'][0]['message']['content'].strip()



@app.post("/query")
async def query(request: QueryRequest):
    try:
        # Use provided credentials or default
        db_creds = request.db_credentials or get_default_db_credentials()
        
        db_structure = get_db_structure(db_creds)
        table_info_str = "\n".join(
            [f"Table: {table}, Columns: {', '.join(columns)}" for table, columns in db_structure.items()])

        # Choose LLM based on request
        nl_to_sql_func = choose_llm(request.llm_choice)

        # Convert natural language to SQL
        sql_query = nl_to_sql_func(request.question, table_info_str)
        print(sql_query)

        # Execute the SQL query
        results = execute_sql_query(sql_query, db_creds)

        return {
            "question": request.question,
            "sql_query": sql_query,
            "results": results
        }
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        # Use provided credentials or default
        db_creds = request.db_credentials or get_default_db_credentials()
        
        db_structure = get_db_structure(db_creds)

        system_message = f"""You are a friendly AI assistant for a Tiki product review website.

Database schema:
- reviews table: review_id, product_id, rating (numeric 1-5), title, content, author, review_date, verified_purchase, helpful_count, review_url
- products table: product_id, product_name, category

IMPORTANT SEARCH RULES:
1. For greetings ("hi", "hey", "hello") → Respond warmly without SQL
2. For general questions → Answer directly without SQL
3. For product searches → Use INTELLIGENT MATCHING:

EXACT MATCH STRATEGY (cho tìm kiếm chính xác):
- When user mentions a SPECIFIC product model/name → Use = (equals) for EXACT match
- Examples: "Samsung Galaxy S23", "iPhone 15 Pro Max", "Xiaomi Redmi Note 12"
- SQL: WHERE product_name = 'exact_product_name'

FUZZY MATCH STRATEGY (cho tìm kiếm mở rộng):
- When user asks broadly → Use ILIKE for fuzzy search
- Examples: "Samsung phones", "laptops", "headphones under 1M"
- SQL: WHERE product_name ILIKE '%keyword%'

SQL Query Guidelines:
- ALWAYS JOIN reviews and products: SELECT r.*, p.product_name FROM reviews r JOIN products p ON r.product_id = p.product_id
- For EXACT product: WHERE p.product_name = 'Samsung Galaxy S23 Ultra'
- For CATEGORY/BRAND: WHERE p.product_name ILIKE '%Samsung%'
- Add ORDER BY rating DESC or review_date DESC for better results
- ALWAYS add LIMIT (default 20)
- No ``` or 'sql' tags - just raw SQL

Detection Examples:
User says: "Samsung Galaxy S23 Ultra" → EXACT match
SQL: SELECT r.*, p.product_name FROM reviews r JOIN products p ON r.product_id = p.product_id WHERE p.product_name = 'Samsung Galaxy S23 Ultra' LIMIT 20

User says: "Samsung phones" → FUZZY match  
SQL: SELECT r.*, p.product_name FROM reviews r JOIN products p ON r.product_id = p.product_id WHERE p.product_name ILIKE '%Samsung%' LIMIT 20

User says: "best rated Samsung" → FUZZY with ORDER
SQL: SELECT r.*, p.product_name FROM reviews r JOIN products p ON r.product_id = p.product_id WHERE p.product_name ILIKE '%Samsung%' ORDER BY r.rating DESC LIMIT 20
        """

        messages = [{"role": "system", "content": system_message}] + [m.dict() for m in request.messages]

        # Choose LLM based on request
        if request.llm_choice == "openai":
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0,
            )
            ai_message = response.choices[0].message.content.strip()
        elif request.llm_choice == "gemini":
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(
                [messages[i]['content'] for i in range(len(messages))])  # Only using the last message for simplicity
            ai_message = response.text.strip()
        elif request.llm_choice == "local":
            response = requests.post(
                f"{LOCAL_LLM_URL}/v1/chat/completions",
                json={
                    "model": "defog/sqlcoder-7b-2/sqlcoder-7b-q5_k_m.gguf",  # or any other model you have in Ollama
                    "messages": messages,
                    "stream": False
                }
            )
            response = response.json()

            if response:
                ai_message = response['choices'][0]['message']['content'].strip()

            else:
                raise HTTPException(status_code=500, detail="Error in local LLM request")
        else:
            raise ValueError("Invalid LLM choice")

        # Check if the AI's response contains a SQL query
        if "SELECT" in ai_message.upper():
            try:
                results = execute_sql_query(ai_message, db_creds)
                formatted_response = format_response_with_llm(ai_message, str(results), request.llm_choice)

                return {
                    "role": "assistant",
                    "content": formatted_response,
                    "tabular_data": results
                }
            except Exception as e:
                error_message = f"Error executing query: {str(e)}"
                formatted_response = format_response_with_llm(ai_message, error_message, request.llm_choice)
                return {"role": "assistant", "content": formatted_response}
        else:
            return {"role": "assistant", "content": ai_message}

    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))


class SimpleChatRequest(BaseModel):
    messages: List[Message]
    llm_choice: Literal["openai", "gemini", "local"] = "openai"


@app.post("/chat/simple")
async def chat_simple(request: SimpleChatRequest):
    """Simple chat without database requirements - just pure conversation"""
    try:
        system_message = """You are a helpful AI assistant specializing in product reviews and e-commerce data. 
        You can help users find information, answer questions, and provide insights about products."""

        messages = [{"role": "system", "content": system_message}] + [m.dict() for m in request.messages]

        # Choose LLM based on request
        if request.llm_choice == "openai":
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.7,
            )
            ai_message = response.choices[0].message.content.strip()
        elif request.llm_choice == "gemini":
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(
                "\n".join([msg['content'] for msg in messages]))
            ai_message = response.text.strip()
        elif request.llm_choice == "local":
            response = requests.post(
                f"{LOCAL_LLM_URL}/v1/chat/completions",
                json={
                    "model": "defog/sqlcoder-7b-2/sqlcoder-7b-q5_k_m.gguf",
                    "messages": messages,
                    "stream": False
                }
            )
            response = response.json()
            if response:
                ai_message = response['choices'][0]['message']['content'].strip()
            else:
                raise HTTPException(status_code=500, detail="Error in local LLM request")
        else:
            raise ValueError("Invalid LLM choice")

        return {
            "role": "assistant",
            "content": ai_message
        }

    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/db-structure")
async def get_db_structure_endpoint(request: DBStructureRequest):
    try:
        # Use provided credentials or default
        db_creds = request.db_credentials or get_default_db_credentials()
        
        structure = get_db_structure(db_creds)
        return {"structure": structure}
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))

class HealthData(BaseModel):
    average_heart_rate: float
    average_temperature: float
    average_ecg: float
    average_spo2: float


def get_average_sensor_data(user_id: int, days: int = 800):


    return HealthData(
        average_heart_rate=random.randint(60, 100),
        average_temperature=random.randint(96, 100),
        average_ecg=random.randint(60, 100),
        average_spo2=random.randint(90, 100)
    )


@app.get("/api/health_data/{user_id}")
async def health_data_api(user_id: int):
    data = get_average_sensor_data(user_id)
    if data is None:
        print(f"No data found for user {user_id}")
        raise HTTPException(status_code=404, detail="No data found for this user")
    return data


# ==================== Supabase Review Endpoints ====================

class ReviewCreate(BaseModel):
    url: str
    title: Optional[str] = None
    review: Optional[str] = None
    rating: Optional[float] = None
    metadata: Optional[dict] = None


@app.post("/api/reviews")
async def create_review(review: ReviewCreate):
    """Store a review in Supabase 'reviews' table."""
    try:
        record = review.dict(exclude_none=True)
        # Map API 'url' field to DB 'review_url' column
        if "url" in record:
            record["review_url"] = record.pop("url")
        inserted = supabase_client.insert("reviews", record)
        return {"success": True, "data": inserted}
    except Exception as e:
        print(f"Error inserting review: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/reviews")
async def get_reviews(limit: int = 10, url: Optional[str] = None):
    """Retrieve reviews from Supabase 'reviews' table."""
    try:
        if url:
            # API accepts 'url' param; map to DB column 'review_url'
            reviews = supabase_client.select("reviews", match={"review_url": url})
        else:
            # Supabase select doesn't have a native limit in the wrapper; fetch all and slice
            reviews = supabase_client.select("reviews")
            if reviews and len(reviews) > limit:
                reviews = reviews[:limit]
        return {"success": True, "data": reviews, "count": len(reviews) if reviews else 0}
    except Exception as e:
        print(f"Error fetching reviews: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Tiki Scraper Endpoints ====================

class TikiScrapeRequest(BaseModel):
    url: str
    max_pages: int = 1
    per_page: int = 20


class TikiCategoryScrapeRequest(BaseModel):
    category_url: str
    max_pages: int = 1
    per_page: int = 40
    include_reviews: bool = False
    reviews_per_product: int = 5


class TikiElectronicsScrapeRequest(BaseModel):
    max_pages_per_category: int = 2
    per_page: int = 40
    include_reviews: bool = False


@app.post("/api/scrape/tiki")
async def scrape_tiki_endpoint(request: TikiScrapeRequest):
    """Scrape Tiki product and reviews using public API.
    
    Example request:
    {
      "url": "https://tiki.vn/dien-thoai-samsung-galaxy-s23-ultra-p251769512.html",
      "max_pages": 2,
      "per_page": 20
    }
    """
    try:
        scraped = scrape_tiki(request.url, max_pages=request.max_pages, per_page=request.per_page)
        
        # Insert reviews into Supabase
        inserted_count = 0
        for r in scraped["reviews"]:
            record = {
                "review_url": scraped["product_url"],
                "title": r.get("title"),
                "review": r.get("content"),
                "rating": str(r.get("rating")) if r.get("rating") is not None else None,
                "source": "tiki",
                "metadata": {
                    "product_id": scraped.get("product_id"),
                    "product_name": scraped.get("product_name"),
                    "author": r.get("author"),
                    "created_at": r.get("created_at"),
                    "thank_count": r.get("thank_count"),
                    "review_id": r.get("review_id"),
                },
            }
            supabase_client.insert("reviews", record)
            inserted_count += 1
        
        return {
            "success": True,
            "inserted": inserted_count,
            "product": {
                "product_id": scraped.get("product_id"),
                "product_name": scraped.get("product_name"),
                "average_rating": scraped.get("average_rating"),
                "review_count": scraped.get("review_count"),
                "url": scraped.get("product_url"),
            },
            "reviews_scraped": len(scraped["reviews"]),
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error scraping Tiki: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scrape/tiki/category")
async def scrape_tiki_category_endpoint(request: TikiCategoryScrapeRequest):
    """Scrape products from a Tiki category page.
    
    Example request:
    {
      "category_url": "https://tiki.vn/dien-thoai-may-tinh-bang/c1789",
      "max_pages": 2,
      "per_page": 40,
      "include_reviews": true,
      "reviews_per_product": 5
    }
    """
    try:
        scraped = scrape_category(
            request.category_url,
            max_pages=request.max_pages,
            per_page=request.per_page,
            include_reviews=request.include_reviews,
            reviews_per_product=request.reviews_per_product,
        )
        
        # Insert products and reviews into Supabase
        inserted_products = 0
        inserted_reviews = 0
        
        for product in scraped["products"]:
            # Insert product metadata as a review record with product info
            product_record = {
                "review_url": product.get("product_url"),
                "title": product.get("product_name"),
                "rating": str(product.get("average_rating")) if product.get("average_rating") else None,
                "source": "tiki_category",
                "metadata": {
                    "product_id": product.get("product_id"),
                    "price": product.get("price"),
                    "original_price": product.get("original_price"),
                    "discount_rate": product.get("discount_rate"),
                    "review_count": product.get("review_count"),
                    "quantity_sold": product.get("quantity_sold"),
                    "brand_name": product.get("brand_name"),
                    "category_id": scraped.get("category_id"),
                    "category_name": scraped.get("category_name"),
                },
            }
            supabase_client.insert("reviews", product_record)
            inserted_products += 1
            
            # Insert individual reviews if available
            if product.get("reviews"):
                for r in product["reviews"]:
                    review_record = {
                        "review_url": product.get("product_url"),
                        "title": r.get("title"),
                        "review": r.get("content"),
                        "rating": str(r.get("rating")) if r.get("rating") is not None else None,
                        "source": "tiki",
                        "metadata": {
                            "product_id": product.get("product_id"),
                            "product_name": product.get("product_name"),
                            "author": r.get("author"),
                            "created_at": r.get("created_at"),
                            "thank_count": r.get("thank_count"),
                            "review_id": r.get("review_id"),
                        },
                    }
                    supabase_client.insert("reviews", review_record)
                    inserted_reviews += 1
        
        return {
            "success": True,
            "category_id": scraped.get("category_id"),
            "category_name": scraped.get("category_name"),
            "products_scraped": scraped.get("products_scraped"),
            "inserted_products": inserted_products,
            "inserted_reviews": inserted_reviews,
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error scraping Tiki category: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scrape/tiki/electronics")
async def scrape_tiki_electronics_endpoint(request: TikiElectronicsScrapeRequest):
    """Scrape all electronics categories from Tiki.
    
    Scrapes from:
    - Điện thoại - Máy tính bảng (c1789)
    - Thiết bị KTS - Phụ kiện số (c1815)
    
    Example request:
    {
      "max_pages_per_category": 2,
      "per_page": 40,
      "include_reviews": false
    }
    """
    try:
        scraped = scrape_all_electronics(
            max_pages_per_category=request.max_pages_per_category,
            per_page=request.per_page,
            include_reviews=request.include_reviews,
        )
        
        # Insert all products and reviews
        total_inserted_products = 0
        total_inserted_reviews = 0
        
        for category_data in scraped["categories"]:
            for product in category_data["products"]:
                # Insert product metadata
                product_record = {
                    "review_url": product.get("product_url"),
                    "title": product.get("product_name"),
                    "rating": str(product.get("average_rating")) if product.get("average_rating") else None,
                    "source": "tiki_category",
                    "metadata": {
                        "product_id": product.get("product_id"),
                        "price": product.get("price"),
                        "original_price": product.get("original_price"),
                        "discount_rate": product.get("discount_rate"),
                        "review_count": product.get("review_count"),
                        "quantity_sold": product.get("quantity_sold"),
                        "brand_name": product.get("brand_name"),
                        "category_id": category_data.get("category_id"),
                        "category_name": category_data.get("category_name"),
                    },
                }
                supabase_client.insert("reviews", product_record)
                total_inserted_products += 1
                
                # Insert reviews if available
                if product.get("reviews"):
                    for r in product["reviews"]:
                        review_record = {
                            "review_url": product.get("product_url"),
                            "title": r.get("title"),
                            "review": r.get("content"),
                            "rating": str(r.get("rating")) if r.get("rating") is not None else None,
                            "source": "tiki",
                            "metadata": {
                                "product_id": product.get("product_id"),
                                "product_name": product.get("product_name"),
                                "author": r.get("author"),
                                "created_at": r.get("created_at"),
                                "thank_count": r.get("thank_count"),
                                "review_id": r.get("review_id"),
                            },
                        }
                        supabase_client.insert("reviews", review_record)
                        total_inserted_reviews += 1
        
        return {
            "success": True,
            "categories_scraped": len(scraped["categories"]),
            "total_products": scraped["total_products"],
            "inserted_products": total_inserted_products,
            "inserted_reviews": total_inserted_reviews,
            "categories": [
                {
                    "category_id": c["category_id"],
                    "category_name": c["category_name"],
                    "products_scraped": c["products_scraped"],
                }
                for c in scraped["categories"]
            ],
        }
    
    except Exception as e:
        print(f"Error scraping Tiki electronics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/electronics/categories")
async def get_electronics_categories():
    """Get list of available electronics categories."""
    return {
        "success": True,
        "categories": [
            {
                "key": key,
                "id": info["id"],
                "name": info["name"],
                "url": info["url"],
            }
            for key, info in ELECTRONICS_CATEGORIES.items()
        ],
    }


@app.get("/")
async def root():
    """Root route for platform health checks and human-friendly info.
    Some platforms probe '/' — return a helpful payload instead of 404.
    """
    return {
        "status": "ok",
        "message": "Chatbot Reviewer Backend. See /health or /docs",
        "health": "/health",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "message": "Backend is running!",
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "chat_simple": "/chat/simple",
            "chat_with_db": "/chat",
            "scrape_tiki": "/api/scrape/tiki",
            "categories": "/api/electronics/categories"
        }
    }


@app.get("/favicon.ico")
async def favicon():
    """Return a 204 for favicon probes to reduce 404 log noise."""
    from fastapi import Response
    return Response(status_code=204)
