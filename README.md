# Ecommerce Scraper 

Ecommerce Scraper is the backend service for collecting, cleaning, storing, and analyzing product reviews scraped from e-commerce marketplaces (initial focus: Tiki). The backend provides scraping utilities, data normalization, storage via Supabase, and AI/NLP helpers to generate summaries or run natural-language queries against the data.

Purpose

General purpose

The Ecommerce Scraper project aims to provide richer, multi-perspective product reviews built from real user feedback. The system helps:

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
cd "Ecommerce Scraper"
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
   



