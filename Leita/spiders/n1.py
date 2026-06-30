import scrapy
import json
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


def extract_attribute_value(attributes, slug):
    for attr in attributes:
        if attr.get("attribute", {}).get("slug") == slug:
            values = attr.get("values", [])
            if values:
                return values[0].get("value")
    return None


def extract_picture(variants):
    for variant in variants:
        media_list = variant.get("media", [])
        if media_list:
            image_info = media_list[0].get("image", {})
            return image_info.get("productList") or image_info.get("productGallery")
    return None


def get_first_variant_sku(product):
    variants = product.get("variants", [])
    if variants:
        metadata = variants[0].get("metadata", {})
        return metadata.get("sku")
    return None


def is_in_stock(product):
    variants = product.get("variants", [])
    for variant in variants:
        stock = variant.get("stockLevel", {}).get("stockLevel", "").lower()
        if stock and stock != "out of stock":
            return True
    return False


class N1FullCatalogueSpider(scrapy.Spider):
    name = "n1"
    allowed_domains = ["backend.n1.is"]

    API_URL = "https://backend.n1.is/api/products/attribute_filter/?page_size=24&page=1"

    # Broad category that was confirmed working.
    CATEGORY_SLUG = "004-hjolbardar-og-tengdar-vorur"

    # Map substrings of product.category.slug → season label.
    SLUG_SEASON_MAP = {
        "sumardekk":   "Sumardekk",
        "vetrardekk":  "Vetrardekk",
        "heilsarsdekk": "Heilsársdekk",
    }

    # Sub-strings of category slug that identify non-passenger-tire products.
    # Checked before the multiprice request so we skip both the request and the item.
    # N1 slugs are ASCII/unaccented, so "motor" matches "motordekk", etc.
    SKIP_SLUG_FRAGMENTS = frozenset({
        "motor",      # motorcycle tires
        "reidhjol",   # bicycle tires
        "fjorhjol",   # ATV / quad
        "atv",
        "vinnuvela",  # machinery tires
        "slaettuvela", # lawnmower tires
        "grasdekk",   # turf / lawn tires
        "felg",       # rims / wheels (felgur)
        "voru",       # vörubíladekk (truck tires) — "voru" prefix in slug
        "slanga",     # inner tubes
        "ventill",    # valves / accessories
    })

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Content-Type": "application/json",
        "Origin": "https://vefverslun.n1.is",
        "Referer": "https://vefverslun.n1.is/voruflokkur/hjolbardar-og-tengdar-vorur",
        "Accept": "*/*",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_skus = set()

    def start_requests(self):
        payload = json.dumps({"attributes": [], "categorySlug": self.CATEGORY_SLUG})
        yield scrapy.Request(
            url=self.API_URL,
            method="POST",
            headers=self.HEADERS,
            body=payload,
            callback=self.parse,
            meta={
                "payload_headers": self.HEADERS,
                "payload_body": payload,
            },
        )

    def parse(self, response):
        self.logger.info(f"Response {response.status} — {response.url}")
        try:
            data = response.json()
        except Exception as e:
            self.logger.error(f"JSON error: {e}")
            return

        results = data.get("results", [])

        candidate_products = []
        skus = []

        for product in results:
            if not is_in_stock(product):
                continue

            sku = get_first_variant_sku(product)
            if not sku or sku in self.seen_skus:
                continue
            self.seen_skus.add(sku)

            product_name = product.get("name")
            attributes = product.get("attributes", [])
            manufacturer = extract_attribute_value(attributes, "ProductManufacturer")

            width    = extract_attribute_value(attributes, "ProductTireSectionWidthName")
            profile  = extract_attribute_value(attributes, "ProductTireTreadProfile")
            sidewall = extract_attribute_value(attributes, "ProductTireSidewallSize")
            size = f"{width}/{profile}/{sidewall}" if (width and profile and sidewall) else None

            variants = product.get("variants", [])
            picture = extract_picture(variants)

            # Resolve category slug and skip non-passenger categories immediately —
            # before the multiprice request — so we pay for those API calls only
            # for items we'll actually keep.
            cat_slug = (product.get("category") or {}).get("slug", "").lower()
            if any(frag in cat_slug for frag in self.SKIP_SLUG_FRAGMENTS):
                continue

            season = ""
            for key, label in self.SLUG_SEASON_MAP.items():
                if key in cat_slug:
                    season = label
                    break

            candidate_products.append({
                "name":          product_name,
                "manufacturer":  manufacturer,
                "size":          size,
                "picture":       picture,
                "stock":         "in stock",
                "season":        season,
                "sku":           sku,
                "category_slug": cat_slug,
            })
            skus.append(sku)

        if skus:
            multiprice_url = (
                "https://backend.n1.is/api/products/multiprice/?"
                + "&".join(f"skus={sku}" for sku in skus)
            )
            yield scrapy.Request(
                url=multiprice_url,
                callback=self.parse_multiprice,
                meta={"products": candidate_products},
            )

        # Pagination
        parsed = urlparse(response.url)
        qs = parse_qs(parsed.query)
        current_page = int(qs.get("page", [1])[0])
        if results:
            qs["page"] = [str(current_page + 1)]
            next_url = urlunparse((
                parsed.scheme, parsed.netloc, parsed.path,
                parsed.params, urlencode(qs, doseq=True), parsed.fragment,
            ))
            yield scrapy.Request(
                url=next_url,
                method="POST",
                headers=response.meta["payload_headers"],
                body=response.meta["payload_body"],
                callback=self.parse,
                meta=response.meta,
            )

    def parse_multiprice(self, response):
        try:
            price_data = response.json()
        except Exception as e:
            self.logger.error(f"Multiprice JSON error: {e}")
            return

        price_map = {entry.get("itemId"): entry for entry in price_data}

        for prod in response.meta["products"]:
            sku = prod.pop("sku", None)
            price_info = price_map.get(sku)
            prod["price"] = price_info.get("price", "N/A") if price_info else "N/A"
            prod["source"] = "n1.is"
            yield prod
