
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional
import requests

from .tiki_scraper import scrape_tiki, fetch_product, DEFAULT_HEADERS, _get_json


CATEGORY_ID_RE = re.compile(r"/c(\d+)")


def parse_category_id(url: str) -> Optional[int]:
    """Extract category ID from Tiki category URL.
    
    Examples:
      https://tiki.vn/dien-thoai-may-tinh-bang/c1789 -> 1789
      https://tiki.vn/thiet-bi-kts-phu-kien-so/c1815 -> 1815
    """
    if not url:
        return None
    m = CATEGORY_ID_RE.search(url)
    return int(m.group(1)) if m else None


def fetch_category_products(
    category_id: int,
    page: int = 1,
    limit: int = 40,
    sort: str = "top_seller",
) -> Dict[str, Any]:
    """Fetch one page of products from a Tiki category.
    
    Args:
        category_id: Tiki category ID (e.g., 1789 for phones)
        page: Page number (1-indexed)
        limit: Products per page (max 40)
        sort: Sort order (top_seller, newest, price,desc, price,asc)
    
    Returns:
        {
          "data": [{"id": int, "name": str, "price": float, ...}],
          "paging": {"current_page": int, "total": int, "last_page": int}
        }
    """
    url = "https://tiki.vn/api/personalish/v1/blocks/listings"
    params = {
        "limit": limit,
        "category": category_id,
        "page": page,
        "sort": sort,
        "aggregations": 2,
    }
    return _get_json(url, params=params)


def normalize_product(p: Dict[str, Any], category_name: str = "") -> Dict[str, Any]:
    """Normalize product data from category listing."""
    product_id = p.get("id")
    
    # Build product URL
    product_url = p.get("url_path", "")
    if product_url and not product_url.startswith("http"):
        product_url = f"https://tiki.vn/{product_url}"
    
    return {
        "product_id": product_id,
        "product_name": p.get("name"),
        "product_url": product_url,
        "price": p.get("price"),
        "original_price": p.get("original_price"),
        "discount_rate": p.get("discount_rate"),
        "average_rating": p.get("rating_average"),
        "review_count": p.get("review_count"),
        "quantity_sold": (p.get("quantity_sold") or {}).get("value"),
        "thumbnail_url": p.get("thumbnail_url"),
        "brand_name": (p.get("brand") or {}).get("name"),
        "category_name": category_name,
    }


def scrape_category(
    category_url: str,
    max_pages: int = 1,
    per_page: int = 40,
    include_reviews: bool = False,
    reviews_per_product: int = 5,
) -> Dict[str, Any]:
    """Scrape products from a Tiki category page.
    
    Args:
        category_url: Full category URL or just category ID
        max_pages: Max number of pages to scrape
        per_page: Products per page (max 40)
        include_reviews: Whether to scrape reviews for each product
        reviews_per_product: Number of reviews to fetch per product
    
    Returns:
        {
          "category_id": int,
          "category_name": str,
          "total_products": int,
          "products": [
            {
              "product_id": int,
              "product_name": str,
              "product_url": str,
              "price": float,
              "average_rating": float,
              "review_count": int,
              "reviews": [...] if include_reviews else None
            },
            ...
          ]
        }
    """
    # Parse category ID
    if isinstance(category_url, int):
        category_id = category_url
    else:
        category_id = parse_category_id(category_url)
        if not category_id:
            raise ValueError(f"Cannot parse category ID from: {category_url}")
    
    products = []
    current_page = 1
    total_products = 0
    category_name = ""
    
    while current_page <= max_pages:
        print(f"[Tiki Category] Fetching page {current_page} of category {category_id}...")
        page_data = fetch_category_products(category_id, page=current_page, limit=per_page)
        
        data_list = page_data.get("data") or []
        if not data_list:
            print(f"[Tiki Category] No more products on page {current_page}")
            break
        
        # Get category name from first product
        if not category_name and data_list:
            first_product = data_list[0]
            categories = first_product.get("categories") or {}
            category_name = categories.get("name", f"Category {category_id}")
        
        for p in data_list:
            normalized = normalize_product(p, category_name)
            
            # Optionally scrape reviews for each product
            if include_reviews and normalized["product_url"]:
                try:
                    print(f"  → Scraping reviews for: {normalized['product_name'][:50]}...")
                    review_data = scrape_tiki(
                        normalized["product_url"],
                        max_pages=1,
                        per_page=reviews_per_product
                    )
                    normalized["reviews"] = review_data.get("reviews", [])
                    time.sleep(0.5)  # Rate limit between product scrapes
                except Exception as e:
                    print(f"  ✗ Error scraping reviews: {e}")
                    normalized["reviews"] = []
            else:
                normalized["reviews"] = None
            
            products.append(normalized)
        
        paging = page_data.get("paging") or {}
        total_products = paging.get("total", len(products))
        last_page = paging.get("last_page", 1)
        
        if current_page >= last_page:
            break
        
        current_page += 1
        time.sleep(0.8)  # Rate limit between pages
    
    return {
        "category_id": category_id,
        "category_name": category_name,
        "total_products": total_products,
        "products_scraped": len(products),
        "products": products,
    }


# Predefined electronics categories
ELECTRONICS_CATEGORIES = {
    "phones_tablets": {
        "id": 1789,
        "name": "Điện thoại - Máy tính bảng",
        "url": "https://tiki.vn/dien-thoai-may-tinh-bang/c1789",
    },
    "accessories": {
        "id": 1815,
        "name": "Thiết bị KTS - Phụ kiện số",
        "url": "https://tiki.vn/thiet-bi-kts-phu-kien-so/c1815",
    },
}


def scrape_all_electronics(
    max_pages_per_category: int = 2,
    per_page: int = 40,
    include_reviews: bool = False,
) -> Dict[str, Any]:
    """Scrape all predefined electronics categories.
    
    Returns:
        {
          "categories": [
            {"category_id": ..., "products": [...]},
            ...
          ],
          "total_products": int
        }
    """
    results = []
    total_products = 0
    
    for key, cat_info in ELECTRONICS_CATEGORIES.items():
        print(f"\n{'='*60}")
        print(f"Scraping category: {cat_info['name']}")
        print(f"{'='*60}")
        
        try:
            category_data = scrape_category(
                cat_info["id"],
                max_pages=max_pages_per_category,
                per_page=per_page,
                include_reviews=include_reviews,
            )
            results.append(category_data)
            total_products += category_data["products_scraped"]
            
            print(f"✓ Scraped {category_data['products_scraped']} products from {cat_info['name']}")
        except Exception as e:
            print(f"✗ Error scraping {cat_info['name']}: {e}")
    
    return {
        "categories": results,
        "total_products": total_products,
    }


__all__ = [
    "parse_category_id",
    "fetch_category_products",
    "normalize_product",
    "scrape_category",
    "scrape_all_electronics",
    "ELECTRONICS_CATEGORIES",
]
