"""TASK-438: API вкладки «Поиск» — лента сеансов города по времени. Только при флаге search_board."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.application.client_ui_flags import search_board_enabled
from src.application.ice_board import MAX_DAYS, CityNotFound, get_ice_board
from src.shared.config import get_settings

router = APIRouter(tags=["webapp"])


@router.get("/client/ice-board")
async def get_client_ice_board(
    response: Response,
    city_id: int = Query(...),
    day_from: date | None = Query(None, alias="from"),
    days: int = Query(1, ge=1, le=MAX_DAYS),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    if not search_board_enabled(client_catalog_telegram_key(principal), get_settings()):
        raise HTTPException(status_code=403, detail="search_board_off")
    try:
        return await get_ice_board(session, city_id=city_id, day_from=day_from, days=days)
    except CityNotFound:
        raise HTTPException(status_code=404, detail="city_not_found") from None
