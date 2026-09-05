"""
Infrastructure: read-only catalog data (cities, services). For client bot and public API.
"""
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Same eligibility as GET /public/trainers (city + service + arena), without slot/time filters.
_CATALOG_TRAINER_WHERE = (
    "t.status = 'active' AND COALESCE(t.is_catalog_visible, true) = true"
)


class CatalogRepository:
    """Lookup tables: cities and services. Raw SQL, read-only."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_cities(self) -> list[dict[str, Any]]:
        """Active cities only, ordered by sort_order, then id.

        ``country`` (TASK-043) lets callers resolve display currency client-side without an
        extra request — e.g. price input suffix on the profile screen.
        """
        r = await self._session.execute(
            text("SELECT id, name, sort_order, country FROM cities WHERE is_active ORDER BY sort_order, id")
        )
        return [
            {"id": row[0], "name": row[1], "sort_order": row[2], "country": row[3]} for row in r.fetchall()
        ]

    _SERVICE_TRAINER_COUNT_SQL = f"""
        SELECT COUNT(DISTINCT t.id)::int
        FROM trainer_services ts
        INNER JOIN trainers t ON t.id = ts.trainer_id AND {_CATALOG_TRAINER_WHERE}
        INNER JOIN trainer_profiles p ON p.trainer_id = t.id
        WHERE ts.service_id = s.id
    """

    async def list_services(self, city_id: int | None = None) -> list[dict[str, Any]]:
        """
        Services for catalog pickers with trainer_count (active, catalog-visible trainers).
        With city_id, all services are returned; trainer_count is scoped to that city (may be 0).
        """
        # asyncpg cannot infer type for :city_id when it is NULL and reused in IS NULL checks — split queries.
        if city_id is None:
            r = await self._session.execute(
                text(
                    f"""
                    SELECT s.id, s.name, s.sort_order, s.client_summary,
                           s.slug, s.vertical_key, s.effort_profile, s.scenario_tags,
                           ({self._SERVICE_TRAINER_COUNT_SQL}) AS trainer_count
                    FROM services s
                    ORDER BY s.sort_order, s.id
                    """
                )
            )
        else:
            count_in_city = f"({self._SERVICE_TRAINER_COUNT_SQL} AND p.city_id = :city_id)"
            r = await self._session.execute(
                text(
                    f"""
                    SELECT s.id, s.name, s.sort_order, s.client_summary,
                           s.slug, s.vertical_key, s.effort_profile, s.scenario_tags,
                           {count_in_city} AS trainer_count
                    FROM services s
                    ORDER BY {count_in_city} DESC, s.sort_order, s.id
                    """
                ),
                {"city_id": city_id},
            )
        return [
            {
                "id": row[0],
                "name": row[1],
                "sort_order": row[2],
                "client_summary": row[3],
                "slug": row[4],
                "vertical_key": row[5],
                "effort_profile": row[6],
                "scenario_tags": row[7],
                "trainer_count": row[8],
            }
            for row in r.fetchall()
        ]

    async def list_arenas(
        self, city_id: int, *, service_id: int | None = None, include_unconfirmed: bool = False
    ) -> list[dict[str, Any]]:
        """
        Active arenas in a city with address and coords for map link.

        When ``service_id`` is set, each row includes ``trainer_count``: distinct active
        catalog-visible trainers in ``city_id`` who offer that service and list the arena
        in ``trainer_arenas`` (matches catalog arena filter semantics).

        ``include_unconfirmed``: trainer-created arenas start ``is_confirmed=false``
        (TASK-046) — visible to trainers of the same city (pass ``True``, e.g. the
        authenticated trainer profile screen), hidden from the public client catalog
        (default ``False``, e.g. ``GET /api/public/arenas``) until an admin confirms.

        Public callers also hide ``arena_profiles.status != 'published'`` (TASK-048).
        Missing profile is treated as published so legacy rows stay listed. ``district``
        may be NULL — the row is still returned.
        """
        confirmed_filter = "" if include_unconfirmed else "AND a.is_confirmed"
        published_filter = (
            ""
            if include_unconfirmed
            else "AND (p.status IS NULL OR p.status = 'published')"
        )
        if service_id is None:
            r = await self._session.execute(
                text(
                    f"""
                    SELECT a.id, a.city_id, a.name, a.sort_order, a.address,
                           a.latitude, a.longitude, a.is_confirmed, p.district, p.slug, p.status
                    FROM arenas a
                    LEFT JOIN arena_profiles p ON p.arena_id = a.id
                    WHERE a.city_id = :cid AND a.is_active {confirmed_filter} {published_filter}
                    ORDER BY a.sort_order, a.id
                    """
                ),
                {"cid": city_id},
            )
            return [
                {
                    "id": row[0],
                    "city_id": row[1],
                    "name": row[2],
                    "sort_order": row[3],
                    "address": row[4],
                    "latitude": row[5],
                    "longitude": row[6],
                    "is_confirmed": bool(row[7]),
                    "district": row[8],
                    "slug": row[9],
                    "status": row[10],
                }
                for row in r.fetchall()
            ]

        tw = _CATALOG_TRAINER_WHERE
        r = await self._session.execute(
            text(
                f"""
                SELECT
                    a.id,
                    a.city_id,
                    a.name,
                    a.sort_order,
                    a.address,
                    a.latitude,
                    a.longitude,
                    a.is_confirmed,
                    COALESCE(cnt.trainer_count, 0) AS trainer_count,
                    p.district,
                    p.slug,
                    p.status
                FROM arenas a
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                LEFT JOIN (
                    SELECT ta.arena_id, COUNT(DISTINCT t.id)::int AS trainer_count
                    FROM trainer_arenas ta
                    INNER JOIN trainers t ON t.id = ta.trainer_id AND {tw}
                    INNER JOIN trainer_profiles tp
                        ON tp.trainer_id = t.id AND tp.city_id = :city_id
                    INNER JOIN trainer_services ts
                        ON ts.trainer_id = t.id AND ts.service_id = :service_id
                    INNER JOIN arenas ar
                        ON ar.id = ta.arena_id AND ar.city_id = :city_id AND ar.is_active
                    GROUP BY ta.arena_id
                ) cnt ON cnt.arena_id = a.id
                WHERE a.city_id = :city_id AND a.is_active {confirmed_filter} {published_filter}
                ORDER BY COALESCE(cnt.trainer_count, 0) DESC, a.sort_order, a.id
                """
            ),
            {"city_id": city_id, "service_id": int(service_id)},
        )
        return [
            {
                "id": row[0],
                "city_id": row[1],
                "name": row[2],
                "sort_order": row[3],
                "address": row[4],
                "latitude": row[5],
                "longitude": row[6],
                "is_confirmed": bool(row[7]),
                "trainer_count": int(row[8]),
                "district": row[9],
                "slug": row[10],
                "status": row[11],
            }
            for row in r.fetchall()
        ]

    async def platform_stats(self) -> dict[str, int]:
        """One-shot aggregate for trust card: active trainers / cities / arenas."""
        # Three independent COUNTs; cheap enough to leave un-cached (no PII, no joins).
        r = await self._session.execute(
            text(
                f"""
                SELECT
                    (SELECT COUNT(*) FROM trainers t WHERE {_CATALOG_TRAINER_WHERE})::int AS trainers_total,
                    (SELECT COUNT(*) FROM cities WHERE is_active)::int AS cities_count,
                    (
                        SELECT COUNT(*) FROM arenas a
                        LEFT JOIN arena_profiles p ON p.arena_id = a.id
                        WHERE a.is_active AND a.is_confirmed
                          AND (p.status IS NULL OR p.status = 'published')
                    )::int AS arenas_count
                """
            )
        )
        row = r.fetchone()
        if row is None:
            return {"trainers_total": 0, "cities_count": 0, "arenas_count": 0}
        return {
            "trainers_total": int(row[0] or 0),
            "cities_count": int(row[1] or 0),
            "arenas_count": int(row[2] or 0),
        }
