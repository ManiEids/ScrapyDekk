# Leita — Icelandic Tire Price Scraper

Scrapes tire listings from three Icelandic retailers, merges the results into a single `combined_tire_data.json` feed, and publishes it as a rolling GitHub Release asset.

A WordPress plugin on [dekkjahusid.is](https://dekkjahusid.is) pulls that asset to keep its price comparison table up to date.

## Sources

| Spider | Retailer | Method |
|--------|----------|--------|
| `klettur` | [dekk.klettur.is](https://dekk.klettur.is) | JSON API |
| `mitra` | [mitra.is](https://mitra.is) | JSON API |
| `nesdekk` | [nesdekk.is](https://nesdekk.is) | HTML scrape |

## Automated runs

A GitHub Actions workflow ([`.github/workflows/scrape.yml`](.github/workflows/scrape.yml)) runs every 24 hours and publishes the merged feed to the **tire-feed** release tag. No secrets are required.

You can also trigger a run manually from the **Actions** tab → **Scrape tires & publish feed** → **Run workflow**.

## Running locally

**Requirements:** Python 3.10+ and `pip install -r requirements.txt`

```bash
# Run all spiders in parallel, then merge
python run_all.py

# Or run a single spider
scrapy crawl klettur -O klettur.json

# Merge existing JSON files into the combined feed
python merge_tires.py
```

`combined_tire_data.json` is written to the repo root. It is excluded from version control (see `.gitignore`) — the canonical copy lives in the GitHub Release asset.

## Output format

Each entry in `combined_tire_data.json`:

```json
{
  "seller": "Klettur",
  "sku": "...",
  "manufacturer": "Michelin",
  "product_name": "205/55R16 Michelin Primacy 4 91V",
  "width": 205,
  "aspect_ratio": 55,
  "rim_size": 16,
  "season": "Sumardekk",
  "price": 18990,
  "stock": "in stock",
  "inventory_count": 8,
  "picture": "https://...",
  "source": "klettur.is"
}
```

## Project structure

```
.github/workflows/scrape.yml  # cron + publish workflow
Leita/spiders/
    klettur.py                # active
    mitra.py                  # active
    nesdekk.py                # active
    dekkjahollin.py           # inactive (kept for reference)
    dekkjasalan.py            # inactive (kept for reference)
    n1.py                     # inactive (kept for reference)
merge_tires.py                # normalises + merges spider output
run_all.py                    # local runner (parallel spiders → merge)
requirements.txt
```
