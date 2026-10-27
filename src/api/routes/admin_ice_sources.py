"""Admin ice schedule sources (link, collection mode, posting days). New module — do not grow webapp.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth.deps import get_admin_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPrincipal
from src.application.admin_ice_sources import (
    SourceValidationError,
    list_admin_ice_sources,
    save_admin_ice_source,
)

router = APIRouter(tags=["webapp-admin-ice-sources"])


class AdminIceSourceBody(BaseModel):
    source_url: str | None = Field(None, max_length=600)
    fetch_mode: str
    publish_days: list[int] = Field(default_factory=list, max_length=7)
    remind: bool = False


@router.get("/admin/ice-sources")
async def get_admin_ice_sources(
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    return await list_admin_ice_sources(session)


@router.put("/admin/ice-sources/{arena_id:int}")
async def put_admin_ice_source(
    arena_id: int,
    body: AdminIceSourceBody,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    try:
        ok = await save_admin_ice_source(
            session,
            arena_id=arena_id,
            source_url=body.source_url,
            fetch_mode=body.fetch_mode,
            publish_days=body.publish_days,
            remind=body.remind,
            admin_telegram_id=int(principal.user_id),
        )
    except SourceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Arena not found")
    return {"ok": True}
