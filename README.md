# Tiki Product Reviewer — Backend

Tiki Product Reviewer is the backend service for collecting, cleaning, storing, and analyzing product reviews scraped from e-commerce marketplaces (initial focus: Tiki). The backend provides scraping utilities, data normalization, storage via Supabase, and AI/NLP helpers to generate summaries or run natural-language queries against the data.

Purpose

General purpose

The Tiki Product Reviewer project aims to provide richer, multi-perspective product reviews built from real user feedback. The system helps:

- Consumers: get a broader view of a product before purchase through aggregated reviews and AI-generated summaries.
- Businesses: extract customer insights to identify strengths and weaknesses, and inform product or UX improvements.

Backend-specific goals

This backend release focuses on:

- Collecting and processing review/product data from Tiki (electronics categories initially).
- Producing a clean, structured dataset suitable for downstream AI/NLP tasks such as summary generation and sentiment analysis.
- Serving APIs for scraping, ingestion, querying, and AI-assisted analysis.

System overview

The backend is organized as a pipeline:

- Scraper: fetches product pages and reviews from Tiki (implemented in `scripts/scraper/`).
- Data processing: normalizes and structures scraped data for storage.
- OpenAI integration: helpers for text generation, summarization and text-to-SQL (see `scripts/openai_wrapper.py`).
- Storage: Supabase client wrapper used to insert and query review records (`scripts/supabase_client.py`).
- Testing: pytest-based tests to validate scrapers and integration flows (`tests/`).

Key features

- Scraping of categories and products (`scripts/scraper/tiki_category_scraper.py`, `scripts/scraper/tiki_scraper.py`, `scripts/scraper/scrape_electronics.py`).
- REST API entry point and chat/query endpoints (`main.py`).
- OpenAI/LLM wrapper for generating summaries or converting NL to SQL (`scripts/openai_wrapper.py`).
- Supabase integration for persistent storage (`scripts/supabase_client.py`).
- Tests and integration checks (`tests/test_scraper.py`, `tests/test_integration.py`, `test_backend.py`).

Technology and libraries

- Language: Python 3.10+
- Web scraping: requests, BeautifulSoup4, Playwright (optional) for browser automation
- AI / NLP: openai (OpenAI API), google-generativeai (Gemini) as configured in the code
- Database / BaaS: Supabase (supabase-py client)
- Testing: pytest
- Dependencies: listed in `requirements.txt`

Repository layout (important files)

```
.
├── main.py                        # FastAPI application & endpoints
├── scripts/
│   ├── openai_wrapper.py          # OpenAI helper
│   ├── supabase_client.py         # Supabase wrapper
│   └── scraper/
│       ├── tiki_scraper.py
│       ├── tiki_category_scraper.py
│       ├── scrape_electronics.py
│       └── app.py                 # Flask scraper service
├── tests/                         # Unit & integration tests
├── supabase_functions.sql         # Helper SQL functions for Supabase
├── requirements.txt               # Python dependencies
└── README.md
```

Installation and setup (Windows / PowerShell)

Follow these steps to set up the project locally on Windows using PowerShell.

1) Clone and change directory

```powershell
git clone <repo-url>
cd "Tiki Product Reviewer Backend"
```

2) Create and activate a virtual environment (recommended)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3) Install Python dependencies

```powershell
pip install -r requirements.txt
```

4) (Optional) Install Playwright browsers for browser-based scraping

```powershell
playwright install chromium
```

5) Create a `.env` file at project root with required environment variables

Example `.env` (replace placeholders):

```
OPENAI_API_KEY=sk-...
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_API_KEY=eyJ...
GEMINI_API_KEY=your-gemini-key
LOCAL_LLM_URL=http://localhost:11434
SCRAPER_PORT=
```


Running the project

Development mode — run FastAPI and the scraper separately:

1) Start the FastAPI backend (port 8000):

```powershell
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

2) Start the Flask scraper service (port 5001 by default):

```powershell
python scripts/scraper/app.py
```

Production hints

You can run the services with production servers. Example (Uvicorn + Gunicorn):

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
# For Flask scraper (use gunicorn from WSL or Linux/macOS environment)
gunicorn -w 4 -b 0.0.0.0:5001 scraper.app:app
```

API examples

- Health: GET `/health`
- Simple chat: POST `/chat/simple` with JSON { messages: [...], llm_choice: 'openai' }
- Text-to-SQL: POST `/query` with JSON { question: '...', llm_choice: 'openai' }
- Scrape Tiki product: POST `/api/scrape/tiki` with JSON { url: '...', max_pages: 1, per_page: 20 }

Testing

Run unit and integration tests with pytest:

```powershell
pytest tests/ -v
```

Note: some integration tests require network access and Supabase credentials. Those can be skipped or run in an environment with the correct `.env` values.

Roadmap / next steps

- Extend scrapers to cover more Tiki categories (home, books, fashion).
- Integrate a vector store + RAG pipeline to enable a product-review chatbot.
- Harden scraping (proxies, rotating user agents, robust retry and backoff).
- Add sentiment analysis and a small analytics dashboard.

Contributing

1. Fork the repository and create a feature branch: `git checkout -b feature/name`.
2. Implement changes and add tests where applicable.
3. Run tests locally and open a pull request with a clear description.

Suggested improvements to contribute:

- Add a `CONTRIBUTING.md` with coding style and PR checklist.
- Add CI (GitHub Actions) to run pytest on every pull request.
- Add a Dockerfile and a small `docker-compose.yml` for local development.

Legal and compliance notes

This project contains scrapers for demonstration and research. Always comply with target websites' terms of service and robots.txt. For production usage consider using official APIs where available and seek legal advice about large-scale data collection.

If you want, I can also add a `CONTRIBUTING.md`, GitHub Actions workflow to run tests, or a Dockerfile for development and deployment.
