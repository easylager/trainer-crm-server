"""Admin ice session week grid (TASK-050). New module — do not grow webapp.py."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth.deps import get_admin_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPrincipal
from src.application.ice_session_use_cases import (
    IceSessionValidationError,
    apply_ice_session_patch,
    copy_ice_week,
    create_ice_session,
    delete_ice_session,
    list_ice_week_grid,
    monday_of,
    rematerialize_recurrence,
)

router = APIRouter(tags=["webapp-admin-ice-sessions"])


class AdminIceSessionCreateBody(BaseModel):
    local_date: date
    starts_at_local: str = Field(..., description="HH:MM arena local time")
    duration_minutes: int
    kind: str = "public_skate"
    price_adult_minor: int | None = None
    price_child_minor: int | None = None
    price_rental_minor: int | None = None
    price_note: str | None = None
    session_label: str | None = None
    age_note: str | None = None
    capacity_note: str | None = None
    external_url: str | None = None
    repeat_weekly: bool = False


class AdminIceSessionPatchBody(BaseModel):
    local_date: date | None = None
    starts_at_local: str | None = None
    duration_minutes: int | None = None
    kind: str | None = None
    price_adult_minor: int | None = None
    price_child_minor: int | None = None
    price_rental_minor: int | None = None
    price_note: str | None = None
    session_label: str | None = None
    age_note: str | None = None
    capacity_note: str | None = None
    external_url: str | None = None


class AdminIceCopyWeekBody(BaseModel):
    from_week_start: date


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail="Not found")
    if isinstance(exc, IceSessionValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.get("/admin/arenas/{arena_id:int}/ice-sessions")
async def get_admin_ice_week(
    arena_id: int,
    week_start: date | None = Query(None),
    include_cancelled: bool = Query(False),
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        return await list_ice_week_grid(
            session,
            arena_id,
            week_start=week_start or monday_of(date.today()),
            include_cancelled=include_cancelled,
        )
    except LookupError as exc:
        raise _map_error(exc) from exc


@router.post("/admin/arenas/{arena_id:int}/ice-sessions")
async def post_admin_ice_session(
    arena_id: int,
    body: AdminIceSessionCreateBody,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        created = await create_ice_session(
            session,
            arena_id,
            local_date=body.local_date,
            starts_at_local=body.starts_at_local,
            duration_minutes=body.duration_minutes,
            kind=body.kind,
            price_adult_minor=body.price_adult_minor,
            price_child_minor=body.price_child_minor,
            price_rental_minor=body.price_rental_minor,
            price_note=body.price_note,
            session_label=body.session_label,
            age_note=body.age_note,
            capacity_note=body.capacity_note,
            external_url=body.external_url,
            repeat_weekly=body.repeat_weekly,
        )
    except (LookupError, IceSessionValidationError) as exc:
        raise _map_error(exc) from exc
    await session.commit()
    return created


@router.patch("/admin/ice-sessions/{session_id:int}")
async def patch_admin_ice_session(
    session_id: int,
    body: AdminIceSessionPatchBody,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    fields = body.model_dump(exclude_unset=True)
    try:
        updated = await apply_ice_session_patch(session, session_id, fields)
    except (LookupError, IceSessionValidationError) as exc:
        raise _map_error(exc) from exc
    await session.commit()
    return updated


@router.delete("/admin/ice-sessions/{session_id:int}")
async def delete_admin_ice_session(
    session_id: int,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        result = await delete_ice_session(session, session_id)
    except LookupError as exc:
        raise _map_error(exc) from exc
    await session.commit()
    return result


@router.post("/admin/arenas/{arena_id:int}/ice-sessions/copy-week")
async def post_admin_copy_ice_week(
    arena_id: int,
    body: AdminIceCopyWeekBody,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        result = await copy_ice_week(session, arena_id, from_week_start=body.from_week_start)
    except (LookupError, IceSessionValidationError) as exc:
        raise _map_error(exc) from exc
    await session.commit()
    return result


@router.post("/admin/ice-sessions/recurrence/{recurrence_key}/rematerialize")
async def post_admin_rematerialize_ice(
    recurrence_key: str,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        result = await rematerialize_recurrence(session, recurrence_key)
    except LookupError as exc:
        raise _map_error(exc) from exc
    await session.commit()
    return result
