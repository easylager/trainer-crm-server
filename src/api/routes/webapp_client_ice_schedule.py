"""TASK-449: API вкладки «Лёд» v2 — расписание города по дням/видам. Только при флаге redesign_s4."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.application.client_ui_flags import redesign_s4_enabled, redesign_s5_enabled
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
    # TASK-450 (5.3): плашка «Твоя компания» на сеансах с моей открытой компанией — только под s5.
    telegram_id = client_catalog_telegram_key(principal)
    if redesign_s5_enabled(telegram_id, get_settings()):
        from src.application.ice_company.flag import city_enabled

        payload["company_share"] = bool(city_enabled(city_id))
        from datetime import datetime, timezone

        from src.application.ice_company.mine import my_open_companies

        mine = await my_open_companies(session, telegram_id, datetime.now(timezone.utc))
        by_session = {
            c["session_id"]: {"code": c["code"], "going_count": c["going_count"], "page_url": c["page_url"]}
            for c in mine
            if c.get("session_id") is not None
        }
        if by_session:
            for row in payload.get("ongoing") or []:
                comp = by_session.get(row.get("session_id"))
                if comp:
                    row["company"] = comp
            for row in payload.get("upcoming") or []:
                comp = by_session.get(row.get("session_id"))
                if comp:
                    row["company"] = comp
            for g in payload.get("groups") or []:
                for row in g.get("rows") or []:
                    comp = by_session.get(row.get("session_id"))
                    if comp:
                        row["company"] = comp
            tm = payload.get("tomorrow_morning") or {}
            for row in tm.get("rows") or []:
                comp = by_session.get(row.get("session_id"))
                if comp:
                    row["company"] = comp
    return payload
