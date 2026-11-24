"""Вкладка «Я»: один ответ на экран, имя и «мой каток» (TASK-368)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.application.catalog_consumer_events import (
    KIND_ME_HOME_ARENA_SET,
    KIND_ME_NAME_SET,
    KIND_ME_OPEN,
    SURFACE_MINIAPP_ME,
    me_value_dedup_key,
    record_catalog_consumer_event,
    telegram_actor_hash,
)
from src.application.client_account import set_account_name, set_home_arena
from src.application.client_me import client_me, home_arena_payload
from src.application.client_use_cases import get_client_id_by_telegram_id
from src.application.client_ui_flags import redesign_s4_enabled, redesign_s5_enabled
from src.shared.config import get_settings
from src.api.routes.webapp_client_hockey import _player_name

router = APIRouter(tags=["webapp"])

_INT4_MAX = 2_147_483_647
_NO_STORE = "private, no-store"


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
    label: str | None = None


class _Club(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    short: str
    color: str
    logo: str | None
    label_ink: str
    next_match: _NextMatch | None


class _Photo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thumb: str | None
    card: str | None


class _HomeArena(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    name: str
    href: str
    sessions_left_today: int
    tomorrow_first: str | None
    subscribed: bool
    photo: _Photo | None = None
    today_times: list[str] | None = None


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
    line: str | None = None


class _PassV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: int
    total: int
    trainer_id: int
    trainer_name: str
    trainer_photo_key: str | None
    expires_label: str | None
    book_href: str


class _SavedV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arenas: int
    trainers: int
    line: str


class _CompanyPhoto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thumb: str | None
    card: str | None


class _CompanyV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str
    session_id: int | None
    arena_id: int | None
    arena_name: str
    starts_local: str
    day_label: str
    going_count: int
    going_names: list[str]
    crowd_line: str
    my_status: str
    page_url: str
    photo: _CompanyPhoto | None = None


class _BadgeProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    done: int
    total: int


class _BadgeV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    name: str
    name_gen: str | None = None
    family: str
    total: int
    earned: bool
    earned_at: str | None
    progress: _BadgeProgress


class _Person(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: int | None
    name: str | None
    is_you: bool
    active: bool


class _Family(BaseModel):
    model_config = ConfigDict(extra="forbid")
    people: list[_Person] = Field(min_length=1)


class _MyTrainer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    href: str


class _Rows(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bookings: _Bookings | None
    passes: _Passes | None
    saved: _Count | None
    family: _Family
    requests: _Count | None
    trainer: _MyTrainer | None


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
    joined_label: str | None = None
    pass_: _PassV2 | None = Field(None, alias="pass")
    saved_detail: _SavedV2 | None = None
    companies: list[_CompanyV2] | None = None
    badges: list[_BadgeV2] | None = None


class NameIn(BaseModel):
    name: str = Field(max_length=200)


class NameOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class HomeArenaIn(BaseModel):
    arena_id: int | None = Field(ge=1, le=_INT4_MAX)


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
    dedup_key: str | None = None,
) -> None:
    await record_catalog_consumer_event(
        session,
        kind=kind,
        surface=SURFACE_MINIAPP_ME,
        actor_hash=telegram_actor_hash(account_key),
        arena_id=arena_id,
        payload=payload,
        dedup=dedup,
        dedup_key=dedup_key,
    )


@router.get("/client/me", response_model=ClientMeOut, response_model_exclude_unset=True)
async def get_client_me(
    response: Response,
    init_data: str | None = None,
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> ClientMeOut:
    response.headers["Cache-Control"] = _NO_STORE
    account_key = client_catalog_telegram_key(principal)
    payload = await client_me(
        session,
        account_key=account_key,
        profile_id=_parse_profile_id_header(x_profile_id),
        telegram_name=_player_name(None, _init_raw(init_data, x_telegram_init_data)),
        include_v2=redesign_s4_enabled(account_key, get_settings()),
        include_companies=redesign_s4_enabled(account_key, get_settings())
        and redesign_s5_enabled(account_key, get_settings()),
        # PDEC-040 батч C: полка значков есть и на старом «Я» (client-me) — там s4 нет.
        include_badges=redesign_s5_enabled(account_key, get_settings()),
    )
    body = ClientMeOut.model_validate(payload)
    await session.commit()
    await _event(session, kind=KIND_ME_OPEN, account_key=account_key)
    return body


@router.put("/client/me/name", response_model=NameOut)
async def put_client_me_name(
    body: NameIn,
    response: Response,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> NameOut:
    response.headers["Cache-Control"] = _NO_STORE
    account_key = client_catalog_telegram_key(principal)
    try:
        saved = await set_account_name(session, account_key, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    await session.commit()
    await _event(
        session,
        kind=KIND_ME_NAME_SET,
        account_key=account_key,
        dedup_key=me_value_dedup_key(
            kind=KIND_ME_NAME_SET, actor_hash=telegram_actor_hash(account_key), value=saved
        ),
    )
    return NameOut(name=saved)


@router.put("/client/me/home-arena", response_model=HomeArenaOut)
async def put_client_me_home_arena(
    body: HomeArenaIn,
    response: Response,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> HomeArenaOut:
    response.headers["Cache-Control"] = _NO_STORE
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
    )
    return body
