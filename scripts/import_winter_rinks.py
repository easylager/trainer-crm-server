"""Импорт seed сезонных точек 2025/26 (TASK-343). Идемпотентен.

    python scripts/import_winter_rinks.py path/to/seasonal_rinks_seed_2025_26.csv          # dry-run: отчёт
    python scripts/import_winter_rinks.py path/to/seed.csv --apply [--publish]

Без ``--apply`` ничего не пишется (транзакция откатывается). ``--publish`` делает профили
``published`` — до готовности страниц точки не включать.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.application.winter_import import import_points, plan_rows, read_seed  # noqa: E402
from src.infrastructure.db import async_session_factory  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("seed")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--publish", action="store_true")
    args = ap.parse_args()
    planned = plan_rows(read_seed(args.seed))
    async with async_session_factory() as session:
        report = await import_points(session, planned, now=datetime.now(timezone.utc), publish=args.publish)
        if args.apply:
            await session.commit()
        else:
            await session.rollback()
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    print("APPLIED" if args.apply else "DRY-RUN (rolled back)")


if __name__ == "__main__":
    asyncio.run(main())
