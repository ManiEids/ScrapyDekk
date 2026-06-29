import scrapy
import json
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


class MitraTiresSpider(scrapy.Spider):
    name = "mitra"
    allowed_domains = ["mitra.is"]

    # The ?page=N param is silently ignored by the API — every page returns
    # the full catalogue (~813 items). We start at page=1 and stop as soon as
    # a page yields zero NEW items (meaning all items were already seen).
    start_urls = ["https://mitra.is/api/tires/?page=1"]

    custom_settings = {
        "CONCURRENT_REQUESTS": 8,
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/134.0.0.0 Safari/537.36"
            ),
        },
    }

    # Extract manufacturer from title regardless of ordering
    SIZE_PREFIX_RE = re.compile(
        r"^\d{3}/\d{2,3}\s*(?:ZR|Z|R|B)\s*\d{2}", re.IGNORECASE
    )
    JUNK_TOKENS_RE = re.compile(r"^\d{2,3}[A-Z]{0,2}$", re.IGNORECASE)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_ids = set()

    def parse(self, response):
        self.logger.info(f"Response URL: {response.url}")
        try:
            data = json.loads(response.text)
        except Exception as e:
            self.logger.error(f"Error parsing JSON: {e}")
            return

        if not data:
            self.logger.info("Empty response. Done.")
            return

        new_items = 0
        for tire in data:
            product_id = tire.get("product_id")
            if not product_id or product_id in self.seen_ids:
                continue
            self.seen_ids.add(product_id)
            new_items += 1

            try:
                # API sometimes returns negative inventory (e.g. -4) — clamp to 0
                inventory = max(0, int(tire.get("inventory", 0)))
            except (ValueError, TypeError):
                inventory = 0

            price = (tire.get("price") or "").strip()
            width = (tire.get("width") or "").strip()
            profile = (tire.get("aspect_ratio") or "").strip()
            rim = (tire.get("diameter") or "").strip()
            title = (tire.get("title") or "").strip()
            sku = (tire.get("product_number") or "").strip()  # e.g. "VN0001735"

            manufacturer = self._extract_manufacturer(title)

            # Season from group object: {"title": "Sumardekk"} or "Vetrardekk"
            group = tire.get("group") or {}
            season = group.get("title", "")

            picture = (tire.get("card_image") or "").strip()
            if picture.startswith("//"):
                picture = "https:" + picture

            yield {
                "product_id":   product_id,
                "sku":          sku,
                "title":        title,
                "manufacturer": manufacturer,
                "price":        price,
                "width":        width,
                "profile":      profile,
                "rim":          rim,
                "season":       season,
                "picture":      picture,
                "inventory":    inventory,
                "stock":        "in stock" if inventory > 0 else "out of stock",
                "source":       "mitra.is",
            }

        self.logger.info(f"Page yielded {new_items} new items (total seen: {len(self.seen_ids)})")

        # The API returns the full catalogue on every page — stop as soon as
        # we get a page with zero new items (all already seen = we're done).
        if new_items == 0:
            self.logger.info("No new items on this page. Stopping.")
            return

        # Advance to next page (handles the rare case of true pagination)
        parsed = urlparse(response.url)
        qs = parse_qs(parsed.query)
        current_page = int(qs.get("page", ["1"])[0])
        qs["page"] = [str(current_page + 1)]
        next_url = urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, urlencode(qs, doseq=True), parsed.fragment
        ))
        yield scrapy.Request(next_url, callback=self.parse)

    def _extract_manufacturer(self, title: str) -> str | None:
        if not title:
            return None
        if self.SIZE_PREFIX_RE.match(title):
            remainder = self.SIZE_PREFIX_RE.sub("", title).strip()
            for tok in remainder.split():
                if not self.JUNK_TOKENS_RE.match(tok):
                    return tok
            return None
        return title.split()[0]