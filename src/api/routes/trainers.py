"""Trainer CRUD: create, list, get, patch profile/status."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.shared.audit import ACTOR_API, audit_log
from src.api.schemas import (
    TrainerCreateBody,
    TrainerProfilePatchBody,
    TrainerStatusPatchBody,
)
from src.application.trainer_use_cases import (
    create_trainer,
    get_trainer,
    list_trainers,
    update_trainer_profile,
    update_trainer_status,
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
