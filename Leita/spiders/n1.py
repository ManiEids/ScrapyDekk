import scrapy
import json
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# Extract attribute value
def extract_attribute_value(attributes, slug):
    for attr in attributes:
        if attr.get("attribute", {}).get("slug") == slug:
            values = attr.get("values", [])
            if values:
                return values[0].get("value")
    return None

# Extract picture URL
def extract_picture(variants):
    for variant in variants:
        media_list = variant.get("media", [])
        if media_list:
            image_info = media_list[0].get("image", {})
            return image_info.get("productList") or image_info.get("productGallery")
    return None

# Get first variant SKU
def get_first_variant_sku(product):
    variants = product.get("variants", [])
    if variants:
        metadata = variants[0].get("metadata", {})
        return metadata.get("sku")
    return None

# Check if in stock
def is_in_stock(product):
    variants = product.get("variants", [])
    for variant in variants:
        stock = variant.get("stockLevel", {}).get("stockLevel", "").lower()
        if stock and stock != "out of stock":
            return True
    return False

class N1FullCatalogueSpider(scrapy.Spider):
    name = "n1"
    allowed_domains = ["backend.n1.is"]

    # Start requests
    def start_requests(self):
        payload = {
            "attributes": [],
            "categorySlug": "004-hjolbardar-og-tengdar-vorur"
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Content-Type": "application/json",
            "Origin": "https://vefverslun.n1.is",
            "Referer": "https://vefverslun.n1.is/voruflokkur/hjolbardar-og-tengdar-vorur",
            "Accept": "*/*"
        }
        body = json.dumps(payload)
        url = "https://backend.n1.is/api/products/attribute_filter/?page_size=24&page=1"
        yield scrapy.Request(
            url=url,
            method="POST",
            headers=headers,
            body=body,
            callback=self.parse,
            meta={"payload_body": body, "payload_headers": headers}
        )

    # Parse response
    def parse(self, response):
        self.logger.info(f"Received response {response.status} from {response.url}")
        try:
            data = response.json()
        except Exception as e:
            self.logger.error("Error parsing JSON: " + str(e))
            return

        results = data.get("results", [])
        self.logger.info(f"Found {len(results)} products on this page.")

        candidate_products = []
        skus = []

        for product in results:
            if not is_in_stock(product):
                continue

            product_name = product.get("name")
            attributes = product.get("attributes", [])
            manufacturer = extract_attribute_value(attributes, "ProductManufacturer")

            width = extract_attribute_value(attributes, "ProductTireSectionWidthName")
            profile = extract_attribute_value(attributes, "ProductTireTreadProfile")
            sidewall = extract_attribute_value(attributes, "ProductTireSidewallSize")
            size = None
            if width and profile and sidewall:
                size = f"{width}/{profile}/{sidewall}"

            variants = product.get("variants", [])
            picture = extract_picture(variants)
            sku = get_first_variant_sku(product)
            if not sku:
                continue

            candidate_products.append({
                "name": product_name,
                "manufacturer": manufacturer,
                "size": size,
                "picture": picture,
                "stock": "in stock",
                "sku": sku
            })
            skus.append(sku)

        if skus:
            multiprice_url = "https://backend.n1.is/api/products/multiprice/?" + "&".join([f"skus={sku}" for sku in skus])
            yield scrapy.Request(
                url=multiprice_url,
                callback=self.parse_multiprice,
                meta={"products": candidate_products}
            )
        else:
            self.logger.info("No candidate products on this page after filtering.")

        parsed = urlparse(response.url)
        qs = parse_qs(parsed.query)
        current_page = int(qs.get("page", [1])[0])
        if results:
            next_page_number = current_page + 1
            qs["page"] = [str(next_page_number)]
            new_query = urlencode(qs, doseq=True)
            next_page_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
            self.logger.info(f"Following next page: {next_page_url}")
            yield scrapy.Request(
                url=next_page_url,
                method="POST",
                headers=response.meta["payload_headers"],
                body=response.meta["payload_body"],
                callback=self.parse,
                meta=response.meta
            )
        else:
            self.logger.info("No more results, stopping pagination.")

    # Parse multiprice
    def parse_multiprice(self, response):
        try:
            price_data = response.json()
        except Exception as e:
            self.logger.error("Error parsing multiprice JSON: " + str(e))
            return

        products = response.meta["products"]
        price_map = {}
        for entry in price_data:
            sku = entry.get("itemId")
            price_map[sku] = entry

        for prod in products:
            sku = prod["sku"]
            price_info = price_map.get(sku)
            if price_info:
                prod["price"] = price_info.get("price", "N/A")
            else:
                prod["price"] = "N/A"
            prod.pop("sku", None)
            yield prod
