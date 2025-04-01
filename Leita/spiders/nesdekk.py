import scrapy
import re

class NesdekkSpider(scrapy.Spider):
    name = "nesdekk"
    allowed_domains = ["nesdekk.is"]
    start_urls = [
        "https://nesdekk.is/dekkjaleit/?tyre-filter=1"
    ]
    
    # Parse síðuna
    def parse(self, response):
        for product in response.css("li.product"):
            name = product.css("h2.woocommerce-loop-product__title::text").get()
            if name:
                name = name.strip()
            
            price = product.css("span.price span.woocommerce-Price-amount.amount bdi").xpath("string()").get()
            if price:
                price = price.strip()
            
            picture = product.css("a.woocommerce-LoopProduct-link img::attr(src)").get()
            
            stock = product.css("div.stock strong::text").get()
            if stock:
                stock = stock.strip()
            else:
                stock = "in stock"
            
            tyre_size = product.css("div.tyre-details a.tyre-size::text").get()
            if tyre_size:
                tyre_size = tyre_size.strip()
            
            manufacturer = product.css("div.tyre-details a.tyre-brand::text").get()
            if manufacturer:
                manufacturer = manufacturer.strip()
            
            yield {
                "name": name,
                "price": price,
                "picture": picture,
                "stock": stock,
                "tyre_size": tyre_size,
                "manufacturer": manufacturer,
            }
        
        next_page = response.css("a.next.page-numbers::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)
