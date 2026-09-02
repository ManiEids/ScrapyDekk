# Spider: Nesdekk
# Purpose: Scrape tire listings including accurate inventory count
# Input: HTML response from nesdekk.is listing pages
# Output: Structured product data with parsed inventory numbers

import re
import scrapy


# nesdekk.is is behind Cloudflare, which answers anything that is not a real
# browser with 403 + "cf-mitigated: challenge" when the request comes from a
# datacenter IP. Headers alone do not help: probed from a GitHub runner
# (AS8075 Microsoft), python urllib sending a full Chrome header set was
# blocked on every page, while curl_cffi reproducing Chrome's TLS/JA3
# handshake got 200 on every page from the same IP with no proxy.
#
# So this spider swaps Scrapy's downloader for scrapy-impersonate, which
# fetches through curl_cffi.
#
# Scrapy's UserAgentMiddleware has to be switched off alongside it. It injects
# "Scrapy/x.y.z (+https://scrapy.org)" into every request, and curl_cffi sends
# that verbatim - producing a Chrome TLS handshake carrying a Scrapy
# User-Agent. Cloudflare reads that contradiction as a bot and challenges it,
# which is exactly what happened in run 33615453122: the impersonation was
# active (responses carried the "impersonate" flag and Chrome's HTTP/2
# fingerprint) yet every page still came back 403.
#
# With the middleware off, curl_cffi supplies the User-Agent belonging to the
# profile it is imitating, so the headers and the handshake agree and stay in
# agreement when curl_cffi updates its browser profiles. For the same reason,
# do not set DEFAULT_REQUEST_HEADERS here.
IMPERSONATE = "chrome"  # alias for curl_cffi's newest Chrome profile


class ImpersonateMiddleware:
    """Tag every request, robots.txt included, with the browser to imitate."""

    # spider is positional in Scrapy 2.x and dropped in a future release.
    def process_request(self, request, spider=None):
        request.meta.setdefault("impersonate", IMPERSONATE)
        return None


class NesdekkSpider(scrapy.Spider):
    name = "nesdekk"
    allowed_domains = ["nesdekk.is"]
    start_urls = ["https://nesdekk.is/dekkjaleit/?tyre-filter=1"]

    custom_settings = {
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_impersonate.ImpersonateDownloadHandler",
            "https": "scrapy_impersonate.ImpersonateDownloadHandler",
        },
        "DOWNLOADER_MIDDLEWARES": {
            "Leita.spiders.nesdekk.ImpersonateMiddleware": 543,
            # Let the impersonation own the User-Agent; see the note above.
            "scrapy.downloadermiddlewares.useragent.UserAgentMiddleware": None,
        },
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        # Cloudflare rate-limits before it blocks; back off instead of dying.
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 5,
        "RETRY_HTTP_CODES": [403, 429, 500, 502, 503, 504, 522, 524, 408],
    }

    SEASON_MAP = {
        "sumardekk":      "Sumardekk",
        "vetrardekk":     "Vetrardekk",
        "vetrardekk-on":  "Vetrardekk",
        "heilsársdekk":   "Heilsársdekk",
        "heilsarsdekk":   "Heilsársdekk",
    }

    # Extracts number before "stk"
    INV_RE = re.compile(r"(\d+)\s*stk", re.IGNORECASE)

    def parse(self, response):
        for product in response.css("li.product"):

            # ── Season ────────────────────────────────────────────────
            season_text = product.css("a.tyre-type::text").get()
            season = ""
            if season_text:
                key = season_text.strip().lower()
                season = self.SEASON_MAP.get(key, season_text.strip())
            else:
                classes = product.css("::attr(class)").get() or ""
                for cls in classes.split():
                    if cls.startswith("product_cat-"):
                        slug = cls[len("product_cat-"):]
                        if slug in self.SEASON_MAP:
                            season = self.SEASON_MAP[slug]
                            break

            # ── Stock status ──────────────────────────────────────────
            li_classes = product.css("::attr(class)").get() or ""
            if "outofstock" in li_classes:
                stock = "out of stock"
            elif "instock" in li_classes:
                stock = "in stock"
            else:
                stock = "unknown"

            # ── FIXED: Stock text extraction ──────────────────────────
            # Collect ALL text inside div.stock (including <strong>)
            stock_text = "".join(
                product.css("div.stock *::text").getall()
            ).strip()

            # ── Inventory parsing ─────────────────────────────────────
            inventory = None
            low = stock_text.lower()

            if not low:
                inventory = None

            elif "ekki" in low or "uppselt" in low:
                inventory = 0

            elif "fleiri en" in low:
                # "more than X"
                m = self.INV_RE.search(low)
                if m:
                    inventory = int(m.group(1)) + 1
                else:
                    inventory = 25  # fallback assumption

            else:
                # "Aðeins X stk eftir á lager"
                m = self.INV_RE.search(low)
                if m:
                    inventory = int(m.group(1))

            # Force consistency with class-based stock
            if stock == "out of stock":
                inventory = 0

            # ── Identifiers ───────────────────────────────────────────
            sku = product.css(
                "a.add_to_cart_button::attr(data-product_sku)"
            ).get()
            if sku:
                sku = sku.strip()

            product_id = product.css(
                "a.add_to_cart_button::attr(data-product_id)"
            ).get()

            # ── Name ──────────────────────────────────────────────────
            name = product.css("h2.woocommerce-loop-product__title::text").get()
            if name:
                name = name.strip()

            # ── Price ─────────────────────────────────────────────────
            sale_price = product.css(
                "span.price ins .woocommerce-Price-amount bdi"
            )
            if sale_price:
                price = sale_price.xpath("string()").get()
            else:
                price = product.css(
                    "span.price .woocommerce-Price-amount bdi"
                ).xpath("string()").get()

            if price:
                price = price.strip()

            # ── Image ─────────────────────────────────────────────────
            picture = (
                product.css("a.woocommerce-LoopProduct-link img::attr(data-src)").get()
                or product.css("a.woocommerce-LoopProduct-link img::attr(srcset)").get()
                or product.css("a.woocommerce-LoopProduct-link img::attr(src)").get()
                or ""
            )

            if picture and "," in picture:
                last_entry = picture.strip().split(",")[-1].strip()
                picture = last_entry.split()[0]

            if picture and (
                "eprel.ec.europa.eu" in picture
                or "woocommerce-placeholder" in picture
            ):
                picture = ""

            # ── Other details ─────────────────────────────────────────
            tyre_size = product.css(
                "div.tyre-details a.tyre-size::text"
            ).get()
            if tyre_size:
                tyre_size = tyre_size.strip()

            manufacturer = product.css(
                "div.tyre-details a.tyre-brand::text"
            ).get()
            if manufacturer:
                manufacturer = manufacturer.strip()

            yield {
                "product_id":   product_id,
                "sku":          sku,
                "name":         name,
                "manufacturer": manufacturer,
                "season":       season,
                "tyre_size":    tyre_size,
                "price":        price,
                "picture":      picture,
                "stock":        stock,
                "inventory":    inventory,
                "stock_text":   stock_text,
                "source":       "nesdekk.is",
            }

        # ── Pagination ────────────────────────────────────────────────
        next_page = response.css("a.next.page-numbers::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)