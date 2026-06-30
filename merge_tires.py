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


_JUNK_TOKEN_RE = re.compile(r'^\d+([.,]\d+)?"?$')  # e.g. 35, 35", 12,50

def _is_junk_token(tok):
    # Pure number/inch-annotation OR 1-2 uppercase letter season/load code
    return bool(_JUNK_TOKEN_RE.match(tok) or re.match(r'^[A-Z]{1,2}$', tok, re.IGNORECASE))


def extract_manufacturer_from_name(name):
    """
    Fallback manufacturer extraction from Klettur product names.
    Handles metric:   "205/55R16 S Nexen N-Blue HD Plus 91H"       → "Nexen"
    And flotation:    "35x12,50R17 S Zeta Fortrak MT 121Q"         → "Zeta"
    And inch-annot:   "285/75R18 35\" S Goodyear Wrl DuraTrac 129Q" → "Goodyear"
    """
    if not name:
        return None
    size_match = re.search(r'\d{3}/\d{2,3}[A-Z]?\d{2}[A-Z]*\s+', name)
    if not size_match:
        # R is mandatory; allow trailing letter suffix (LT, C, E) before whitespace
        size_match = re.search(r'\d{2}x\d{2}[,.]?\d*R\d{2}[A-Z]*\s+', name, re.IGNORECASE)
    if not size_match:
        return None
    tokens = name[size_match.end():].split()
    for tok in tokens:
        if not _is_junk_token(tok):
            return tok
    return None


# N1 names: "{rim} R {width}/{aspect} {Manufacturer} {rest}"
# E.g. "19 R 245/55 Michelin X-Ice North 4 SUV 107T TL" → "Michelin"
_N1_NAME_RE = re.compile(r'\d+\s+R\s+\d{3}/\d{2,3}\s+(\S+)', re.IGNORECASE)

def extract_manufacturer_from_n1_name(name):
    if not name:
        return None
    m = _N1_NAME_RE.search(name)
    return m.group(1) if m else None


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


# Values that look like a manufacturer but aren't one.
# Matched case-insensitively; any match → manufacturer set to None.
_MFR_JUNK = {
    "annað",    # Icelandic "other / misc"
    "sólað",    # retread category (neutral form)
    "sóluð",    # retread category (feminine form)
    "x",        # single-letter; appears on Michelin X-line tires, not a real brand
    "velocity", # Velocity = wheel brand, all their N1 rows are tire+wheel packages
}

# Tire-size strings accidentally stored as manufacturer.
# Covers metric (130/80-17), flotation (35x12,50R17), and sizes like 35"
_SIZE_AS_MFR_RE = re.compile(r'^\d{2,3}[./x]\d{2,3}|^\d{2,3}"', re.IGNORECASE)

# Flotation/off-road size in product name: 35x12,50R17 / 33x10.50R15 / 37x12,50R20LT
# R is mandatory — bias-ply/turf sizes like "31x15,50-15" (no R) must not match.
# [A-Z]* allows optional LT/C/E load-range suffix directly after rim digits.
_FLOTATION_NAME_RE = re.compile(r'\b\d{2}x\d{2}[,.]?\d*R\d{2}[A-Z]*\b', re.IGNORECASE)

# Extracts the four numeric parts of a flotation size for structured output.
# "37x12,50R20LT" → groups (37, 12, 50, 20)  diameter, width_int, width_frac, rim
_FLOTATION_PARSE_RE = re.compile(r'\b(\d{2})x(\d{2})[,.]?(\d*)R(\d{2})', re.IGNORECASE)

# N1 stores flotation tires in reversed order: "{rim} R {diameter}x{section} {Brand}..."
# E.g. "17 R 37x13.50 BFGoodrich Mud Terrain T/A KM3" → rim=17, dia=37, sec=13.5
_N1_FLOTATION_NAME_RE = re.compile(r'(\d{2})\s+R\s+(\d{2})x(\d{2})[.,]?(\d*)\s', re.IGNORECASE)

# Hyphen-separated sizes without R ("180/70-15", "400/50-15") indicate motorcycle/
# agricultural/turf tires — not radial passenger/jeep tires.
_NON_RADIAL_SIZE_IN_NAME_RE = re.compile(r'\d{3}/\d{2,3}-\d{2}', re.IGNORECASE)

# Truck/commercial rim sizes appear as "R22,5" or "R17,5" in the product name.
# Klettur stores the rim as an integer (22) so the structured rim_size field cannot
# distinguish 22" passenger from 22.5" truck — check the name instead.
_TRUCK_RIM_IN_NAME_RE = re.compile(r'R\d{2}[.,]5\b', re.IGNORECASE)


def is_jeep_tire(item):
    """
    Returns True for flotation/off-road tires.
    These use WIDTHxASPECTRRIM inch sizing, not the standard metric format.
    """
    # Fast path: already classified during tire-dict construction
    if item.get("size_type") == "flotation":
        return True
    # All sellers: flotation size string present in the product name
    if _FLOTATION_NAME_RE.search(item.get("product_name") or ""):
        return True
    # Mitra stores flotation tires as: width = section-width in inches (8–16),
    # aspect_ratio = outer diameter in inches (28–50)
    width  = item.get("width")
    aspect = item.get("aspect_ratio")
    rim    = item.get("rim_size")
    if width is not None and aspect is not None and rim is not None:
        if 8 <= width <= 16 and 28 <= aspect <= 50 and 12 <= rim <= 24:
            return True
    return False

# Canonical name map — keyed on lower-case raw value → correct display name.
_MFR_NORM = {
    # Case variants
    "goodyear":         "Goodyear",
    "goodYear".lower(): "Goodyear",   # "goodyear" — same key, fine
    "gy":               "Goodyear",
    "bridgestone":      "Bridgestone",  # covers BRIDGESTONE
    "bfgoodrich":       "BFGoodrich",   # covers Bfgoodrich + BfGoodrich
    "doublecoin":       "Double Coin",
    # Model name / sub-brand → parent brand
    "dunloptrx":        "Dunlop",
    "sailunice":        "Sailun",
    "atrezzo":          "Sailun",       # Sailun Atrezzo is a product line
    "gt":               "GT Radial",
    # Combined brands → pick primary (cleaner for UI filters)
    "zeta/pace":        "Zeta",
    "landsail/sentury": "Landsail",
    "sonix/ilink":      "Sonix",
    "rapid/aoteli":     "Rapid",
    # Incomplete / abbreviated names
    "c":                "Maxxis",       # Klettur uses "C" for Maxxis commercial tires
    "mickey":           "Mickey Thompson",
    # Brand split — unify under one canonical name
    "cooper":           "Cooper",
    "cooper tires":     "Cooper",
}


def normalize_manufacturer(name):
    if not name or not name.strip():
        return None
    name = name.strip()
    lower = name.lower()
    if lower in _MFR_JUNK:
        return None
    if _SIZE_AS_MFR_RE.match(name):
        return None
    return _MFR_NORM.get(lower, name)



_BLOCKED_MANUFACTURERS = {
    "Westlake",
    "Rapid",
    "Headway",
    "Landsail",
    "Interstate",
    "Tristar",
    "Kormoran",
    "Viking",
    "General",
    "Roadmarch",
    "Maxtrek",
    "Tri-ace",
    "Rockblade",
    "BKT",
    "Goodride",
    "Avon",
    "Mitas",
    "Bandenmarkt",
    "Minerva",
    "Delinte",
    "Double Coin",
    "Superia",
    "Unigrip",
    "HiFly",
    "Aeolus",
    "Golden",
    "Crosswind",
    "Imperial",
    "Maxam",
    "Gripmax",
    "Milestone",
    "Atlas",
    "Duraturn",
    "FireMax",
    "Roadstone",
    "Doublestar",
    "Tracmax",
    "Pearly",
    "Joyroad",
    "Trazano",
    "Albourgh",
    "Trailermaxx",
    "Caliber",
    "Delcora",
}


_NON_TIRE_KEYWORDS = [
    # Accessories / tools
    'slanga', 'ventill', 'felga', 'felgur', 'viðgerð',
    'repair', 'sealant', 'pumpa', 'verkfæri', 'hetta', 'bolti',
    # Tire+wheel packages (Icelandic "með felgu" = "with rim")
    'með felgu',
    # Truck tires
    'vörubíladekk',
    # Retreaded tires in product names (manufacturer normalisation catches the mfr field)
    'sóluð', 'sólað',
    # Non-passenger vehicle categories (Icelandic)
    'mótorhjóladekk',   # motorcycle tire
    'reiðhjóladekk',    # bicycle tire
    'vinnuvéladekk',    # machinery tire
    'sláttuvéladekk',   # lawnmower tire
    'dráttarvéladekk',  # tractor tire
    'hjólbörudekk',     # wheelbarrow tire
    'grasdekk',         # turf / lawn tire
    # Known motorcycle product lines that appear on N1 without Icelandic category words
    'cobra chrome',     # Avon Cobra Chrome (Harley-Davidson)
    'commander iii',    # Michelin Commander III (Harley-Davidson)
    'anakee',           # Michelin Anakee (adventure motorcycle)
    'roadrider',        # Avon Roadrider (classic motorcycle)
    'maxxcross',        # Maxxis MAXXCross (motocross)
]


def is_valid_tire(item):
    price = item.get("price")
    if price is None or price < 1000:
        return False

    name = (item.get("product_name") or "").lower()
    if any(k in name for k in _NON_TIRE_KEYWORDS):
        return False

    mfr = (item.get("manufacturer") or "").lower()
    if mfr in _BLOCKED_MANUFACTURERS:
        return False

    # Klettur stores the truck-tire category as season="Vörubíladekk" in their API.
    # The product name doesn't contain the word, so the keyword check above misses it.
    if "vörubíladekk" in (item.get("season") or "").lower():
        return False

    # Flotation/off-road (jeep) tires bypass metric dimension checks,
    # but only if the inch size actually parsed (else the card renders "NonexNone").
    if is_jeep_tire(item):
        return item.get("width") is not None and item.get("aspect_ratio") is not None

    # Truck/commercial rims appear as R22,5 / R17,5 / R19,5 in the product name.
    # Klettur stores rim as an integer so structured rim_size field alone can't catch them.
    if _TRUCK_RIM_IN_NAME_RE.search(item.get("product_name") or ""):
        return False

    # Null manufacturer + dash-separated size (no R) → motorcycle/agricultural/turf tire
    # that happens to fall within metric dimension ranges. Drop it.
    if item.get("manufacturer") is None:
        pname = item.get("product_name") or ""
        if _NON_RADIAL_SIZE_IN_NAME_RE.search(pname):
            return False

    width  = item.get("width")
    aspect = item.get("aspect_ratio")
    rim    = item.get("rim_size")
    if None in (width, aspect, rim):
        return False
    if not (125 <= width <= 355):
        return False
    if not (25 <= aspect <= 95):
        return False
    if not (12 <= rim <= 24):
        return False
    return True


def drop_reason(item):
    price = item.get("price")
    if price is None or price < 1000:
        return f"price invalid: {price}"

    name = (item.get("product_name") or "").lower()
    for k in _NON_TIRE_KEYWORDS:
        if k in name:
            return f"keyword: {k}"

    mfr = (item.get("manufacturer") or "").lower()
    if mfr in _BLOCKED_MANUFACTURERS:
        return f"blocked manufacturer: {item.get('manufacturer')}"

    if "vörubíladekk" in (item.get("season") or "").lower():
        return "season field is Vörubíladekk (truck tire from Klettur API)"

    if is_jeep_tire(item):
        return "valid jeep tire"  # should not appear in dropped

    if _TRUCK_RIM_IN_NAME_RE.search(item.get("product_name") or ""):
        return "truck/commercial rim size (R17.5/R19.5/R22.5)"

    if item.get("manufacturer") is None:
        pname = item.get("product_name") or ""
        if _NON_RADIAL_SIZE_IN_NAME_RE.search(pname):
            return "no manufacturer + non-radial size (likely non-passenger tire)"

    width  = item.get("width")
    aspect = item.get("aspect_ratio")
    rim    = item.get("rim_size")
    if None in (width, aspect, rim):
        missing = [k for k, v in {"width": width, "aspect_ratio": aspect, "rim_size": rim}.items() if v is None]
        return f"missing: {', '.join(missing)}"
    if not (125 <= width <= 355):
        return f"width out of range: {width}"
    if not (25 <= aspect <= 95):
        return f"aspect_ratio out of range: {aspect}"
    if not (12 <= rim <= 24):
        return f"rim_size out of range: {rim}"
    return "unknown"


# -----------------------------
# Main merge logic
# -----------------------------

def main():
    sellers_files = {
        'Klettur':  'klettur.json',
        'Mitra':    'mitra.json',
        'Nesdekk':  'nesdekk.json',
        'N1':       'n1.json',
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
                raw_mfr      = item.get('manufacturer')
                # Klettur sometimes stores a flotation size (e.g., "35x12,50R17") as
                # the manufacturer field — treat those as missing and extract from name.
                if raw_mfr and re.match(r'^\d{2}x', raw_mfr, re.IGNORECASE):
                    raw_mfr = None
                manufacturer = raw_mfr or extract_manufacturer_from_name(product_name)
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
                tyre_size_str = item.get('tyre_size')
                width, aspect, rim = parse_size(tyre_size_str)
                if width is None:
                    fm_flt = _FLOTATION_PARSE_RE.search(str(tyre_size_str or ''))
                    if fm_flt:
                        frac   = fm_flt.group(3)
                        aspect = int(fm_flt.group(1))
                        width  = round(int(fm_flt.group(2)) + (int(frac) / (10 ** len(frac)) if frac else 0), 2)
                        rim    = int(fm_flt.group(4))
                product_name = item.get('name')
                manufacturer = item.get('manufacturer')
                sku          = item.get('sku')
                season       = normalize_season(item.get('season', ''))
                price        = normalize_price(item.get('price'))
                inventory    = item.get('inventory')
                raw_stock    = (item.get('stock') or '').lower()
                stock        = 'out of stock' if 'out' in raw_stock else 'in stock'
                picture      = item.get('picture') or ''

            # ── N1 ───────────────────────────────────────────────────────
            # Spider yields: name, manufacturer, size ("205/55/16"),
            #   picture, stock, season, price (raw number), category_slug, source
            # No sku, no inventory (spider pre-filters to in-stock only)
            elif seller == 'N1':
                # N1's broad category includes motorcycle/bicycle sub-categories.
                # Slugs are unaccented ASCII so "motordekk", "reidhjol" etc. are safe to check.
                cat_slug = item.get('category_slug', '')
                if any(frag in cat_slug for frag in ('motor', 'reidhjol', 'fjorhjol', 'atv')):
                    continue
                width, aspect, rim = parse_size(item.get('size'))
                product_name = item.get('name')
                if width is None:
                    fm_flt = _N1_FLOTATION_NAME_RE.search(product_name or '')
                    if fm_flt:
                        frac   = fm_flt.group(4)
                        rim    = int(fm_flt.group(1))
                        aspect = int(fm_flt.group(2))
                        width  = round(int(fm_flt.group(3)) + (int(frac) / (10 ** len(frac)) if frac else 0), 2)
                manufacturer = item.get('manufacturer') or extract_manufacturer_from_n1_name(product_name)
                sku          = None
                season       = normalize_season(item.get('season', ''))
                price        = normalize_price(item.get('price'))
                stock        = item.get('stock', 'in stock')
                picture      = item.get('picture') or ''

            else:
                continue

            tire = {
                "seller":          seller,
                "sku":             sku,
                "manufacturer":    normalize_manufacturer(manufacturer),
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

            # Flotation/off-road tires: tag, override season, and map to standard fields.
            # width = section width in inches (e.g. 12), aspect_ratio = outer diameter in
            # inches (e.g. 33), so the WordPress card renders "33x12.50R18" correctly.
            if is_jeep_tire(tire):
                tire["season"]    = "Jeppadekk"
                tire["size_type"] = "flotation"
                fm = _FLOTATION_PARSE_RE.search(tire.get("product_name") or "")
                if fm:
                    frac = fm.group(3)
                    tire["aspect_ratio"] = int(fm.group(1))
                    tire["width"]        = round(int(fm.group(2)) + (int(frac) / (10 ** len(frac)) if frac else 0), 2)
                    tire["rim_size"]     = int(fm.group(4))
                elif seller in ("Mitra", "Nesdekk", "N1"):
                    # width/aspect/rim were set correctly in the seller block
                    # (section_width_inches / outer_diameter_inches / rim_inches).
                    # Restore float precision — safe_int() truncated them.
                    tire["width"]        = width
                    tire["aspect_ratio"] = aspect
                    tire["rim_size"]     = rim
                else:
                    tire["width"]        = None
                    tire["aspect_ratio"] = None
            else:
                tire["size_type"] = "metric"

            combined.append(tire)
            if is_valid_tire(tire):
                seller_ok += 1

        print(f"   ✅ {seller_ok} valid  |  ❌ {len(data) - seller_ok} filtered")

    filtered = [t for t in combined if is_valid_tire(t)]
    dropped  = [dict(t, _drop_reason=drop_reason(t)) for t in combined if not is_valid_tire(t)]

    # Stats: season breakdown for the WordPress filter
    season_counts = {}
    for t in filtered:
        season_counts[t["season"] or "(none)"] = season_counts.get(t["season"] or "(none)", 0) + 1

    with open('combined_tire_data.json', 'w', encoding='utf-8') as out:
        json.dump(filtered, out, ensure_ascii=False, indent=2)

    with open('dropped_tire_data.json', 'w', encoding='utf-8') as out:
        json.dump(dropped, out, ensure_ascii=False, indent=2)

    print(f"\n✅ Total kept:    {len(filtered)}")
    print(f"❌ Total dropped: {len(dropped)}  → dropped_tire_data.json")
    print(f"📄 Written to:    combined_tire_data.json")
    print(f"\nSeason breakdown:")
    for s, n in sorted(season_counts.items(), key=lambda x: -x[1]):
        print(f"   {s:18} {n}")


if __name__ == "__main__":
    print("🚀 Running tire merge...")
    main()