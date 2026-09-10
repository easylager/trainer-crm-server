"""Repair Конькобежный стадион when prod reused arena_id=115 for Moscow CSKA."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from src.application.minsk_speed_oval_identity import (
    arena_row_needs_speed_oval_repair,
    repair_speed_oval_identity,
)
from src.shared.minsk_speed_oval import (
    ADDRESS,
    ARENA_ID,
    LATITUDE,
    LONGITUDE,
    NAME,
    SLUG,
    WEBSITE_URL,
)


def test_arena_row_needs_speed_oval_repair_detects_moscow_cska() -> None:
    assert arena_row_needs_speed_oval_repair(
        {
            "name": "Ледовая площадка Клфк ЦСКА",
            "city_id": 30,
            "country": "RU",
            "slug": "cska-wrong",
        },
        minsk_city_id=2,
    )


def test_arena_row_needs_speed_oval_repair_ok_for_minsk_oval() -> None:
    assert not arena_row_needs_speed_oval_repair(
        {
            "name": NAME,
            "city_id": 2,
            "country": "BY",
            "slug": SLUG,
        },
        minsk_city_id=2,
    )


async def _ensure_minsk_city(db_session) -> int:
    row = (
        await db_session.execute(
            text("SELECT id FROM cities WHERE country = 'BY' AND name = 'Минск' ORDER BY id LIMIT 1")
        )
    ).scalar()
    if row is not None:
        return int(row)
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO cities (name, country, price_group, is_active, sort_order)
                    VALUES ('Минск', 'BY', 'BY_BASE', true, 1)
                    RETURNING id
                    """
                )
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_repair_speed_oval_identity_moves_cska_row_to_minsk(db_session) -> None:
    minsk_id = await _ensure_minsk_city(db_session)

    ru_city = (
        await db_session.execute(
            text(
                """
                INSERT INTO cities (name, country, price_group, is_active, sort_order)
                VALUES (:name, 'RU', 'RU_BASE', true, 9100)
                RETURNING id
                """
            ),
            {"name": f"MoscowFix-{uuid.uuid4().hex[:6]}"},
        )
    ).scalar_one()

    existing = (
        await db_session.execute(text("SELECT 1 FROM arenas WHERE id = :id"), {"id": ARENA_ID})
    ).scalar()
    if existing:
        await db_session.execute(
            text(
                """
                UPDATE arenas
                SET city_id = :cid,
                    name = :name,
                    address = 'Ленинградский проспект 39',
                    latitude = 55.795498,
                    longitude = 37.5370241
                WHERE id = :id
                """
            ),
            {"id": ARENA_ID, "cid": int(ru_city), "name": "Ледовая площадка Клфк ЦСКА"},
        )
    else:
        await db_session.execute(
            text(
                """
                INSERT INTO arenas (id, city_id, name, address, latitude, longitude, is_active, is_confirmed)
                VALUES (:id, :cid, :name, 'Ленинградский проспект 39', 55.795498, 37.5370241, true, true)
                """
            ),
            {"id": ARENA_ID, "cid": int(ru_city), "name": "Ледовая площадка Клфк ЦСКА"},
        )

    await db_session.execute(
        text(
            """
            INSERT INTO arena_profiles (arena_id, city_id, slug, status)
            VALUES (:id, :cid, 'cska-wrong', 'published')
            ON CONFLICT (arena_id) DO UPDATE SET city_id = EXCLUDED.city_id, slug = EXCLUDED.slug
            """
        ),
        {"id": ARENA_ID, "cid": int(ru_city)},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
            VALUES (:id, 'minskarena_speed_oval_v1', true, 'daily', now(), '{}'::jsonb)
            ON CONFLICT (arena_id) DO UPDATE SET parser_key = EXCLUDED.parser_key
            """
        ),
        {"id": ARENA_ID},
    )
    await db_session.flush()

    repaired = await repair_speed_oval_identity(db_session)
    assert repaired is True

    row = (
        await db_session.execute(
            text(
                """
                SELECT a.name, a.city_id, a.address, a.latitude, a.longitude,
                       c.country, p.slug, p.website_url
                FROM arenas a
                JOIN cities c ON c.id = a.city_id
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                WHERE a.id = :id
                """
            ),
            {"id": ARENA_ID},
        )
    ).mappings().one()
    assert row["country"] == "BY"
    assert int(row["city_id"]) == int(minsk_id)
    assert row["name"] == NAME
    assert row["address"] == ADDRESS
    assert float(row["latitude"]) == LATITUDE
    assert float(row["longitude"]) == LONGITUDE
    assert row["slug"] == SLUG
    assert row["website_url"] == WEBSITE_URL
