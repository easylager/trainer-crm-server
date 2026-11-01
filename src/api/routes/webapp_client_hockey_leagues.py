"""Клиентское API лиг друзей «Кто кого»: создать, вступить, таблица, выйти."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.api.routes.webapp_client_hockey import _player_name
from src.application.hockey_leagues import (
    FEW_MATCHES,
    InvalidTerms,
    League,
    LeagueFull,
    LeagueRow,
    LeagueSummary,
    TooManyLeagues,
    build_terms,
    create_league,
    extend_league,
    join_by_code,
    league_table,
    league_titles,
    leave_league,
    matches_in_terms,
    player_leagues,
    rename_league,
)
from src.application.hockey_races import crown_counts, league_crown_wall, race_summary
from src.application.hockey_share import record_card_event
from src.application.place_links import telegram_open_link
from src.shared.config import Settings

router = APIRouter(tags=["webapp"])

_TOO_MANY = "Можно состоять максимум в 20 лигах"
_LEAGUE_FULL = "В лиге уже 100 человек"
_NOT_FOUND = "Лига не найдена"
_FORBIDDEN = "Нет доступа к этой лиге"


class TermsBody(BaseModel):
    """Набор команд и срок лиги. Без них — «Динамо-Минск, до конца сезона»."""

    scope: Literal["all", "extraliga", "dinamo", "clubs"] = "dinamo"
    clubs: list[str] = []
    term: Literal["season", "month", "weeks4", "playoff", "dates"] = "season"
    month: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None


class CreateLeagueBody(BaseModel):
    name: str
    display_name: str | None = None
    terms: TermsBody | None = None


class ExtendLeagueBody(BaseModel):
    terms: TermsBody | None = None


class JoinLeagueBody(BaseModel):
    code: str
    display_name: str | None = None
    # С какой карточки в чате пришёл: для воронки TASK-300.
    from_card: Literal["result", "league"] | None = None


class RenameLeagueBody(BaseModel):
    name: str


def invite_url_for_code(code: str) -> str | None:
    """Ссылка в Mini App. Без настроенного бота ссылки нет."""
    settings = Settings()  # type: ignore[call-arg]
    return telegram_open_link(
        client_bot_username=settings.client_bot_username,
        mini_app_short_name=settings.client_mini_app_short_name,
        main_mini_app=settings.client_bot_main_mini_app,
        start_param=f"kk_{code}",
    )


def _raise_league(exc: Exception) -> NoReturn:
    if isinstance(exc, ValueError):  # в том числе InvalidTerms
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=_NOT_FOUND) from exc
    if isinstance(exc, LeagueFull):
        raise HTTPException(status_code=409, detail=_LEAGUE_FULL) from exc
    if isinstance(exc, TooManyLeagues):
        raise HTTPException(status_code=409, detail=_TOO_MANY) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=_FORBIDDEN) from exc
    raise exc


def _summary_out(row: LeagueSummary) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "members": row.members,
        "is_owner": row.is_owner,
        "my_rank": row.my_rank,
        "my_points": row.my_points,
        "invite_url": invite_url_for_code(row.invite_code),
        **_terms_out(row.scope, row.clubs, row.term_kind, row.starts_at, row.ends_at),
        "active": row.active,
    }


def _terms_out(scope: str, clubs, term_kind: str, starts_at, ends_at) -> dict:
    return {
        "scope": scope,
        "clubs": list(clubs),
        "term": term_kind,
        "starts_at": None if starts_at is None else starts_at.isoformat(),
        "ends_at": None if ends_at is None else ends_at.isoformat(),
    }


def _terms_from(body: TermsBody | None, now: datetime):
    if body is None:
        return None
    return build_terms(
        scope=body.scope,
        clubs=body.clubs,
        term=body.term,
        now=now,
        month=body.month,
        starts_at=body.starts_on,
        ends_at=body.ends_on,
    )


def _table_row(row: LeagueRow, player_key: int, titles: dict | None = None) -> dict:
    return {
        "rank": row.rank,
        "display_name": row.display_name,
        "points": row.points,
        "exact": row.exact,
        "played": row.played,
        "correct_percent": None if not row.played else round(100 * row.correct / row.played),
        "is_me": row.player_key == player_key,
        "title": (titles or {}).get(row.player_key),
    }


async def _created_out(session: AsyncSession, league: League, player_key: int, now: datetime) -> dict:
    rows = await league_table(session, league_id=league.id, player_key=player_key, now=now)
    mine = next(row for row in rows if row.player_key == player_key)
    return {
        "id": league.id,
        "name": league.name,
        "members": len(rows),
        "is_owner": league.owner_key == player_key,
        "my_rank": mine.rank,
        "my_points": mine.points,
        "invite_url": invite_url_for_code(league.invite_code),
        **_terms_out(league.scope, league.clubs, league.term_kind, league.starts_at, league.ends_at),
        "active": _aware_end(league.ends_at) > now,
    }


def _aware_end(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _init_raw(init_data: str | None, header: str | None) -> str:
    return (init_data or header or "").strip()


@router.get("/client/hockey/leagues")
async def get_client_hockey_leagues(
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    rows = await player_leagues(session, player_key=player_key, now=now)
    return {"items": [_summary_out(row) for row in rows]}


@router.post("/client/hockey/leagues")
async def post_client_hockey_league(
    body: CreateLeagueBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        terms = _terms_from(body.terms, now)
        league = await create_league(
            session,
            owner_key=player_key,
            owner_name=_player_name(body.display_name, _init_raw(init_data, x_telegram_init_data)),
            name=body.name,
            terms=terms,
            now=now,
        )
        payload = await _created_out(session, league, player_key, now)
        payload.update(await _terms_hint(session, league, now))
    except (ValueError, TooManyLeagues) as exc:
        _raise_league(exc)
    await session.commit()
    return payload


async def _terms_hint(session: AsyncSession, league: League, now: datetime) -> dict:
    """Сколько матчей ещё впереди в сроке; меньше пяти — предупреждаем (пауза, клуб вылетел)."""
    from src.application.hockey_leagues import Terms

    count = await matches_in_terms(
        session,
        Terms(league.scope, league.clubs, league.term_kind, league.starts_at, league.ends_at),  # type: ignore[arg-type]
        now=now,
    )
    return {"matches_in_term": count, "few_matches": count < FEW_MATCHES}


@router.post("/client/hockey/leagues/terms-preview")
async def post_client_hockey_league_terms_preview(
    body: TermsBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Перед созданием: окно дат и сколько матчей попадёт в срок."""
    now = datetime.now(timezone.utc)
    try:
        terms = _terms_from(body, now)
    except InvalidTerms as exc:
        _raise_league(exc)
    count = await matches_in_terms(session, terms, now=now)  # type: ignore[arg-type]
    return {
        **_terms_out(terms.scope, terms.clubs, terms.term_kind, terms.starts_at, terms.ends_at),  # type: ignore[union-attr]
        "matches_in_term": count,
        "few_matches": count < FEW_MATCHES,
    }


@router.post("/client/hockey/leagues/join")
async def post_client_hockey_league_join(
    body: JoinLeagueBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    already = {row.id for row in await player_leagues(session, player_key=player_key, now=now)}
    try:
        league = await join_by_code(
            session,
            player_key=player_key,
            display_name=_player_name(body.display_name, _init_raw(init_data, x_telegram_init_data)),
            code=body.code,
        )
        payload = await _created_out(session, league, player_key, now)
    except (LookupError, LeagueFull, TooManyLeagues) as exc:
        _raise_league(exc)
    if body.from_card and league.id not in already:
        await record_card_event(session, kind="joined", card=body.from_card, league_id=league.id)
    await session.commit()
    return payload


@router.get("/client/hockey/leagues/{league_id}")
async def get_client_hockey_league(
    league_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        rows = await league_table(session, league_id=league_id, player_key=player_key, now=now)
    except (LookupError, PermissionError) as exc:
        _raise_league(exc)
    summary = next(
        item for item in await player_leagues(session, player_key=player_key, now=now) if item.id == league_id
    )
    titles = await league_titles(session, league_id=league_id, now=now)
    crowns = await crown_counts(session, league_id=league_id)
    return {
        "id": summary.id,
        "name": summary.name,
        "is_owner": summary.is_owner,
        "invite_url": invite_url_for_code(summary.invite_code),
        **_terms_out(summary.scope, summary.clubs, summary.term_kind, summary.starts_at, summary.ends_at),
        "active": summary.active,
        "race": await race_summary(session, now=now),
        "wall": await league_crown_wall(session, league_id=league_id, now=now),
        "items": [{**_table_row(row, player_key, titles), "crowns": crowns.get(row.player_key, 0)} for row in rows],
    }


@router.patch("/client/hockey/leagues/{league_id}")
async def patch_client_hockey_league(
    league_id: int,
    body: RenameLeagueBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        league = await rename_league(session, league_id=league_id, player_key=player_key, name=body.name)
        payload = await _created_out(session, league, player_key, now)
    except (ValueError, LookupError, PermissionError) as exc:
        _raise_league(exc)
    await session.commit()
    return payload


@router.delete("/client/hockey/leagues/{league_id}/membership")
async def delete_client_hockey_league_membership(
    league_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    player_key = client_catalog_telegram_key(principal)
    try:
        result = await leave_league(session, league_id=league_id, player_key=player_key)
    except (LookupError, PermissionError) as exc:
        _raise_league(exc)
    await session.commit()
    return {"result": result}


@router.post("/client/hockey/leagues/{league_id}/extend")
async def post_client_hockey_league_extend(
    league_id: int,
    body: ExtendLeagueBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """«Продлить»: новая лига с теми же людьми на следующий срок. У лиги одно продолжение — повтор вернёт его."""
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        terms = _terms_from(body.terms, now)
        league, created = await extend_league(
            session, league_id=league_id, player_key=player_key, now=now, terms=terms
        )
        payload = await _created_out(session, league, player_key, now)
        payload.update(await _terms_hint(session, league, now))
    except (ValueError, LookupError, PermissionError, TooManyLeagues) as exc:
        _raise_league(exc)
    await session.commit()
    return {**payload, "created": created}
