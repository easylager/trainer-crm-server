"""Client watches hub: trainer slot wait + ice arena watches."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.client_bootstrap import ensure_acting_client_id
from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.api.routes.webapp_client_trainer_edges import _existing_edge_client_id, _parse_profile_id_header
from src.api.miniapp_auth.deps import MiniappCredentialIn, require_miniapp_credential_in
from src.api.miniapp_auth.types import MiniAppPlatform
from src.application.bell_follow_use_cases import (
    follow_arena_from_bell,
    record_surface_write_access_outcome,
    record_write_access_outcome,
)
from src.application.client_ice_watch_use_cases import (
    IceWatchChannelUnsupported,
    client_watches_hub_payload,
    subscribe_ice_watch,
    unsubscribe_ice_watch,
    watches_summary,
)
from src.application.client_profile_use_cases import resolve_acting_client_id
from src.application.client_trainer_edge_use_cases import unsubscribe_notify_slots as uc_unsubscribe_notify_slots
from src.infrastructure.db.models import (
    ICE_WATCH_KIND_SCHEDULE_FRESH,
    ICE_WATCH_KIND_SEASON_OPEN,
    ICE_WATCH_KIND_SESSIONS,
)

router = APIRouter(tags=["webapp"])

CHANNEL_UNSUPPORTED = "channel_unsupported"


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
    cred: MiniappCredentialIn = Depends(require_miniapp_credential_in),
):
    # TASK-328 AC5: напоминания уходят только клиентским ботом Telegram. В MAX канала
    # доставки нет — не создаём подписку, которую некому выполнить.
    if principal.platform != MiniAppPlatform.TELEGRAM:
        raise HTTPException(status_code=409, detail=CHANNEL_UNSUPPORTED)
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await ensure_acting_client_id(session, principal, cred.raw, _parse_profile_id_header(x_profile_id))
    kind = (body.watch_kind or ICE_WATCH_KIND_SESSIONS).strip().lower()
    if kind not in (ICE_WATCH_KIND_SESSIONS, ICE_WATCH_KIND_SCHEDULE_FRESH, ICE_WATCH_KIND_SEASON_OPEN):
        raise HTTPException(status_code=400, detail="Недопустимый тип подписки.")
    if kind == ICE_WATCH_KIND_SEASON_OPEN:
        filter_json = {}
    else:
        filter_json = {
            "when": (body.when or "any").strip().lower() or "any",
            "day": (body.day or "").strip() or None,
            "intent": (body.intent or "skate").strip().lower() or "skate",
        }
    try:
        watch = await subscribe_ice_watch(
            session,
            client_id=client_id,
            telegram_id=catalog_tid,
            arena_id=int(body.arena_id),
            watch_kind=kind,
            filter_json=filter_json,
            city_id=body.city_id,
        )
    except IceWatchChannelUnsupported as exc:
        raise HTTPException(status_code=409, detail=CHANNEL_UNSUPPORTED) from exc
    return {"watch": watch}


class BellFollowBody(BaseModel):
    arena_id: int = Field(..., ge=1)


class WriteAccessOutcomeBody(BaseModel):
    arena_id: int = Field(..., ge=1)
    outcome: str = Field(..., max_length=20)
    retry: bool = False


@router.post("/client/bell-follow")
async def post_client_bell_follow(
    body: BellFollowBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Вход по колокольчику сайта (``follow_arena_<id>``): гарантирует подписку, идемпотентно."""
    if principal.platform != MiniAppPlatform.TELEGRAM:
        raise HTTPException(status_code=409, detail=CHANNEL_UNSUPPORTED)
    result = await follow_arena_from_bell(
        session, telegram_id=client_catalog_telegram_key(principal), arena_id=int(body.arena_id)
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Каток не найден.")
    return result


@router.post("/client/bell-follow/outcome")
async def post_client_bell_follow_outcome(
    body: WriteAccessOutcomeBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Исход запроса разрешения писать (granted | denied | already | unsupported) для метрики охвата."""
    if principal.platform != MiniAppPlatform.TELEGRAM:
        raise HTTPException(status_code=409, detail=CHANNEL_UNSUPPORTED)
    telegram_id = client_catalog_telegram_key(principal)
    client_id = await resolve_acting_client_id(session, telegram_id, None)
    recorded = await record_write_access_outcome(
        session,
        telegram_id=telegram_id,
        client_id=client_id,
        arena_id=int(body.arena_id),
        outcome=(body.outcome or "").strip().lower(),
        retry=body.retry,
    )
    if not recorded:
        raise HTTPException(status_code=400, detail="Неизвестный исход.")
    return {"ok": True}


class SurfaceWriteAccessOutcomeBody(BaseModel):
    surface: str = Field(..., max_length=20)
    outcome: str = Field(..., max_length=20)
    arena_id: int | None = Field(default=None, ge=1)
    trainer_id: int | None = Field(default=None, ge=1)
    retry: bool = False


def _bot_chat_link(arena_id: int | None) -> str | None:
    """Ссылка на чат клиентского бота; для подписки на каток — ``/start watch_<id>``. Имя бота из настроек."""
    from src.application.place_links import telegram_bot_start_link, watch_start_param
    from src.application.trainer_invite_links import normalize_client_bot_username
    from src.shared.config import Settings

    username = Settings().client_bot_username
    if arena_id is not None:
        return telegram_bot_start_link(client_bot_username=username, start_param=watch_start_param(arena_id))
    bot = normalize_client_bot_username(username)
    return f"https://t.me/{bot}" if bot else None


@router.post("/client/write-access/outcome")
async def post_client_write_access_outcome(
    body: SurfaceWriteAccessOutcomeBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Исход запроса разрешения писать с экрана записи / ожидания слотов / подписки на каток.

    В ответе ``bot_link``: куда вести, если спросить нечем и надо нажать «Старт» в боте.
    """
    if principal.platform != MiniAppPlatform.TELEGRAM:
        raise HTTPException(status_code=409, detail=CHANNEL_UNSUPPORTED)
    telegram_id = client_catalog_telegram_key(principal)
    client_id = await resolve_acting_client_id(session, telegram_id, None)
    recorded = await record_surface_write_access_outcome(
        session,
        telegram_id=telegram_id,
        client_id=client_id,
        surface=(body.surface or "").strip().lower(),
        outcome=(body.outcome or "").strip().lower(),
        arena_id=body.arena_id,
        trainer_id=body.trainer_id,
        retry=body.retry,
    )
    if not recorded:
        raise HTTPException(status_code=400, detail="Неизвестный исход.")
    try:
        link = _bot_chat_link(body.arena_id if body.surface.strip().lower() == "arena_watch" else None)
    except Exception:  # noqa: BLE001 — без ссылки кнопка просто не рисуется
        link = None
    return {"ok": True, "bot_link": link}


@router.delete("/client/ice-watches/{watch_id:int}")
async def delete_client_ice_watch(
    watch_id: int,
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await _existing_edge_client_id(session, catalog_tid, x_profile_id)
    watch = (
        await unsubscribe_ice_watch(session, client_id=client_id, watch_id=watch_id)
        if client_id is not None
        else None
    )
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
    client_id = await _existing_edge_client_id(session, catalog_tid, x_profile_id)
    if client_id is not None:
        await uc_unsubscribe_notify_slots(client_id, catalog_tid, trainer_id, session)
    return {"success": True}
