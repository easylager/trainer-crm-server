"""«Вечер» лиги друзей «Кто кого»: кто как сходил за игровой день (TASK-431).

Игровой день лиги — дата начала матча по Минску (``MINSK_TZ``), только матчи набора команд лиги
(``League.match_scope``) внутри её срока. В лиге бывает по четыре матча за вечер (Динамо и Экстралига), поэтому
всё в «Вечере» считается за день, а не за матч.

Ходы — как в таблице лиги: только на матчи, начавшиеся после вступления участника. Чужие ходы до начала матча
показываем без счёта и очков (одна сторона, как ``friends_picks``), после старта — целиком (как ``friends_moves``).
Отменённые матчи в день не входят. Ключи игроков наружу не уходят: строку называет ``public_id``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_slices_sql import SCOPE_SQL
from src.ingestion.hockey_sources import MINSK_TZ

# Отметка хода по матчу дня: в плюсе, мимо, ждёт итога (матч не сыгран), без хода.
HIT, MISS, WAIT, NONE = "hit", "miss", "wait", "none"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def game_day(starts_at: datetime) -> date:
    """Игровой день матча — дата начала по Минску."""
    return _utc(starts_at).astimezone(MINSK_TZ).date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Минская полночь дня и следующего — в UTC."""
    start = datetime(day.year, day.month, day.day, tzinfo=MINSK_TZ)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


@dataclass(frozen=True)
class DayMatch:
    id: int
    home: str
    away: str
    starts_at: datetime
    status: str
    home_score: int | None
    away_score: int | None

    def started(self, now: datetime) -> bool:
        return self.status != "scheduled" or _utc(self.starts_at) <= _utc(now)


@dataclass
class Member:
    player_key: int
    display_name: str
    pid: str
    joined_at: datetime
    club: str | None = None  # «своя» команда, как у бота (``_FAN_CLUB``)


@dataclass
class DayRow:
    """Участник за игровой день: ходы по матчам дня и сумма очков (с козырем, как в таблицах)."""

    member: Member
    picks: dict[int, dict] = field(default_factory=dict)

    @property
    def scored(self) -> list[dict]:
        return [p for p in self.picks.values() if p["points"] is not None and p["final"]]

    @property
    def moves(self) -> int:
        """Сыгранные ходы: на матчи с итогом и посчитанными очками."""
        return len(self.scored)

    @property
    def points(self) -> int:
        return sum(p["points"] * (2 if p["doubled"] else 1) for p in self.scored)

    @property
    def hits(self) -> int:
        return sum(1 for p in self.scored if p["points"] > 0)


_DAYS = text(f"""
    SELECT DISTINCT (m.starts_at AT TIME ZONE 'Europe/Minsk')::date AS day
    FROM game_matches AS m
    WHERE m.status <> 'cancelled' AND m.starts_at >= :since AND m.starts_at < :until
      {SCOPE_SQL}
    ORDER BY day
    """)

_DAY_MATCHES = text(f"""
    SELECT m.id, m.home_team, m.away_team, m.starts_at, m.status, m.home_score, m.away_score
    FROM game_matches AS m
    WHERE m.status <> 'cancelled' AND m.starts_at >= :since AND m.starts_at < :until
      {SCOPE_SQL}
    ORDER BY m.starts_at, m.id
    """)


def _members_sql():
    from src.application.hockey_notices import _FAN_CLUB

    return text(f"""
        SELECT mb.player_key, pl.display_name, pl.public_id AS pid, mb.joined_at, {_FAN_CLUB} AS club
        FROM hockey_league_members AS mb
        JOIN hockey_players AS pl ON pl.player_key = mb.player_key
        LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = pl.player_key
        WHERE mb.league_id = :league_id
        ORDER BY mb.joined_at, mb.player_key
        """)


# Ходы участников на матчи дня — только после вступления (как в таблице лиги).
_DAY_PICKS = text("""
    SELECT p.match_id, p.player_key, p.side, p.home_score, p.away_score, p.points, p.doubled,
           m.status = 'final' AS final
    FROM hockey_picks AS p
    JOIN hockey_league_members AS mb ON mb.player_key = p.player_key AND mb.league_id = :league_id
    JOIN game_matches AS m ON m.id = p.match_id
    WHERE p.match_id = ANY(:match_ids) AND m.starts_at >= mb.joined_at
    """)


def _window(league, since: datetime, until: datetime) -> tuple[datetime, datetime]:
    """Пересечение окна с сроком лиги."""
    return max(_utc(since), _utc(league.starts_at)), min(_utc(until), _utc(league.ends_at))


async def league_days(session: AsyncSession, league) -> list[date]:
    """Все игровые дни лиги в её сроке (по возрастанию)."""
    params = {"since": _utc(league.starts_at), "until": _utc(league.ends_at), **league.match_scope.params}
    return [r.day for r in (await session.execute(_DAYS, params)).all()]


def visible_days(days: list[date], today: date) -> list[date]:
    """Дни, которые листают стрелки: прошедшие и сегодняшний. Пока у лиги ни одного — её первый день впереди."""
    shown = [d for d in days if d <= today]
    if shown:
        return shown
    return days[:1]


def default_day(days: list[date], today: date) -> date | None:
    """Вечер по умолчанию: сегодня, если сегодня есть матчи лиги; иначе последний день с матчами."""
    shown = visible_days(days, today)
    return shown[-1] if shown else None


async def day_matches(session: AsyncSession, league, day: date) -> list[DayMatch]:
    since, until = _window(league, *day_bounds(day))
    if since >= until:
        return []
    params = {"since": since, "until": until, **league.match_scope.params}
    return [
        DayMatch(
            id=r.id,
            home=r.home_team,
            away=r.away_team,
            starts_at=r.starts_at,
            status=r.status,
            home_score=r.home_score,
            away_score=r.away_score,
        )
        for r in (await session.execute(_DAY_MATCHES, params)).all()
    ]


async def league_members(session: AsyncSession, league_id: int, *, now: datetime) -> list[Member]:
    from src.application.hockey_notices import FAN_WINDOW

    params = {"league_id": league_id, "now": _utc(now), "fan_since": _utc(now) - FAN_WINDOW}
    return [
        Member(player_key=r.player_key, display_name=r.display_name, pid=r.pid, joined_at=r.joined_at, club=r.club)
        for r in (await session.execute(_members_sql(), params)).all()
    ]


async def day_rows(
    session: AsyncSession, league_id: int, members: list[Member], matches: list[DayMatch]
) -> list[DayRow]:
    rows = {m.player_key: DayRow(member=m) for m in members}
    if matches:
        params = {"league_id": league_id, "match_ids": [m.id for m in matches]}
        for r in (await session.execute(_DAY_PICKS, params)).all():
            if r.player_key in rows:
                rows[r.player_key].picks[r.match_id] = dict(r._mapping)
    return list(rows.values())


def day_complete(matches: list[DayMatch]) -> bool:
    """День лиги сыгран: у всех его матчей есть итог (отменённые в день не входят, их не ждём)."""
    return bool(matches) and all(m.status == "final" for m in matches)


def mark(pick: dict | None, match: DayMatch) -> str:
    if pick is None:
        return NONE
    if match.status == "final" and pick["points"] is not None:
        return HIT if pick["points"] > 0 else MISS
    return WAIT


def pick_out(pick: dict | None, match: DayMatch, *, mine: bool, now: datetime) -> dict:
    """Отметка по матчу. Чужой ход до начала матча — только сторона: счёт и очки открываются со стартом."""
    state = mark(pick, match)
    out: dict = {"match_id": match.id, "state": state}
    if pick is None:
        return out
    out["side"] = pick["side"]
    if mine or match.started(now):
        out["home_score"] = pick["home_score"]
        out["away_score"] = pick["away_score"]
        out["doubled"] = bool(pick["doubled"])
        out["points"] = None if pick["points"] is None else pick["points"] * (2 if pick["doubled"] else 1)
    return out


def match_out(m: DayMatch, *, now: datetime) -> dict:
    return {
        "id": m.id,
        "home": m.home,
        "away": m.away,
        "starts_at": _utc(m.starts_at).isoformat(),
        "status": m.status,
        "started": m.started(now),
        "home_score": m.home_score if m.status == "final" else None,
        "away_score": m.away_score if m.status == "final" else None,
    }


def neighbours(days: list[date], day: date) -> tuple[date | None, date | None]:
    before = [d for d in days if d < day]
    after = [d for d in days if d > day]
    return (before[-1] if before else None), (after[0] if after else None)


def _sort_key(row: DayRow, me: int) -> tuple:
    return (row.member.player_key != me, -row.points, -row.moves, row.member.display_name, row.member.player_key)


async def league_evening(session: AsyncSession, *, league, player_key: int, now: datetime, day: date | None) -> dict:
    """«Вечер» лиги за день ``day`` (``None`` — по умолчанию). Участие проверяет вызывающий."""
    now = _utc(now)
    today = game_day(now)
    days = visible_days(await league_days(session, league), today)
    if day not in days:  # не задан или не день лиги (чужая дата, будущий день) — вечер по умолчанию
        day = days[-1] if days else None
    if day is None:
        return {"day": None, "prev": None, "next": None, "complete": False, "matches": [], "items": []}
    matches = await day_matches(session, league, day)
    members = await league_members(session, league.id, now=now)
    rows = await day_rows(session, league.id, members, matches)
    prev, nxt = neighbours(days, day)
    items = []
    for row in sorted(rows, key=lambda r: _sort_key(r, player_key)):
        mine = row.member.player_key == player_key
        items.append(
            {
                "pid": row.member.pid,
                "display_name": row.member.display_name,
                "is_me": mine,
                "marks": [pick_out(row.picks.get(m.id), m, mine=mine, now=now) for m in matches],
                "hits": row.hits,
                "moves": row.moves,
                "points": row.points,
            }
        )
    return {
        "day": day.isoformat(),
        "prev": None if prev is None else prev.isoformat(),
        "next": None if nxt is None else nxt.isoformat(),
        "complete": day_complete(matches),
        "matches": [match_out(m, now=now) for m in matches],
        "items": items,
    }


__all__ = [
    "HIT",
    "MISS",
    "NONE",
    "WAIT",
    "DayMatch",
    "DayRow",
    "Member",
    "day_bounds",
    "day_complete",
    "day_matches",
    "day_rows",
    "default_day",
    "game_day",
    "league_days",
    "league_evening",
    "league_members",
    "mark",
    "neighbours",
    "visible_days",
]
