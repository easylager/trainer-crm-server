"""Client watches hub: trainer slot wait + ice arena watches."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.api.routes.webapp_client_trainer_edges import _parse_profile_id_header, _resolve_edge_client_id_or_400
from src.application.client_ice_watch_use_cases import (
    client_watches_hub_payload,
    subscribe_ice_watch,
    unsubscribe_ice_watch,
    watches_summary,
)
from src.application.client_profile_use_cases import resolve_acting_client_id
from src.application.client_trainer_edge_use_cases import unsubscribe_notify_slots as uc_unsubscribe_notify_slots
from src.infrastructure.db.models import ICE_WATCH_KIND_SCHEDULE_FRESH, ICE_WATCH_KIND_SESSIONS

router = APIRouter(tags=["webapp"])


class IceWatchBody(BaseModel):
    arena_id: int
    watch_kind: str = Field(default=ICE_WATCH_KIND_SESSIONS)
    city_id: int | None = None
    when: str | None = None
    day: str | None = None
    intent: str | None = "skate"


@router.get("/client/watches/summary")
async def get_client_watches_summary(
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await resolve_acting_client_id(session, catalog_tid, _parse_profile_id_header(x_profile_id))
    if client_id is None:
        return {"active_count": 0, "trainer_slot_watches": 0, "ice_watches": 0}
    return await watches_summary(session, int(client_id))


@router.get("/client/watches")
async def get_client_watches_hub(
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await resolve_acting_client_id(session, catalog_tid, _parse_profile_id_header(x_profile_id))
    if client_id is None:
        return {
            "active_count": 0,
            "trainer_slot_watches": 0,
            "ice_watches": 0,
            "trainer_notifications": [],
            "ice_watch_items": [],
        }
    return await client_watches_hub_payload(session, int(client_id))


@router.post("/client/ice-watches")
async def post_client_ice_watch(
    body: IceWatchBody,
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await _resolve_edge_client_id_or_400(session, catalog_tid, x_profile_id)
    kind = (body.watch_kind or ICE_WATCH_KIND_SESSIONS).strip().lower()
    if kind not in (ICE_WATCH_KIND_SESSIONS, ICE_WATCH_KIND_SCHEDULE_FRESH):
        raise HTTPException(status_code=400, detail="Недопустимый тип подписки.")
    filter_json = {
        "when": (body.when or "any").strip().lower() or "any",
        "day": (body.day or "").strip() or None,
        "intent": (body.intent or "skate").strip().lower() or "skate",
    }
    watch = await subscribe_ice_watch(
        session,
        client_id=client_id,
        telegram_id=catalog_tid,
        arena_id=int(body.arena_id),
        watch_kind=kind,
        filter_json=filter_json,
        city_id=body.city_id,
    )
    return {"watch": watch}


@router.delete("/client/ice-watches/{watch_id:int}")
async def delete_client_ice_watch(
    watch_id: int,
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await _resolve_edge_client_id_or_400(session, catalog_tid, x_profile_id)
    watch = await unsubscribe_ice_watch(session, client_id=client_id, watch_id=watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="Подписка не найдена.")
    return {"watch": watch}


@router.delete("/client/watches/trainer-slots/{trainer_id:int}")
async def delete_client_trainer_slot_watch(
    trainer_id: int,
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await _resolve_edge_client_id_or_400(session, catalog_tid, x_profile_id)
    await uc_unsubscribe_notify_slots(client_id, catalog_tid, trainer_id, session)
    return {"success": True}
