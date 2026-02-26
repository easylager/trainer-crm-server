"""Public API (no auth): catalog (cities, services, trainers) and photo serving for client/bot."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.application.catalog_use_cases import list_arenas, list_cities, list_services
from src.application.trainer_use_cases import list_active_trainers_for_client
from src.infrastructure import s3

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/cities")
async def get_cities(session: AsyncSession = Depends(get_session)) -> dict[str, list]:
    """List cities for filters (e.g. client bot city picker)."""
    items = await list_cities(session)
    return {"items": items}


@router.get("/services")
async def get_services(session: AsyncSession = Depends(get_session)) -> dict[str, list]:
    """List services for filters (e.g. client bot service picker)."""
    items = await list_services(session)
    return {"items": items}


@router.get("/arenas")
async def get_arenas(
    city_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, list]:
    """List arenas in a city (for client filter and trainer slot)."""
    items = await list_arenas(session, city_id)
    return {"items": items}


@router.get("/trainers")
async def list_active_trainers(
    limit: int = 10,
    offset: int = 0,
    city_id: int | None = None,
    service_id: int | None = None,
    arena_id: int | None = None,
    order_by: str = "rating",
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Active trainers; optional city, service, arena. order_by: rating (Bayesian) or id."""
    items, total = await list_active_trainers_for_client(
        session,
        limit=limit,
        offset=offset,
        city_id=city_id,
        service_id=service_id,
        arena_id=arena_id,
        order_by=order_by,
    )
    return {"items": items, "total": total}


@router.get("/photos/{file_key:path}")
async def serve_photo(file_key: str) -> Response:
    """Serve photo from S3 or local storage. URL = API_BASE_URL + /api/public/photos/ + file_key."""
    result = s3.get_photo(file_key)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    body, content_type = result
    return Response(content=body, media_type=content_type)
