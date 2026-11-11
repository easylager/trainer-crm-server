"""Вкладка «Я»: один ответ на экран, имя и «мой каток» (TASK-368)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.application.catalog_consumer_events import (
    KIND_ME_HOME_ARENA_SET,
    KIND_ME_NAME_SET,
    KIND_ME_OPEN,
    SURFACE_MINIAPP_ME,
    record_catalog_consumer_event,
    telegram_actor_hash,
)
from src.application.client_account import set_account_name, set_home_arena
from src.application.client_me import client_me, home_arena_payload
from src.application.client_use_cases import get_client_id_by_telegram_id
from src.api.routes.webapp_client_hockey import _player_name

router = APIRouter(tags=["webapp"])


def _parse_profile_id_header(x_profile_id: str | None) -> int | None:
    if not x_profile_id:
        return None
    try:
        return int(x_profile_id)
    except ValueError:
        return None


class _NextMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    starts_at: str
    opponent: str
    href: str


class _Club(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    short: str
    color: str
    logo: str | None
    label_ink: str
    next_match: _NextMatch | None


class _HomeArena(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    name: str
    href: str
    sessions_left_today: int
    tomorrow_first: str | None
    subscribed: bool


class _Stats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trainings: int | None
    streak_weeks: int | None
    kk_points: int | None
    kk_place: int | None


class _Bookings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    next_starts_at: str | None


class _Passes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lessons_left: int


class _Count(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int


class _Family(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profiles: int


class _Rows(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bookings: _Bookings | None
    passes: _Passes | None
    saved: _Count | None
    family: _Family
    requests: _Count | None


class ClientMeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    initial: str
    city: str | None
    club: _Club | None
    home_arena: _HomeArena | None
    stats: _Stats
    rows: _Rows
    profile_name: str | None


class NameIn(BaseModel):
    name: str


class NameOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class HomeArenaIn(BaseModel):
    arena_id: int | None


class HomeArenaOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    home_arena: _HomeArena | None


def _init_raw(init_data: str | None, x_telegram_init_data: str | None) -> str:
    return (init_data or x_telegram_init_data or "").strip()


async def _event(
    session: AsyncSession,
    *,
    kind: str,
    account_key: int,
    arena_id: int | None = None,
    payload: dict | None = None,
    dedup: bool = True,
) -> None:
    await record_catalog_consumer_event(
        session,
        kind=kind,
        surface=SURFACE_MINIAPP_ME,
        actor_hash=telegram_actor_hash(account_key),
        arena_id=arena_id,
        payload=payload,
        dedup=dedup,
    )


@router.get("/client/me", response_model=ClientMeOut)
async def get_client_me(
    init_data: str | None = None,
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> ClientMeOut:
    account_key = client_catalog_telegram_key(principal)
    payload = await client_me(
        session,
        account_key=account_key,
        profile_id=_parse_profile_id_header(x_profile_id),
        telegram_name=_player_name(None, _init_raw(init_data, x_telegram_init_data)),
    )
    body = ClientMeOut.model_validate(payload)
    await session.commit()
    await _event(session, kind=KIND_ME_OPEN, account_key=account_key)
    return body


@router.put("/client/me/name", response_model=NameOut)
async def put_client_me_name(
    body: NameIn,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> NameOut:
    account_key = client_catalog_telegram_key(principal)
    try:
        saved = await set_account_name(session, account_key, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    await _event(session, kind=KIND_ME_NAME_SET, account_key=account_key, dedup=False)
    return NameOut(name=saved)


@router.put("/client/me/home-arena", response_model=HomeArenaOut)
async def put_client_me_home_arena(
    body: HomeArenaIn,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> HomeArenaOut:
    account_key = client_catalog_telegram_key(principal)
    try:
        arena_id = await set_home_arena(session, account_key, body.arena_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    own = await get_client_id_by_telegram_id(session, account_key)
    home = await home_arena_payload(session, arena_id=arena_id, client_id=own)
    body = HomeArenaOut.model_validate({"home_arena": home})
    await session.commit()
    await _event(
        session,
        kind=KIND_ME_HOME_ARENA_SET,
        account_key=account_key,
        arena_id=arena_id,
        payload={"arena_id": arena_id},
        dedup=False,
    )
    return body
