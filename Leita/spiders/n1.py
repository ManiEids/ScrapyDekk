"""
N1 Algolia Spider

What it does:
- Reads N1 tire products from N1's public Algolia search index.
- Splits large searches by season, rim, width, and profile so Algolia's 1000-hit pagination cap is avoided.
- Emits the raw N1 format already expected by merge_tires.py.

Input:
- Public Algolia app id/search key and PROD_PRODUCTS index.

Output item fields:
- name, manufacturer, size, picture, stock, season, price, sku, category_slug, source
"""

import json
import os
import re
from urllib.parse import urlencode

import scrapy


APP_ID = os.environ.get("N1_ALGOLIA_APP_ID", "LU6HO9UFWF")
API_KEY = os.environ.get("N1_ALGOLIA_SEARCH_KEY", "1fc8f9f8099e352754bc2d197f6f12a8")
INDEX_NAME = os.environ.get("N1_ALGOLIA_INDEX", "PROD_PRODUCTS")
ALGOLIA_HOST = f"{APP_ID.lower()}-dsn.algolia.net"


class N1AlgoliaSpider(scrapy.Spider):
    name = "n1"

    allowed_domains = [
        ALGOLIA_HOST,
        f"{APP_ID.lower()}.algolia.net",
    ]

    ALGOLIA_URL = f"https://{ALGOLIA_HOST}/1/indexes/{INDEX_NAME}/query"

    CATEGORY_LVL1 = "Hjólbarðar og tengdar vörur > Fólksbíla- og jeppadekk"
    CATEGORY_LVL2_VALUES = [
        "Hjólbarðar og tengdar vörur > Fólksbíla- og jeppadekk > Sumardekk",
        "Hjólbarðar og tengdar vörur > Fólksbíla- og jeppadekk > Vetrardekk",
        "Hjólbarðar og tengdar vörur > Fólksbíla- og jeppadekk > Heilsársdekk",
    ]

    RIM_VALUES = [str(n) for n in range(12, 25)]

    METRIC_WIDTH_VALUES = [
        "125", "135", "145", "155", "165", "175", "185", "195",
        "205", "215", "225", "235", "245", "255", "265", "275",
        "285", "295", "305", "315", "325", "335", "345", "355",
    ]

    METRIC_PROFILE_VALUES = [
        "25", "30", "35", "40", "45", "50", "55", "60",
        "65", "70", "75", "80", "85", "90", "95",
    ]

    # Flotation/off-road sizes can appear in Algolia facets as inch values.
    # Examples: 33x12.5R15 may be stored as diameter=33 and/or section=12.5.
    INCH_DIAMETER_VALUES = [str(n) for n in range(28, 45)]
    INCH_SECTION_VALUES = [
        "8", "8.5", "9", "9.5", "10", "10.5", "11", "11.5",
        "12", "12.5", "13", "13.5", "14", "14.5", "15", "15.5", "16",
        "8,5", "9,5", "10,5", "11,5", "12,5", "13,5", "14,5", "15,5",
    ]

    WIDTH_VALUES = METRIC_WIDTH_VALUES + INCH_DIAMETER_VALUES + INCH_SECTION_VALUES
    PROFILE_VALUES = METRIC_PROFILE_VALUES + INCH_DIAMETER_VALUES + INCH_SECTION_VALUES

    # Start with the passenger/jeep category, then split by tire dimensions.
    # This avoids Algolia's 1000-hit retrieval cap without needing backend.n1.is.
    SPLIT_STEPS = [
        ("hierarchical_categories.lvl2", CATEGORY_LVL2_VALUES),
        ("attributes.ProductTireSidewallSize", RIM_VALUES),
        ("attributes.ProductTireSectionWidthName", WIDTH_VALUES),
        ("attributes.ProductTireTreadProfile", PROFILE_VALUES),
    ]

    MAX_ALGOLIA_RETRIEVABLE_HITS = 1000
    HITS_PER_PAGE = 1000

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "CONCURRENT_REQUESTS": 4,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
        "DOWNLOAD_DELAY": 0.05,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 0.2,
        "AUTOTHROTTLE_MAX_DELAY": 2.0,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 4,
        "RETRY_HTTP_CODES": [408, 429, 500, 502, 503, 504],
        "DOWNLOAD_TIMEOUT": 30,
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Algolia-Application-Id": APP_ID,
            "X-Algolia-API-Key": API_KEY,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        },
    }

    METRIC_NAME_RE = re.compile(
        r"^\s*(?P<rim>\d{2})\s+R\s+(?P<width>\d{3})/(?P<profile>\d{2,3})\b",
        re.IGNORECASE,
    )
    FLOTATION_NAME_RE = re.compile(
        r"^\s*(?P<rim>\d{2})\s+R\s+(?P<diameter>\d{2})x(?P<section>\d{1,2}(?:[.,]\d+)?)\b",
        re.IGNORECASE,
    )
    SIZE_PREFIX_RE = re.compile(
        r"^\s*\d{2}\s+R\s+(?:\d{3}/\d{2,3}|\d{2}x\d{2}(?:[.,]\d+)?)\s+",
        re.IGNORECASE,
    )

    MULTI_WORD_BRANDS = [
        "Mickey Thompson",
        "Double Coin",
        "GT Radial",
        "General Tire",
        "BF Goodrich",
    ]

    SKIP_CATEGORY_WORDS = [
        "mótorhjóladekk",
        "motorhjóladekk",
        "reiðhjóladekk",
        "reidhjol",
        "fjórhjól",
        "fjorhjol",
        "atv",
        "sláttuvél",
        "slaettuvel",
        "vinnuvél",
        "vinnuvel",
        "dráttarvél",
        "drattarvel",
        "felgur",
        "slöngur",
        "slongur",
        "ventlar",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_object_ids = set()
        self.seen_skus = set()

    def start_requests(self):
        base_filters = [f"hierarchical_categories.lvl1:{self.CATEGORY_LVL1}"]
        yield self._make_request(filters=base_filters, page=0, split_depth=0)

    def _make_request(self, filters, page, split_depth):
        params = {
            "query": "",
            "page": page,
            "hitsPerPage": self.HITS_PER_PAGE,
            "analytics": "false",
            "clickAnalytics": "false",
            "getRankingInfo": "false",
            "facetFilters": json.dumps(filters, ensure_ascii=False),
            "attributesToRetrieve": json.dumps([
                "sku",
                "name",
                "categories",
                "hierarchical_categories",
                "attributes",
                "media",
                "price",
                "stock_level",
                "stock_level_stores",
                "variants_stock_levels",
                "objectID",
            ]),
        }

        body = json.dumps({"params": urlencode(params, doseq=True)})

        return scrapy.Request(
            url=self.ALGOLIA_URL,
            method="POST",
            body=body,
            callback=self.parse_search,
            errback=self.errback_log,
            dont_filter=True,
            meta={
                "filters": filters,
                "page": page,
                "split_depth": split_depth,
            },
        )

    def parse_search(self, response):
        filters = response.meta["filters"]
        page = response.meta["page"]
        split_depth = response.meta["split_depth"]

        try:
            data = response.json()
        except Exception as exc:
            self.logger.error("N1 Algolia JSON error: %s. Body preview: %r", exc, response.text[:500])
            return

        if data.get("message"):
            self.logger.error("N1 Algolia error: %s", data.get("message"))
            return

        nb_hits = int(data.get("nbHits") or 0)
        nb_pages = int(data.get("nbPages") or 0)
        hits = data.get("hits") or []

        self.logger.info(
            "N1 slice page=%s hits=%s nbHits=%s filters=%s",
            page,
            len(hits),
            nb_hits,
            filters,
        )

        if page == 0 and nb_hits > self.MAX_ALGOLIA_RETRIEVABLE_HITS:
            if split_depth < len(self.SPLIT_STEPS):
                facet_name, values = self.SPLIT_STEPS[split_depth]
                self.logger.info(
                    "N1 slice too large (%s). Splitting by %s into %s slices.",
                    nb_hits,
                    facet_name,
                    len(values),
                )
                for value in values:
                    yield self._make_request(
                        filters=filters + [f"{facet_name}:{value}"],
                        page=0,
                        split_depth=split_depth + 1,
                    )
                return

            self.logger.warning(
                "N1 slice still has %s hits after all split levels. "
                "Only the first %s can be reached by Algolia pagination.",
                nb_hits,
                self.MAX_ALGOLIA_RETRIEVABLE_HITS,
            )

        for hit in hits:
            item = self._hit_to_item(hit)
            if item:
                yield item

        if page == 0 and nb_pages > 1:
            max_pages = min(
                nb_pages,
                (self.MAX_ALGOLIA_RETRIEVABLE_HITS + self.HITS_PER_PAGE - 1) // self.HITS_PER_PAGE,
            )
            for next_page in range(1, max_pages):
                yield self._make_request(
                    filters=filters,
                    page=next_page,
                    split_depth=split_depth,
                )

    def _hit_to_item(self, hit):
        object_id = str(hit.get("objectID") or "").strip()
        sku = str(hit.get("sku") or object_id).strip()

        dedupe_key = sku or object_id
        if dedupe_key in self.seen_skus:
            return None

        name = (hit.get("name") or "").strip()
        if not name:
            return None

        categories = hit.get("categories") or []
        category_text = " > ".join(str(c) for c in categories).lower()
        if any(word in category_text for word in self.SKIP_CATEGORY_WORDS):
            return None

        if self.CATEGORY_LVL1.lower() not in category_text:
            return None

        stock = (hit.get("stock_level") or "").strip().lower()
        if not stock or stock == "out of stock":
            return None

        price = self._clean_price(hit.get("price"))
        if price is None:
            return None

        attributes = hit.get("attributes") or {}
        width = self._clean_dimension(attributes.get("ProductTireSectionWidthName"))
        profile = self._clean_dimension(attributes.get("ProductTireTreadProfile"))
        rim = self._clean_dimension(attributes.get("ProductTireSidewallSize"))

        size_type = "metric"
        flotation_size = self._flotation_size_from_name(name)
        if flotation_size:
            # Prefer the product-name flotation size over Algolia tire attributes.
            # N1 names are rim-first: "15 R 33X12.5 Brand...".
            # The canonical value below is easier to debug: "33x12.5R15".
            size = flotation_size
            size_type = "flotation"
        elif width and profile and rim:
            size = f"{width}/{profile}/{rim}"
        else:
            size = self._metric_size_from_name(name)

        season = self._season_from_hit(hit)
        manufacturer = self._manufacturer_from_name(name)
        picture = self._picture_from_media(hit.get("media") or [])

        self.seen_skus.add(dedupe_key)
        if object_id:
            self.seen_object_ids.add(object_id)

        return {
            "name": name,
            "manufacturer": manufacturer,
            "size": size,
            "size_type": size_type,
            "picture": picture,
            "stock": stock,
            "season": season,
            "price": price,
            "sku": sku,
            "category_slug": category_text,
            "source": "n1.is",
        }

    def _clean_price(self, value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)

        text = str(value).strip().lower()
        text = text.replace("kr", "").replace("isk", "").strip()
        text = text.replace(" ", "")

        if text.endswith(".00"):
            text = text[:-3]

        # Icelandic thousands separator: 61.990 -> 61990
        # Decimal comma is not expected from N1, but normalize it safely.
        text = text.replace(".", "").replace(",", ".")

        try:
            return int(float(text))
        except (TypeError, ValueError):
            return None

    def _clean_dimension(self, value):
        if value is None:
            return None
        value = str(value).strip().replace(",", ".")
        return value or None

    def _metric_size_from_name(self, name):
        metric = self.METRIC_NAME_RE.search(name)
        if metric:
            return f"{metric.group('width')}/{metric.group('profile')}/{metric.group('rim')}"
        return None

    def _flotation_size_from_name(self, name):
        match = self.FLOTATION_NAME_RE.search(name)
        if not match:
            return None

        rim = match.group("rim")
        diameter = match.group("diameter")
        section = match.group("section").replace(",", ".")
        return f"{diameter}x{section}R{rim}"

    def _manufacturer_from_name(self, name):
        rest = self.SIZE_PREFIX_RE.sub("", name, count=1).strip()
        if not rest:
            return None

        rest_lower = rest.lower()
        for brand in self.MULTI_WORD_BRANDS:
            if rest_lower.startswith(brand.lower()):
                return brand.replace(" ", "") if brand == "BF Goodrich" else brand

        first = rest.split()[0].strip(" ,.;:-")
        return first or None

    def _season_from_hit(self, hit):
        attributes = hit.get("attributes") or {}
        season = (attributes.get("ProductTireSeason") or "").strip()
        if season:
            return season

        categories = hit.get("categories") or []
        text = " > ".join(str(c) for c in categories).lower()
        if "sumardekk" in text:
            return "Sumardekk"
        if "vetrardekk" in text or "vetrar" in text:
            return "Vetrardekk"
        if "heils" in text:
            return "Heilsársdekk"
        return ""

    def _picture_from_media(self, media):
        for image in media:
            if not isinstance(image, dict):
                continue
            for key in ("product_list", "255", "product_gallery", "540", "1080", "product_gallery_2x"):
                url = image.get(key)
                if url:
                    return url
        return ""

    def errback_log(self, failure):
        request = failure.request
        self.logger.error(
            "N1 Algolia request failed: %s %s — %s",
            request.method,
            request.url,
            failure.value,
        )
