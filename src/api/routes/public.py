"""Public API (no auth): catalog (cities, services, trainers) and photo serving for client/bot."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.application.catalog_use_cases import list_arenas, list_cities, list_services
from src.application.subscription_use_cases import trainer_has_active_subscription
from src.application.trainer_use_cases import get_trainer, list_active_trainers_for_client
from src.infrastructure import s3
from src.shared.config import Settings

router = APIRouter(prefix="/api/public", tags=["public"])


def _photo_url_from_cdn(file_key: str) -> str | None:
    """Build CDN URL for file_key if photo_cdn_base_url is set."""
    base = (Settings().photo_cdn_base_url or "").strip().rstrip("/")
    if not base or not file_key or ".." in file_key:
        return None
    if not file_key.startswith("trainers/"):
        return None
    return base + "/" + quote(file_key, safe="/")


def _enrich_trainer_photo_urls(trainer: dict) -> bool:
    """Mutate trainer: add url/list_url and _source to each photo (CDN > presigned S3 > proxy). Returns True if any direct URL was set."""
    photos = trainer.get("photos") or []
    any_direct = False
    cdn_base = (Settings().photo_cdn_base_url or "").strip().rstrip("/")
    for ph in photos:
        fk = ph.get("file_key")
        fk_list = ph.get("file_key_list")
        source = "proxy"
        if cdn_base:
            if fk:
                url = _photo_url_from_cdn(fk)
                if url:
                    ph["url"] = url
                    source = "cdn"
                    any_direct = True
            if fk_list:
                list_url = _photo_url_from_cdn(fk_list)
                if list_url:
                    ph["list_url"] = list_url
                    if source != "cdn":
                        source = "cdn"
                    any_direct = True
        else:
            if fk:
                url = s3.presign_get_url(fk)
                if url:
                    ph["url"] = url
                    source = "direct"
                    any_direct = True
            if fk_list:
                list_url = s3.presign_get_url(fk_list)
                if list_url:
                    ph["list_url"] = list_url
                    if source != "direct":
                        source = "direct"
                    any_direct = True
        ph["_source"] = source
    return any_direct


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
    for t in items:
        _enrich_trainer_photo_urls(t)
    first_photo_sources = [(t.get("photos") or [{}])[0].get("_source") for t in items if t.get("photos")]
    if any(s == "cdn" for s in first_photo_sources):
        photo_source = "cdn"
    elif any(s == "direct" for s in first_photo_sources):
        photo_source = "direct"
    else:
        photo_source = "proxy"
    return {"items": items, "total": total, "_photo_source": photo_source}


@router.get("/trainers/{trainer_id:int}")
async def get_one_active_trainer(
    trainer_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Single active trainer for catalog «Мой тренер» card. Same shape as list item. 404 if no active subscription."""
    trainer = await get_trainer(session, trainer_id)
    if not trainer or (trainer.get("status") or "").strip().lower() != "active":
        raise HTTPException(status_code=404, detail="Trainer not found")
    if not await trainer_has_active_subscription(session, trainer_id):
        raise HTTPException(status_code=404, detail="Trainer not found")
    _enrich_trainer_photo_urls(trainer)
    trainer["_photo_source"] = (trainer.get("photos") or [{}])[0].get("_source", "proxy") if trainer.get("photos") else "proxy"
    return trainer


@router.get("/photos/{file_key:path}")
async def serve_photo(file_key: str) -> Response:
    """Serve photo from S3 or local storage. URL = API_BASE_URL + /api/public/photos/ + file_key."""
    result = s3.get_photo(file_key)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    body, content_type = result
    # file_key is content-addressed by uuid in path; safe to cache aggressively at client/CDN.
    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
