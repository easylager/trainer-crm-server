"""TASK-366: флаги клиентского интерфейса — новая навигация your-season и вкладка «Записи»."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.application.client_ui_flags import has_trainer_history, season_ui_enabled
from src.shared.config import get_settings

router = APIRouter(tags=["webapp"])


@router.get("/client/ui-flags")
async def get_client_ui_flags(
    response: Response,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> dict[str, bool]:
    response.headers["Cache-Control"] = "no-store"
    account_key = client_catalog_telegram_key(principal)
    season_ui = season_ui_enabled(account_key, get_settings())
    bookings_tab = season_ui and await has_trainer_history(session, account_key)
    return {"season_ui": season_ui, "bookings_tab": bookings_tab}
