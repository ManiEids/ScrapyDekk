#!/usr/bin/env python3
"""Reuse the previous feed's rows for any core seller that scraped empty.

nesdekk.is is behind Cloudflare and answers the runner with HTTP 403 when it
scores the request as a bot.  That used to abort the whole publish, so
dekkjahusid.is got no feed at all -- Klettur, Mitra and N1 prices went stale
along with Nesdekk's.

This script runs after merge_tires.py.  If a core seller contributed no rows,
its rows from the last published feed are re-added, tagged `stale` with the
date they went stale, and dropped once they exceed MAX_STALE_DAYS.  Rows that
scraped normally are left exactly as merge_tires.py wrote them.
"""

import json
import os
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

FEED = Path("combined_tire_data.json")
PREVIOUS = Path("previous_feed.json")

CORE_SELLERS = ["Klettur", "Mitra", "Nesdekk"]
MAX_STALE_DAYS = int(os.environ.get("MAX_STALE_DAYS", "3"))


def load_rows(path):
    """Return a list of rows, or None if the file is missing or unusable."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"::warning::{path} is not valid JSON ({exc}); ignoring it")
        return None
    if not isinstance(data, list):
        print(f"::warning::{path} is not a JSON array; ignoring it")
        return None
    return data


def parse_stale_since(value, default):
    """Read a `stale_since` date, falling back to `default` when unusable."""
    if not value:
        return default
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return default


def main():
    feed = load_rows(FEED)
    if feed is None:
        sys.exit(f"{FEED} is missing or unreadable - run merge_tires.py first")

    counts = Counter(row.get("seller") for row in feed)
    missing = [s for s in CORE_SELLERS if counts.get(s, 0) == 0]
    if not missing:
        print("All core sellers scraped rows; nothing to carry over.")
        return

    previous = load_rows(PREVIOUS)
    if previous is None:
        print(
            "::warning::No usable previous feed, so nothing can be carried "
            f"over for: {', '.join(missing)}"
        )
        return

    today = date.today()
    cutoff = today - timedelta(days=MAX_STALE_DAYS)

    for seller in missing:
        rows = [r for r in previous if r.get("seller") == seller]
        if not rows:
            print(
                f"::warning::{seller} scraped 0 rows and is absent from the "
                "previous feed too"
            )
            continue

        kept = []
        for row in rows:
            # A row with no stale_since was fresh in the previous feed, so it
            # goes stale as of today.
            since = parse_stale_since(row.get("stale_since"), today)
            if since < cutoff:
                continue
            carried = dict(row)
            carried["stale"] = True
            carried["stale_since"] = since.isoformat()
            kept.append(carried)

        if not kept:
            print(
                f"::warning::{seller} scraped 0 rows and its carried-over data "
                f"is older than {MAX_STALE_DAYS} days; dropping the seller"
            )
            continue

        oldest = min(date.fromisoformat(r["stale_since"]) for r in kept)
        age = (today - oldest).days
        feed.extend(kept)
        print(
            f"::warning::{seller} scraped 0 rows; carried over {len(kept)} rows "
            f"from the previous feed (stale since {oldest.isoformat()}, "
            f"{age} day(s) old, dropped after {MAX_STALE_DAYS})"
        )

    FEED.write_text(
        json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Feed now holds {len(feed)} rows.")


if __name__ == "__main__":
    main()
