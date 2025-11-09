from flask import Flask, request, jsonify
import selectorlib
import requests
from dateutil import parser as dateparser
from supabase import create_client, Client
from dotenv import load_dotenv
import os
from datetime import datetime
from typing import Any, Dict
from .tiki_scraper import scrape_tiki
from supabase_client import SupabaseClient

load_dotenv()
try:
    supabase_wrapper = SupabaseClient()
    supabase = None
except Exception:
    # Fallback to direct client for backwards compatibility
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_API_KEY")
    supabase: Client = create_client(url, key)  # type: ignore[assignment]
    supabase_wrapper = None  # type: ignore[assignment]

class Review:
    def __init__(self, author, content, date, found_helpful, images, product, rating, title, url, variant, verified_purchase):
        self.author = author
        self.content = content
        self.date = datetime.strptime(date, '%d %b %Y').isoformat()
        self.found_helpful = found_helpful
        self.images = images
        self.product = product
        self.rating = float(rating) if rating else None
        self.title = title
        self.url = url
        self.variant = variant
        self.verified_purchase = verified_purchase

class ProductReview:
    def __init__(self, average_rating, histogram, next_page, number_of_reviews, product_title, reviews):
        self.average_rating = average_rating
        self.histogram = histogram
        self.next_page = next_page
        self.number_of_reviews = number_of_reviews
        self.product_title = product_title
        self.reviews = [Review(**review) for review in reviews]

app = Flask(__name__)
extractor = selectorlib.Extractor.from_yaml_file('selectors.yml')

def insert_data(product_review: ProductReview):
    # Insert product data
    product_data = {
        "title": product_review.product_title,
        "average_rating": product_review.average_rating,
        "number_of_reviews": product_review.number_of_reviews,
        "next_page": product_review.next_page
    }
    # Insert via available supabase client
    if supabase_wrapper:
        product_result = supabase_wrapper.insert("products", product_data)
        product_id = product_result[0]['id'] if product_result else None
    else:
        product_result = supabase.table("products").insert(product_data).execute()
        product_id = product_result.data[0]['id']
    product_title = product_review.product_title


    for review in product_review.reviews:
        review_data = {
            "product_id": product_id,
            "product_title": product_title,
            "author": review.author,
            "content": review.content,
            "review_date": review.date,
            "found_helpful": review.found_helpful,
            "images": review.images,
            "rating": review.rating,
            "title": review.title,
            "review_url": review.url,
            "variant": review.variant,
            "verified_purchase": review.verified_purchase
        }
        if supabase_wrapper:
            supabase_wrapper.insert("reviews", review_data)
        else:
            supabase.table("reviews").insert(review_data).execute()

    print(f"Inserted data for product: {product_review.product_title}")

def scrape(url):
    headers = {
        'authority': 'www.amazon.com',
        'pragma': 'no-cache',
        'cache-control': 'no-cache',
        'dnt': '1',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (X11; CrOS x86_64 8172.45.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/51.0.2704.64 Safari/537.36',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
        'sec-fetch-site': 'none',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-dest': 'document',
        'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8',
    }

    # Download the page using requests
    print("Downloading %s" % url)
    r = requests.get(url, headers=headers)
    # Simple check to check if page was blocked (Usually 503)
    if r.status_code > 500:
        if "To discuss automated access to Amazon data please contact" in r.text:
            print("Page %s was blocked by Amazon. Please try using better proxies\n" % url)
        else:
            print("Page %s must have been blocked by Amazon as the status code was %d" % (url, r.status_code))
        return None

    data = extractor.extract(r.text, base_url=url)
    reviews = []
    for r in data['reviews']:
        print(r)
        r["product"] = data["product_title"]
        r['url'] = url
        if 'verified_purchase' in r:
            if 'Verified Purchase' in r['verified_purchase']:
                r['verified_purchase'] = True
            else:
                r['verified_purchase'] = False
        if r['title']:
            r['rating'] = float(r['title'].split('out of')[0].strip())
            r['title'] = r['title'].split('stars')[1].strip()
        date_posted = r['date'].split('on ')[-1]
        if r['images']:
            r['images'] = "\n".join(r['images'])
        r['date'] = dateparser.parse(date_posted).strftime('%d %b %Y')
        reviews.append(r)
    histogram = {}
    if data['histogram']:
        for h in data['histogram']:
            histogram[h['key']] = h['value']
    data['histogram'] = histogram
    data['average_rating'] = float(data['average_rating'].split(' out')[0])
    data['reviews'] = reviews
    data['number_of_reviews'] = int(data['number_of_reviews'].split('global')[0].strip().replace(',', ''))
    return data


@app.route('/')
def api():
    url = request.args.get('url', None)
    if url:
        data = scrape(url)
        if data:
            product_review = ProductReview(**data)
            insert_data(product_review)
            return data
        else:
            return jsonify({'error': 'Failed to scrape data'}), 500
    return jsonify({'error': 'URL to scrape is not provided'}), 400

if __name__ == '__main__':
    app.run()

@app.post('/scrape_tiki')
def scrape_tiki_endpoint():
    try:
        body: Dict[str, Any] = request.get_json(force=True)  # type: ignore[assignment]
        product_url = body.get('url')
        max_pages = int(body.get('max_pages', 1))
        per_page = int(body.get('per_page', 20))
        if not product_url:
            return jsonify({"error": "Missing 'url' in body"}), 400

        scraped = scrape_tiki(product_url, max_pages=max_pages, per_page=per_page)

        inserted_count = 0
        for r in scraped["reviews"]:
            record = {
                "review_url": scraped["product_url"],
                "title": r.get("title"),
                "review": r.get("content"),
                "rating": r.get("rating"),
                "source": "tiki",
                "metadata": {
                    "product_id": scraped.get("product_id"),
                    "product_name": scraped.get("product_name"),
                    "author": r.get("author"),
                    "created_at": r.get("created_at"),
                    "thank_count": r.get("thank_count"),
                },
            }
            if supabase_wrapper:
                supabase_wrapper.insert("reviews", record)
            else:
                supabase.table("reviews").insert(record).execute()
            inserted_count += 1

        return jsonify({
            "success": True,
            "inserted": inserted_count,
            "product": {
                "product_id": scraped.get("product_id"),
                "product_name": scraped.get("product_name"),
                "average_rating": scraped.get("average_rating"),
                "review_count": scraped.get("review_count"),
                "url": scraped.get("product_url"),
            },
            "reviews": inserted_count,
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500