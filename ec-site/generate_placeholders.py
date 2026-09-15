"""One-time generator for local SVG placeholder product images.

Run manually with `python3 generate_placeholders.py` whenever data/products.json
changes; the output under static/img/products/ is checked into the repo like
any other static asset, not regenerated at build/run time.
"""
import json
from pathlib import Path

BASE = Path(__file__).parent
PRODUCTS_PATH = BASE / "data" / "products.json"
OUT_DIR = BASE / "static" / "img" / "products"

CATEGORY_COLORS = {
    "電子機器": "#6366F1",
    "ファッション/衣料": "#8B5CF6",
    "ホーム/リビング": "#0EA5E9",
    "ビューティー": "#EC4899",
    "スポーツ/アウトドア": "#10B981",
    "本/文具": "#F59E0B",
}

SVG_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="480" height="480" viewBox="0 0 480 480">
  <rect width="480" height="480" fill="{color}"/>
  <rect x="24" y="24" width="432" height="432" rx="16" fill="{color}" fill-opacity="0.15"/>
  <text x="240" y="250" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
        font-size="28" font-weight="600" fill="#FFFFFF" text-anchor="middle">{name}</text>
  <text x="240" y="286" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
        font-size="16" fill="#FFFFFF" fill-opacity="0.85" text-anchor="middle">{category}</text>
</svg>
"""


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    products = json.loads(PRODUCTS_PATH.read_text(encoding="utf-8"))
    for p in products:
        color = CATEGORY_COLORS.get(p["category"], "#6366F1")
        svg = SVG_TEMPLATE.format(color=color, name=p["name"], category=p["category"])
        out_path = OUT_DIR / p["image"]
        out_path.write_text(svg, encoding="utf-8")
    print(f"generated {len(products)} placeholder SVGs in {OUT_DIR}")


if __name__ == "__main__":
    main()
