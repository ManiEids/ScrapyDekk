import json, sys
from collections import Counter
data = json.load(open("combined_tire_data.json", encoding="utf-8"))
counts = Counter(i.get("seller") for i in data)
stale = Counter(i.get("seller") for i in data if i.get("stale"))
print("Merged total:", len(data))
for s in ["Klettur", "Mitra", "Nesdekk", "N1"]:
    c = stale.get(s, 0)
    print(f"{s}: {counts.get(s, 0)}" + (f"  ({c} carried over)" if c else ""))
missing = [s for s in ["Klettur", "Mitra", "Nesdekk"] if counts.get(s, 0) == 0]
if missing:
    sys.exit(f"Refusing to publish. Missing core seller data: {', '.join(missing)}")
if len(data) < 1000:
    sys.exit(f"Refusing to publish suspiciously small feed: {len(data)} rows")
print("Feed validation passed.")
