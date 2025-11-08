"""Tiki.vn product and reviews scraper using public web APIs.

This module avoids brittle HTML parsing by calling Tiki's web API endpoints.

Contract
- Input: product page URL like https://tiki.vn/some-product-p123456.html
- Output: dict with keys:
    {
      "product_id": int,
      "product_name": str,
      "average_rating": float | None,
      "review_count": int | None,
      "product_url": str,
      "reviews": [
          {
            "review_id": int,
            "author": str | None,
            "title": str | None,
            "content": str | None,
            "rating": float | None,
            "created_at": str,  # ISO 8601
            "thank_count": int | None
          }, ...
      ]
    }

Notes
- This is best-effort based on Tiki's current API shape and may change.
- Add light retry and a browser-like header to reduce blocks.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from dateutil import parser as dateparser


PRODUCT_ID_RE = re.compile(r"-p(\d+)\.html")


def parse_product_id(url: str) -> Optional[int]:
    """Extract numeric product ID from a Tiki product URL.

    Examples:
      https://tiki.vn/some-slug-p123456.html -> 123456
    """
    if not url:
        return None
    m = PRODUCT_ID_RE.search(url)
    return int(m.group(1)) if m else None


DEFAULT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "vi,en-US;q=0.9,en;q=0.8",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "origin": "https://tiki.vn",
    "referer": "https://tiki.vn/",
}


def _get_json(url: str, params: Optional[Dict[str, Any]] = None, retries: int = 3, backoff: float = 0.8) -> Any:
    last_err: Optional[Exception] = None
    for i in range(retries):
        try:
            resp = requests.get(url, params=params or {}, headers=DEFAULT_HEADERS, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            last_err = RuntimeError(f"HTTP {resp.status_code} for {url}")
        except Exception as e:  # noqa: BLE001
            last_err = e
        time.sleep(backoff * (i + 1))
    if last_err:
        raise last_err
    raise RuntimeError("Unknown error fetching JSON")


def fetch_product(product_id: int) -> Dict[str, Any]:
    """Fetch product details from Tiki API."""
    url = f"https://tiki.vn/api/v2/products/{product_id}"
    data = _get_json(url, params={"platform": "web"})

    return {
        "product_id": product_id,
        "product_name": data.get("name"),
        "average_rating": data.get("rating_average"),
        "review_count": data.get("review_count"),
    }


def fetch_reviews(product_id: int, page: int = 1, limit: int = 20) -> Dict[str, Any]:
    """Fetch one page of reviews for a product.

    Returns dict with keys: {"data": list, "paging": {"current_page", "last_page"}}
    """
    url = "https://tiki.vn/api/v2/reviews"
    params = {
        "product_id": product_id,
        "page": page,
        "limit": limit,
        "include": "comments,contribute_info,attribute_vote_summary,attribute_vote,tags,template_tags",
        "sort": "score|desc,id|desc,stars|all",
    }
    return _get_json(url, params=params)


def normalize_review(r: Dict[str, Any]) -> Dict[str, Any]:
    created_at_iso: Optional[str] = None
    created = r.get("created_at")
    if created:
        try:
            created_at_iso = dateparser.parse(created).isoformat()
        except Exception:  # noqa: BLE001
            created_at_iso = str(created)

    return {
        "review_id": r.get("id"),
        "author": (r.get("created_by") or {}).get("name"),
        "title": r.get("title"),
        "content": r.get("content"),
        "rating": float(r.get("rating")) if r.get("rating") is not None else None,
        "created_at": created_at_iso,
        "thank_count": r.get("thank_count"),
    }


def scrape_tiki(url: str, max_pages: int = 1, per_page: int = 20) -> Dict[str, Any]:
    """High-level scraping: product + first N pages of reviews."""
    pid = parse_product_id(url)
    if not pid:
        raise ValueError("Cannot extract product_id from URL. Expect ...-p<id>.html")

    product = fetch_product(pid)

    reviews: List[Dict[str, Any]] = []
    current_page = 1
    last_page = 1
    while current_page <= max_pages:
        page_data = fetch_reviews(pid, page=current_page, limit=per_page)
        data_list = page_data.get("data") or []
        reviews.extend(normalize_review(r) for r in data_list)
        paging = page_data.get("paging") or {}
        last_page = paging.get("last_page") or last_page
        if current_page >= last_page:
            break
        current_page += 1

    return {
        **product,
        "product_url": url,
        "reviews": reviews,
    }


__all__ = [
    "parse_product_id",
    "fetch_product",
    "fetch_reviews",
    "normalize_review",
    "scrape_tiki",
]
