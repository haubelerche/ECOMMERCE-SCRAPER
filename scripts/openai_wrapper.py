import os
from typing import Optional, Literal
from openai import OpenAI, OpenAIError


class OpenAIWrapper:

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY must be set in environment or passed to constructor")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = model

    def text_to_sql(
        self,
        question: str,
        table_info: str,
        database_type: str = "PostgreSQL",
        temperature: float = 0.0,
    ) -> str:

        prompt = f"""
The SQL code should not have ``` in beginning or end and should not include the word 'sql' in output.

Given the following tables in a {database_type} database:

{table_info}

Convert the following natural language question to a SQL query:

{question}

Return only the SQL query, without any additional explanation.
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a SQL expert. Convert natural language questions to SQL queries."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=500,
            )

            if not response.choices or not response.choices[0].message.content:
                raise ValueError("Empty response from OpenAI API")

            sql_query = response.choices[0].message.content.strip()
            
            # Clean up common formatting issues
            sql_query = sql_query.replace("```sql", "").replace("```", "").strip()
            
            return sql_query

        except OpenAIError as e:
            raise OpenAIError(f"OpenAI API error: {str(e)}")
        except Exception as e:
            raise ValueError(f"Error generating SQL: {str(e)}")

    def format_results(
        self,
        query_results: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        """Format query results with AI-generated insights.
        
        Args:
            query_results: Query results to analyze
            temperature: Sampling temperature for creative responses
            max_tokens: Maximum tokens in response
            
        Returns:
            Formatted markdown response with insights
        """
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

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a data analyst providing insights on query results. Use markdown formatting in your responses."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )

            if not response.choices or not response.choices[0].message.content:
                raise ValueError("Empty response from OpenAI API")

            return response.choices[0].message.content.strip()

        except OpenAIError as e:
            raise OpenAIError(f"OpenAI API error: {str(e)}")
        except Exception as e:
            raise ValueError(f"Error formatting results: {str(e)}")


# Singleton instance for convenience
_default_wrapper: Optional[OpenAIWrapper] = None


def get_openai_wrapper(api_key: Optional[str] = None, model: str = "gpt-4o-mini") -> OpenAIWrapper:
    """Get or create default OpenAI wrapper instance."""
    global _default_wrapper
    if _default_wrapper is None:
        _default_wrapper = OpenAIWrapper(api_key=api_key, model=model)
    return _default_wrapper
