import json
import unicodedata
from pathlib import Path

_DATA_PATH = Path(__file__).parent / "data" / "products.json"
PRODUCTS = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
CATEGORIES = sorted({p["category"] for p in PRODUCTS})


def get_products(category=None, query=""):
    terms = unicodedata.normalize("NFKC", query).casefold().split()
    products = PRODUCTS
    if category:
        products = [p for p in products if p["category"] == category]
    if terms:
        products = [
            p for p in products
            if all(
                term in unicodedata.normalize(
                    "NFKC", " ".join((p["name"], p["description"], p["category"]))
                ).casefold()
                for term in terms
            )
        ]
    return products


def get_categories():
    return CATEGORIES


def get_product(product_id):
    for p in PRODUCTS:
        if p["id"] == product_id:
            return p
    return None
