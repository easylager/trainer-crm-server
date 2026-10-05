#!/usr/bin/env python3
"""TASK-179: counts of schedule_basis per city for visible future sessions."""
from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.application.arena_public_use_cases import _CURRENT_SESSION_SQL, STATUS_ACTIVE
from src.shared.ice_discovery_scope import ice_discovery_countries

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
        from datetime import datetime, timezone

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
