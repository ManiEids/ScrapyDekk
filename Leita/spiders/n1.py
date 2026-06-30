"""
N1 Algolia spider.

What it does:
- Queries N1's public Algolia search index using the same plain JSON body as n1_probe.py.
- Starts from the confirmed lvl0 tyre category, then splits by rim/width/profile to avoid Algolia's 1000 result cap.
- Emits fields expected by merge_tires.py: name, manufacturer, size, size_type, picture, stock, season, price, sku, category_slug, source.

Input:
- Public N1 Algolia app id/search key/index.

Output:
- n1.json when run with: scrapy crawl n1 -O n1.json
"""

import json
import os
import re

import scrapy


APP_ID = os.environ.get("N1_ALGOLIA_APP_ID", "LU6HO9UFWF")
API_KEY = os.environ.get("N1_ALGOLIA_SEARCH_KEY", "1fc8f9f8099e352754bc2d197f6f12a8")
INDEX_NAME = os.environ.get("N1_ALGOLIA_INDEX", "PROD_PRODUCTS")
ALGOLIA_URL = f"https://{APP_ID.lower()}-dsn.algolia.net/1/indexes/{INDEX_NAME}/query"


class N1AlgoliaSpider(scrapy.Spider):
    name = "n1"

    # Keep this broad. The exact host is dynamic from APP_ID.
    allowed_domains = ["algolia.net", "algolianet.com"]

    CATEGORY_LVL0 = "Hjólbarðar og tengdar vörur"
    PASSENGER_CATEGORY_TEXT = "fólksbíla- og jeppadekk"

    HITS_PER_PAGE = 500
    MAX_RETRIEVABLE_HITS = 1000

    # Split lvl0 by tire dimensions. lvl0 is confirmed by your n1_probe.py.
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
    INCH_DIAMETER_VALUES = [str(n) for n in range(28, 45)]
    INCH_SECTION_VALUES = [
        "8", "8.5", "9", "9.5", "10", "10.5", "11", "11.5",
        "12", "12.5", "13", "13.5", "14", "14.5", "15", "15.5", "16",
        "8,5", "9,5", "10,5", "11,5", "12,5", "13,5", "14,5", "15,5",
    ]

    SPLIT_STEPS = [
        ("attributes.ProductTireSidewallSize", RIM_VALUES),
        ("attributes.ProductTireSectionWidthName", METRIC_WIDTH_VALUES + INCH_DIAMETER_VALUES + INCH_SECTION_VALUES),
        ("attributes.ProductTireTreadProfile", METRIC_PROFILE_VALUES + INCH_DIAMETER_VALUES + INCH_SECTION_VALUES),
    ]

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "CONCURRENT_REQUESTS": 4,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
        "DOWNLOAD_DELAY": 0.05,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 0.2,
        "AUTOTHROTTLE_MAX_DELAY": 2,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 4,
        "RETRY_HTTP_CODES": [408, 429, 500, 502, 503, 504],
        "DOWNLOAD_TIMEOUT": 30,
        "FEED_EXPORT_ENCODING": "utf-8",
    }

    HEADERS = {
        "X-Algolia-Application-Id": APP_ID,
        "X-Algolia-API-Key": API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Referer": "https://n1.is/",
        "Origin": "https://n1.is",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
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
        r"^\s*\d{2}\s+R\s+(?:\d{3}/\d{2,3}|\d{2}x\d{1,2}(?:[.,]\d+)?)\s+",
        re.IGNORECASE,
    )

    MULTI_WORD_BRANDS = [
        "BFGoodrich",
        "BF Goodrich",
        "Mickey Thompson",
        "Double Coin",
        "GT Radial",
        "General Tire",
    ]

    SKIP_CATEGORY_WORDS = [
        "mótorhjóladekk", "motorhjóladekk", "motorhjol", "mótorhjol",
        "reiðhjóladekk", "reidhjol",
        "fjórhjól", "fjorhjol", "atv",
        "sláttuvél", "slaettuvel", "vinnuvél", "vinnuvel", "dráttarvél", "drattarvel",
        "felgur", "slöngur", "slongur", "ventlar",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_keys = set()

    def _initial_requests(self):
        """
        What it does: creates the first Algolia request.
        Input: none.
        Output: one Scrapy request to N1 Algolia.
        """
        base_filters = [f"hierarchical_categories.lvl0:{self.CATEGORY_LVL0}"]
        yield self._request(filters=base_filters, page=0, split_depth=0)

    async def start(self):
        """
        What it does: Scrapy 2.13+ compatible entry point.
        Input: none.
        Output: initial request(s).
        """
        for request in self._initial_requests():
            yield request

    def start_requests(self):
        """
        What it does: older Scrapy compatible entry point.
        Input: none.
        Output: initial request(s).
        """
        yield from self._initial_requests()

    def _request(self, filters, page, split_depth):
        """
        What it does: builds one Algolia POST request.
        Input: facet filters, page number, split depth.
        Output: Scrapy request returning one Algolia result page.
        """
        body = {
            "query": "",
            "page": page,
            "hitsPerPage": self.HITS_PER_PAGE,
            "analytics": False,
            "clickAnalytics": False,
            "getRankingInfo": False,
            # Same style as your working probe: list-of-lists facetFilters.
            "facetFilters": [[f] for f in filters],
            "attributesToRetrieve": [
                "sku",
                "name",
                "categories",
                "hierarchical_categories",
                "category_breadcrumbs",
                "attributes",
                "media",
                "price",
                "stock_level",
                "stock_level_stores",
                "variants_stock_levels",
                "objectID",
            ],
        }

        return scrapy.Request(
            url=ALGOLIA_URL,
            method="POST",
            headers=self.HEADERS,
            body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
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
        """
        What it does: handles an Algolia result page and splits large slices.
        Input: Algolia JSON response.
        Output: N1 tire items or more smaller requests.
        """
        filters = response.meta["filters"]
        page = response.meta["page"]
        split_depth = response.meta["split_depth"]

        try:
            data = response.json()
        except Exception as exc:
            self.logger.error("N1 Algolia JSON error: %s. Body preview: %r", exc, response.text[:500])
            return

        if data.get("message"):
            self.logger.error("N1 Algolia error: %s. Body preview: %r", data.get("message"), response.text[:500])
            return

        nb_hits = int(data.get("nbHits") or 0)
        nb_pages = int(data.get("nbPages") or 0)
        hits = data.get("hits") or []

        self.logger.info(
            "N1 Algolia page=%s hits=%s nbHits=%s filters=%s",
            page,
            len(hits),
            nb_hits,
            filters,
        )

        # Algolia page pagination cannot safely retrieve beyond 1000 hits.
        # Split broad slices before yielding anything from them.
        if page == 0 and nb_hits > self.MAX_RETRIEVABLE_HITS:
            if split_depth < len(self.SPLIT_STEPS):
                facet_name, values = self.SPLIT_STEPS[split_depth]
                self.logger.info(
                    "N1 slice too large: %s hits. Splitting by %s into %s slices.",
                    nb_hits,
                    facet_name,
                    len(values),
                )
                for value in values:
                    yield self._request(
                        filters=filters + [f"{facet_name}:{value}"],
                        page=0,
                        split_depth=split_depth + 1,
                    )
                return

            self.logger.warning(
                "N1 slice still has %s hits after all split levels. Only first %s are reachable.",
                nb_hits,
                self.MAX_RETRIEVABLE_HITS,
            )

        for hit in hits:
            item = self._hit_to_item(hit)
            if item:
                yield item

        if page == 0 and nb_pages > 1:
            max_pages = min(nb_pages, self.MAX_RETRIEVABLE_HITS // self.HITS_PER_PAGE)
            for next_page in range(1, max_pages):
                yield self._request(filters=filters, page=next_page, split_depth=split_depth)

    def _hit_to_item(self, hit):
        """
        What it does: converts one Algolia product hit into your raw N1 item shape.
        Input: one Algolia hit.
        Output: dict for n1.json, or None if it is not a usable passenger/jeep tire.
        """
        name = (hit.get("name") or "").strip()
        if not name:
            return None

        category_text = self._category_text(hit).lower()
        if self.PASSENGER_CATEGORY_TEXT not in category_text:
            return None
        if any(word in category_text for word in self.SKIP_CATEGORY_WORDS):
            return None

        stock = (hit.get("stock_level") or "").strip().lower()
        if not stock or "out of stock" in stock:
            return None

        price = self._clean_price(hit.get("price"))
        if price is None:
            return None

        object_id = str(hit.get("objectID") or "").strip()
        sku = str(hit.get("sku") or object_id).strip() or None
        dedupe_key = sku or object_id or name
        if dedupe_key in self.seen_keys:
            return None
        self.seen_keys.add(dedupe_key)

        attributes = hit.get("attributes") or {}
        size_type = "metric"

        flotation_size = self._flotation_size_from_name(name)
        if flotation_size:
            size = flotation_size
            size_type = "flotation"
        else:
            size = self._metric_size_from_attributes(attributes) or self._metric_size_from_name(name)

        if not size:
            return None

        return {
            "name": name,
            "manufacturer": self._manufacturer_from_name(name),
            "size": size,
            "size_type": size_type,
            "picture": self._picture_from_media(hit.get("media") or []),
            "stock": stock,
            "season": self._season_from_hit(hit),
            "price": price,
            "sku": sku,
            "category_slug": category_text,
            "source": "n1.is",
        }

    def _category_text(self, hit):
        """
        What it does: combines category fields into searchable text.
        Input: one Algolia hit.
        Output: category text string.
        """
        pieces = []
        categories = hit.get("categories") or []
        pieces.extend(str(c) for c in categories)

        hierarchical = hit.get("hierarchical_categories") or {}
        pieces.extend(str(v) for v in hierarchical.values() if v)

        breadcrumbs = hit.get("category_breadcrumbs") or []
        for crumb in breadcrumbs:
            if isinstance(crumb, dict):
                pieces.append(str(crumb.get("breadcrumb_name") or crumb.get("name") or ""))

        return " > ".join(p for p in pieces if p)

    def _metric_size_from_attributes(self, attributes):
        """
        What it does: builds metric size from Algolia tire attributes.
        Input: attributes dict.
        Output: size string like 245/45/19, or None.
        """
        width = self._clean_dimension(attributes.get("ProductTireSectionWidthName"))
        profile = self._clean_dimension(attributes.get("ProductTireTreadProfile"))
        rim = self._clean_dimension(attributes.get("ProductTireSidewallSize"))
        if width and profile and rim:
            return f"{width}/{profile}/{rim}"
        return None

    def _metric_size_from_name(self, name):
        """
        What it does: parses N1 metric name format.
        Input: product name like '19 R 245/45 Michelin...'.
        Output: size string like 245/45/19, or None.
        """
        match = self.METRIC_NAME_RE.search(name)
        if not match:
            return None
        return f"{match.group('width')}/{match.group('profile')}/{match.group('rim')}"

    def _flotation_size_from_name(self, name):
        """
        What it does: parses N1 rim-first offroad format.
        Input: product name like '17 R 37x13.50 BFGoodrich...'.
        Output: canonical size like 37x13.50R17, or None.
        """
        match = self.FLOTATION_NAME_RE.search(name)
        if not match:
            return None
        section = match.group("section").replace(",", ".")
        return f"{match.group('diameter')}x{section}R{match.group('rim')}"

    def _manufacturer_from_name(self, name):
        """
        What it does: extracts manufacturer after N1's size prefix.
        Input: full product name.
        Output: manufacturer string or None.
        """
        rest = self.SIZE_PREFIX_RE.sub("", name, count=1).strip()
        if not rest:
            return None

        rest_lower = rest.lower()
        for brand in self.MULTI_WORD_BRANDS:
            if rest_lower.startswith(brand.lower()):
                return "BFGoodrich" if brand.lower() == "bf goodrich" else brand

        return rest.split()[0].strip(" ,.;:-") or None

    def _season_from_hit(self, hit):
        """
        What it does: extracts N1 season from attributes/categories.
        Input: one Algolia hit.
        Output: normalized Icelandic season string, or empty string.
        """
        attributes = hit.get("attributes") or {}
        season = (attributes.get("ProductTireSeason") or "").strip()
        if season:
            return season

        text = self._category_text(hit).lower()
        if "sumardekk" in text:
            return "Sumardekk"
        if "vetrardekk" in text or "vetrar" in text:
            return "Vetrardekk"
        if "heils" in text:
            return "Heilsársdekk"
        return ""

    def _picture_from_media(self, media):
        """
        What it does: chooses the smallest useful N1 product image.
        Input: media list from Algolia.
        Output: image URL string or empty string.
        """
        for image in media:
            if not isinstance(image, dict):
                continue
            for key in ("product_list", "255", "product_gallery", "540", "1080", "product_gallery_2x"):
                url = image.get(key)
                if url:
                    return url
        return ""

    def _clean_dimension(self, value):
        """
        What it does: converts Algolia dimension values to clean strings.
        Input: raw dimension value.
        Output: string value or None.
        """
        if value is None:
            return None
        text = str(value).strip().replace(",", ".")
        return text or None

    def _clean_price(self, value):
        """
        What it does: converts N1 price to integer ISK.
        Input: raw price value.
        Output: int price or None.
        """
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)

        text = str(value).strip().lower()
        text = text.replace("kr", "").replace("isk", "").replace(" ", "")
        if text.endswith(".00"):
            text = text[:-3]
        text = text.replace(".", "").replace(",", ".")

        try:
            return int(float(text))
        except (TypeError, ValueError):
            return None

    def errback_log(self, failure):
        request = failure.request
        self.logger.error(
            "N1 Algolia request failed: %s %s — %s",
            request.method,
            request.url,
            failure.value,
        )
