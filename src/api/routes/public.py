"""Public API (no auth): catalog (cities, services, trainers) and photo serving for client/bot."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.application.catalog_use_cases import list_arenas, list_cities, list_services
from src.application.subscription_tier_use_cases import get_trainer_booking_availability
from src.application.training_group_use_cases import (
    batch_open_groups_count_for_trainers,
    list_open_training_groups_catalog,
    list_open_training_groups_public,
)
from src.application.trainer_use_cases import (
    get_trainer,
    list_active_trainers_for_client,
    list_public_trainer_reviews,
    list_trainer_education,
)
from src.infrastructure import s3
from src.shared.config import Settings
from src.shared.public_trainer_payload import sanitize_trainer_for_public_catalog

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


async def _batch_trainer_photos(session: AsyncSession, trainer_ids: list[int]) -> dict[int, list[dict]]:
    """First-page catalog photos for many trainers (same shape as list_active_with_details)."""
    if not trainer_ids:
        return {}
    placeholders = ", ".join(f":pid{i}" for i in range(len(trainer_ids)))
    params: dict = {f"pid{i}": v for i, v in enumerate(trainer_ids)}
    r = await session.execute(
        text(
            f"""
            SELECT trainer_id, file_key, file_key_list, sort_order
            FROM trainer_photos
            WHERE trainer_id IN ({placeholders})
            ORDER BY trainer_id, sort_order
            """
        ),
        params,
    )
    out: dict[int, list[dict]] = {tid: [] for tid in trainer_ids}
    for row in r.fetchall():
        tid = int(row[0])
        out.setdefault(tid, []).append(
            {"file_key": row[1], "file_key_list": row[2], "sort_order": row[3]}
        )
    return out


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
    response: Response,
    limit: int = 10,
    offset: int = 0,
    city_id: int | None = None,
    service_id: int | None = None,
    arena_id: int | None = None,
    order_by: str = "rating",
    # Time-based filters
    filter_days: str | None = None,  # comma-separated: "1,2,3" for Mon,Tue,Wed
    filter_time_slots: str | None = None,  # comma-separated: "09:00-12:00,18:00-21:00"
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Active trainers; optional city, service, arena. order_by: rating (Bayesian) or id.
    
    Each trainer includes `can_book` flag: True if clients can self-book (tier >= online).
    Trainers are always visible in catalog if status=active, regardless of subscription tier.
    """
    # Parse filter parameters
    days_filter = None
    if filter_days:
        try:
            days_filter = [int(d.strip()) for d in filter_days.split(',') if d.strip().isdigit()]
        except ValueError:
            days_filter = None
    
    time_slots_filter = None
    if filter_time_slots:
        time_slots_filter = [slot.strip() for slot in filter_time_slots.split(',') if slot.strip()]
    if days_filter is not None and len(days_filter) == 0:
        days_filter = None
    if time_slots_filter is not None and len(time_slots_filter) == 0:
        time_slots_filter = None

    # Trainer names/photos change after moderation — must not be served from browser HTTP cache.
    response.headers["Cache-Control"] = "no-store"

    items, total = await list_active_trainers_for_client(
        session,
        limit=limit,
        offset=offset,
        city_id=city_id,
        service_id=service_id,
        arena_id=arena_id,
        order_by=order_by,
        filter_days=days_filter,
        filter_time_slots=time_slots_filter,
    )
    trainer_ids_page = [t["id"] for t in items]
    open_grp = await batch_open_groups_count_for_trainers(session, trainer_ids_page)
    # Enrich with booking availability and photo URLs (strip internal ids from catalog payloads)
    for i, t in enumerate(items):
        t = sanitize_trainer_for_public_catalog(t)
        t["open_groups_count"] = int(open_grp.get(t["id"], 0))
        items[i] = t
        _enrich_trainer_photo_urls(t)
        availability = await get_trainer_booking_availability(session, t["id"])
        t["can_book"] = availability["can_book"]
    
    first_photo_sources = [(t.get("photos") or [{}])[0].get("_source") for t in items if t.get("photos")]
    if any(s == "cdn" for s in first_photo_sources):
        photo_source = "cdn"
    elif any(s == "direct" for s in first_photo_sources):
        photo_source = "direct"
    else:
        photo_source = "proxy"
    return {"items": items, "total": total, "_photo_source": photo_source}


@router.get("/training-groups")
async def list_catalog_training_groups(
    response: Response,
    limit: int = 10,
    offset: int = 0,
    city_id: int | None = None,
    service_id: int | None = None,
    arena_id: int | None = None,
    filter_days: str | None = Query(
        None,
        description="Comma-separated weekday 0=Mon..6=Sun (matches training_group_schedule_rules)",
    ),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Open recruiting groups across trainers (catalog browse). Same group rules as per-trainer list."""
    response.headers["Cache-Control"] = "no-store"
    days_filter: list[int] | None = None
    if filter_days:
        try:
            days_filter = [int(d.strip()) for d in filter_days.split(",") if d.strip().isdigit()]
        except ValueError:
            days_filter = None
    if days_filter is not None and len(days_filter) == 0:
        days_filter = None

    items, total = await list_open_training_groups_catalog(
        session,
        city_id=city_id,
        service_id=service_id,
        arena_id=arena_id,
        filter_days=days_filter,
        limit=limit,
        offset=offset,
    )
    tids = list({it["trainer_id"] for it in items})
    photos_by_tid = await _batch_trainer_photos(session, tids)
    out_items = []
    for it in items:
        tid = int(it["trainer_id"])
        tr = {
            "id": tid,
            "profile": (it.get("trainer") or {}).get("profile"),
            "photos": photos_by_tid.get(tid, []),
        }
        _enrich_trainer_photo_urls(tr)
        avail = await get_trainer_booking_availability(session, tid)
        tr["can_book"] = avail["can_book"]
        row = {k: v for k, v in it.items() if k != "trainer"}
        row["trainer"] = tr
        out_items.append(row)

    first_photo_sources = [(row["trainer"].get("photos") or [{}])[0].get("_source") for row in out_items if row.get("trainer")]
    if any(s == "cdn" for s in first_photo_sources):
        photo_source = "cdn"
    elif any(s == "direct" for s in first_photo_sources):
        photo_source = "direct"
    else:
        photo_source = "proxy"
    return {"items": out_items, "total": total, "_photo_source": photo_source}


@router.get("/trainers/{trainer_id:int}")
async def get_one_active_trainer(
    trainer_id: int,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Single active trainer for catalog. Visible if status=active (regardless of subscription).
    
    Returns `can_book` flag: True if clients can self-book (tier >= online).
    Without online tier, trainer is visible but clients must contact directly.
    """
    response.headers["Cache-Control"] = "no-store"
    trainer = await get_trainer(session, trainer_id)
    if not trainer or (trainer.get("status") or "").strip().lower() != "active":
        raise HTTPException(status_code=404, detail="Trainer not found")

    trainer = sanitize_trainer_for_public_catalog(trainer)
    _enrich_trainer_photo_urls(trainer)
    trainer["_photo_source"] = (trainer.get("photos") or [{}])[0].get("_source", "proxy") if trainer.get("photos") else "proxy"
    
    # Add booking availability info
    availability = await get_trainer_booking_availability(session, trainer_id)
    trainer["can_book"] = availability["can_book"]
    trainer["booking_reason"] = availability["reason"]  # null if can_book, else 'crm_only'/'no_subscription'

    edu = await list_trainer_education(session, trainer_id, public_only=True)
    trainer["education_entries"] = edu if edu is not None else []

    return trainer


@router.get("/trainers/{trainer_id:int}/training-groups")
async def list_trainer_training_groups_public(
    trainer_id: int,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Open cohorts with catalog_visible + recruiting (for client catalog)."""
    response.headers["Cache-Control"] = "no-store"
    trainer = await get_trainer(session, trainer_id)
    if not trainer or (trainer.get("status") or "").strip().lower() != "active":
        raise HTTPException(status_code=404, detail="Trainer not found")
    groups = await list_open_training_groups_public(session, trainer_id)
    return {"groups": groups}


@router.get("/trainers/{trainer_id:int}/reviews")
async def get_trainer_reviews_public(
    trainer_id: int,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Public list of ratings/reviews for a catalog trainer (no client identifiers). Same visibility as GET /trainers/{id}."""
    lim = min(max(1, limit), 100)
    off = max(0, offset)
    result = await list_public_trainer_reviews(session, trainer_id, limit=lim, offset=off)
    if result is None:
        raise HTTPException(status_code=404, detail="Trainer not found")
    items, total = result
    return {"items": items, "total": total}


@router.get("/trainers/{trainer_id:int}/education")
async def get_trainer_education_public(
    trainer_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, list]:
    """Public education list: same visibility as catalog (pending + approved snapshots; see repository predicate)."""
    trainer = await get_trainer(session, trainer_id)
    if not trainer or (trainer.get("status") or "").strip().lower() != "active":
        raise HTTPException(status_code=404, detail="Trainer not found")
    items = await list_trainer_education(session, trainer_id, public_only=True)
    return {"items": items or []}


@router.get("/photos/{file_key:path}")
async def serve_photo(file_key: str) -> Response:
    """
    Serve catalog trainer photos from S3 or local storage. Only object keys under `trainers/`
    are readable here (private prefixes like `legal/`, `certificates/` are rejected in s3.get_photo).
    """
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
