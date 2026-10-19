"""Домашний матч Динамо как событие (TASK-304): страница матча, ответ, приглашение, настройка игры.

Звать друзей — движком «компании» льда (``ice_company``). Всё под флагом игры: выключен — 404.
Ключ игрока и ключи участников компаний наружу не отдаются: «Кто из ваших» — только имена.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import (
    MiniAppPlatform,
    MiniAppPrincipal,
    client_catalog_telegram_key,
    get_client_miniapp_principal,
)
from src.api.routes.public_ice_company import _save_prepared as save_prepared
from src.api.routes.webapp_client_hockey import _player_name
from src.application import hockey_event
from src.application.ice_company.service import CompanyRejected
from src.shared.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webapp"])

_NAME_MAX = 24
_FALLBACK_NAME = "Участник"


class RsvpBody(BaseModel):
    status: str
    display_name: str | None = None
    # Код компании друга, из чьего приглашения открыли страницу: ответ ложится и к нему.
    company: str | None = None


class InviteBody(BaseModel):
    display_name: str | None = None


class PrefsBody(BaseModel):
    kk_hidden: bool


def _require_enabled() -> None:
    if not hockey_event.enabled():
        raise HTTPException(status_code=404, detail="Не найдено")


def _require_telegram(principal: MiniAppPrincipal) -> None:
    if principal.platform != MiniAppPlatform.TELEGRAM:
        raise HTTPException(status_code=403, detail="Позвать друзей на матч можно из Telegram")


async def _name(session: AsyncSession, player_key: int, given: str | None, init_raw: str) -> str:
    name = _player_name(given, init_raw)
    if not name:
        # Имя из игры: тот, кто ходил в «Кто кого», уже представился.
        known = (
            await session.execute(
                text("SELECT display_name FROM hockey_players WHERE player_key = :k"), {"k": player_key}
            )
        ).scalar_one_or_none()
        name = str(known or "").strip()
    return (name or _FALLBACK_NAME)[:_NAME_MAX]


def _http(exc: CompanyRejected) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


async def _view(session: AsyncSession, principal: MiniAppPrincipal, match_id: int) -> dict:
    try:
        return await hockey_event.event_view(
            session,
            player_key=client_catalog_telegram_key(principal),
            match_id=match_id,
            now=datetime.now(timezone.utc),
        )
    except hockey_event.MatchNotFound:
        raise HTTPException(status_code=404, detail="Матч не найден") from None


@router.get("/client/hockey/matches/{match_id}/event")
async def get_client_hockey_event(
    match_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _require_enabled()
    return await _view(session, principal, match_id)


@router.put("/client/hockey/matches/{match_id}/rsvp")
async def put_client_hockey_rsvp(
    match_id: int,
    body: RsvpBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _require_enabled()
    _require_telegram(principal)
    player_key = client_catalog_telegram_key(principal)
    name = await _name(session, player_key, body.display_name, (init_data or x_telegram_init_data or "").strip())
    try:
        await hockey_event.rsvp(
            session,
            player_key=player_key,
            match_id=match_id,
            status=body.status,
            display_name=name,
            company_code=body.company,
            now=datetime.now(timezone.utc),
        )
    except hockey_event.MatchNotFound:
        raise HTTPException(status_code=404, detail="Матч не найден") from None
    except CompanyRejected as exc:
        raise _http(exc) from None
    return await _view(session, principal, match_id)


@router.post("/client/hockey/matches/{match_id}/invite")
async def post_client_hockey_invite(
    match_id: int,
    body: InviteBody | None = None,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Карточка «Идём на матч?» для чата. Без бота — текст и ссылка для t.me/share."""
    _require_enabled()
    _require_telegram(principal)
    player_key = client_catalog_telegram_key(principal)
    settings = Settings()  # type: ignore[call-arg]
    name = await _name(
        session, player_key, body.display_name if body else None, (init_data or x_telegram_init_data or "").strip()
    )
    try:
        card = await hockey_event.invite(
            session,
            player_key=player_key,
            match_id=match_id,
            display_name=name,
            now=datetime.now(timezone.utc),
            settings=settings,
        )
    except hockey_event.MatchNotFound:
        raise HTTPException(status_code=404, detail="Матч не найден") from None
    except CompanyRejected as exc:
        raise _http(exc) from None
    if not card["url"].startswith("http"):
        raise HTTPException(status_code=503, detail="Ссылка появится, когда бот будет настроен")
    prepared = await save_prepared(
        settings.telegram_bot_token_client,
        player_key,
        card["code"],
        card["text"],
        card["buttons"],
        None,
        title="Звать на матч",
    )
    await hockey_event.track_shared(session, city_id=card["city_id"], prepared=prepared is not None)
    await session.commit()
    return {"prepared_message_id": prepared, "text": card["text"], "url": card["url"]}


@router.get("/client/hockey/prefs")
async def get_client_hockey_prefs(
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _require_enabled()
    return {"kk_hidden": await hockey_event.kk_hidden(session, client_catalog_telegram_key(principal))}


@router.put("/client/hockey/prefs")
async def put_client_hockey_prefs(
    body: PrefsBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _require_enabled()
    hidden = await hockey_event.set_kk_hidden(session, client_catalog_telegram_key(principal), body.kk_hidden)
    await session.commit()
    return {"kk_hidden": hidden}
