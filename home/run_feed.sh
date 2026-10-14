#!/usr/bin/env bash
# Nightly feed build for a machine on a residential IP (nesdekk.is challenges
# datacenter/Azure ASNs, so GitHub runners cannot scrape it any more).
# spiders -> merge -> carry-over -> validate -> upload tire-feed asset -> dispatch wp-sync.
# Needs: git, python3, gh (authenticated; repo write + actions write).
# DRY_RUN=1 runs everything except the upload and the WordPress dispatch.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="${REPO:-ManiEids/ScrapyDekk}"
export MAX_STALE_DAYS="${MAX_STALE_DAYS:-3}"
LOGDIR="${LOGDIR:-$PWD/home/logs}"; mkdir -p "$LOGDIR"
exec > >(tee -a "$LOGDIR/run-$(date +%F).log") 2>&1
echo "=== feed run $(date -Is) ==="

[ "${NO_PULL:-0}" = 1 ] || git pull --ff-only -q || echo "warn: git pull failed, using local checkout"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
export PATH="$PWD/.venv/bin:$PATH"

rm -f klettur.json mitra.json nesdekk.json n1.json combined_tire_data.json previous_feed.json
common=(-s DOWNLOAD_TIMEOUT=30 -s AUTOTHROTTLE_ENABLED=True -s AUTOTHROTTLE_START_DELAY=0.5 -s AUTOTHROTTLE_MAX_DELAY=6)
# Core spiders run in parallel; nesdekk is deliberately gentle.
timeout 15m scrapy crawl klettur -O klettur.json "${common[@]}" -s CLOSESPIDER_TIMEOUT=840 \
  -s CONCURRENT_REQUESTS=8 -s CONCURRENT_REQUESTS_PER_DOMAIN=4 > "$LOGDIR/klettur.log" 2>&1 & P1=$!
timeout 15m scrapy crawl mitra -O mitra.json "${common[@]}" -s CLOSESPIDER_TIMEOUT=840 \
  -s CONCURRENT_REQUESTS=8 -s CONCURRENT_REQUESTS_PER_DOMAIN=4 > "$LOGDIR/mitra.log" 2>&1 & P2=$!
timeout 30m scrapy crawl nesdekk -O nesdekk.json "${common[@]}" -s CLOSESPIDER_TIMEOUT=1740 \
  -s CONCURRENT_REQUESTS=2 -s CONCURRENT_REQUESTS_PER_DOMAIN=2 -s DOWNLOAD_DELAY=0.5 > "$LOGDIR/nesdekk.log" 2>&1 & P3=$!
wait $P1 || echo "warn: klettur exited non-zero"
wait $P2 || echo "warn: mitra exited non-zero"
wait $P3 || echo "warn: nesdekk exited non-zero"
timeout 12m scrapy crawl n1 -O n1.json "${common[@]}" > "$LOGDIR/n1.log" 2>&1 || { echo "warn: n1 failed"; echo '[]' > n1.json; }

for f in klettur mitra nesdekk n1; do
  [ -s "$f.json" ] || echo '[]' > "$f.json"
  echo "$f raw: $(python3 -c "import json;print(len(json.load(open('$f.json'))))")"
done

# previous feed for carry-over (a missing one just disables carry-over)
gh release download tire-feed --repo "$REPO" --pattern combined_tire_data.json \
  --output previous_feed.json --clobber || rm -f previous_feed.json

python merge_tires.py
python carry_over.py
python home/validate_feed.py

if [ "${DRY_RUN:-0}" = 1 ]; then echo "DRY_RUN: skipping upload + wp-sync"; exit 0; fi
gh release upload tire-feed combined_tire_data.json --repo "$REPO" --clobber
gh workflow run wp-sync.yml --repo "$REPO" --ref main
echo "=== done $(date -Is) ==="
