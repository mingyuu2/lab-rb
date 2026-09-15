import json
from pathlib import Path

_DATA_PATH = Path(__file__).parent / "data" / "products.json"
PRODUCTS = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
CATEGORIES = sorted({p["category"] for p in PRODUCTS})


def get_products(category=None):
    if category:
        return [p for p in PRODUCTS if p["category"] == category]
    return PRODUCTS


def get_categories():
    return CATEGORIES


def get_product(product_id):
    for p in PRODUCTS:
        if p["id"] == product_id:
            return p
    return None
