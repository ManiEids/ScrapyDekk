"""
Klettur Spider

Scrapes all tires from the Klettur API.
Applies VAT (24%) to match frontend prices.
"""

import scrapy
import json
import re


class KletturSpider(scrapy.Spider):
    name = "klettur"
    allowed_domains = ["dekk.klettur.is"]

    custom_settings = {
        "CONCURRENT_REQUESTS": 6,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 6,
        "DOWNLOAD_DELAY": 0.5,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 0.5,
        "AUTOTHROTTLE_MAX_DELAY": 5.0,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 8,
        "RETRY_HTTP_CODES": [429, 500, 502, 503, 504],
        "HTTPERROR_ALLOWED_CODES": [429],
        "DEFAULT_REQUEST_HEADERS": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/134.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
        },
        "DNSCACHE_ENABLED": True,
    }

    API_BASE   = "https://dekk.klettur.is/api/tires"
    IMAGE_BASE = "https://dekk.klettur.is/storage/"

    VAT_RATE = 0.24

    CARGO_RE = re.compile(r"\d{2}C\b", re.IGNORECASE)
    TRUCK_RIM_RE = re.compile(r"R\d{2}[,.]\d", re.IGNORECASE)

    SIZE_RE = re.compile(
        r"\d{3}/\d{2,3}\s*(?:ZR|Z|R|B)\s*\d{2}", re.IGNORECASE
    )

    JUNK_RE = re.compile(r"^\d{2,3}[A-Z]{0,2}$", re.IGNORECASE)
    CARGO_CODES = {"CS", "CV", "C"}

    STRIP_WORDS = re.compile(
        r"\b(Sumardekk|Vetradekk|Vetrardekk|Ársdekk|NEGLT|óneglanlegt"
        r"|neglanlegt|XL|TL|Burðar|Burðardekk|Heilsárs|Jeppadekk"
        r"|Vagnadekk|remix|sólað|DEMO)\b",
        re.IGNORECASE,
    )

    seen_ids: set = set()

    # ── Price helpers ───────────────────────────────────────────

    def apply_vat(self, price_raw):
        """Convert API price (excl VAT) → final price (incl VAT)"""
        try:
            return int(round(float(price_raw) * (1 + self.VAT_RATE)))
        except Exception:
            return None

    def format_price(self, price_int):
        """Format to Icelandic style"""
        if price_int is None:
            return ""
        return f"{price_int:,}".replace(",", ".") + " kr"

    # ── Requests ───────────────────────────────────────────────

    async  def start(self):
        yield scrapy.Request(
            url=f"{self.API_BASE}?page=1",
            callback=self.parse_first_page,
        )

    def parse_first_page(self, response):
        body = response.json()
        outer = body.get("data") or {}
        last_page = outer.get("last_page", 1)

        self.logger.info(f"Total pages: {last_page}")

        yield from self._process_page(outer.get("data", []))

        for page in range(2, last_page + 1):
            yield scrapy.Request(
                url=f"{self.API_BASE}?page={page}",
                callback=self.parse_page,
                dont_filter=True,
            )

    def parse_page(self, response):
        if response.status == 429:
            self.logger.warning(f"429 hit: {response.url}")
            return

        try:
            body = response.json()
        except Exception as e:
            self.logger.error(f"JSON error on {response.url}: {e}")
            return

        outer = body.get("data") or {}
        yield from self._process_page(outer.get("data", []))

    # ── Item processing ────────────────────────────────────────

    def _process_page(self, tires):
        for tire in tires:
            item_id = tire.get("ItemId")

            if not item_id or item_id in self.seen_ids:
                continue

            self.seen_ids.add(item_id)

            try:
                item = self._make_item(tire)
                if item:
                    yield item
            except Exception as e:
                self.logger.warning(f"Failed on {item_id}: {e}")

    def _make_item(self, tire: dict):
        name = (tire.get("ItemName") or "").strip()

        if self.CARGO_RE.search(name):
            return None

        if self.TRUCK_RIM_RE.search(name):
            return None

        # ── Correct price handling ───────────────────────

        price_raw = tire.get("Price")
        price_int = self.apply_vat(price_raw)
        price = self.format_price(price_int)

        # ── Other fields ────────────────────────────────

        try:
            qty = int(tire.get("QTY", 0))
        except Exception:
            qty = 0

        try:
            tire_types = json.loads(tire.get("type", "") or "[]")
        except Exception:
            tire_types = []

        if "Sumardekk" in tire_types:
            season = "Sumardekk"
        elif "Vetrardekk" in tire_types:
            season = "Vetrardekk"
        else:
            season = ""

        photourl = tire.get("photourl") or ""
        picture = (self.IMAGE_BASE + photourl) if photourl else ""

        return {
            "sku":          tire.get("ItemId"),
            "name":         name,
            "manufacturer": self._extract_manufacturer(name),
            "width":        tire.get("Width"),
            "profile":      tire.get("Height"),
            "rim":          tire.get("RimSize"),
            "season":       season,

            # Correct pricing
            "price":        price,        # formatted (22.990 kr)
            "price_int":    price_int,    # 22990
            "price_raw":    price_raw,    # 18540.32

            "qty":          qty,
            "stock":        "in stock" if qty > 0 else "out of stock",
            "picture":      picture,
            "source":       "klettur.is",
        }

    # ── Manufacturer extraction ────────────────────────────────

    def _extract_manufacturer(self, name: str) -> str | None:
        if not name:
            return None

        remainder = self.SIZE_RE.sub("", name).strip()
        remainder = self.STRIP_WORDS.sub("", remainder).strip()

        for tok in remainder.split():
            if len(tok) <= 1:
                continue
            if self.JUNK_RE.match(tok):
                continue
            if tok.upper() in self.CARGO_CODES:
                continue
            if tok in ("S", "V"):
                continue
            return tok

        return None