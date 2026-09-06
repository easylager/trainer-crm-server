"""Public Ice Discovery read-only routes (TASK-051). New module — do not grow webapp.py."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.routes.public import _enrich_trainer_photo_urls
from src.application.arena_public_use_cases import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    IcePublicQueryError,
    get_public_arena_card,
    list_ice_cities,
    list_public_arena_sessions,
    list_public_arena_trainers,
    list_public_ice_arenas,
    record_ice_city_interest,
    search_public_ice,
)
from src.shared.config import Settings

router = APIRouter(prefix="/api/public", tags=["public-ice"])


def _query_error(exc: IcePublicQueryError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/ice/map-config")
async def get_ice_map_config(response: Response) -> dict[str, str | None]:
    """Browser Yandex Maps JS API key. Empty → Ice tab shows a map empty state (no OSM)."""
    response.headers["Cache-Control"] = "no-store"
    key = (Settings().yandex_maps_js_api_key or "").strip() or None
    return {"yandex_maps_js_api_key": key}


@router.get("/ice/arenas")
async def get_public_ice_arenas(
    response: Response,
    city_id: int | None = None,
    bbox: str | None = Query(None, description="min_lat,min_lon,max_lat,max_lon"),
    near: str | None = Query(None, description="lat,lon"),
    intent: str = Query("skate", description="skate | coach | group"),
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    cursor: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Ice tab list. intent=skate only includes arenas with a future public_skate|open_ice slot."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return await list_public_ice_arenas(
            session,
            city_id=city_id,
            bbox=bbox,
            near=near,
            intent=intent,
            limit=limit,
            cursor=cursor,
        )
    except IcePublicQueryError as exc:
        raise _query_error(exc) from exc


class IceCityInterestBody(BaseModel):
    city_id: int
    intent: str = "skate"
    source: str = Field(default="coming_soon_cta", max_length=32)


@router.get("/ice/cities")
async def get_ice_cities(response: Response, session: AsyncSession = Depends(get_session)) -> dict:
    """Ice tab city picker: only cities with a map rink or a catalog trainer."""
    response.headers["Cache-Control"] = "no-store"
    return await list_ice_cities(session)


@router.post("/ice/interest")
async def post_ice_interest(
    body: IceCityInterestBody,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Record that a client asked for skating in a city that has trainers but no map rinks."""
    response.headers["Cache-Control"] = "no-store"
    try:
        payload = await record_ice_city_interest(
            session, city_id=body.city_id, intent=body.intent, source=body.source
        )
    except IcePublicQueryError as exc:
        raise _query_error(exc) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="City not found")
    return payload


@router.get("/search")
async def get_public_search(
    response: Response,
    q: str = Query(..., min_length=1),
    limit: int = Query(8, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """One search, three result groups: arena, trainer, city (tsvector + optional pg_trgm)."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return await search_public_ice(session, q, limit=limit)
    except IcePublicQueryError as exc:
        raise _query_error(exc) from exc


@router.get("/arenas/{arena_ref}/sessions")
async def get_public_arena_sessions(
    arena_ref: str,
    response: Response,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Canonical ice_sessions feed grouped by local_date. Expired slots are omitted."""
    response.headers["Cache-Control"] = "no-store"
    payload = await list_public_arena_sessions(
        session, arena_ref, date_from=date_from, date_to=date_to
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Arena not found")
    return payload


@router.get("/arenas/{arena_ref}/trainers")
async def get_public_arena_trainers(
    arena_ref: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Trainers on an arena with can_book from get_trainer_booking_availability."""
    response.headers["Cache-Control"] = "no-store"
    payload = await list_public_arena_trainers(session, arena_ref)
    if payload is None:
        raise HTTPException(status_code=404, detail="Arena not found")
    for trainer in payload["items"]:
        _enrich_trainer_photo_urls(trainer)
    return payload


@router.get("/arenas/{arena_ref}")
async def get_public_arena_card_route(
    arena_ref: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Arena card: profile, media, tier on read, honest freshness/source."""
    response.headers["Cache-Control"] = "no-store"
    payload = await get_public_arena_card(session, arena_ref)
    if payload is None:
        raise HTTPException(status_code=404, detail="Arena not found")
    return payload
