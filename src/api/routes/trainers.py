"""Trainer CRUD: create, list, get, patch profile/status."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.shared.audit import ACTOR_API, audit_log
from src.api.schemas import (
    TRAINER_EDUCATION_OPTIONS,
    TrainerCreateBody,
    TrainerEducationCreateBody,
    TrainerEducationPatchBody,
    TrainerProfilePatchBody,
    TrainerStatusPatchBody,
    TrainerTermsCreateBody,
)
from src.application.trainer_use_cases import (
    create_trainer,
    create_trainer_education,
    delete_trainer_education,
    get_trainer,
    get_trainer_moderation_readiness,
    list_trainer_education,
    list_trainers,
    try_submit_trainer_for_moderation_review,
    update_trainer_education,
    update_trainer_profile,
    update_trainer_status,
)
from src.application.legal_use_cases import (
    accept_trainer_terms,
    create_trainer_terms_document,
    get_trainer_terms_status,
)

router = APIRouter(prefix="/api/trainers", tags=["trainers"])

_NOT_FOUND = HTTPException(status_code=404, detail="Trainer not found")


@router.post("")
async def create(
    body: TrainerCreateBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    """Create trainer; optional profile, services (with prices), arena_ids in body."""
    services_payload: list[dict] | None = None
    if body.services:
        services_payload = [s.model_dump() for s in body.services]
    elif body.service_ids:
        services_payload = [{"service_id": sid, "price_byn": None} for sid in body.service_ids]
    trainer_id = await create_trainer(
        session,
        profile=body.profile.model_dump() if body.profile else None,
        services=services_payload,
        arena_ids=body.arena_ids or None,
    )
    audit_log("trainer.created", ACTOR_API, "api", {"trainer_id": trainer_id})
    return {"id": trainer_id}


@router.get("")
async def list_(
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, list]:
    """List trainers; ?status=active for client catalog."""
    items = await list_trainers(session, limit=limit, offset=offset, status=status)
    return {"items": items}


@router.get("/education-options")
async def education_options() -> dict[str, list[str]]:
    """Available options for trainer profile education select."""
    return {"items": list(TRAINER_EDUCATION_OPTIONS)}


@router.get("/{trainer_id}")
async def get_one(
    trainer_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get trainer by id with profile, photos, service_ids."""
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        raise _NOT_FOUND
    return trainer


@router.get("/{trainer_id}/education")
async def get_trainer_education(
    trainer_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, list]:
    """List trainer education entries for owner/admin flows."""
    items = await list_trainer_education(session, trainer_id, public_only=False)
    if items is None:
        raise _NOT_FOUND
    return {"items": items}


@router.post("/{trainer_id}/education", status_code=201)
async def create_education(
    trainer_id: int,
    body: TrainerEducationCreateBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create trainer education entry in pending moderation state."""
    try:
        created = await create_trainer_education(session, trainer_id, payload=body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if created is None:
        raise _NOT_FOUND
    audit_log("trainer.education_created", ACTOR_API, "api", {"trainer_id": trainer_id, "education_id": created["id"]})
    return created


@router.patch("/{trainer_id}/education/{education_id}")
async def patch_education(
    trainer_id: int,
    education_id: int,
    body: TrainerEducationPatchBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Patch trainer education; approved row creates pending revision."""
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
        raise _NOT_FOUND
    audit_log(
        "trainer.education_updated",
        ACTOR_API,
        "api",
        {"trainer_id": trainer_id, "education_id": education_id, "revision_created": updated["revision_created"]},
    )
    return updated


@router.delete("/{trainer_id}/education/{education_id}")
async def delete_education(
    trainer_id: int,
    education_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    """Delete one education entry (same semantics as webapp DELETE)."""
    result = await delete_trainer_education(session, trainer_id, education_id)
    if result is None:
        raise _NOT_FOUND
    if not result:
        raise _NOT_FOUND
    audit_log(
        "trainer.education_deleted",
        ACTOR_API,
        "api",
        {"trainer_id": trainer_id, "education_id": education_id},
    )
    return {"ok": True}


@router.patch("/{trainer_id}/profile")
async def patch_profile(
    trainer_id: int,
    body: TrainerProfilePatchBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    """Partial update of profile and/or service_ids."""
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
        raise _NOT_FOUND
    audit_log("trainer.profile_updated", ACTOR_API, "api", {"trainer_id": trainer_id})
    return {"ok": True}


@router.patch("/{trainer_id}/status")
async def patch_status(
    trainer_id: int,
    body: TrainerStatusPatchBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    """Update trainer status (e.g. active, deactivated)."""
    ok = await update_trainer_status(session, trainer_id, body.status)
    if not ok:
        raise _NOT_FOUND
    audit_log("trainer.status_updated", ACTOR_API, "api", {"trainer_id": trainer_id, "status": body.status})
    return {"ok": True}


@router.post("/admin/legal/trainer-terms")
async def admin_create_trainer_terms(
    body: TrainerTermsCreateBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Admin: register trainer_terms document stored in bucket under file_key."""
    # NOTE: auth for admin is expected at API gateway / infra level.
    doc = await create_trainer_terms_document(
        session,
        version=body.version,
        title=body.title,
        file_key=body.file_key,
        make_active=body.make_active,
    )
    audit_log("legal.trainer_terms_created", ACTOR_API, "api", {"document_id": doc["id"], "version": body.version})
    return doc


@router.get("/{trainer_id}/terms-status")
async def get_trainer_terms_status_api(
    trainer_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return status of trainer_terms acceptance for given trainer (for site onboarding)."""
    # We do not perform auth here; caller must ensure trainer_id belongs to current user.
    status = await get_trainer_terms_status(session, trainer_id)
    return status


@router.post("/{trainer_id}/terms-accept")
async def post_trainer_terms_accept(
    trainer_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Mark active trainer_terms as accepted by trainer (idempotent)."""
    ok = await accept_trainer_terms(session, trainer_id)
    if not ok:
        raise HTTPException(status_code=400, detail="No active trainer_terms configured")
    audit_log("legal.trainer_terms_accepted", ACTOR_API, "api", {"trainer_id": trainer_id})
    return {"ok": True}


@router.get("/{trainer_id}/moderation-readiness")
async def get_moderation_readiness(
    trainer_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Completeness checklist for onboarding UI (caller must enforce ownership). See trainer_profile_completeness."""
    data = await get_trainer_moderation_readiness(session, trainer_id)
    if not data:
        raise _NOT_FOUND
    return data


@router.post("/{trainer_id}/submit-for-moderation")
async def post_submit_for_moderation(
    trainer_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """422 if profile incomplete. Queues for admin review (status stays pending_profile); see try_submit_trainer_for_moderation_review."""
    result = await try_submit_trainer_for_moderation_review(session, trainer_id)
    if result.get("error") == "not_found":
        raise _NOT_FOUND
    if not result.get("ok"):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Profile incomplete for moderation",
                "missing_fields": result.get("missing_fields", []),
                "missing_labels_ru": result.get("missing_labels_ru", []),
            },
        )
    if result.get("noop"):
        return {
            "ok": True,
            "noop": True,
            "trainer_status": result.get("trainer_status"),
            "reason": result.get("reason"),
        }
    return {"ok": True, "submitted": True}

