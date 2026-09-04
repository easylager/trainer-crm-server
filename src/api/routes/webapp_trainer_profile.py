"""
Trainer profile Mini App API: single aggregate GET/PATCH + photo upload helpers.

Auth: Telegram Web App initData validated with the trainer bot token only.
trainer_id is always resolved from initData → DB (get_trainer_id_linked_any_status), never from the client body.

Available for linked trainers in any status (onboarding pending_profile … active): same rule as
GET /api/webapp/trainer/onboarding/moderation-readiness — edit before and after activation.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import time as dt_time

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, get_trainer_miniapp_principal, get_trainer_miniapp_principal_multipart
from src.api.schemas import (
    TRAINER_EDUCATION_OPTIONS,
    PhotoRegisterBody,
    TrainerCatalogVisibilityPatchBody,
    TrainerEducationCreateBody,
    TrainerEducationPatchBody,
    TrainerProfilePatchBody,
    TrainerServiceUiAccentsPatchBody,
)
from src.api.routes.public import _enrich_trainer_photo_urls
from src.application.trainer_link import get_trainer_id_linked_any_status_from_principal
from src.application.trainer_profile_pending import (
    merge_profile_pending_for_editor,
    trainer_has_pending_text_revision,
    trainer_has_photo_pending_revision,
)
from src.application.catalog_use_cases import list_arenas, list_cities, list_services
from src.application.arena_schedule_preset import (
    get_schedule_grid_preset_for_trainer,
    normalize_trainer_schedule_grid_step,
    schedule_grid_preset_to_api,
)
from src.application.trainer_notification_prefs import validate_push_notification_window
from src.application.trainer_arena_setup_use_cases import (
    set_trainer_arena_mobile,
)
from src.application.trainer_arena_create_use_cases import create_trainer_arena
from src.application.trainer_use_cases import (
    TrainerPhotoFileKeyError,
    create_trainer_education,
    delete_trainer_education,
    get_trainer,
    list_trainer_education,
    register_photo,
    set_trainer_catalog_visibility,
    try_submit_trainer_for_moderation_review,
    update_trainer_education,
    update_trainer_profile,
    upload_trainer_education_document_photo_from_bytes,
    upload_trainer_photo_from_bytes,
)
from src.infrastructure.repositories.trainer_repository import TrainerRepository
from src.application.trainer_profile_completeness import moderation_readiness_dict
from src.infrastructure import s3
from src.shared.audit import ACTOR_API, audit_log
from src.shared.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter()


def _digest_api_str_to_time(s: str | None) -> dt_time | None:
    if s is None or (isinstance(s, str) and not str(s).strip()):
        return None
    s = str(s).strip()
    parts = s.split(":")
    if len(parts) != 2:
        return None
    h, m = int(parts[0]), int(parts[1])
    return dt_time(hour=h, minute=m)


async def _linked_trainer_id(session: AsyncSession, principal: MiniAppPrincipal) -> int:
    trainer_id = await get_trainer_id_linked_any_status_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Telegram not linked to a trainer")
    return trainer_id


async def trainer_schedule_settings_payload(session: AsyncSession, trainer_id: int) -> dict:
    """Mini App «Настройки»: saved step + whether primary arena's preset overrides the trainer."""
    trainer = await get_trainer(session, trainer_id)
    preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
    step = normalize_trainer_schedule_grid_step((trainer or {}).get("schedule_grid_step_minutes"))
    locked = preset.get("arena_id") is not None
    primary_arena_name: str | None = None
    if locked and preset.get("arena_id") is not None:
        r = await session.execute(
            text("SELECT name FROM arenas WHERE id = :aid"),
            {"aid": int(preset["arena_id"])},
        )
        row = r.fetchone()
        if row and row[0] is not None:
            n = str(row[0]).strip()
            primary_arena_name = n or None
    return {
        "schedule_grid_step_minutes": step,
        "arena_grid_locked": locked,
        "primary_arena_name": primary_arena_name,
        "effective_schedule_grid": schedule_grid_preset_to_api(preset),
    }


async def build_trainer_profile_webapp_payload(session: AsyncSession, trainer_id: int) -> dict:
    """
    Same JSON shape as GET /trainer/profile.
    Used by trainer hub bootstrap to avoid an extra HTTP round-trip.
    """
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")
    pub = trainer.get("profile") if isinstance(trainer.get("profile"), dict) else {}
    pen = trainer.get("profile_pending") if isinstance(trainer.get("profile_pending"), dict) else None
    merged_profile = merge_profile_pending_for_editor(pub, pen)
    trainer_for_editor = dict(trainer)
    if merged_profile is not None:
        trainer_for_editor["profile"] = merged_profile
    photos_catalog_published = [dict(p) for p in (trainer.get("photos") or [])]
    _enrich_trainer_photo_urls({"photos": photos_catalog_published})
    pp = trainer.get("photo_pending") if isinstance(trainer.get("photo_pending"), dict) else None
    fk_p = (pp.get("file_key") or "").strip() if pp else ""
    if fk_p:
        trainer_for_editor["photos"] = [
            {
                "file_key": fk_p,
                "file_key_list": (pp.get("file_key_list") or "").strip() or None,
                "sort_order": 0,
            }
        ]
    else:
        trainer_for_editor["photos"] = list(trainer.get("photos") or [])
    _enrich_trainer_photo_urls(trainer_for_editor)
    readiness = moderation_readiness_dict(
        trainer_for_editor,
        trainer_status=(trainer.get("status") or "").strip() or None,
    )
    education_entries = await list_trainer_education(session, trainer_id, public_only=False)
    if education_entries is None:
        education_entries = []
    schedule_settings = await trainer_schedule_settings_payload(session, trainer_id)
    return {
        "trainer": trainer_for_editor,
        "profile_catalog_published": pub,
        "photos_catalog_published": photos_catalog_published,
        "has_pending_profile_revision": trainer_has_pending_text_revision(trainer),
        "has_pending_photo_revision": trainer_has_photo_pending_revision(trainer),
        "moderation_readiness": readiness,
        "education_entries": education_entries,
        "schedule_settings": schedule_settings,
    }


async def build_trainer_hub_profile_bootstrap_payload(session: AsyncSession, trainer_id: int) -> dict:
    """
    Minimal profile JSON for GET /trainer/hub/bootstrap — only fields used by trainer-home
    (mergeHubAccessFromProfilePayload: trainer id, status, profile.group_classes_enabled).
    Avoids photos, education, moderation aggregates, and presign work from the full profile payload.
    """
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")
    pub = trainer.get("profile") if isinstance(trainer.get("profile"), dict) else {}
    pen = trainer.get("profile_pending") if isinstance(trainer.get("profile_pending"), dict) else None
    merged_profile = merge_profile_pending_for_editor(pub, pen)
    gce = False
    if isinstance(merged_profile, dict):
        gce = bool(merged_profile.get("group_classes_enabled"))
    st = (trainer.get("status") or "").strip()
    return {
        "trainer": {
            "id": trainer.get("id"),
            "status": st,
            "profile": {
                "group_classes_enabled": gce,
            },
        },
    }


class WebappTrainerPhotoPresignBody(BaseModel):
    content_type: str = Field(default="image/jpeg", max_length=128)


class TrainerArenaSetupBody(BaseModel):
    mode: str = Field(..., min_length=1, max_length=32)
    arena_name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=512)
    confirm_duplicate: bool = False
    city_id: int | None = Field(
        default=None,
        ge=1,
        description="City for create mode when profile.city_id is unset or trainer changed city without Save.",
    )


@router.post("/trainer/profile/arena-setup")
async def post_trainer_arena_setup_for_webapp(
    body: TrainerArenaSetupBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
):
    """
    Arena self-service (TASK-046): mobile format, or create a real arena directly.

    ``mode=create`` writes a real ``arenas`` row (``is_confirmed=false``) and auto-attaches
    it to the trainer — no waiting on support/admin to use it (AC-002/AC-003). Superseded
    the old ``mode=request`` text-only support ticket (AC-006), which no longer exists.
    """
    trainer_id = await _linked_trainer_id(session, principal)
    mode = (body.mode or "").strip().lower()
    if mode == "mobile":
        trainer = await set_trainer_arena_mobile(session, trainer_id)
        if not trainer:
            raise HTTPException(status_code=404, detail="Trainer not found")
        readiness = moderation_readiness_dict(
            trainer,
            trainer_status=(trainer.get("status") or "").strip() or None,
        )
        return {"trainer": trainer, "moderation_readiness": readiness}
    if mode == "create":
        try:
            result = await create_trainer_arena(
                session,
                trainer_id,
                name=body.arena_name or "",
                address=body.address or "",
                confirm_duplicate=body.confirm_duplicate,
                city_id=body.city_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Trainer not found") from exc
        if result.get("status") == "duplicate_warning":
            return result
        trainer = result.get("trainer")
        if not trainer:
            raise HTTPException(status_code=404, detail="Trainer not found")
        readiness = moderation_readiness_dict(
            trainer,
            trainer_status=(trainer.get("status") or "").strip() or None,
        )
        return {
            "status": "created",
            "arena_id": result.get("arena_id"),
            "trainer": trainer,
            "moderation_readiness": readiness,
        }
    raise HTTPException(status_code=422, detail="mode must be mobile or create")


@router.get("/trainer/profile/arenas")
async def get_trainer_profile_arenas_for_webapp(
    city_id: int = Query(..., ge=1),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
):
    """
    Arenas for the trainer's own arena picker (TASK-046 AC-004): unlike
    ``GET /api/public/arenas`` (client catalog), includes trainer-created arenas still
    awaiting admin confirmation — the creator and other trainers of the same city can
    select and use them right away.
    """
    trainer_id = await _linked_trainer_id(session, principal)
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")
    # Picker may show arenas for a city selected in the form before Save (draft city).
    # Authenticated trainer is allowed to browse any city they can pick in the dropdown.
    items = await list_arenas(session, city_id, include_unconfirmed=True)
    return {"items": items}


@router.get("/trainer/profile")
async def get_trainer_profile_for_webapp(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
):
    """
    Full trainer aggregate for the profile Mini App editor.

    Includes: same shape as ``get_trainer`` (profile, photos, services, arena_ids, status, moderation fields),
    photo preview URLs when CDN/presign available, structured education rows, and ``moderation_readiness``
    (same rules as ``GET /api/webapp/trainer/onboarding/moderation-readiness`` / ``moderation_readiness_dict``).

    **Who can call:** any trainer whose Telegram account is linked (``trainers.telegram_id``), including
    ``pending_profile`` and ``active`` — product rule: edit before moderation approval and after.
    """
    trainer_id = await _linked_trainer_id(session, principal)
    return await build_trainer_profile_webapp_payload(session, trainer_id)


@router.get("/trainer/profile/page-bootstrap")
async def get_trainer_profile_page_bootstrap(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
):
    """
    Single response for the profile Mini App first paint: full ``GET /trainer/profile`` payload plus
    cities, services, and education select options (otherwise 4 parallel HTTP requests from the client).
    """
    trainer_id = await _linked_trainer_id(session, principal)
    cities, services, profile_payload = await asyncio.gather(
        list_cities(session),
        list_services(session),
        build_trainer_profile_webapp_payload(session, trainer_id),
    )
    return {
        **profile_payload,
        "refs": {
            "cities": {"items": cities},
            "services": {"items": services},
            "education_options": {"items": list(TRAINER_EDUCATION_OPTIONS)},
        },
    }


@router.patch("/trainer/profile")
async def patch_trainer_profile_for_webapp(
    body: TrainerProfilePatchBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
):
    """
    Partial profile update; semantics match ``PATCH /api/trainers/{trainer_id}/profile`` but ownership is
    implied by initData. Triggers ``clear_moderation_submitted_at`` when any tracked field changes
    (see ``update_trainer_profile``).
    """
    trainer_id = await _linked_trainer_id(session, principal)
    profile = body.profile.model_dump(exclude_unset=True) if body.profile else {}
    services_payload = [s.model_dump() for s in body.services] if body.services is not None else None
    primary_set = "primary_arena_id" in body.model_fields_set
    step_set = "schedule_grid_step_minutes" in body.model_fields_set
    push_set = (
        "push_notification_start_hour" in body.model_fields_set
        or "push_notification_end_hour" in body.model_fields_set
    )
    if push_set:
        repo = TrainerRepository(session)
        sh = body.push_notification_start_hour
        eh = body.push_notification_end_hour
        if sh is None and eh is None:
            await repo.clear_push_notification_window(trainer_id)
        else:
            if sh is None or eh is None:
                raise HTTPException(
                    status_code=422,
                    detail="Укажите оба часа окна уведомлений или сбросьте к стандарту сервиса (оба null).",
                )
            try:
                validate_push_notification_window(sh, eh)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            await repo.set_push_notification_window(trainer_id, sh, eh)

    digest_set = "digest_enabled" in body.model_fields_set or "digest_send_time" in body.model_fields_set
    if digest_set:
        repo = TrainerRepository(session)
        cur = await get_trainer(session, trainer_id)
        if not cur:
            raise HTTPException(status_code=404, detail="Trainer not found")
        en = bool(cur.get("digest_enabled", True))
        st: dt_time | None = _digest_api_str_to_time(cur.get("digest_send_time"))  # type: ignore[arg-type]
        if "digest_enabled" in body.model_fields_set:
            if body.digest_enabled is None:
                raise HTTPException(status_code=422, detail="digest_enabled: укажите true или false.")
            en = bool(body.digest_enabled)
        if "digest_send_time" in body.model_fields_set:
            raw = body.digest_send_time
            if raw is not None and str(raw).strip():
                st = _digest_api_str_to_time(str(raw).strip())
            elif en:
                st = None
            # If digest is off and client sends null time, keep previous ``st`` (from ``cur``).
        await repo.set_digest_settings(trainer_id, digest_enabled=en, digest_send_time=st)

    try:
        ok = await update_trainer_profile(
            session,
            trainer_id,
            profile=profile,
            service_ids=body.service_ids if services_payload is None else None,
            services=services_payload,
            arena_ids=body.arena_ids,
            primary_arena_id=body.primary_arena_id,
            primary_arena_id_set=primary_set,
            schedule_grid_step_minutes=body.schedule_grid_step_minutes,
            schedule_grid_step_minutes_set=step_set,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Trainer not found")
    audit_log("trainer.profile_updated", ACTOR_API, "webapp_trainer_profile", {"trainer_id": trainer_id})

    # Notify admins once the trainer has filled in the intro block (name, phone, city)
    from src.application.trainer_profile_completeness import is_intro_block_complete
    from src.application.trainer_events_notify import notify_admins_trainer_intro_completed

    trainer = await get_trainer(session, trainer_id)
    if trainer and is_intro_block_complete(trainer):
        claimed = await session.execute(
            text(
                """
                UPDATE trainer_profiles
                SET moderation_readiness_notified_at = NOW()
                WHERE trainer_id = :trainer_id AND moderation_readiness_notified_at IS NULL
                RETURNING trainer_id
                """
            ),
            {"trainer_id": trainer_id},
        )
        if claimed.fetchone() is not None:
            await session.commit()
            await notify_admins_trainer_intro_completed(trainer_id, trainer)

    return {"ok": True}


@router.patch("/trainer/profile/service-ui-accents")
async def patch_trainer_service_ui_accents_for_webapp(
    body: TrainerServiceUiAccentsPatchBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
) -> dict[str, bool]:
    """Update hub/schedule border accent presets per offered service. Auth: trainer initData."""
    trainer_id = await _linked_trainer_id(session, principal)
    if not body.items:
        return {"ok": True}
    r_allowed = await session.execute(
        text("SELECT service_id FROM trainer_services WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    allowed = {int(row[0]) for row in r_allowed.fetchall()}
    requested_ids = {it.service_id for it in body.items}
    bad = sorted(requested_ids - allowed)
    if bad:
        raise HTTPException(
            status_code=422,
            detail="Услуги не в вашем каталоге: " + ", ".join(str(x) for x in bad),
        )
    repo = TrainerRepository(session)
    pairs = [(it.service_id, it.ui_accent) for it in body.items]
    await repo.patch_trainer_service_ui_accents(trainer_id, pairs)
    await session.commit()
    audit_log(
        "trainer.service_ui_accents_updated",
        ACTOR_API,
        "webapp_trainer_profile",
        {"trainer_id": trainer_id, "count": len(pairs)},
    )
    return {"ok": True}


@router.patch("/trainer/catalog-visibility")
async def patch_trainer_catalog_visibility_for_webapp(
    body: TrainerCatalogVisibilityPatchBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
) -> dict[str, bool]:
    """
    The trainer's own opt-in to the public client catalog. Available in every status.

    It used to be ``status=active`` only, on the reasoning that onboarding accounts are not
    listed anyway. But that left a trainer who had not been approved yet with no way to say
    «я не хочу в каталог» *before* it happened — and the profile screen queued them for
    moderation automatically. Turning the switch on is now the act that asks for publication
    (``try_submit_trainer_for_moderation_review`` refuses while it is off), so it has to be
    reachable exactly when the trainer is still deciding.
    """
    trainer_id = await _linked_trainer_id(session, principal)
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")
    ok = await set_trainer_catalog_visibility(session, trainer_id, visible=body.is_catalog_visible)
    if not ok:
        raise HTTPException(status_code=404, detail="Trainer not found")
    if body.is_catalog_visible:
        # Switching it on IS the request to be published, whichever screen flipped it — the hub
        # card does not open the profile at all. Idempotent and quiet: an incomplete profile or
        # an already-queued one just comes back as a noop, and the trainer sees the same thing
        # either way (the profile lists what is still missing).
        await try_submit_trainer_for_moderation_review(session, trainer_id)
    audit_log(
        "trainer.catalog_visibility_updated",
        ACTOR_API,
        "webapp_trainer_profile",
        {"trainer_id": trainer_id, "is_catalog_visible": body.is_catalog_visible},
    )
    return {"ok": True}


@router.post("/trainer/education", status_code=201)
async def webapp_create_trainer_education(
    body: TrainerEducationCreateBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
):
    """Create education row; trainer_id from initData only (same rules as REST POST /trainers/{id}/education)."""
    trainer_id = await _linked_trainer_id(session, principal)
    try:
        created = await create_trainer_education(session, trainer_id, payload=body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if created is None:
        raise HTTPException(status_code=404, detail="Trainer not found")
    audit_log(
        "trainer.education_created",
        ACTOR_API,
        "webapp_trainer_profile",
        {"trainer_id": trainer_id, "education_id": created["id"]},
    )
    return created


@router.patch("/trainer/education/{education_id}")
async def webapp_patch_trainer_education(
    education_id: int,
    body: TrainerEducationPatchBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
):
    """Patch one education entry; trainer_id from initData only."""
    trainer_id = await _linked_trainer_id(session, principal)
    try:
        updated = await update_trainer_education(
            session,
            trainer_id,
            education_id,
            payload=body.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Education entry not found")
    audit_log(
        "trainer.education_updated",
        ACTOR_API,
        "webapp_trainer_profile",
        {
            "trainer_id": trainer_id,
            "education_id": education_id,
            "revision_created": updated["revision_created"],
        },
    )
    return updated


@router.delete("/trainer/education/{education_id}")
async def webapp_delete_trainer_education(
    education_id: int,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
):
    """Delete one education entry; trainer_id from initData only."""
    trainer_id = await _linked_trainer_id(session, principal)
    result = await delete_trainer_education(session, trainer_id, education_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Trainer not found")
    if not result:
        raise HTTPException(status_code=404, detail="Education entry not found")
    audit_log(
        "trainer.education_deleted",
        ACTOR_API,
        "webapp_trainer_profile",
        {"trainer_id": trainer_id, "education_id": education_id},
    )
    return {"ok": True}


@router.post("/trainer/education/documents")
async def webapp_trainer_education_document_upload(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal_multipart),
):
    """Upload one diploma/certificate photo and return scoped storage keys for education entry payloads."""
    trainer_id = await _linked_trainer_id(session, principal)
    content_type = file.content_type or "image/jpeg"
    body_bytes = await file.read()
    ok, err, file_key, file_key_list = await upload_trainer_education_document_photo_from_bytes(
        session, trainer_id, body_bytes, content_type
    )
    if not ok:
        if err == "too_large":
            raise HTTPException(status_code=413, detail="File too large")
        if err == "not_image":
            raise HTTPException(status_code=400, detail="Not a valid image")
        if err == "storage":
            raise HTTPException(status_code=503, detail="Storage temporarily unavailable")
        raise HTTPException(status_code=404, detail="Trainer not found")
    out: dict[str, str] = {"file_key": file_key or ""}
    if file_key_list:
        out["file_key_list"] = file_key_list
    return out


@router.post("/trainer/photos/presign")
async def webapp_trainer_photo_presign(
    body: WebappTrainerPhotoPresignBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
):
    """Presigned PUT URL for direct S3 upload; trainer_id from initData only."""
    trainer_id = await _linked_trainer_id(session, principal)
    try:
        url, file_key = s3.presign_upload_url(trainer_id, content_type=body.content_type)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"upload_url": url, "file_key": file_key}


@router.post("/trainer/photos/register")
async def webapp_trainer_photo_register(
    body: PhotoRegisterBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
):
    """Register photo after presigned upload; trainer_id from initData only."""
    trainer_id = await _linked_trainer_id(session, principal)
    try:
        ok = await register_photo(session, trainer_id, body.file_key)
    except TrainerPhotoFileKeyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Trainer not found")
    return {"file_key": body.file_key}


@router.post("/trainer/photos")
async def webapp_trainer_photo_upload(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal_multipart),
):
    """
    Multipart upload (same behaviour as ``POST /api/upload/photo``) but ``trainer_id`` comes from initData
    only — never from form fields. Pass initData in ``X-Telegram-Init-Data`` or form field ``init_data``.
    """
    trainer_id = await _linked_trainer_id(session, principal)
    content_type = file.content_type or "image/jpeg"
    body_bytes = await file.read()
    ok, err, file_key, file_key_list = await upload_trainer_photo_from_bytes(
        session, trainer_id, body_bytes, content_type
    )
    if not ok:
        if err == "too_large":
            raise HTTPException(status_code=413, detail="File too large")
        if err == "not_image":
            raise HTTPException(status_code=400, detail="Not a valid image")
        if err == "storage":
            raise HTTPException(status_code=503, detail="Storage temporarily unavailable")
        raise HTTPException(status_code=404, detail="Trainer not found")
    out: dict[str, str] = {"file_key": file_key or ""}
    if file_key_list:
        out["file_key_list"] = file_key_list
    return out
