"""
Helpers for integration tests: reuse seeded catalog rows (cities, services, arenas).

Never INSERT junk names into `cities` / `services` — those tables are user-facing in the Mini App.
Tests must use existing seed data from migrations (`0028_seed_services`, etc.) and optional `scripts/seed_*.py`.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def require_seed_service_id(session: AsyncSession) -> int:
    r = await session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    row = r.fetchone()
    if not row:
        pytest.skip("No services in DB — run migrations (0028_seed_services)")
    return int(row[0])


async def require_seed_city_id(session: AsyncSession) -> int:
    r = await session.execute(
        text("SELECT id FROM cities WHERE COALESCE(is_active, true) ORDER BY id LIMIT 1")
    )
    row = r.fetchone()
    if not row:
        pytest.skip("No cities in DB — run seed_cities or migrations")
    return int(row[0])


async def require_seed_arena_city_name(session: AsyncSession) -> tuple[int, int, str]:
    """
    One active arena: (arena_id, city_id, trimmed arena name) for venue / trainer_arena tests.
    """
    r = await session.execute(
        text(
            """
            SELECT a.id, a.city_id, trim(both FROM a.name)
            FROM arenas a
            WHERE COALESCE(a.is_active, true)
            ORDER BY a.id
            LIMIT 1
            """
        )
    )
    row = r.fetchone()
    if not row:
        pytest.skip("No arenas in DB — run scripts/seed_arenas.py against test DB")
    return int(row[0]), int(row[1]), str(row[2])
