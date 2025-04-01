import subprocess
from multiprocessing import Pool
from pathlib import Path

spiders = [
    "dekkjahollin",
    "klettur",
    "mitra",
    "n1",
    "nesdekk",
    "dekkjasalan"
]

# Step 1: Clean up old JSON files
def delete_old_jsons():
    print("🔄 Cleaning up old JSON files...")
    for spider in spiders:
        json_path = Path(f"{spider}.json")
        if json_path.exists():
            json_path.unlink()
            print(f"🗑️ Deleted: {json_path}")
    output_json = Path("combined_tire_data.json")
    if output_json.exists():
        output_json.unlink()
        print(f"🗑️ Deleted: {output_json}")

# Step 2: Run each spider
def run_spider(spider):
    print(f"🕷️ Starting spider: {spider}")
    subprocess.run(["scrapy", "crawl", spider, "-o", f"{spider}.json"])
    print(f"✅ Finished spider: {spider}")

if __name__ == "__main__":
    delete_old_jsons()

    print("\n🚀 Running all spiders in parallel...")
    with Pool(len(spiders)) as pool:
        pool.map(run_spider, spiders)

    print("\n📦 All spiders finished. Running merge script...")
    result = subprocess.run(["python", "merge_tires.py"])

    if result.returncode == 0:
        print("✅ Merge completed successfully. Running seed script...")
        seed_result = subprocess.run(["python", "seed_db.py"])
        if seed_result.returncode == 0:
            print("✅ Database seeding completed.")
        else:
            print("❌ Seeding script failed.")
    else:
        print("❌ Merge script failed.")
