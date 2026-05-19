"""
Application layer: catalog lookups (cities, services). Read-only for client bot and public API.
"""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.repositories import CatalogRepository


async def list_cities(session: AsyncSession) -> list[dict[str, Any]]:
    """All cities for filters; ordered by sort_order."""
    return await CatalogRepository(session).list_cities()


async def list_services(
    session: AsyncSession, city_id: int | None = None
) -> list[dict[str, Any]]:
    """Services for filters; optional city scopes list to services with trainers in city."""
    return await CatalogRepository(session).list_services(city_id=city_id)


async def list_arenas(session: AsyncSession, city_id: int) -> list[dict[str, Any]]:
    """Arenas in a city for filter and slot creation."""
    return await CatalogRepository(session).list_arenas(city_id)
