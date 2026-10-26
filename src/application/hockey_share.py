"""Данные для карточек «Кто кого» в чате и их воронка (TASK-300). Рисует hockey_cards."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_cards import league_card_version, match_when
from src.application.hockey_leagues import league_preview
from src.application.hockey_matches import STATUS_FINAL, MatchRow, get_match

logger = logging.getLogger(__name__)

CARD_KINDS = ("shared", "opened", "joined")
CARDS = ("result", "league", "crown")

_MY_POINTS = text("""
    SELECT points FROM hockey_picks
    WHERE match_id = :match_id AND player_key = CAST(:player_key AS BIGINT) AND points IS NOT NULL
""")

_NEXT_OPEN = text("""
    SELECT home_team, away_team, starts_at FROM hockey_matches
    WHERE status = 'scheduled' AND starts_at > :now
    ORDER BY starts_at LIMIT 1
""")

_EVENT = text("""
    INSERT INTO hockey_card_events (kind, card, league_id, match_id, prepared)
    VALUES (:kind, :card, :league_id, :match_id, :prepared)
""")


@dataclass(frozen=True)
class ResultCard:
    match: MatchRow
    points: int


@dataclass(frozen=True)
class LeagueCard:
    name: str
    invite_code: str
    members: int
    names: list[str]
    next_match: str | None
    version: str


async def result_card(session: AsyncSession, *, player_key: int, match_id: int) -> ResultCard | None:
    """Итог моего хода, если есть чем похвастаться: матч сыгран и победитель угадан (20, 30 или 50)."""
    match = await get_match(session, match_id)
    if match is None or match.status != STATUS_FINAL:
        return None
    points = (await session.execute(_MY_POINTS, {"match_id": match_id, "player_key": player_key})).scalar_one_or_none()
    if points not in (20, 30, 50):
        return None
    return ResultCard(match=match, points=int(points))


async def next_match_line(session: AsyncSession, *, now: datetime) -> str | None:
    record = (await session.execute(_NEXT_OPEN, {"now": now})).one_or_none()
    if record is None:
        return None
    return f"{record.home_team} — {record.away_team}, {match_when(record.starts_at)}"


async def league_card(session: AsyncSession, code: str, *, now: datetime) -> LeagueCard | None:
    preview = await league_preview(session, code)
    if preview is None:
        return None
    upcoming = await next_match_line(session, now=now)
    names = list(preview["names"])
    return LeagueCard(
        name=preview["name"],
        invite_code=preview["invite_code"],
        members=int(preview["members"]),
        names=names,
        next_match=upcoming,
        version=league_card_version(preview["name"], int(preview["members"]), names, upcoming),
    )


async def record_card_event(
    session: AsyncSession,
    *,
    kind: str,
    card: str,
    league_id: int | None = None,
    match_id: int | None = None,
    prepared: bool | None = None,
) -> None:
    """Счётчик воронки. Сбой записи не должен ломать ни шаринг, ни вступление."""
    if kind not in CARD_KINDS or card not in CARDS:
        raise ValueError(f"unknown card event {kind}/{card}")
    params = {"kind": kind, "card": card, "league_id": league_id, "match_id": match_id, "prepared": prepared}
    try:
        async with session.begin_nested():
            await session.execute(_EVENT, params)
    except Exception:  # noqa: BLE001
        logger.warning("hockey card event not recorded kind=%s card=%s", kind, card, exc_info=True)


__all__ = [
    "CARDS",
    "CARD_KINDS",
    "LeagueCard",
    "ResultCard",
    "league_card",
    "next_match_line",
    "record_card_event",
    "result_card",
]
