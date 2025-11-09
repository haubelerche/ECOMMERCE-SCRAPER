
from __future__ import annotations

import argparse
import time
from typing import Any
from dateutil import parser as dateparser

from dotenv import load_dotenv, find_dotenv
from scraper.tiki_category_scraper import scrape_all_electronics
from supabase_client import SupabaseClient

# Load environment variables from .env if present
load_dotenv(find_dotenv())


def insert_records(supabase: SupabaseClient, records: list[dict[str, Any]], table: str = "reviews") -> int:
    inserted = 0
    for r in records:
        try:
            supabase.insert(table, r)
            inserted += 1
            # small delay to be polite
            time.sleep(0.02)
        except Exception as e:
            print(f"Warning: failed to insert record: {e}")
    return inserted


def run(max_pages_per_category: int, per_page: int, include_reviews: bool, dry_run: bool):
    print(f"Starting Tiki electronics scrape: max_pages_per_category={max_pages_per_category}, per_page={per_page}, include_reviews={include_reviews}, dry_run={dry_run}")

    scraped = scrape_all_electronics(max_pages_per_category=max_pages_per_category, per_page=per_page, include_reviews=include_reviews)

    total_products = 0
    total_reviews = 0

    if dry_run:
        print("Dry run mode - not inserting into Supabase. Summary of what would be inserted:")
        for category in scraped["categories"]:
            print(f"Category {category['category_name']} ({category['category_id']}): products_scraped={category['products_scraped']}")
            total_products += category['products_scraped']
            for p in category['products']:
                if p.get("reviews"):
                    total_reviews += len(p["reviews"])
        print(f"Total products: {total_products}, total reviews (fetched): {total_reviews}")
        return

    # Initialize Supabase client
    sb = SupabaseClient()

    inserted_products = 0
    inserted_reviews = 0
    gen_review_counter = 0

    for category in scraped["categories"]:
        print(f"Inserting products from category: {category['category_name']} ({category['category_id']})")
        for product in category["products"]:
            # Map product fields to your existing `products` table
            pid = product.get("product_id")
            pid_text = str(pid) if pid is not None else None
            product_row = {
                "product_id": pid_text,
                "product_name": product.get("product_name"),
                "category": category.get("category_name") or None,
            }

            try:
                # upsert product by product_id
                sb.upsert("products", product_row, on_conflict="product_id")
                inserted_products += 1
            except Exception as e:
                print(f"Warning: failed to upsert product {pid_text}: {e}")

            # Insert product reviews into `reviews` table according to your schema
            if product.get("reviews"):
                for r in product["reviews"]:
                    # Determine review_id: prefer scraped review_id, otherwise generate one
                    rid = r.get("review_id")
                    if rid is None:
                        gen_review_counter += 1
                        rid = f"gen-{pid_text}-{int(time.time()*1000)}-{gen_review_counter}"

                    # Parse date to ISO date (YYYY-MM-DD) if available
                    review_date = None
                    created = r.get("created_at")
                    if created:
                        try:
                            dt = dateparser.parse(created)
                            review_date = dt.date().isoformat()
                        except Exception:
                            review_date = None

                    review_row = {
                        "review_id": str(rid),
                        "product_id": pid_text,
                        "rating": float(r.get("rating")) if r.get("rating") is not None else None,
                        "title": r.get("title"),
                        "content": r.get("content"),
                        "author": r.get("author"),
                        "review_date": review_date,
                        "verified_purchase": False,  # Tiki API doesn't expose this reliably
                        "helpful_count": r.get("thank_count") if r.get("thank_count") is not None else None,
                        "review_url": product.get("product_url"),
                    }

                    try:
                        # Use upsert on review_id to avoid duplicates
                        sb.upsert("reviews", review_row, on_conflict="review_id")
                        inserted_reviews += 1
                    except Exception as e:
                        print(f"Warning: failed to upsert review {rid} for product {pid_text}: {e}")

    print(f"Done. Upserted products: {inserted_products}, upserted reviews: {inserted_reviews}")


def parse_args():
    p = argparse.ArgumentParser(description="Scrape Tiki electronics categories and insert into Supabase")
    p.add_argument("--max-pages-per-category", type=int, default=2, help="Max pages per category to scrape")
    p.add_argument("--per-page", type=int, default=40, help="Products per page to request from Tiki (max 40)")
    p.add_argument("--include-reviews", action="store_true", help="Also fetch a few reviews per product (slower)")
    p.add_argument("--dry-run", action="store_true", help="Fetch data but do not insert into Supabase")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args.max_pages_per_category, args.per_page, args.include_reviews, args.dry_run)
