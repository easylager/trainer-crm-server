"""Repair Конькобежный стадион when arena_id=115 still points at Moscow CSKA on prod."""
from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.minsk_speed_oval import (
    ADDRESS,
    ARENA_ID,
    LATITUDE,
    LONGITUDE,
    NAME,
    PARSER_KEY,
    PHONE,
    SLUG,
    WEBSITE_URL,
)


def arena_row_needs_speed_oval_repair(row: Mapping[str, Any], *, minsk_city_id: int) -> bool:
    name = (row.get("name") or "").lower()
    if row.get("country") != "BY":
        return True
    if int(row.get("city_id") or 0) != int(minsk_city_id):
        return True
    if "цска" in name or "клфк" in name:
        return True
    if (row.get("slug") or "") != SLUG:
        return True
    return False


def _minsk_city_id_sync(conn: Connection) -> int | None:
    row = conn.execute(
        text(
            """
            SELECT id FROM cities
            WHERE country = 'BY' AND name = 'Минск'
            ORDER BY id
            LIMIT 1
            """
        )
    ).scalar()
    if row is not None:
        return int(row)
    row = conn.execute(
        text(
            """
            SELECT id FROM cities
            WHERE country = 'BY' AND name ILIKE 'Минск%'
            ORDER BY id
            LIMIT 1
            """
        )
    ).scalar()
    return int(row) if row is not None else None


def repair_speed_oval_identity_sync(conn: Connection) -> bool:
    """Return True when arena 115 (speed oval parser target) was repaired.

    Sync path for Alembic: must use the migration connection so uncommitted DDL
    from earlier revisions in the same transaction is visible.
    """
    minsk_id = _minsk_city_id_sync(conn)
    if minsk_id is None:
        return False

    job_arena = conn.execute(
        text("SELECT arena_id FROM ice_parser_jobs WHERE parser_key = :key ORDER BY id LIMIT 1"),
        {"key": PARSER_KEY},
    ).scalar()
    if job_arena is not None and int(job_arena) != ARENA_ID:
        return False

    row = conn.execute(
        text(
            """
            SELECT a.name, a.city_id, c.country, p.slug
            FROM arenas a
            JOIN cities c ON c.id = a.city_id
            LEFT JOIN arena_profiles p ON p.arena_id = a.id
            WHERE a.id = :id
            """
        ),
        {"id": ARENA_ID},
    ).mappings().first()
    if row is None:
        return False

    if not arena_row_needs_speed_oval_repair(row, minsk_city_id=minsk_id):
        conn.execute(
            text(
                """
                UPDATE arena_profiles
                SET website_url = :website
                WHERE arena_id = :id
                  AND COALESCE(website_url, '') <> :website
                """
            ),
            {"id": ARENA_ID, "website": WEBSITE_URL},
        )
        return False

    conn.execute(
        text(
            """
            UPDATE arenas
            SET city_id = :minsk_id,
                name = :name,
                address = :address,
                latitude = :lat,
                longitude = :lon,
                is_active = true,
                is_confirmed = true
            WHERE id = :id
            """
        ),
        {
            "id": ARENA_ID,
            "minsk_id": minsk_id,
            "name": NAME,
            "address": ADDRESS,
            "lat": LATITUDE,
            "lon": LONGITUDE,
        },
    )

    profile = conn.execute(
        text("SELECT 1 FROM arena_profiles WHERE arena_id = :id"),
        {"id": ARENA_ID},
    ).scalar()
    if profile is None:
        conn.execute(
            text(
                """
                INSERT INTO arena_profiles (
                    arena_id, city_id, slug, phone, website_url, status
                ) VALUES (
                    :id, :minsk_id, :slug, :phone, :website, 'published'
                )
                """
            ),
            {
                "id": ARENA_ID,
                "minsk_id": minsk_id,
                "slug": SLUG,
                "phone": PHONE,
                "website": WEBSITE_URL,
            },
        )
        return True

    conn.execute(
        text(
            """
            UPDATE arena_profiles
            SET city_id = :minsk_id,
                slug = :slug,
                phone = COALESCE(NULLIF(phone, ''), :phone),
                website_url = :website,
                status = 'published'
            WHERE arena_id = :id
            """
        ),
        {
            "id": ARENA_ID,
            "minsk_id": minsk_id,
            "slug": SLUG,
            "phone": PHONE,
            "website": WEBSITE_URL,
        },
    )
    return True


async def repair_speed_oval_identity(session: AsyncSession) -> bool:
    """Async wrapper used by application/tests."""
    return await session.run_sync(lambda sync_sess: repair_speed_oval_identity_sync(sync_sess.connection()))
