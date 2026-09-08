#!/usr/bin/env python3
"""Fetch a URL via a Belarus Globalping probe (real BY residential/ISP IP).

Proves geo-unblocking. Public API truncates HTTP body at 10 KB, so this is a
reachability check, not a full-page dump.

  python scripts/spike/fetch_via_by_globalping.py https://ledlife.by/massovye_kataniya/
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

API = "https://api.globalping.io/v1/measurements"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data/globalping-by-bodies"


def _json_req(url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_from_by(url: str, limit: int = 1) -> dict:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    created = _json_req(
        API,
        {
            "type": "http",
            "target": host,
            "locations": [{"country": "BY", "limit": limit}],
            "measurementOptions": {
                "protocol": "HTTPS" if parsed.scheme != "http" else "HTTP",
                "request": {"method": "GET", "path": path, "host": host},
            },
        },
    )
    mid = created["id"]
    body: dict = {}
    for _ in range(20):
        body = _json_req(f"{API}/{mid}")
        if body.get("status") == "finished":
            break
        time.sleep(1.5)
    return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    args = parser.parse_args()
    data = fetch_from_by(args.url)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"status={data.get('status')} id={data.get('id')}")
    for res in data.get("results") or []:
        probe = res.get("probe") or {}
        loc = probe.get("location") or probe
        r = res.get("result") or {}
        html = r.get("rawBody") or ""
        city = loc.get("city")
        print(
            f"  {loc.get('country')}/{city} HTTP {r.get('statusCode')} "
            f"truncated={r.get('truncated')} body={len(html)}B network={loc.get('network')}"
        )
        if html:
            slug = (city or "by").lower().replace(" ", "-")
            path = OUT_DIR / f"{slug}.html"
            path.write_text(html, encoding="utf-8")
            print(f"  wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
