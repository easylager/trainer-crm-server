#!/usr/bin/env python
"""
Воронка открытки «Пойдёшь со мной на каток?» и K-фактор (TASK-237). Read-only.

    DATABASE_URL=postgresql+asyncpg://... python scripts/report_zovi_funnel.py --days 14
    DATABASE_URL="$DATABASE_PUBLIC_URL" python scripts/report_zovi_funnel.py --days 14 --until 2026-10-26

Логика подсчёта — в ``src/application/zovi_funnel.py``; здесь только печать.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.application.zovi_funnel import (  # noqa: E402
    compute_funnel,
    format_funnel_report,
    load_funnel_events,
    report_window,
)


def _normalize_async_url(url: str) -> str:
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


async def main() -> int:
    parser = argparse.ArgumentParser(description="Воронка открытки и K-фактор")
    parser.add_argument("--days", type=int, default=14, help="Окно в сутках по Минску (по умолчанию 14)")
    parser.add_argument("--until", type=date.fromisoformat, default=None, help="Последний день окна, YYYY-MM-DD")
    args = parser.parse_args()
    if args.days < 1:
        print("--days must be >= 1", file=sys.stderr)
        return 2

    raw_url = os.environ.get("DATABASE_URL", "").strip()
    if not raw_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    since, until = report_window(args.days, args.until)
    engine = create_async_engine(_normalize_async_url(raw_url))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            events = await load_funnel_events(session, since=since, until=until)
    finally:
        await engine.dispose()
    report = compute_funnel(events)
    print("\n".join(format_funnel_report(report, days=args.days, since=since, until=until)))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
