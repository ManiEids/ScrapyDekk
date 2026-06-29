import json
import re

# -----------------------------
# Helpers
# -----------------------------

def safe_int(val):
    if val is None:
        return None
    try:
        if isinstance(val, str):
            val = val.replace(',', '.')
        return int(float(val))
    except (ValueError, TypeError):
        return None


def normalize_price(price_str):
    """
    Normalize ISK prices to integer.
    Handles all formats encountered across the three sources:
      "18.990 kr"   → 18990   (Klettur formatted)
      "14900.00"    → 14900   (Mitra raw float string)
      "27.995kr."   → 27995   (Nesdekk no space)
      "16.990 kr."  → 16990   (Nesdekk with space)
    """
    if price_str is None:
        return None
    if isinstance(price_str, (int, float)):
        return int(price_str)
    price_str = str(price_str).strip()
    # Remove currency label and whitespace
    price_str = re.sub(r'[a-zA-Z\s]', '', price_str)
    # Normalise decimal separator
    price_str = price_str.replace(',', '.')
    # Strip trailing ".00" (Mitra float strings)
    if price_str.endswith('.00'):
        price_str = price_str[:-3]
    # Remove remaining dots (Icelandic thousands separators: "18.990" → "18990")
    price_str = price_str.replace('.', '')
    try:
        return int(price_str) if price_str else None
    except ValueError:
        return None


def parse_size(size_str):
    """
    Parse passenger tire size string.
    Input:  '205/55R16', '175-65-14', '205/55/16'
    Output: (width_str, aspect_str, rim_str) or (None, None, None)
    """
    if not size_str:
        return None, None, None
    size_str = str(size_str).replace(',', '.')
    # Skip fractional rim sizes (truck: 17.5, 19.5)
    if re.search(r'R\d{2}[.,]\d', size_str):
        return None, None, None
    m = re.search(r'(\d{3})[-/](\d{2,3})[-/R]?(\d{2})', size_str)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None, None, None


def extract_manufacturer_from_name(name):
    """
    Fallback manufacturer extraction from Klettur product names.
    E.g. "205/55R16 S Nexen N-Blue HD Plus Sumardekk 91H" → "Nexen"
    """
    if not name:
        return None
    size_match = re.search(r'\d{3}/\d{2,3}[A-Z]?\d{2}[A-Z]*\s+', name)
    if not size_match:
        return None
    after_size = name[size_match.end():]
    season_match = re.match(r'[A-Z]{1,2}\s+', after_size)
    after_season = after_size[season_match.end():] if season_match else after_size
    parts = after_season.split()
    return parts[0] if parts else None


def normalize_season(season):
    """Standardize season values across sellers."""
    if not season:
        return ""
    s = season.strip().lower()
    if "sumar" in s:
        return "Sumardekk"
    if "vetra" in s or "vetrar" in s:
        return "Vetrardekk"
    if "heils" in s or "all season" in s or "allseason" in s:
        return "Heilsársdekk"
    return season  # return original if unrecognised


def is_valid_tire(item):
    """
    Accept only real passenger car and light-SUV tires.
    """
    width  = item.get("width")
    aspect = item.get("aspect_ratio")
    rim    = item.get("rim_size")
    price  = item.get("price")

    if None in (width, aspect, rim):
        return False
    if not (125 <= width <= 355):
        return False
    if not (25 <= aspect <= 95):
        return False
    if not (12 <= rim <= 24):
        return False
    if price is None or price < 1000:
        return False

    name = (item.get("product_name") or "").lower()
    non_tire_keywords = [
        'slanga', 'ventill', 'felga', 'felgur', 'viðgerð',
        'repair', 'sealant', 'pumpa', 'verkfæri', 'hetta', 'bolti',
    ]
    if any(k in name for k in non_tire_keywords):
        return False

    return True


# -----------------------------
# Main merge logic
# -----------------------------

def main():
    sellers_files = {
        'Klettur':  'klettur.json',
        'Mitra':    'mitra.json',
        'Nesdekk':  'nesdekk.json',
    }

    combined = []

    for seller, filename in sellers_files.items():
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            print(f"⚠️  {filename} not found, skipping.")
            continue
        except json.JSONDecodeError as e:
            print(f"⚠️  {filename} is invalid JSON: {e}")
            continue

        print(f"📂 {seller}: {len(data)} raw items")
        seller_ok = 0

        for item in data:
            inventory = None  # default

            # ── KLETTUR ──────────────────────────────────────────────────
            if seller == 'Klettur':
                width        = item.get('width')
                aspect       = item.get('profile')
                rim          = item.get('rim')
                product_name = item.get('name')
                manufacturer = item.get('manufacturer') or extract_manufacturer_from_name(item.get('name'))
                sku          = item.get('sku')
                season       = normalize_season(item.get('season', ''))
                price        = normalize_price(item.get('price'))
                inventory    = item.get('qty')
                stock        = item.get('stock', 'unknown')
                picture      = item.get('picture') or ''

            # ── MITRA ────────────────────────────────────────────────────
            elif seller == 'Mitra':
                width        = item.get('width')
                aspect       = item.get('profile')
                rim          = item.get('rim')
                product_name = item.get('title')
                manufacturer = item.get('manufacturer')
                sku          = item.get('sku')
                season       = normalize_season(item.get('season', ''))
                price        = normalize_price(item.get('price'))
                inventory    = item.get('inventory')
                stock        = item.get('stock', 'unknown')
                picture      = item.get('picture') or ''

            # ── NESDEKK ──────────────────────────────────────────────────
            # Spider now yields: product_id, sku, name, manufacturer,
            #   season, tyre_size, price, picture, stock, inventory,
            #   stock_text, source
            elif seller == 'Nesdekk':
                width, aspect, rim = parse_size(item.get('tyre_size'))
                product_name = item.get('name')
                manufacturer = item.get('manufacturer')
                sku          = item.get('sku')
                season       = normalize_season(item.get('season', ''))
                price        = normalize_price(item.get('price'))
                inventory    = item.get('inventory')
                raw_stock    = (item.get('stock') or '').lower()
                stock        = 'out of stock' if 'out' in raw_stock else 'in stock'
                picture      = item.get('picture') or ''

            else:
                continue

            tire = {
                "seller":          seller,
                "sku":             sku,
                "manufacturer":    manufacturer,
                "product_name":    product_name,
                "width":           safe_int(width),
                "aspect_ratio":    safe_int(aspect),
                "rim_size":        safe_int(rim),
                "season":          season,
                "price":           price,
                "stock":           stock,
                "inventory_count": safe_int(inventory) if inventory is not None else None,
                "picture":         picture,
                "source":          item.get('source', seller.lower() + '.is'),
            }

            combined.append(tire)
            if is_valid_tire(tire):
                seller_ok += 1

        print(f"   ✅ {seller_ok} valid  |  ❌ {len(data) - seller_ok} filtered")

    filtered = [t for t in combined if is_valid_tire(t)]

    # Stats: season breakdown for the WordPress filter
    season_counts = {}
    for t in filtered:
        season_counts[t["season"] or "(none)"] = season_counts.get(t["season"] or "(none)", 0) + 1

    with open('combined_tire_data.json', 'w', encoding='utf-8') as out:
        json.dump(filtered, out, ensure_ascii=False, indent=2)

    print(f"\n✅ Total kept:    {len(filtered)}")
    print(f"❌ Total dropped: {len(combined) - len(filtered)}")
    print(f"📄 Written to:    combined_tire_data.json")
    print(f"\nSeason breakdown:")
    for s, n in sorted(season_counts.items(), key=lambda x: -x[1]):
        print(f"   {s:18} {n}")


if __name__ == "__main__":
    print("🚀 Running tire merge...")
    main()