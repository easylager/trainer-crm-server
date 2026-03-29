"""
Trainer profile Mini App API: single aggregate GET/PATCH + photo upload helpers.

Auth: Telegram Web App initData validated with the trainer bot token only.
trainer_id is always resolved from initData → DB (get_trainer_id_linked_any_status), never from the client body.

Available for linked trainers in any status (onboarding pending_profile … active): same rule as
GET /api/webapp/trainer/onboarding/moderation-readiness — edit before and after activation.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.schemas import (
    PhotoRegisterBody,
    TrainerEducationCreateBody,
    TrainerEducationPatchBody,
    TrainerProfilePatchBody,
)
from src.api.routes.public import _enrich_trainer_photo_urls
from src.application.trainer_link import get_trainer_id_linked_any_status
from src.application.trainer_use_cases import (
    TrainerPhotoFileKeyError,
    create_trainer_education,
    delete_trainer_education,
    get_trainer,
    list_trainer_education,
    register_photo,
    update_trainer_education,
    update_trainer_profile,
    upload_trainer_photo_from_bytes,
)
from src.application.trainer_profile_completeness import moderation_readiness_dict
from src.infrastructure import s3
from src.shared.audit import ACTOR_API, audit_log
from src.shared.config import Settings
from src.shared.telegram_webapp import InitDataAuthError, require_telegram_user_id

logger = logging.getLogger(__name__)

router = APIRouter()


def _trainer_telegram_id_from_init(init_data: str) -> int:
    try:
        return require_telegram_user_id(init_data, Settings().telegram_bot_token_trainer)
    except InitDataAuthError:
        raise HTTPException(status_code=401, detail="Invalid or expired init data") from None


async def _require_linked_trainer_id(session: AsyncSession, init_raw: str | None) -> int:
    if not init_raw or not init_raw.strip():
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id_from_init(init_raw.strip())
    trainer_id = await get_trainer_id_linked_any_status(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Telegram not linked to a trainer")
    return trainer_id


class WebappTrainerPhotoPresignBody(BaseModel):
    content_type: str = Field(default="image/jpeg", max_length=128)


@router.get("/trainer/profile")
async def get_trainer_profile_for_webapp(
    init_data: str | None = Query(None, description="Telegram initData if not sent as header"),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """
    Full trainer aggregate for the profile Mini App editor.

    Includes: same shape as ``get_trainer`` (profile, photos, services, arena_ids, status, moderation fields),
    photo preview URLs when CDN/presign available, structured education rows, and ``moderation_readiness``
    (same rules as ``GET /api/webapp/trainer/onboarding/moderation-readiness`` / ``moderation_readiness_dict``).

    **Who can call:** any trainer whose Telegram account is linked (``trainers.telegram_id``), including
    ``pending_profile`` and ``active`` — product rule: edit before moderation approval and after.
    """
    raw = init_data or x_telegram_init_data
    trainer_id = await _require_linked_trainer_id(session, raw)
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")
    _enrich_trainer_photo_urls(trainer)
    readiness = moderation_readiness_dict(
        trainer,
        trainer_status=(trainer.get("status") or "").strip() or None,
    )
    education_entries = await list_trainer_education(session, trainer_id, public_only=False)
    if education_entries is None:
        education_entries = []
    return {
        "trainer": trainer,
        "moderation_readiness": readiness,
        "education_entries": education_entries,
    }


@router.patch("/trainer/profile")
async def patch_trainer_profile_for_webapp(
    body: TrainerProfilePatchBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """
    Partial profile update; semantics match ``PATCH /api/trainers/{trainer_id}/profile`` but ownership is
    implied by initData. Triggers ``clear_moderation_submitted_at`` when any tracked field changes
    (see ``update_trainer_profile``).
    """
    raw = init_data or x_telegram_init_data
    trainer_id = await _require_linked_trainer_id(session, raw)
    profile = body.profile.model_dump(exclude_unset=True) if body.profile else {}
    services_payload = [s.model_dump() for s in body.services] if body.services is not None else None
    ok = await update_trainer_profile(
        session,
        trainer_id,
        profile=profile,
        service_ids=body.service_ids if services_payload is None else None,
        services=services_payload,
        arena_ids=body.arena_ids,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Trainer not found")
    audit_log("trainer.profile_updated", ACTOR_API, "webapp_trainer_profile", {"trainer_id": trainer_id})
    return {"ok": True}


@router.post("/trainer/education", status_code=201)
async def webapp_create_trainer_education(
    body: TrainerEducationCreateBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Create education row; trainer_id from initData only (same rules as REST POST /trainers/{id}/education)."""
    raw = init_data or x_telegram_init_data
    trainer_id = await _require_linked_trainer_id(session, raw)
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
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Patch one education entry; trainer_id from initData only."""
    raw = init_data or x_telegram_init_data
    trainer_id = await _require_linked_trainer_id(session, raw)
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
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Delete one education entry; trainer_id from initData only."""
    raw = init_data or x_telegram_init_data
    trainer_id = await _require_linked_trainer_id(session, raw)
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


@router.post("/trainer/photos/presign")
async def webapp_trainer_photo_presign(
    body: WebappTrainerPhotoPresignBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Presigned PUT URL for direct S3 upload; trainer_id from initData only."""
    raw = init_data or x_telegram_init_data
    trainer_id = await _require_linked_trainer_id(session, raw)
    try:
        url, file_key = s3.presign_upload_url(trainer_id, content_type=body.content_type)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"upload_url": url, "file_key": file_key}


@router.post("/trainer/photos/register")
async def webapp_trainer_photo_register(
    body: PhotoRegisterBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Register photo after presigned upload; trainer_id from initData only."""
    raw = init_data or x_telegram_init_data
    trainer_id = await _require_linked_trainer_id(session, raw)
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
    init_data: str | None = Form(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """
    Multipart upload (same behaviour as ``POST /api/upload/photo``) but ``trainer_id`` comes from initData
    only — never from form fields. Pass initData in ``X-Telegram-Init-Data`` or form field ``init_data``.
    """
    raw = init_data or x_telegram_init_data
    trainer_id = await _require_linked_trainer_id(session, raw)
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
