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
        """All cities ordered by sort_order, then id."""
        r = await self._session.execute(
            text("SELECT id, name, sort_order FROM cities ORDER BY sort_order, id")
        )
        return [{"id": row[0], "name": row[1], "sort_order": row[2]} for row in r.fetchall()]

    async def list_services(self) -> list[dict[str, Any]]:
        """All services ordered by sort_order, then id."""
        r = await self._session.execute(
            text("SELECT id, name, sort_order FROM services ORDER BY sort_order, id")
        )
        return [{"id": row[0], "name": row[1], "sort_order": row[2]} for row in r.fetchall()]

    async def list_arenas(self, city_id: int) -> list[dict[str, Any]]:
        """Arenas in a city with address and coords for map link; ordered by sort_order, id."""
        r = await self._session.execute(
            text(
                "SELECT id, city_id, name, sort_order, address, latitude, longitude FROM arenas WHERE city_id = :cid ORDER BY sort_order, id"
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
