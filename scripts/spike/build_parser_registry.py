#!/usr/bin/env python3
"""Single source of truth for Minsk ice parser status.

Runs live fetch checks + reads last extraction artifact.
No DB writes.

  python scripts/spike/build_parser_registry.py
  python scripts/spike/build_parser_registry.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SPIKE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SPIKE_DIR))
from http_fetch import FetchResult, classify_block, fetch_html  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_YAML = ROOT / "data/minsk-parser-registry.yaml"
REGISTRY_JSON = ROOT / "data/minsk-parser-registry.json"
EXTRACT_JSON = ROOT / "data/minsk-ice-sessions.json"
PROD_CSV = ROOT / "data/minsk-arenas-prod.csv"
TZ = ZoneInfo("Europe/Minsk")

PRICE_RE = re.compile(
    r"\b(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:р\.?|руб(?:\.|лей)?|BYN|бел\.?\s*руб)\b",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"\b((?:[01]?\d|2[0-3])[:\.][0-5]\d)\b")
MK_KEYWORDS = ("массов", "катан", "сеанс", "ледов", "каток")
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
IMAGE_PRICE_RE = re.compile(
    r"""<img[^>]+src=["']([^"']*(?:/cena|/price|cen[a-z_]*|preisk)[^"']*\.(?:png|jpg|jpeg|webp))["']""",
    re.I,
)


@dataclass
class SourceCheck:
    url: str
    role: str
    http_status: int | None
    fetch_ok: bool
    block_reason: str | None = None
    geo_bypass_attempted: bool = False
    geo_bypass_worked: bool = False
    has_times_signal: bool = False
    has_prices_signal: bool = False
    has_price_images: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class ArenaRegistry:
    arena_id: int
    name: str
    target: str
    sources: list[SourceCheck]
    schedule_status: str
    prices_status: str
    parser_status: str
    extractor: str | None
    sessions_extracted: int
    price_catalog_items: int
    blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)


ARENA_DEFS: list[dict[str, Any]] = [
    {
        "arena_id": 3,
        "name": "ТЦ Замок",
        "target": "mass_skating",
        "extractor": "zamok_html_v1",
        "sources": [
            {"url": "https://tczamok.by/entertainments/ice-rink", "role": "schedule+prices"},
        ],
    },
    {
        "arena_id": 5,
        "name": "Ледовый дворец спорта Минской области",
        "target": "mass_skating",
        "extractor": "ledby_html_v1",
        "sources": [
            {"url": "http://led.by/category/timetable/", "role": "schedule"},
            {"url": "http://led.by/mass_skating/", "role": "prices"},
        ],
    },
    {
        "arena_id": 6,
        "name": "Чижовка-арена",
        "target": "mass_skating",
        "extractor": "chizhovka_html_v1",
        "sources": [
            {"url": "https://chizhovka-arena.by/fizkultura-i-sport/katanie-na-konkah", "role": "schedule"},
            {"url": "https://chizhovka-arena.by/czeny/katanie-na-konkah", "role": "prices"},
            {"url": "https://katki.chizhovka-arena.by/", "role": "tickets"},
        ],
    },
    {
        "arena_id": 7,
        "name": "ТЦ DiaMond city",
        "target": "mass_skating",
        "extractor": "diamond_html_v1",
        "sources": [
            {"url": "https://diamondcity.by/ledovaya-arena", "role": "schedule"},
            {"url": "https://diamondcity.by/ceny", "role": "prices"},
        ],
    },
    {
        "arena_id": 8,
        "name": 'Каток хк "Юность"',
        "target": "mass_skating",
        "extractor": "junost_weekend_grid_v1",
        "sources": [
            {"url": "https://junost.hockey.by/clubs/skating/", "role": "prices"},
            {"url": "https://junost.by/seansy_massovogo_kataniya_na_vyhodnyh/", "role": "schedule", "try_geo_bypass": True},
        ],
    },
    {
        "arena_id": 4,
        "name": "СДЮШОР по фигурному катанию",
        "target": "mass_skating",
        "extractor": None,
        "sources": [
            {"url": "https://ledlife.by/massovye_kataniya/", "role": "schedule+prices", "try_geo_bypass": True},
        ],
    },
    {
        "arena_id": 2,
        "name": "Минск Арена",
        "target": "mass_skating",
        "extractor": "minskarena_bycard_v1",
        "sources": [
            {"url": "https://minskarena.by/services.html", "role": "schedule"},
            {"url": "https://bycard.by/afisha/minsk/katki/5821807", "role": "aggregator"},
            {"url": "https://abws.bycard.by/api/v3/pages/events/konkobezhnyy-stadion-minsk-arena", "role": "schedule+prices"},
        ],
    },
    {
        "arena_id": 9,
        "name": "Олимпик-арена",
        "target": "unknown",
        "extractor": None,
        "sources": [{"url": "https://olympicarena.by/", "role": "site"}],
    },
    {
        "arena_id": 13,
        "name": 'Хоккейный центр "JUSTSKATE"',
        "target": "training_only",
        "extractor": None,
        "sources": [{"url": "https://justskate.by/", "role": "site"}],
    },
    {
        "arena_id": 14,
        "name": 'Хоккейный центр «Финт»',
        "target": "training_only",
        "extractor": None,
        "sources": [{"url": "https://fint-tm.by/raspisanie-trenirovok/", "role": "site"}],
    },
    {
        "arena_id": 12,
        "name": "Лыжероллерная трасса",
        "target": "not_ice",
        "extractor": None,
        "sources": [],
    },
]


def strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def analyze_body(result: FetchResult, role: str) -> SourceCheck:
    check = SourceCheck(
        url=result.url,
        role=role,
        http_status=result.http_status,
        fetch_ok=result.ok,
        block_reason=classify_block(result),
        geo_bypass_attempted=result.geo_bypass_attempted,
        geo_bypass_worked=result.geo_bypass_worked,
    )
    if not result.body:
        return check

    text = strip_html(result.body)
    check.has_times_signal = len(TIME_RE.findall(text)) >= 3 or any(w in text for w in WEEKDAYS)
    check.has_prices_signal = bool(PRICE_RE.findall(text))
    if "цен" in role or "price" in role or "prices" in role:
        imgs = IMAGE_PRICE_RE.findall(result.body)
        check.has_price_images = [u if u.startswith("http") else f"https://diamondcity.by{u}" for u in imgs[:5]]
        if check.has_price_images and not check.has_prices_signal:
            check.notes = "prices likely in image(s) on page"
    return check


def load_extract_stats() -> dict[int, dict[str, Any]]:
    if not EXTRACT_JSON.exists():
        return {}
    data = json.loads(EXTRACT_JSON.read_text(encoding="utf-8"))
    out: dict[int, dict[str, Any]] = {}
    for a in data.get("arenas", []):
        out[int(a["arena_id"])] = {
            "extract_status": a.get("extract_status"),
            "sessions": len(a.get("sessions") or []),
            "price_catalog_items": len(a.get("price_catalog") or []),
            "extractor": a.get("extractor"),
            "extract_notes": a.get("extract_notes"),
        }
    return out


def derive_statuses(definition: dict[str, Any], sources: list[SourceCheck], stats: dict[str, Any]) -> ArenaRegistry:
    target = definition["target"]
    if target in ("training_only", "not_ice"):
        return ArenaRegistry(
            arena_id=definition["arena_id"],
            name=definition["name"],
            target=target,
            sources=sources,
            schedule_status="n/a",
            prices_status="n/a",
            parser_status="skipped",
            extractor=None,
            sessions_extracted=0,
            price_catalog_items=0,
            blockers=[f"not a mass-skating target ({target})"],
        )

    sched_sources = [s for s in sources if "schedule" in s.role or s.role in ("site", "aggregator", "schedule+prices", "tickets")]
    price_sources = [s for s in sources if "price" in s.role or s.role in ("schedule+prices", "site")]

    sched_ok = any(s.fetch_ok and s.has_times_signal for s in sched_sources)
    sched_partial = any(s.fetch_ok for s in sched_sources) and stats.get("sessions", 0) > 0
    sched_blocked = any(s.block_reason for s in sched_sources if "schedule" in s.role)

    prices_html = any(s.fetch_ok and s.has_prices_signal for s in price_sources)
    prices_image = any(s.has_price_images for s in price_sources)
    prices_catalog = stats.get("price_catalog_items", 0) > 0

    if stats.get("sessions", 0) > 0:
        schedule_status = "ok" if sched_ok else "partial"
    elif sched_ok:
        schedule_status = "ok"
    elif sched_partial:
        schedule_status = "partial"
    elif sched_blocked:
        schedule_status = "blocked"
    else:
        schedule_status = "failed"

    if prices_html or prices_catalog:
        prices_status = "ok"
    elif prices_image:
        prices_status = "image_only"
    elif any(s.fetch_ok for s in price_sources):
        prices_status = "missing_on_page"
    elif any(s.block_reason for s in price_sources):
        prices_status = "blocked"
    else:
        prices_status = "unknown"

    if target == "unknown" and stats.get("sessions", 0) == 0:
        parser_status = "unknown"
    elif schedule_status == "ok" and prices_status == "ok":
        parser_status = "ready"
    elif schedule_status in ("ok", "partial") and prices_status in ("ok", "image_only", "missing_on_page"):
        parser_status = "partial"
    elif prices_status == "ok" and any(s.fetch_ok for s in sources):
        parser_status = "partial"
    elif schedule_status == "blocked" or prices_status == "blocked":
        parser_status = "blocked"
    elif target == "unknown":
        parser_status = "unknown"
    else:
        parser_status = "failed"

    blockers: list[str] = []
    next_actions: list[str] = []
    for s in sources:
        if s.block_reason:
            blockers.append(f"{s.url}: {s.block_reason}")
    if prices_status == "image_only":
        imgs = next((s.has_price_images for s in price_sources if s.has_price_images), [])
        blockers.append(f"DiaMond prices only as PNG: {', '.join(imgs)}")
        next_actions.append("OCR or manual transcription of official price image")
    if schedule_status == "blocked":
        next_actions.append("Fetch from BY egress IP (Railway BY region / local VPS) or Playwright snapshot")
    if definition["arena_id"] == 2 and stats.get("sessions", 0) == 0:
        parser_status = "partial"
    if definition["arena_id"] == 2:
        next_actions.append("Poll ByCard calendar until isSelling=1 (season tickets)")
    if definition["arena_id"] == 8:
        next_actions.append("Confirm weekend grid from BY IP against junost.by origin")

    return ArenaRegistry(
        arena_id=definition["arena_id"],
        name=definition["name"],
        target=target,
        sources=sources,
        schedule_status=schedule_status,
        prices_status=prices_status,
        parser_status=parser_status,
        extractor=stats.get("extractor") or definition.get("extractor"),
        sessions_extracted=stats.get("sessions", 0),
        price_catalog_items=stats.get("price_catalog_items", 0),
        blockers=blockers,
        next_actions=next_actions,
    )


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Minsk ice parser registry — single source of truth",
        f"# generated_at: {payload['generated_at']}",
        "# Run: python scripts/spike/build_parser_registry.py",
        "",
    ]
    for arena in payload["arenas"]:
        lines.append(f"- arena_id: {arena['arena_id']}")
        lines.append(f"  name: \"{arena['name']}\"")
        lines.append(f"  target: {arena['target']}")
        lines.append(f"  parser_status: {arena['parser_status']}")
        lines.append(f"  schedule_status: {arena['schedule_status']}")
        lines.append(f"  prices_status: {arena['prices_status']}")
        lines.append(f"  extractor: {arena['extractor'] or 'null'}")
        lines.append(f"  sessions_extracted: {arena['sessions_extracted']}")
        lines.append(f"  price_catalog_items: {arena['price_catalog_items']}")
        if arena["blockers"]:
            lines.append("  blockers:")
            for b in arena["blockers"]:
                lines.append(f"    - \"{b}\"")
        if arena["next_actions"]:
            lines.append("  next_actions:")
            for a in arena["next_actions"]:
                lines.append(f"    - \"{a}\"")
        if arena["sources"]:
            lines.append("  sources:")
            for s in arena["sources"]:
                lines.append(f"    - url: {s['url']}")
                lines.append(f"      role: {s['role']}")
                lines.append(f"      http_status: {s['http_status']}")
                lines.append(f"      fetch_ok: {str(s['fetch_ok']).lower()}")
                if s.get("block_reason"):
                    lines.append(f"      block_reason: \"{s['block_reason']}\"")
                if s.get("has_price_images"):
                    lines.append("      price_images:")
                    for img in s["has_price_images"]:
                        lines.append(f"        - {img}")
                if s.get("notes"):
                    lines.append(f"      notes: \"{s['notes']}\"")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_registry() -> dict[str, Any]:
    extract_stats = load_extract_stats()
    arenas: list[ArenaRegistry] = []

    for definition in ARENA_DEFS:
        checks: list[SourceCheck] = []
        for src in definition.get("sources") or []:
            time.sleep(0.35)
            result = fetch_html(src["url"], try_geo_bypass=bool(src.get("try_geo_bypass")))
            checks.append(analyze_body(result, src["role"]))
        stats = extract_stats.get(definition["arena_id"], {})
        arenas.append(derive_statuses(definition, checks, stats))

    summary = {
        "ready": sum(1 for a in arenas if a.parser_status == "ready"),
        "partial": sum(1 for a in arenas if a.parser_status == "partial"),
        "blocked": sum(1 for a in arenas if a.parser_status == "blocked"),
        "skipped": sum(1 for a in arenas if a.parser_status == "skipped"),
        "failed": sum(1 for a in arenas if a.parser_status in ("failed", "unknown")),
    }

    return {
        "schema_version": "1",
        "generated_at": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": "Europe/Minsk",
        "artifacts": {
            "extract_json": str(EXTRACT_JSON.relative_to(ROOT)),
            "registry_yaml": str(REGISTRY_YAML.relative_to(ROOT)),
        },
        "summary": summary,
        "arenas": [
            {
                **{k: v for k, v in asdict(a).items() if k != "sources"},
                "sources": [asdict(s) for s in a.sources],
            }
            for a in sorted(arenas, key=lambda x: x.arena_id)
        ],
    }


def print_table(payload: dict[str, Any]) -> None:
    s = payload["summary"]
    print(f"parser_status summary: ready={s['ready']} partial={s['partial']} blocked={s['blocked']} skipped={s['skipped']} failed={s['failed']}")
    print()
    print(f"{'id':>3}  {'parser':<10}  {'sched':<10}  {'prices':<14}  {'sess':>4}  name")
    print("-" * 72)
    for a in payload["arenas"]:
        print(
            f"{a['arena_id']:>3}  {a['parser_status']:<10}  {a['schedule_status']:<10}  "
            f"{a['prices_status']:<14}  {a['sessions_extracted']:>4}  {a['name']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_registry()
    REGISTRY_JSON.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_yaml(REGISTRY_YAML, payload)
    print_table(payload)
    print(f"\nWrote {REGISTRY_YAML.relative_to(ROOT)}")
    print(f"Wrote {REGISTRY_JSON.relative_to(ROOT)}")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
