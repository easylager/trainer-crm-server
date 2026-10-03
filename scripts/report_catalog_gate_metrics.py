#!/usr/bin/env python
"""
Снять метрики каталога для гейта North Star / C-B (TASK-146, миграция 0212).

Read-only: WAU каталога, шеры, клики CTA, входы в мини-апп с startapp.

    DATABASE_URL=postgresql+asyncpg://... python scripts/report_catalog_gate_metrics.py
    DATABASE_URL="$DATABASE_PUBLIC_URL" python scripts/report_catalog_gate_metrics.py --days 7
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.application.catalog_consumer_events import (  # noqa: E402
    get_catalog_virality_cb_metrics,
    get_catalog_wau,
)
from src.application.client_delight_metrics import get_share_counts  # noqa: E402


def _normalize_async_url(url: str) -> str:
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


async def main() -> int:
    parser = argparse.ArgumentParser(description="Catalog gate metrics (WAU, C-B proxy)")
    parser.add_argument("--days", type=int, default=7, help="Окно для WAU и C-B")
    parser.add_argument("--as-of", type=str, default=None, help="ISO datetime UTC")
    args = parser.parse_args()

    raw_url = os.environ.get("DATABASE_URL", "").strip()
    if not raw_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    as_of = (
        datetime.fromisoformat(args.as_of).replace(tzinfo=timezone.utc)
        if args.as_of
        else datetime.now(timezone.utc)
    )

    engine = create_async_engine(_normalize_async_url(raw_url))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            try:
                wau = await get_catalog_wau(session, days=args.days, as_of=as_of)
            except Exception as exc:  # noqa: BLE001
                wau = {"error": f"catalog_consumer_events: {exc.__class__.__name__}"}
            try:
                cb = await get_catalog_virality_cb_metrics(session, days=args.days, as_of=as_of)
            except Exception as exc:  # noqa: BLE001
                cb = {"error": f"virality: {exc.__class__.__name__}"}
            try:
                shares = await get_share_counts(session, days=args.days, as_of=as_of)
            except Exception as exc:  # noqa: BLE001
                shares = {"error": f"client_share_events: {exc.__class__.__name__}"}
    finally:
        await engine.dispose()

    print(f"Каталог — окно {args.days} дн., as_of {as_of.isoformat()}")
    print()
    if "error" in wau:
        print(f"WAU: {wau['error']}")
    else:
        print(f"WAU (public + miniapp): {wau['unique_actors']} уникальных actor_hash")
    print()
    if "error" in cb:
        print(f"C-B прокси: {cb['error']}")
    else:
        print("C-B прокси (не заменяет ручной share→open по ссылке):")
        print(f"  share_events (place/selection/ice_city_day): {cb['share_events']}")
        print(f"  catalog_wau:                                  {cb['catalog_wau']}")
        sw = cb["shares_per_wau"]
        print(f"  shares / WAU:                                 {sw if sw is not None else '—'}")
        print(f"  public_telegram_cta_clicks:                   {cb['public_telegram_cta_clicks']}")
        print(f"  miniapp_deeplink_entries (arena_/catalog*):   {cb['miniapp_deeplink_entries']}")
        op = cb["share_to_deeplink_open_pct"]
        print(f"  deeplink_entries / share_events:                {f'{op}%' if op is not None else '—'}")
    print()
    if "error" in shares:
        print(f"Шеры (все kind): {shares['error']}")
    elif not shares.get("by_kind"):
        print("Шеры (client_share_events): 0")
    else:
        print("Шеры (client_share_events):")
        for kind, v in sorted(shares["by_kind"].items()):
            print(f"  {kind:<14} {v['events']} событий, {v['sharers']} человек")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
