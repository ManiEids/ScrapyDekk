#!/usr/bin/env python3
"""Diagnostic: what can a GitHub runner actually fetch from nesdekk.is?

Not part of the pipeline. Run from the "Nesdekk access probe" workflow to
find out whether Cloudflare's 403 is tied to the client's TLS fingerprint,
the User-Agent, or purely to the runner's datacenter IP - and whether any
useful path is served despite it.
"""

import json
import ssl
import sys
import urllib.error
import urllib.request

BASE = "https://nesdekk.is"

TARGETS = {
    "robots.txt": f"{BASE}/robots.txt",
    "home": f"{BASE}/",
    "listing (no query)": f"{BASE}/dekkjaleit/",
    "listing p1 (scraped)": f"{BASE}/dekkjaleit/?tyre-filter=1",
    "listing p2": f"{BASE}/dekkjaleit/page/2/?tyre-filter=1",
    "product RSS feed": f"{BASE}/dekkjaleit/feed/",
    "product page": f"{BASE}/vara/48-205/55r16-v-pwiz2/",
    "static upload": f"{BASE}/wp-content/uploads/2025/03/PWIZ2-200x150.jpg",
}

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "is-IS,is;q=0.9,en-US;q=0.8,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}

INTERESTING = ("cf-ray", "cf-mitigated", "cf-cache-status", "server", "retry-after")


def summarise(status, headers, body):
    """One-line verdict plus the Cloudflare headers that explain it."""
    hdrs = {k.lower(): v for k, v in dict(headers).items()}
    bits = [f"{k}={hdrs[k]}" for k in INTERESTING if k in hdrs]
    note = ""
    text = (body or b"")[:4000].decode("utf-8", "replace").lower()
    if "just a moment" in text or "cf-chl" in text or "challenge-platform" in text:
        note = "  <-- JS CHALLENGE PAGE"
    elif status == 403:
        note = "  <-- hard block (no challenge)"
    return f"{status}  {' '.join(bits)}{note}"


def probe_urllib(url):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            return summarise(resp.status, resp.headers, resp.read(4000))
    except urllib.error.HTTPError as exc:
        return summarise(exc.code, exc.headers, exc.read(4000))
    except Exception as exc:  # noqa: BLE001 - diagnostic, report anything
        return f"ERROR {type(exc).__name__}: {exc}"


def probe_curl_cffi(url, impersonate):
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        return "curl_cffi not installed"
    try:
        resp = cffi.get(url, impersonate=impersonate, timeout=30)
        return summarise(resp.status_code, resp.headers, resp.content[:4000])
    except Exception as exc:  # noqa: BLE001
        return f"ERROR {type(exc).__name__}: {exc}"


def main():
    print("=" * 78)
    print("CLIENT A: python urllib + Chrome headers (python TLS fingerprint)")
    print("=" * 78)
    results = {}
    for name, url in TARGETS.items():
        line = probe_urllib(url)
        results[f"urllib::{name}"] = line
        print(f"{name:24s} {line}")

    for impersonate in ("chrome", "chrome124", "chrome110"):
        print()
        print("=" * 78)
        print(f"CLIENT B: curl_cffi impersonate={impersonate} (real Chrome TLS/JA3)")
        print("=" * 78)
        probe = probe_curl_cffi(TARGETS["listing p1 (scraped)"], impersonate)
        if "ERROR" in probe and "impersonate" in probe.lower():
            print(f"unsupported target: {probe}")
            continue
        for name, url in TARGETS.items():
            line = probe_curl_cffi(url, impersonate)
            results[f"curl_cffi[{impersonate}]::{name}"] = line
            print(f"{name:24s} {line}")
        break

    print()
    print("=" * 78)
    print("VERDICT")
    print("=" * 78)
    wins = [k for k, v in results.items() if v.startswith("200")]
    if wins:
        print("Reachable from this runner:")
        for w in wins:
            print(f"  OK  {w}")
    else:
        print("Nothing reachable. Every client and path was blocked.")
    with open("probe_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
