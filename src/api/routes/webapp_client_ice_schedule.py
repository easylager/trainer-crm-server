"""TASK-449: API вкладки «Лёд» v2 — расписание города по дням/видам. Только при флаге redesign_s4."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.application.client_ui_flags import redesign_s4_enabled
from src.application.ice_schedule_v2 import get_ice_schedule
from src.shared.config import get_settings

router = APIRouter(tags=["webapp"])


@router.get("/client/ice/schedule")
async def get_client_ice_schedule(
    response: Response,
    city_id: int = Query(...),
    day: str = Query("today"),
    kind: str = Query("skate"),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    if not redesign_s4_enabled(client_catalog_telegram_key(principal), get_settings()):
        raise HTTPException(status_code=404, detail="redesign_s4_off")
    payload = await get_ice_schedule(session, city_id=city_id, day=day, kind=kind)
    if payload is None:
        raise HTTPException(status_code=404, detail="city_not_found")
    if payload.get("__invalid__"):
        raise HTTPException(status_code=422, detail="bad_day_or_kind")
    return payload
