import subprocess
import sys
import time
from multiprocessing import Pool
from pathlib import Path

spiders = [
    "klettur",
    "mitra",
    "nesdekk",
    "n1",
]

PROJECT_DIR = Path(__file__).parent

# Spider-specific Scrapy settings overrides passed via -s flag.
# klettur: high concurrency (API can handle it)
# mitra:   moderate concurrency (JSON API, paginated)
# nesdekk: conservative (HTML scraping, be polite)
SPIDER_SETTINGS = {
    "klettur":  ["-s", "CONCURRENT_REQUESTS=16", "-s", "CONCURRENT_REQUESTS_PER_DOMAIN=16"],
    "mitra":    ["-s", "CONCURRENT_REQUESTS=8"],
    "nesdekk":  ["-s", "CONCURRENT_REQUESTS=4", "-s", "DOWNLOAD_DELAY=0.5"],
}

def delete_old_jsons():
    print("Hreinsa upp gömul JSON skrár...")
    for spider in spiders:
        json_path = PROJECT_DIR / f"{spider}.json"
        if json_path.exists():
            try:
                json_path.unlink()
                print(f"  Eytt: {json_path.name}")
            except PermissionError:
                print(f"  Gat ekki eytt {json_path.name}, sleppum.")
    output_json = PROJECT_DIR / "combined_tire_data.json"
    if output_json.exists():
        try:
            output_json.unlink()
            print(f"  Eytt: combined_tire_data.json")
        except PermissionError:
            print(f"  Gat ekki eytt combined_tire_data.json, sleppum.")

def run_spider(spider):
    t0 = time.time()
    print(f"Byrja a könguló: {spider}")
    extra_settings = SPIDER_SETTINGS.get(spider, [])
    subprocess.run(
        ["scrapy", "crawl", spider, "-O", f"{spider}.json"] + extra_settings,
        cwd=str(PROJECT_DIR),
        check=False,
    )
    elapsed = time.time() - t0
    print(f"Lokid vid könguló: {spider} ({elapsed:.0f}s)")

if __name__ == "__main__":
    total_start = time.time()
    delete_old_jsons()

    print(f"\nKeyri {len(spiders)} köngulær samhlida...")
    with Pool(len(spiders)) as pool:
        pool.map(run_spider, spiders)

    spider_time = time.time() - total_start
    print(f"\nAllar köngulær bunar ({spider_time:.0f}s). Keyri sameiningarskriptu...")

    result = subprocess.run(
        ["python", "merge_tires.py"],
        cwd=str(PROJECT_DIR),
    )

    if result.returncode != 0:
        print("Samkeyrsluskripta mistokst.")
        sys.exit(1)

    total_time = time.time() - total_start
    print(f"Lokid. combined_tire_data.json tilbuin. Heildartimi: {total_time:.0f}s")