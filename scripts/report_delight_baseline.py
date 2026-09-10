#!/usr/bin/env python
"""
Print the EPIC4 gate G-P5 numbers: «вторая запись за 7 дней» + share counts (TASK-096).

Read-only. Safe against production: it runs two SELECTs and writes nothing.

    # local
    DATABASE_URL=postgresql+asyncpg://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm \
        python scripts/report_delight_baseline.py

    # production baseline (readonly public URL from Railway)
    DATABASE_URL="$DATABASE_PUBLIC_URL" python scripts/report_delight_baseline.py --cohort-days 90

Use --as-of to reproduce an earlier reading; the metric is computed from bookings retroactively,
so a baseline taken today and a baseline taken next month for the same --as-of must match.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.application.client_delight_metrics import (  # noqa: E402
    get_second_booking_within_7d,
    get_share_counts,
)


def _normalize_async_url(url: str) -> str:
    """Railway hands out postgresql://; SQLAlchemy async needs an explicit asyncpg driver."""
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


async def main() -> int:
    parser = argparse.ArgumentParser(description="G-P5 baseline (TASK-096)")
    parser.add_argument("--cohort-days", type=int, default=90)
    parser.add_argument("--share-days", type=int, default=30)
    parser.add_argument("--as-of", type=str, default=None, help="ISO datetime, default now (UTC)")
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
            ret = await get_second_booking_within_7d(
                session, as_of=as_of, cohort_days=args.cohort_days
            )
            try:
                shares = await get_share_counts(session, days=args.share_days, as_of=as_of)
            except Exception as exc:  # noqa: BLE001 — table may predate this deploy
                shares = {"error": f"client_share_events unavailable: {exc.__class__.__name__}"}
    finally:
        await engine.dispose()

    print("G-P5 — метрика возврата: вторая запись за 7 дней")
    print(f"  as_of            {ret['as_of']}")
    print(f"  окно когорты     {ret['cohort_start'][:10]} … {ret['cohort_end'][:10]}")
    print(f"  когорта          {ret['cohort_size']} клиентов с первой записью")
    print(f"  вернулись        {ret['returned']}")
    rate = ret["rate_pct"]
    print(f"  доля             {'нет данных (когорта пуста)' if rate is None else f'{rate}%'}")
    print(f"  ещё в окне       {ret['pending_cohort']} (7 дней не истекли — не считаны ни туда, ни туда)")
    print()
    print(f"G-P5 — шеринг за {args.share_days} дн.")
    if "error" in shares:
        print(f"  {shares['error']}")
    elif not shares["by_kind"]:
        print("  0 событий")
    else:
        for kind, v in sorted(shares["by_kind"].items()):
            print(f"  {kind:<14} {v['events']} событий, {v['sharers']} человек")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
