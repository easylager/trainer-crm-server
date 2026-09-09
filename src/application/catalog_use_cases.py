"""
Application layer: catalog lookups (cities, services). Read-only for client bot and public API.
"""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_media import attach_arena_media_payloads
from src.infrastructure.repositories import CatalogRepository


async def list_cities(session: AsyncSession) -> list[dict[str, Any]]:
    """All cities for filters; ordered by sort_order."""
    return await CatalogRepository(session).list_cities()


async def list_services(
    session: AsyncSession, city_id: int | None = None
) -> list[dict[str, Any]]:
    """Services for filters; optional city scopes list to services with trainers in city."""
    return await CatalogRepository(session).list_services(city_id=city_id)


async def list_arenas(
    session: AsyncSession,
    city_id: int,
    *,
    service_id: int | None = None,
    include_unconfirmed: bool = False,
) -> list[dict[str, Any]]:
    """
    Arenas in a city; optional service_id adds per-arena trainer_count for catalog filter UX.

    ``include_unconfirmed=True`` also returns trainer-created arenas pending moderation
    (TASK-046) and Ice Discovery cards that are not ``published`` (TASK-048) — only for
    authenticated trainer-facing callers, never the public catalog.
    The public path also requires ``arena_profiles.status = 'published'`` (TASK-048).
    """
    items = await CatalogRepository(session).list_arenas(
        city_id, service_id=service_id, include_unconfirmed=include_unconfirmed
    )
    await attach_arena_media_payloads(session, items)
    return items


async def list_catalog_scenarios(
    session: AsyncSession, city_id: int | None = None
) -> list[dict[str, Any]]:
    """
    Goal chips for catalog discovery — from services.scenario_tags when set,
    else ice-first defaults keyed by service name patterns.
    """
    services = await list_services(session, city_id=city_id)
    scenarios: list[dict[str, Any]] = []
    seen: set[str] = set()

    for svc in services:
        tags = svc.get("scenario_tags")
        if isinstance(tags, dict):
            for key, meta in tags.items():
                sk = str(key).strip()
                if not sk or sk in seen:
                    continue
                seen.add(sk)
                label = (meta or {}).get("label") if isinstance(meta, dict) else None
                patterns = (meta or {}).get("service_patterns") if isinstance(meta, dict) else None
                scenarios.append(
                    {
                        "key": sk,
                        "label": label or sk,
                        "service_patterns": patterns or [],
                        "service_id": svc.get("id"),
                    }
                )

    if scenarios:
        return scenarios

    # Ice defaults — same semantics as legacy CATALOG_SCENARIO_STUBS in catalog-main.js
    return [
        {
            "key": "skating",
            "label": "⛸️ Улучшить катание",
            "service_patterns": ["совершенствование катания"],
            "service_id": None,
        },
        {
            "key": "from-zero",
            "label": "🌱 С нуля",
            "service_patterns": ["обучение катанию"],
            "service_id": None,
        },
    ]


async def get_platform_stats(session: AsyncSession) -> dict[str, int]:
    """Aggregate metrics for public trust card (trainers / cities / arenas)."""
    return await CatalogRepository(session).platform_stats()
