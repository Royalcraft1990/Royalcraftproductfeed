"""
Royalcraft → ufurnish.com / Awin product feed generator
Fetches live data from Shopify public storefront API and writes
a CSV formatted to the ufurnish.com data feed standard.

Output: ufurnish_feed.csv  (merchant_category column for Awin mapping)
"""

import csv
import html
import json
import re
import urllib.request

# ── Config ────────────────────────────────────────────────────────────────────
STORE_URL   = "https://royalcraftstore.myshopify.com"
STORE_FRONT = "https://www.royalcraft.co.uk"
TARGET_VENDOR = "Royalcraft"          # exact match only
OUTPUT_FILE   = "ufurnish_feed.csv"


# ── Category mapping (Shopify product_type → ufurnish category path) ─────────
CATEGORY_MAP = {
    "Outdoor Furniture":   "Garden Furniture",
    "Outdoor Chairs":      "Garden Furniture > Garden Chairs",
    "Sun Lounger":         "Garden Furniture > Sun Loungers",
    "Parasols":            "Garden Furniture > Parasols & Accessories",
    "Parasol Bases":       "Garden Furniture > Parasols & Accessories",
    "Gazebos":             "Garden Furniture > Garden Buildings > Gazebos",
    "Outdoor Storage Box": "Garden Storage > Storage Boxes",
    "Dining set":          "Home Furniture > Dining Room Furniture > Dining Sets",
    "Dining Table":        "Home Furniture > Dining Room Furniture > Dining Tables",
    "Dining":              "Home Furniture > Dining Room Furniture",
    "Chairs":              "Home Furniture > Dining Room Furniture > Dining Chairs",
    "Dining Chair":        "Home Furniture > Dining Room Furniture > Dining Chairs",
    "Sofa":                "Home Furniture > Sofas & Armchairs > Sofas",
    "Corner Sofa":         "Home Furniture > Sofas & Armchairs > Corner Sofas",
    "Sofa Bed":            "Home Furniture > Sofas & Armchairs > Sofa Beds",
    "Armchair":            "Home Furniture > Sofas & Armchairs > Armchairs",
    "Rocking Chair":       "Home Furniture > Sofas & Armchairs > Rocking Chairs",
    "Footstool":           "Home Furniture > Sofas & Armchairs > Footstools",
    "Stool":               "Home Furniture > Sofas & Armchairs > Stools",
    "Coffee Table":        "Home Furniture > Living Room Furniture > Coffee Tables",
    "Side Table":          "Home Furniture > Living Room Furniture > Side Tables",
    "Console Table":       "Home Furniture > Hallway Furniture > Console Tables",
    "Console table":       "Home Furniture > Hallway Furniture > Console Tables",
    "console table":       "Home Furniture > Hallway Furniture > Console Tables",
    "Sideboard":           "Home Furniture > Dining Room Furniture > Sideboards",
    "Shelving Unit":       "Home Furniture > Storage > Shelving Units",
    "Drawers":             "Home Furniture > Storage > Drawers & Chests",
    "Benches":             "Home Furniture > Hallway Furniture > Benches",
    "Mirrors":             "Home Accessories > Mirrors > Wall Mirrors",
    "Wall Art":            "Home Accessories > Wall Art",
    "Rug":                 "Home Accessories > Rugs",
    "Indoor Rug":          "Home Accessories > Rugs",
    "Indoor/Outdoor Rug":  "Home Accessories > Rugs",
    "Plant Pots":          "Home Accessories > Plant Pots & Planters",
    "Table lamp":          "Home Accessories > Lighting > Table Lamps",
    "Floor Lamps":         "Home Accessories > Lighting > Floor Lamps",
    "Sculpture":           "Home Accessories > Sculptures & Ornaments",
    "Bookends":            "Home Accessories > Bookends",
    "Baskets":             "Home Accessories > Storage Baskets",
    "Indoor Decor":        "Home Accessories",
    "Indoor Furniture":    "Home Furniture",
    "Accessories":         "Home Accessories",
    "Living":              "Home Furniture > Living Room Furniture",
    "Sleeping":            "Home Furniture > Bedroom Furniture",
    "Gift Card":           "",   # excluded
    "":                    "Home Furniture",
}

# ── Colour helpers ────────────────────────────────────────────────────────────
UFURNISH_COLOURS = [
    "Red","White","Grey","Orange","Silver","Black","Yellow",
    "Blue","Brown","Gold","Navy","Beige","Purple","Pink",
    "Green","Natural","Cream","Taupe","Charcoal","Stone",
]
COLOUR_ALIASES = {
    "gray":"Grey","dark grey":"Grey","light grey":"Grey","graphite":"Grey",
    "charcoal":"Charcoal","ivory":"Cream","cream":"Cream","off white":"White",
    "off-white":"White","natural":"Natural","oak":"Natural","teak":"Brown",
    "sand":"Beige","taupe":"Taupe","bronze":"Brown","copper":"Gold",
    "rattan":"Brown","wicker":"Brown","rust":"Orange","terracotta":"Orange",
    "slate":"Grey","smoke":"Grey","light blue":"Blue","dark blue":"Blue",
    "olive":"Green","sage":"Green","forest":"Green","stone":"Stone",
}

def extract_colour(tags, title, option_vals):
    text = " ".join([t.lower() for t in tags] + [title.lower()]
                    + [v.lower() for v in option_vals if v])
    found = []
    for c in UFURNISH_COLOURS:
        if c.lower() in text and c not in found:
            found.append(c)
    for alias, mapped in COLOUR_ALIASES.items():
        if alias in text and mapped not in found:
            found.append(mapped)
    return ", ".join(found[:3])

# ── Material helpers ──────────────────────────────────────────────────────────
MATERIAL_ALIASES = {
    "rattan":"Metal","wicker":"Metal","aluminium":"Metal","aluminum":"Metal",
    "steel":"Metal","iron":"Iron","brass":"Brass","wood":"Wood","oak":"Wood",
    "pine":"Wood","teak":"Wood","mdf":"Wood","timber":"Wood","hardwood":"Wood",
    "glass":"Glass","marble":"Marble","granite":"Stone","stone":"Stone",
    "concrete":"Concrete","porcelain":"Porcelain","ceramic":"Porcelain",
    "leather":"Leather","faux leather":"Faux Leather","pu leather":"Faux Leather",
    "velvet":"Velvet","polyester":"Polyester","polyrattan":"Plastic",
    "plastic":"Plastic","resin":"Plastic","fabric":"Fabric","linen":"Fabric",
    "cotton":"Cotton","wool":"Wool","silk":"Silk",
}

def extract_material(tags, title, description):
    text = " ".join([t.lower() for t in tags] + [title.lower()]
                    + [description.lower()[:300]])
    found = []
    for alias, mapped in MATERIAL_ALIASES.items():
        if alias in text and mapped not in found:
            found.append(mapped)
    return found[0] if found else ""

# ── Dimension extraction ──────────────────────────────────────────────────────
def extract_dims(variant_title):
    m = re.search(r"(\d+)\s*[xX×]\s*(\d+)\s*cm", variant_title or "")
    if m:
        return m.group(1), m.group(2), "cm"
    return "", "", ""

# ── HTML → plain text ─────────────────────────────────────────────────────────
def strip_html(raw):
    if not raw:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    text = re.sub(r"</p>", "\n", text, flags=re.I)
    text = re.sub(r"</li>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

# ── Fetch all products from Shopify public API ────────────────────────────────
def fetch_products():
    products = []
    page = 1
    while True:
        url = f"{STORE_URL}/products.json?limit=250&page={page}"
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read())
        batch = data["products"]
        products.extend(batch)
        print(f"  Page {page}: {len(batch)} products (total: {len(products)})")
        if len(batch) < 250:
            break
        page += 1
    return products

# ── Build CSV rows ────────────────────────────────────────────────────────────
FIELDNAMES = [
    "id","title","link","description","in_stock","price","merchant_category",
    "image_url_1","image_url_2","image_url_3","image_url_4","image_url_5","image_url_6",
    "rrp","colours","material","brand","weight",
    "width","length","dimension_qualifier",
    "Mpn","Ean","Upc","Gtin",
    "parent_id","delivery","delivery_price","delivery_time","return_details",
]

def build_rows(products):
    rows = []
    for product in products:
        if product.get("vendor") != TARGET_VENDOR:
            continue

        ptype    = product.get("product_type", "")
        category = CATEGORY_MAP.get(ptype, "Home Furniture")
        if not category:          # gift cards etc.
            continue

        title       = product["title"]
        handle      = product["handle"]
        link        = f"{STORE_FRONT}/products/{handle}"
        description = strip_html(product.get("body_html", "") or "") or title
        tags        = product.get("tags", [])
        images      = [img["src"] for img in product.get("images", [])[:6]]
        parent_id   = str(product["id"])

        delivery       = "Free Delivery" if any(t.lower() in ("free delivery","free-delivery") for t in tags) else "Standard Delivery"
        delivery_price = "0.00" if delivery == "Free Delivery" else ""

        for variant in product["variants"]:
            sku       = variant.get("sku") or str(variant["id"])
            price     = variant.get("price", "0.00")
            rrp       = variant.get("compare_at_price") or ""
            available = variant.get("available", False)
            grams     = variant.get("grams") or 0
            barcode   = variant.get("barcode") or ""

            opt1, opt2, opt3 = (variant.get(f"option{i}") or "" for i in (1, 2, 3))

            # Variant title
            v_title = title
            if opt1 and opt1 not in ("Default Title", "Default"):
                v_title = f"{title} - {opt1}"
                if opt2 and opt2 != "Default Title":
                    v_title += f" {opt2}"

            # Variant-specific image first, then product images
            vi = variant.get("featured_image")
            if vi and vi.get("src"):
                img_list = [vi["src"]] + [u for u in images if u != vi["src"]]
            else:
                img_list = images[:]
            while len(img_list) < 6:
                img_list.append("")

            width, length, dim_q = extract_dims(opt1 or opt2 or opt3)

            rows.append({
                "id":                  sku,
                "title":               v_title,
                "link":                link,
                "description":         description,
                "in_stock":            "Y" if available else "N",
                "price":               price,
                "merchant_category":   category,
                "image_url_1":         img_list[0],
                "image_url_2":         img_list[1],
                "image_url_3":         img_list[2],
                "image_url_4":         img_list[3],
                "image_url_5":         img_list[4],
                "image_url_6":         img_list[5],
                "rrp":                 rrp,
                "colours":             extract_colour(tags, v_title, [opt1, opt2, opt3]),
                "material":            extract_material(tags, v_title, description),
                "brand":               "Royalcraft",
                "weight":              f"{grams / 1000:.2f}" if grams else "",
                "width":               width,
                "length":              length,
                "dimension_qualifier": dim_q,
                "Mpn":                 sku,
                "Ean":                 barcode if len(barcode) == 13 else "",
                "Upc":                 barcode if len(barcode) == 12 else "",
                "Gtin":                barcode if len(barcode) in (8, 12, 13, 14) else "",
                "parent_id":           parent_id if len(product["variants"]) > 1 else "",
                "delivery":            delivery,
                "delivery_price":      delivery_price,
                "delivery_time":       "3-5 working days",
                "return_details":      "30 day returns",
            })
    return rows


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Fetching products from Shopify...")
    products = fetch_products()
    print(f"Total products fetched: {len(products)}")

    print("Building feed rows...")
    rows = build_rows(products)
    print(f"Royalcraft rows: {len(rows)}")

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Feed written to {OUTPUT_FILE}")

    # Quick validation
    missing = [r["id"] for r in rows if not r.get("image_url_1")]
    if missing:
        print(f"WARNING: {len(missing)} rows missing image_url_1: {missing[:5]}")
    else:
        print("All rows have image_url_1 ✓")
