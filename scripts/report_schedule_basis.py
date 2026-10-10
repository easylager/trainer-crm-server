#!/usr/bin/env python3
"""TASK-179: сколько будущих видимых сеансов по каждому основанию (live/projected/photo/manual), по городам.

Usage: DATABASE_URL=postgresql+asyncpg://... python scripts/report_schedule_basis.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.application.arena_public_use_cases import _CURRENT_SESSION_SQL, STATUS_ACTIVE  # noqa: E402
from src.shared.ice_discovery_scope import ice_discovery_countries  # noqa: E402

_SQL = f"""
SELECT c.name AS city_name, s.schedule_basis, COUNT(*)::int AS n
FROM ice_sessions s
JOIN arenas a ON a.id = s.arena_id
JOIN cities c ON c.id = a.city_id
WHERE {_CURRENT_SESSION_SQL}
  AND a.is_active AND a.is_confirmed
  AND c.country = ANY(:countries)
GROUP BY c.name, s.schedule_basis
ORDER BY c.name, s.schedule_basis
"""


async def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL required", file=sys.stderr)
        return 1
    engine = create_async_engine(url)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        rows = (
            await session.execute(
                text(_SQL),
                {
                    "now": datetime.now(timezone.utc),
                    "st": STATUS_ACTIVE,
                    "countries": list(ice_discovery_countries()),
                },
            )
        ).mappings().all()
    await engine.dispose()
    if not rows:
        print("No future sessions in scope.")
        return 0
    for row in rows:
        print(f"{row['city_name']}\t{row['schedule_basis']}\t{row['n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
