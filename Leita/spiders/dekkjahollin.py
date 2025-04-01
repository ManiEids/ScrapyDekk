import scrapy
import re
from urllib.parse import urlparse, parse_qs
from itertools import product

class DekkjahollinSpider(scrapy.Spider):
    name = "dekkjahollin"
    allowed_domains = ["dekkjahollin.is"]

    rim_mapping = {
        "14": {
            "widths": ["155", "165", "175", "185", "195"],
            "heights": ["75", "70", "65", "60", "55"]
        },
        "15": {
            "widths": ["175", "185", "195", "205", "215", "225"],
            "heights": ["70", "65", "60", "55", "50"]
        },
        "16": {
            "widths": ["195", "205", "215", "225", "235"],
            "heights": ["65", "60", "55", "50", "45"]
        },
        "17": {
            "widths": ["205", "215", "225", "235", "245", "255"],
            "heights": ["65", "60", "55", "50", "45", "40"]
        },
        "18": {
            "widths": ["225", "235", "245", "255", "265"],
            "heights": ["60", "55", "50", "45", "40"]
        },
        "19": {
            "widths": ["235", "245", "255", "265", "275"],
            "heights": ["55", "50", "45", "40"]
        },
        "20": {
            "widths": ["245", "255", "265", "275", "285", "295", "305", "315"],
            "heights": ["55", "50", "45", "40", "35", "30"]
        },
        "21": {
            "widths": ["255", "265", "275", "285", "295", "305", "315"],
            "heights": ["45", "40", "35", "30"]
        },
        "22": {
            "widths": ["265", "275", "285", "295", "305", "315"],
            "heights": ["40", "35", "30"]
        }
    }

    custom_settings = {
        'ROBOTSTXT_OBEY': False,
        'DOWNLOADER_MIDDLEWARES': {
            'scrapy.downloadermiddlewares.robotstxt.RobotsTxtMiddleware': None,
        },
        'DOWNLOAD_DELAY': 0.5,
        'AUTOTHROTTLE_ENABLED': True,
    }

    # Start requests
    def start_requests(self):
        base_url = "https://www.dekkjahollin.is/is/leit?q={size}&t%5B%5D=store"
        for rim, specs in self.rim_mapping.items():
            for width in specs["widths"]:
                for height in specs["heights"]:
                    size = f"{width}/{height}R{rim}"
                    url = base_url.format(size=size)
                    yield scrapy.Request(
                        url=url,
                        callback=self.parse,
                        errback=self.errback_httpbin,
                        meta={'tire_size': size, 'dont_redirect': True}
                    )

    # Parse síðuna
    def parse(self, response):
        tire_size = response.meta.get("tire_size", "Unknown")
        self.logger.info(f"Parsing {response.url} for tire size: {tire_size}")
        
        products = response.css("li.store.product")
        if not products:
            self.logger.debug(f"No products found for size: {tire_size}")
        
        for product in products:
            title = product.css("div.content a.title::text").get()
            if not title:
                continue
            title = title.strip()
            
            price_text = product.css("div.content div.priceBox span.price::text").get()
            price = None
            if price_text:
                price = re.sub(r"(Tilboðsverð:|Verð:)\s*", "", price_text)
                price = re.sub(r"kr\.?", "", price).strip()

            stock = product.css("div.content div.stock::text").get()
            stock = stock.strip() if stock else "Unknown"
            
            picture = None
            style_attr = product.css("div.content div.image::attr(style)").get()
            if style_attr:
                match = re.search(r"url\(['\"]?(.*?)['\"]?\)", style_attr)
                if match:
                    picture = match.group(1).strip()
                    if picture.startswith("/"):
                        picture = "https://www.dekkjahollin.is" + picture
            
            manufacturer = title.split()[0] if title else None
            
            yield {
                "title": title,
                "tire_size": tire_size,
                "price": price,
                "stock": stock,
                "picture": picture,
                "manufacturer": manufacturer,
            }
        
        next_page = response.css("ul.pagination li.next a::attr(href)").get()
        if next_page:
            yield response.follow(
                next_page,
                callback=self.parse,
                errback=self.errback_httpbin,
                meta={'tire_size': tire_size}
            )

    def errback_httpbin(self, failure):
        self.logger.error(repr(failure))
