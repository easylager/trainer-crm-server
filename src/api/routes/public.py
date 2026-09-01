"""Public API (no auth): catalog (cities, services, trainers) and photo serving for client/bot."""
import logging
import re
from datetime import date, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.middleware.http_limits import client_ip_from_request
from src.application.brand_presentation import (
    brand_presentation_to_public_dict,
    resolve_brand_from_collective_row,
)
from src.application.landing_manifest import public_landing_config
from src.application.landing_trainer_start_use_cases import issue_trainer_start_from_landing
from src.application.catalog_use_cases import (
    get_platform_stats,
    list_arenas,
    list_catalog_scenarios,
    list_cities,
    list_services,
)
from src.application.collective_use_cases import get_collective_by_slug, collective_location_payload
from src.application.demand_signals_use_cases import record_profile_view_commit
from src.application.lifecycle_use_cases import resolve_lifecycle_snapshot
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
from src.infrastructure.db.models import DEMAND_SOURCE_CATALOG, DEMAND_SOURCE_DIRECT_LINK
from src.shared.config import Settings
from src.shared.public_trainer_payload import sanitize_trainer_for_public_catalog
from src.shared.audit import ACTOR_API, audit_log
from src.shared.rate_limit import RateLimiter


logger = logging.getLogger(__name__)

# Telegram username rule mirrored from redirects.py (see comment there).
_TELEGRAM_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,64}$")
# Cap to avoid log/hash blowups from rogue clients.
_UA_MAX_LEN = 512

_trainer_start_limiter: RateLimiter | None = None


class TrainerStartBody(BaseModel):
    referral_code: str | None = Field(default=None, max_length=64)
    website: str | None = Field(default=None, max_length=200)  # honeypot — must stay empty


def reset_trainer_start_limiter_for_tests() -> None:
    """Tests only — rebuild limiter from current env."""
    global _trainer_start_limiter
    _trainer_start_limiter = None


def _get_trainer_start_limiter() -> RateLimiter:
    global _trainer_start_limiter
    if _trainer_start_limiter is None:
        s = Settings()
        _trainer_start_limiter = RateLimiter(
            s.landing_trainer_start_max_requests,
            s.landing_trainer_start_window_sec,
        )
    return _trainer_start_limiter


async def issue_trainer_join_from_request(
    session: AsyncSession,
    request: Request,
    *,
    referral_code: str | None = None,
    audit_event: str = "landing.trainer_start_issued",
) -> dict:
    """
    Mint a one-time landing welcome token and return redirect metadata.

    Shared by POST /api/public/trainer-start and GET /join.
    """
    settings = Settings()
    if not settings.landing_trainer_registration_enabled:
        raise HTTPException(status_code=503, detail="Registration temporarily unavailable")

    ip = client_ip_from_request(request)
    limiter = _get_trainer_start_limiter()
    if not limiter.check_and_consume(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    try:
        result = await issue_trainer_start_from_landing(
            session,
            referral_code=referral_code,
            settings=settings,
        )
    except ValueError as exc:
        if str(exc) == "trainer_bot_username_missing":
            raise HTTPException(
                status_code=503,
                detail="Telegram bot is not configured yet. Please try again later.",
            ) from exc
        raise

    audit_log(
        audit_event,
        ACTOR_API,
        ip,
        {
            "trainer_id": result.get("trainer_id"),
            "vertical": settings.landing_vertical,
            "market": settings.landing_market,
            "has_referral": bool(result.get("referral_code")),
        },
    )
    return result


async def issue_trainer_join_redirect(
    request: Request,
    session: AsyncSession,
    *,
    referral_code: str | None = None,
) -> RedirectResponse:
    """Public shareable entry: mint token and 302 to Telegram bot."""
    result = await issue_trainer_join_from_request(
        session,
        request,
        referral_code=referral_code,
        audit_event="landing.trainer_join_redirect",
    )
    redirect_url = result.get("redirect_url")
    if not redirect_url:
        raise HTTPException(
            status_code=503,
            detail="Telegram bot is not configured yet. Please try again later.",
        )
    return RedirectResponse(url=redirect_url, status_code=302)


def _build_contact_telegram_url(trainer_id: int, telegram_username: str | None) -> str | None:
    """Return the trackable redirect URL only when the trainer has a valid Telegram handle."""
    if not telegram_username:
        return None
    candidate = telegram_username.strip().lstrip("@")
    if not _TELEGRAM_USERNAME_RE.fullmatch(candidate):
        return None
    return f"/r/tg/{trainer_id}"


def _resolve_source_from_referer(request: Request) -> str:
    """Pick demand source from Referer; defaults to direct_link."""
    referer = (request.headers.get("referer") or "").lower()
    if "/webapp/catalog" in referer:
        return DEMAND_SOURCE_CATALOG
    return DEMAND_SOURCE_DIRECT_LINK

router = APIRouter(prefix="/api/public", tags=["public"])


def _trainer_public_catalog_exposed(trainer: dict | None) -> bool:
    """Active trainer row may be hidden from client browse until is_catalog_visible is true."""
    if not trainer:
        return False
    if (trainer.get("status") or "").strip().lower() != "active":
        return False
    # Fail closed: opt-in since 0182_catalog_opt_in — a missing flag must not expose a card.
    return bool(trainer.get("is_catalog_visible", False))


# Hard cap on catalog multi-arena filter — defends DB from oversized IN-lists from rogue clients
# without affecting realistic catalog UX (cities have well under 32 arenas).
_ARENA_IDS_FILTER_LIMIT = 32


def _parse_arena_ids_csv(raw: str | None) -> list[int] | None:
    """Parse `arena_ids=1,2,3` query into deduped list[int]; None when empty/invalid/missing."""
    if not raw:
        return None
    parsed: list[int] = []
    seen: set[int] = set()
    for chunk in raw.split(","):
        s = chunk.strip()
        if not s:
            continue
        try:
            n = int(s)
        except ValueError:
            continue
        if n in seen:
            continue
        seen.add(n)
        parsed.append(n)
        if len(parsed) >= _ARENA_IDS_FILTER_LIMIT:
            break
    return parsed or None


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
async def get_services(
    city_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, list]:
    """List services for filters; city_id limits to services with catalog trainers in that city."""
    items = await list_services(session, city_id=city_id)
    return {"items": items}


@router.get("/catalog-scenarios")
async def get_catalog_scenarios(
    city_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, list]:
    """Discovery goal chips for catalog; ice defaults when services lack scenario_tags."""
    items = await list_catalog_scenarios(session, city_id=city_id)
    return {"items": items}


@router.get("/platform-stats")
async def platform_stats(
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    """Aggregate platform stats for public trust card (clients see this on hub/catalog)."""
    # Numbers move slowly; small CDN-edge cache OK, but per-request DB read keeps it fresh enough.
    response.headers["Cache-Control"] = "public, max-age=120"
    return await get_platform_stats(session)


@router.get("/landing-config")
async def landing_config() -> dict:
    """Public manifest slice for Glide landing (copy, bento, visual assets)."""
    return public_landing_config()


@router.post("/trainer-start")
async def trainer_start_from_landing(
    request: Request,
    body: TrainerStartBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Issue one-time Glide bot link for site CTA (trainer row created when user opens Telegram).

    Replaces manual /trainer_welcome_link for organic traffic.
    """
    # Honeypot: bots fill hidden fields; silently reject without hinting.
    if body.website and str(body.website).strip():
        raise HTTPException(status_code=400, detail="Invalid request")

    result = await issue_trainer_join_from_request(
        session,
        request,
        referral_code=body.referral_code,
    )
    return {
        "trainer_id": result.get("trainer_id"),
        "redirect_url": result["redirect_url"],
        "expires_at": result.get("expires_at"),
    }


@router.get("/arenas")
async def get_arenas(
    city_id: int,
    service_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, list]:
    """
    List arenas in a city (for client filter and trainer slot).

    With ``service_id``, each arena includes ``trainer_count``: trainers in this city who
    offer the service and work at that arena (same rules as catalog trainer list filter).
    """
    items = await list_arenas(session, city_id, service_id=service_id)
    return {"items": items}


def _public_logo_url(logo_key: str | None) -> str | None:
    key = (logo_key or "").strip()
    if not key:
        return None
    return f"/api/public/photos/{quote(key, safe='')}"


@router.get("/collectives/{slug}")
async def get_public_collective(
    slug: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Public studio landing metadata for client catalog (?collective=slug)."""
    row = await get_collective_by_slug(session, slug, active_only=True)
    if row is None:
        raise HTTPException(status_code=404, detail="Collective not found")
    brand = resolve_brand_from_collective_row(row)
    payload = brand_presentation_to_public_dict(brand, slug=row["slug"])
    location = await collective_location_payload(session, row)
    payload.update(location)
    payload["seat_limit"] = row.get("seat_limit")
    payload["schedule_mode"] = row.get("schedule_mode") or "member_autonomous"
    payload["organization_format"] = row.get("organization_format")
    from src.application.organization_capabilities import resolve_public_collective_capabilities

    payload.update(
        resolve_public_collective_capabilities(
            organization_format=row.get("organization_format"),
            schedule_mode=payload["schedule_mode"],
        )
    )
    return payload


@router.get("/collectives/{slug}/sessions")
async def get_public_collective_sessions(
    slug: str,
    from_date: date | None = None,
    to_date: date | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Bookable center grid for studio_central collectives (ADR-003 W2)."""
    from src.application.collective_session_use_cases import list_public_collective_sessions

    today = date.today()
    fd = from_date or today
    td = to_date or (today + timedelta(days=28))
    if td < fd:
        raise HTTPException(status_code=400, detail="Invalid date range")
    payload = await list_public_collective_sessions(
        session,
        slug=slug,
        from_date=fd,
        to_date=td,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Collective not found")
    if payload.get("error") == "not_studio_central":
        raise HTTPException(status_code=400, detail="Collective is not studio_central")
    return payload


@router.get("/trainers")
async def list_active_trainers(
    response: Response,
    limit: int = 10,
    offset: int = 0,
    city_id: int | None = None,
    service_id: int | None = None,
    arena_id: int | None = None,
    arena_ids: str | None = None,  # comma-separated; logical OR over selected arenas
    order_by: str = "rating",
    # Time-based filters
    filter_days: str | None = None,  # comma-separated: "1,2,3" for Mon,Tue,Wed
    filter_time_slots: str | None = None,  # comma-separated: "09:00-12:00,18:00-21:00"
    collective_slug: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Active trainers; optional city, service, arena. order_by: rating (Bayesian) or id.

    arena_ids — multi-select arena filter (CSV of ids), logical OR. arena_id is the legacy
    single-id alias and is honored when arena_ids is empty.

    Each trainer includes `can_book` flag: True if clients can self-book (tier >= online).
    Trainers appear when status=active, is_catalog_visible=true, and subscription rules apply.
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

    arena_ids_filter = _parse_arena_ids_csv(arena_ids)

    # Trainer names/photos change after moderation — must not be served from browser HTTP cache.
    response.headers["Cache-Control"] = "no-store"

    items, total = await list_active_trainers_for_client(
        session,
        limit=limit,
        offset=offset,
        city_id=city_id,
        service_id=service_id,
        arena_id=arena_id,
        arena_ids=arena_ids_filter,
        order_by=order_by,
        filter_days=days_filter,
        filter_time_slots=time_slots_filter,
        collective_slug=(collective_slug or "").strip() or None,
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
    arena_ids: str | None = None,  # comma-separated; logical OR over selected arenas
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

    arena_ids_filter = _parse_arena_ids_csv(arena_ids)

    items, total = await list_open_training_groups_catalog(
        session,
        city_id=city_id,
        service_id=service_id,
        arena_id=arena_id,
        arena_ids=arena_ids_filter,
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


async def assemble_trainer_catalog_payload(
    *,
    session: AsyncSession,
    trainer_id: int,
    trainer: dict,
    request: Request,
) -> dict:
    """
    Build JSON body for catalog trainer card (public mini-app). Caller validates visibility / auth.

    Mutates a sanitized copy suitable for API responses (photos enriched, pricing/booking flags).
    """
    # Side-channel SELECT for telegram_username — it is intentionally excluded from get_by_id's
    # public payload (we never echo the raw handle to clients), but we still need it to decide
    # whether a Lead Mode CTA can be offered at all.
    r = await session.execute(
        text("SELECT telegram_username FROM trainers WHERE id = :tid"),
        {"tid": trainer_id},
    )
    tg_row = r.fetchone()
    telegram_username = tg_row[0] if tg_row else None

    trainer = sanitize_trainer_for_public_catalog(trainer)
    _enrich_trainer_photo_urls(trainer)
    trainer["_photo_source"] = (trainer.get("photos") or [{}])[0].get("_source", "proxy") if trainer.get("photos") else "proxy"

    availability = await get_trainer_booking_availability(session, trainer_id)
    trainer["can_book"] = availability["can_book"]
    trainer["booking_reason"] = availability["reason"]  # null if can_book, else 'crm_only'/'no_subscription'

    snap = await resolve_lifecycle_snapshot(session, trainer_id)
    trainer["lifecycle_stage"] = snap.stage.value
    trainer["is_lead_mode"] = snap.is_lead_mode
    # Trackable /r/tg/{id} redirect whenever the trainer has a valid @username — not only Lead Mode.
    trainer["contact_telegram_url"] = _build_contact_telegram_url(trainer_id, telegram_username)

    edu = await list_trainer_education(session, trainer_id, public_only=True)
    trainer["education_entries"] = edu if edu is not None else []

    try:
        await record_profile_view_commit(
            session,
            trainer_id=trainer_id,
            source=_resolve_source_from_referer(request),
            client_ip=client_ip_from_request(request),
            user_agent=(request.headers.get("user-agent") or "")[:_UA_MAX_LEN],
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "demand_signals.record_profile_view_commit failed for trainer_id=%s: %s",
            trainer_id,
            exc,
        )

    return trainer


@router.get("/trainers/{trainer_id:int}")
async def get_one_active_trainer(
    trainer_id: int,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Single trainer for catalog: status=active and is_catalog_visible=true (subscription still applies to list).

    Returns `can_book` flag: True if clients can self-book (tier >= online).
    Without online tier, trainer is visible but clients must contact directly.

    Also returns lifecycle context for Lead Mode UX (see lead-mode-revenue-retention.md):
        - `lifecycle_stage`: "active" | "lead_mode" | "onboarding" | "churned"
        - `is_lead_mode`: bool — convenience flag for the catalog frontend
        - `contact_telegram_url`: trackable redirect "/r/tg/{id}" when the trainer has a valid
          telegram_username on file. Frontend uses this for the "Написать тренеру" CTA.
    """
    response.headers["Cache-Control"] = "no-store"
    trainer = await get_trainer(session, trainer_id)
    if not trainer or not _trainer_public_catalog_exposed(trainer):
        raise HTTPException(status_code=404, detail="Trainer not found")

    return await assemble_trainer_catalog_payload(
        session=session, trainer_id=trainer_id, trainer=trainer, request=request
    )


@router.get("/trainers/{trainer_id:int}/training-groups")
async def list_trainer_training_groups_public(
    trainer_id: int,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Open cohorts with catalog_visible + recruiting (for client catalog)."""
    response.headers["Cache-Control"] = "no-store"
    trainer = await get_trainer(session, trainer_id)
    if not trainer or not _trainer_public_catalog_exposed(trainer):
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
    if not trainer or not _trainer_public_catalog_exposed(trainer):
        raise HTTPException(status_code=404, detail="Trainer not found")
    items = await list_trainer_education(session, trainer_id, public_only=True)
    return {"items": items or []}


@router.get("/photos/{file_key:path}")
async def serve_photo(file_key: str) -> Response:
    """
    Serve catalog trainer photos from S3 or local storage. Keys under `trainers/` or
    `collectives/` (studio brand kit); private prefixes like `legal/` are rejected.
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
