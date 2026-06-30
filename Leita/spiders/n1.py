import json
import os
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import scrapy


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

    allowed_domains = [
        "backend.n1.is",
        "vefverslun.n1.is",
    ]

    API_URL = "https://backend.n1.is/api/products/attribute_filter/?page_size=24&page=1"
    MULTIPRICE_URL = "https://backend.n1.is/api/products/multiprice/"
    CATEGORY_PAGE = "https://vefverslun.n1.is/voruflokkur/hjolbardar-og-tengdar-vorur"

    CATEGORY_SLUG = "004-hjolbardar-og-tengdar-vorur"

    custom_settings = {
        # backend.n1.is/robots.txt currently returns 403 on GitHub Actions.
        # This avoids failing before the API request.
        "ROBOTSTXT_OBEY": False,

        # Be gentle.
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 2,
        "RANDOMIZE_DOWNLOAD_DELAY": True,

        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 1,
        "AUTOTHROTTLE_MAX_DELAY": 10,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 1.0,

        "RETRY_TIMES": 2,
        "RETRY_HTTP_CODES": [429, 500, 502, 503, 504],

        # Let the spider see 403/429 so we can log a useful message.
        "HTTPERROR_ALLOWED_CODES": [403, 429],

        "COOKIES_ENABLED": True,
        "DOWNLOAD_TIMEOUT": 30,
    }

    SLUG_SEASON_MAP = {
        "sumardekk": "Sumardekk",
        "vetrardekk": "Vetrardekk",
        "heilsarsdekk": "Heilsársdekk",
    }

    SKIP_SLUG_FRAGMENTS = frozenset({
        "motor",
        "reidhjol",
        "fjorhjol",
        "atv",
        "vinnuvela",
        "slaettuvela",
        "grasdekk",
        "felg",
        "voru",
        "slanga",
        "ventill",
    })

    BROWSER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "is-IS,is;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
    }

    API_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "is-IS,is;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "application/json",
        "Origin": "https://vefverslun.n1.is",
        "Referer": "https://vefverslun.n1.is/voruflokkur/hjolbardar-og-tengdar-vorur",
        "Connection": "keep-alive",
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_skus = set()

        # Optional.
        # In GitHub Actions, set repository secret SCRAPE_PROXY like:
        # http://user:password@host:port
        #
        # Only use this with permission / legitimate scraping access.
        self.proxy = os.environ.get("SCRAPE_PROXY")

    def _meta(self, extra=None):
        meta = dict(extra or {})
        if self.proxy:
            meta["proxy"] = self.proxy
        return meta

    def _initial_payload(self):
        return json.dumps({
            "attributes": [],
            "categorySlug": self.CATEGORY_SLUG,
        })

    def _api_request(self, url):
        payload = self._initial_payload()
        return scrapy.Request(
            url=url,
            method="POST",
            headers=self.API_HEADERS,
            body=payload,
            callback=self.parse,
            errback=self.errback_log,
            meta=self._meta({
                "payload_headers": self.API_HEADERS,
                "payload_body": payload,
                "handle_httpstatus_list": [403, 429],
            }),
            dont_filter=True,
        )

    async def start(self):
        """
        Scrapy 2.16+ entry point.

        First request the public page to let cookies/session headers settle,
        then call the backend API.
        """
        yield scrapy.Request(
            url=self.CATEGORY_PAGE,
            headers=self.BROWSER_HEADERS,
            callback=self.after_warmup,
            errback=self.errback_log,
            meta=self._meta({"handle_httpstatus_list": [403, 429]}),
            dont_filter=True,
        )

    # Backwards compatibility if you ever pin Scrapy below 2.16 again.
    def start_requests(self):
        yield scrapy.Request(
            url=self.CATEGORY_PAGE,
            headers=self.BROWSER_HEADERS,
            callback=self.after_warmup,
            errback=self.errback_log,
            meta=self._meta({"handle_httpstatus_list": [403, 429]}),
            dont_filter=True,
        )

    def after_warmup(self, response):
        self.logger.info("Warmup response %s — %s", response.status, response.url)

        if response.status in (403, 429):
            self.logger.warning(
                "N1 public warmup returned %s. Trying backend API anyway. Body preview: %r",
                response.status,
                response.text[:300],
            )

        yield self._api_request(self.API_URL)

    def parse(self, response):
        self.logger.info("N1 API response %s — %s", response.status, response.url)

        if response.status in (403, 429):
            self.logger.error(
                "N1 API blocked this request with HTTP %s. Body preview: %r",
                response.status,
                response.text[:500],
            )
            return

        try:
            data = response.json()
        except Exception as e:
            self.logger.error("N1 JSON error: %s. Body preview: %r", e, response.text[:500])
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

            product_name = product.get("name")
            attributes = product.get("attributes", [])
            manufacturer = extract_attribute_value(attributes, "ProductManufacturer")

            width = extract_attribute_value(attributes, "ProductTireSectionWidthName")
            profile = extract_attribute_value(attributes, "ProductTireTreadProfile")
            sidewall = extract_attribute_value(attributes, "ProductTireSidewallSize")
            size = f"{width}/{profile}/{sidewall}" if (width and profile and sidewall) else None

            variants = product.get("variants", [])
            picture = extract_picture(variants)

            cat_slug = (product.get("category") or {}).get("slug", "").lower()
            if any(frag in cat_slug for frag in self.SKIP_SLUG_FRAGMENTS):
                continue

            season = ""
            for key, label in self.SLUG_SEASON_MAP.items():
                if key in cat_slug:
                    season = label
                    break

            self.seen_skus.add(sku)

            candidate_products.append({
                "name": product_name,
                "manufacturer": manufacturer,
                "size": size,
                "picture": picture,
                "stock": "in stock",
                "season": season,
                "sku": sku,
                "category_slug": cat_slug,
            })
            skus.append(sku)

        if skus:
            multiprice_url = self.MULTIPRICE_URL + "?" + "&".join(
                f"skus={sku}" for sku in skus
            )

            yield scrapy.Request(
                url=multiprice_url,
                headers=self.API_HEADERS,
                callback=self.parse_multiprice,
                errback=self.errback_log,
                meta=self._meta({
                    "products": candidate_products,
                    "handle_httpstatus_list": [403, 429],
                }),
            )

        # Pagination.
        parsed = urlparse(response.url)
        qs = parse_qs(parsed.query)
        current_page = int(qs.get("page", [1])[0])

        if results:
            qs["page"] = [str(current_page + 1)]
            next_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(qs, doseq=True),
                parsed.fragment,
            ))

            yield scrapy.Request(
                url=next_url,
                method="POST",
                headers=response.meta["payload_headers"],
                body=response.meta["payload_body"],
                callback=self.parse,
                errback=self.errback_log,
                meta=self._meta({
                    "payload_headers": response.meta["payload_headers"],
                    "payload_body": response.meta["payload_body"],
                    "handle_httpstatus_list": [403, 429],
                }),
            )

    def parse_multiprice(self, response):
        self.logger.info("N1 multiprice response %s — %s", response.status, response.url)

        if response.status in (403, 429):
            self.logger.error(
                "N1 multiprice blocked with HTTP %s. Body preview: %r",
                response.status,
                response.text[:500],
            )
            return

        try:
            price_data = response.json()
        except Exception as e:
            self.logger.error("Multiprice JSON error: %s. Body preview: %r", e, response.text[:500])
            return

        if isinstance(price_data, dict):
            entries = price_data.get("results") or price_data.get("items") or []
        else:
            entries = price_data

        price_map = {entry.get("itemId"): entry for entry in entries if isinstance(entry, dict)}

        for prod in response.meta["products"]:
            sku = prod.pop("sku", None)
            price_info = price_map.get(sku)
            prod["price"] = price_info.get("price", "N/A") if price_info else "N/A"
            prod["source"] = "n1.is"
            yield prod

    def errback_log(self, failure):
        request = failure.request
        self.logger.error("Request failed: %s %s — %s", request.method, request.url, failure.value)