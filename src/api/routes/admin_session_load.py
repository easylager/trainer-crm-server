"""Admin API for session typical load rules (TASK-290)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth.deps import get_admin_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPrincipal
from src.application.session_load_admin import (
    DAY_GROUPS,
    get_arena_load_admin,
    list_global_load_rules,
    replace_arena_day_rules,
    replace_global_day_rules,
    reset_arena_load_rules,
    set_arena_load_character,
)

router = APIRouter(tags=["webapp-admin-session-load"])


class LoadIntervalBody(BaseModel):
    starts_from: str = Field(..., description="HH:MM")
    starts_before: str | None = Field(None, description="HH:MM exclusive, null = end of day")
    level: str


class DayRulesBody(BaseModel):
    day_group: str
    intervals: list[LoadIntervalBody]


class ArenaCharacterBody(BaseModel):
    load_character: str


@router.get("/admin/session-load/global")
async def get_global_session_load(
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    rules = await list_global_load_rules(session)
    return {"day_groups": list(DAY_GROUPS), "rules": rules}


@router.put("/admin/session-load/global")
async def put_global_session_load_day(
    body: DayRulesBody,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        await replace_global_day_rules(
            session,
            day_group=body.day_group,
            intervals=[i.model_dump() for i in body.intervals],
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await list_global_load_rules(session)


@router.get("/admin/arenas/{arena_id:int}/session-load")
async def get_arena_session_load(
    arena_id: int,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        return await get_arena_load_admin(session, arena_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Arena not found") from None


@router.put("/admin/arenas/{arena_id:int}/session-load/character")
async def put_arena_session_load_character(
    arena_id: int,
    body: ArenaCharacterBody,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        await set_arena_load_character(session, arena_id, body.load_character)
        await session.commit()
    except LookupError:
        raise HTTPException(status_code=404, detail="Arena not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await get_arena_load_admin(session, arena_id)


@router.put("/admin/arenas/{arena_id:int}/session-load/rules")
async def put_arena_session_load_rules(
    arena_id: int,
    body: DayRulesBody,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        await replace_arena_day_rules(
            session,
            arena_id=arena_id,
            day_group=body.day_group,
            intervals=[i.model_dump() for i in body.intervals],
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await get_arena_load_admin(session, arena_id)


@router.delete("/admin/arenas/{arena_id:int}/session-load/rules")
async def delete_arena_session_load_rules(
    arena_id: int,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    await reset_arena_load_rules(session, arena_id)
    await session.commit()
    return await get_arena_load_admin(session, arena_id)
