import scrapy

class TiresSpider(scrapy.Spider):
    name = "klettur"
    allowed_domains = ["bud.klettur.is"]
    
    # Start requests
    def start_requests(self):
        url = "https://bud.klettur.is/wp-content/themes/bud.klettur.is/kallkerfi/dekkjalisti/get_tires.php?getalltires=true"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            "Referer": "https://www.klettur.is/",
            "Origin": "https://www.klettur.is",
        }
        yield scrapy.Request(url=url, headers=headers, callback=self.parse)
    
    # Parse JSON data
    def parse(self, response):
        data = response.json()
        
        for tire in data:
            yield tire
