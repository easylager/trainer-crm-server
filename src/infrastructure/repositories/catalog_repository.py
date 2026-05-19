"""
Infrastructure: read-only catalog data (cities, services). For client bot and public API.
"""
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class CatalogRepository:
    """Lookup tables: cities and services. Raw SQL, read-only."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_cities(self) -> list[dict[str, Any]]:
        """Active cities only, ordered by sort_order, then id."""
        r = await self._session.execute(
            text("SELECT id, name, sort_order FROM cities WHERE is_active ORDER BY sort_order, id")
        )
        return [{"id": row[0], "name": row[1], "sort_order": row[2]} for row in r.fetchall()]

    _SERVICE_TRAINER_COUNT_SQL = """
        SELECT COUNT(DISTINCT t.id)::int
        FROM trainer_services ts
        INNER JOIN trainers t ON t.id = ts.trainer_id
            AND t.status = 'active'
            AND COALESCE(t.is_catalog_visible, true) = true
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
                "trainer_count": row[4],
            }
            for row in r.fetchall()
        ]

    async def list_arenas(self, city_id: int) -> list[dict[str, Any]]:
        """Active arenas in a city with address and coords for map link; ordered by sort_order, id."""
        r = await self._session.execute(
            text(
                "SELECT id, city_id, name, sort_order, address, latitude, longitude FROM arenas WHERE city_id = :cid AND is_active ORDER BY sort_order, id"
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
            }
            for row in r.fetchall()
        ]
