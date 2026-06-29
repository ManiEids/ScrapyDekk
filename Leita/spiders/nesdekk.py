# Spider: Nesdekk
# Purpose: Scrape tire listings including accurate inventory count
# Input: HTML response from nesdekk.is listing pages
# Output: Structured product data with parsed inventory numbers

import re
import scrapy


class NesdekkSpider(scrapy.Spider):
    name = "nesdekk"
    allowed_domains = ["nesdekk.is"]
    start_urls = ["https://nesdekk.is/dekkjaleit/?tyre-filter=1"]

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