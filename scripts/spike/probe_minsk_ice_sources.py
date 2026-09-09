#!/usr/bin/env python3
"""Spike: can we read mass-skating schedule + prices from public pages?

Read-only HTTP probe for Minsk arenas. No DB writes, no product code.
Run from repo root:

  python scripts/spike/probe_minsk_ice_sources.py
  python scripts/spike/probe_minsk_ice_sources.py --json

Prod arena list (optional refresh):

  railway run -s Postgres-W--1 -- .venv/bin/python scripts/spike/probe_minsk_ice_sources.py --refresh-prod
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
PROD_CSV = ROOT / "data/minsk-arenas-prod.csv"
MANIFEST = ROOT / "data/minsk-arena-source-manifest.yaml"
REPORT_JSON = ROOT / "data/minsk-ice-probe-report.json"
REPORT_MD = ROOT / "data/minsk-ice-probe-report.md"

TIME_RE = re.compile(r"\b((?:[01]?\d|2[0-3])[:\.][0-5]\d)\b")
PRICE_RE = re.compile(
    r"\b(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:р\.?|руб(?:\.|лей)?|BYN|бел\.?\s*руб)\b",
    re.IGNORECASE,
)
MK_KEYWORDS = (
    "массов",
    "катан",
    "сеанс",
    "ледов",
    "каток",
    "мк ",
    "дискотек",
)
SESSION_GRID_HINTS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


@dataclass
class UrlProbe:
    url: str
    http_status: int | None = None
    error: str | None = None
    bytes: int = 0
    time_samples: list[str] = field(default_factory=list)
    price_samples: list[str] = field(default_factory=list)
    has_mk_keywords: bool = False
    has_weekday_grid: bool = False
    verdict: str = "fail"

    def score(self) -> tuple[bool, bool]:
        """(times_ok, prices_ok) heuristic for spike gate."""
        times_ok = len(self.time_samples) >= 3 or (self.has_weekday_grid and len(self.time_samples) >= 1)
        prices_ok = len(self.price_samples) >= 1
        return times_ok, prices_ok


@dataclass
class ArenaProbe:
    arena_id: int
    name: str
    expectation: str
    notes: str
    urls: list[UrlProbe] = field(default_factory=list)
    best_times: bool = False
    best_prices: bool = False
    spike_verdict: str = "unknown"

    def finalize(self) -> None:
        if self.expectation in ("training_only", "not_ice"):
            self.spike_verdict = "skip_" + self.expectation
            return
        for u in self.urls:
            t, p = u.score()
            self.best_times = self.best_times or t
            self.best_prices = self.best_prices or p
        if self.best_times and self.best_prices:
            self.spike_verdict = "parse_ready"
        elif self.best_times:
            self.spike_verdict = "times_only"
        elif self.best_prices:
            self.spike_verdict = "prices_only"
        elif any(u.http_status and 200 <= u.http_status < 400 for u in self.urls):
            self.spike_verdict = "reachable_no_signal"
        else:
            self.spike_verdict = "unreachable"


def _load_yaml_manifest(path: Path) -> list[dict[str, Any]]:
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return list(data.get("sources") or [])
    except ImportError:
        pass

    entries: list[dict[str, Any]] = []
    block: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- arena_id:"):
            if block:
                entries.append(block)
            block = {"urls": [], "arena_id": int(stripped.split(":", 1)[1].strip())}
            continue
        if block is None or not line.startswith("    "):
            continue
        body = line[4:]
        if body.startswith("name:"):
            block["name"] = body.split(":", 1)[1].strip().strip('"')
        elif body.startswith("expectation:"):
            block["expectation"] = body.split(":", 1)[1].strip()
        elif body.startswith("notes:"):
            block["notes"] = body.split(":", 1)[1].strip().strip('"')
        elif body.startswith("urls:"):
            continue
        elif body.startswith("- "):
            block["urls"].append(body[2:].strip())
        elif line.startswith("      - "):
            block["urls"].append(line.split("- ", 1)[1].strip())
    if block:
        entries.append(block)
    return entries


def fetch_url(url: str, timeout: float = 20.0) -> UrlProbe:
    probe = UrlProbe(url=url)
    req = Request(
        url,
        headers={
            # Many BY rink sites drop non-browser UA (connection reset). Spike models real fetch.
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-BY,ru;q=0.9",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            probe.http_status = getattr(resp, "status", None) or resp.getcode()
            raw = resp.read(500_000)
            probe.bytes = len(raw)
            text = raw.decode("utf-8", errors="replace").lower()
    except HTTPError as e:
        probe.http_status = e.code
        probe.error = str(e)
        probe.verdict = "http_error"
        return probe
    except URLError as e:
        probe.error = str(e.reason)
        probe.verdict = "network_error"
        return probe
    except Exception as e:  # noqa: BLE001 spike script
        probe.error = repr(e)
        probe.verdict = "error"
        return probe

    probe.time_samples = sorted({t.replace(".", ":") for t in TIME_RE.findall(text)})[:20]
    probe.price_samples = sorted(set(PRICE_RE.findall(text)))[:10]
    probe.has_mk_keywords = any(k in text for k in MK_KEYWORDS)
    probe.has_weekday_grid = any(w in text for w in SESSION_GRID_HINTS)

    t_ok, p_ok = probe.score()
    if t_ok and p_ok:
        probe.verdict = "times_and_prices"
    elif t_ok:
        probe.verdict = "times_only"
    elif p_ok:
        probe.verdict = "prices_only"
    elif probe.has_mk_keywords:
        probe.verdict = "keywords_only"
    else:
        probe.verdict = "no_signal"
    return probe


def refresh_prod_csv() -> int:
    import os

    try:
        import psycopg
    except ImportError:
        import psycopg2 as psycopg  # type: ignore

    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_PUBLIC_URL not set; run via: railway run -s Postgres-W--1 -- ...", file=sys.stderr)
        return 1
    with psycopg.connect(url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a.name, a.address, a.latitude, a.longitude, a.is_active, a.is_confirmed
                FROM arenas a
                JOIN cities c ON c.id = a.city_id
                WHERE c.name = 'Минск'
                ORDER BY a.is_active DESC, a.name
                """
            )
            rows = cur.fetchall()
    PROD_CSV.parent.mkdir(parents=True, exist_ok=True)
    with PROD_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["arena_id", "name", "address", "latitude", "longitude", "is_active", "is_confirmed"])
        w.writerows(rows)
    print(f"Refreshed {len(rows)} rows -> {PROD_CSV}")
    return 0


def run_probe() -> list[ArenaProbe]:
    entries = _load_yaml_manifest(MANIFEST)
    results: list[ArenaProbe] = []
    for entry in entries:
        arena = ArenaProbe(
            arena_id=int(entry["arena_id"]),
            name=str(entry.get("name") or ""),
            expectation=str(entry.get("expectation") or "unknown"),
            notes=str(entry.get("notes") or ""),
        )
        for url in entry.get("urls") or []:
            arena.urls.append(fetch_url(url))
            time.sleep(0.4)
        arena.finalize()
        results.append(arena)
    return results


def write_reports(results: list[ArenaProbe]) -> None:
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "prod_csv": str(PROD_CSV.relative_to(ROOT)),
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "summary": _summary(results),
        "arenas": [
            {
                **{k: v for k, v in asdict(a).items() if k != "urls"},
                "urls": [asdict(u) for u in a.urls],
            }
            for a in results
        ],
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Minsk ice source probe (spike)",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "## Summary",
        "",
    ]
    s = payload["summary"]
    lines.append(f"- **parse_ready** (times + prices in HTML): **{s['parse_ready']}**")
    lines.append(f"- **times_only**: {s['times_only']}")
    lines.append(f"- **prices_only**: {s['prices_only']}")
    lines.append(f"- **reachable_no_signal**: {s['reachable_no_signal']}")
    lines.append(f"- **unreachable**: {s['unreachable']}")
    lines.append(f"- **skipped** (training / not ice): {s['skipped']}")
    lines.append("")
    lines.append("## Per arena")
    lines.append("")
    for a in results:
        lines.append(f"### [{a.arena_id}] {a.name} — `{a.spike_verdict}`")
        lines.append(f"Expectation: {a.expectation}. {a.notes}")
        for u in a.urls:
            lines.append(f"- {u.url}: status={u.http_status}, verdict={u.verdict}, times={len(u.time_samples)}, prices={len(u.price_samples)}")
        lines.append("")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def _summary(results: list[ArenaProbe]) -> dict[str, int]:
    keys = (
        "parse_ready",
        "times_only",
        "prices_only",
        "reachable_no_signal",
        "unreachable",
        "skip_training_only",
        "skip_not_ice",
        "unknown",
    )
    out = {k: 0 for k in keys}
    for a in results:
        if a.spike_verdict.startswith("skip_"):
            out[a.spike_verdict] = out.get(a.spike_verdict, 0) + 1
        else:
            out[a.spike_verdict] = out.get(a.spike_verdict, 0) + 1
    out["skipped"] = out.get("skip_training_only", 0) + out.get("skip_not_ice", 0)
    return out


def print_table(results: list[ArenaProbe]) -> None:
    print(f"{'id':>3}  {'verdict':<22}  {'times':^5}  {'prices':^6}  name")
    print("-" * 72)
    for a in results:
        print(f"{a.arena_id:>3}  {a.spike_verdict:<22}  {str(a.best_times):^5}  {str(a.best_prices):^6}  {a.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe public Minsk rink pages for parseable schedule/prices")
    parser.add_argument("--refresh-prod", action="store_true", help="Re-export Minsk arenas from Railway Postgres")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args()

    if args.refresh_prod:
        return refresh_prod_csv()

    if not MANIFEST.exists():
        print(f"Missing manifest: {MANIFEST}", file=sys.stderr)
        return 1

    results = run_probe()
    write_reports(results)
    print_table(results)
    s = _summary(results)
    print()
    print(
        f"Gate: {s['parse_ready']} parse-ready, {s['times_only']} times-only, "
        f"{s['skipped']} skipped (not target MK)"
    )
    print(f"Reports: {REPORT_JSON.relative_to(ROOT)} , {REPORT_MD.relative_to(ROOT)}")
    if args.json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
