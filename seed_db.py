import json
import psycopg2
from psycopg2.extras import execute_batch
from decimal import Decimal

print("🚀 Starting seeding process...")

# Connect to Neon DB
try:
    conn = psycopg2.connect(
        dbname="neondb",
        user="neondb_owner",
        password="npg_lrCXzKNO9A2t",
        host="ep-ancient-queen-a2bhzxqa-pooler.eu-central-1.aws.neon.tech",
        sslmode="require"
    )
    print("🔗 Connected to Neon PostgreSQL.")
except Exception as e:
    print(f"❌ Connection failed: {e}")
    exit()

cur = conn.cursor()

# ✅ Step 1: Truncate the tires table
try:
    cur.execute("TRUNCATE TABLE tires;")
    conn.commit()
    print("🧹 Cleared existing data from 'tires' table.")
except Exception as e:
    print(f"❌ Failed to truncate table: {e}")
    conn.close()
    exit()

# ✅ Step 2: Load new JSON data
try:
    with open("combined_tire_data.json", "r", encoding="utf-8") as f:
        tires = json.load(f)
    print(f"📦 Loaded {len(tires)} tire records.")
except Exception as e:
    print(f"❌ Failed to read JSON file: {e}")
    conn.close()
    exit()

# ✅ Step 3: Prepare records for batch insert
records = []
skipped = 0

for item in tires:
    try:
        records.append((
            item.get("seller"),
            item.get("manufacturer"),
            item.get("product_name"),
            int(item["width"]) if item.get("width") else None,
            int(item["aspect_ratio"]) if item.get("aspect_ratio") else None,
            int(item["rim_size"]) if item.get("rim_size") else None,
            Decimal(str(item["price"])) if item.get("price") is not None else None,
            item.get("stock"),
            int(item["inventory_count"]) if item.get("inventory_count") is not None else None,
            item.get("picture")
        ))
    except Exception as e:
        skipped += 1
        print(f"⚠️ Skipping item due to error: {e}")

# ✅ Step 4: Insert all new records
try:
    print(f"📤 Inserting {len(records)} new tires...")
    execute_batch(cur, """
        INSERT INTO tires (
            seller, manufacturer, product_name,
            width, aspect_ratio, rim_size,
            price, stock, inventory_count, picture
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
    """, records)
    conn.commit()
    print(f"✅ Done! Inserted: {len(records)} | Skipped: {skipped}")
except Exception as e:
    print(f"❌ Insert failed: {e}")

cur.close()
conn.close()
