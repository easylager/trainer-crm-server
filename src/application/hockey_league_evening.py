"""«Вечер» лиги друзей «Кто кого»: кто как сходил за игровой день (TASK-431).

Игровой день лиги — дата начала матча по Минску (``MINSK_TZ``), только матчи набора команд лиги
(``League.match_scope``) внутри её срока. В лиге бывает по четыре матча за вечер (Динамо и Экстралига), поэтому
всё в «Вечере» считается за день, а не за матч.

Ходы — как в таблице лиги: только на матчи, начавшиеся после вступления участника. Чужие ходы до начала матча
показываем без счёта и очков (одна сторона, как ``friends_picks``), после старта — целиком (как ``friends_moves``).
Отменённые матчи в день не входят. Ключи игроков наружу не уходят: строку называет ``public_id``.

Кепка дня (владелец 2026-11-18) заменила «Кепку позора» за последний матч:

* сравниваем средние очки за ход за игровой день (очки дня / число ходов);
* в споре только те, кто сходил хотя бы на половину матчей дня (``ceil(n/2)``);
* решается, когда все матчи дня лиги сыграны; носится до следующего сыгранного игрового дня лиги;
* хуже всех сразу несколько — кепка у каждого; все равны — кепки нет;
* разыгрывается, если в споре хотя бы ``CAP_MIN_CONTENDERS``.

Пороги — константы ниже: владелец пересмотрит их через пару недель.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_slices_sql import SCOPE_SQL
from src.ingestion.hockey_sources import MINSK_TZ

# Отметка хода по матчу дня: в плюсе, мимо, ждёт итога (матч не сыгран), без хода.
HIT, MISS, WAIT, NONE = "hit", "miss", "wait", "none"

# Кепка дня: сколько человек должно быть в споре и какая доля матчей дня нужна, чтобы в него попасть.
CAP_MIN_CONTENDERS = 3
CAP_SHARE = Fraction(1, 2)


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


# ---------- кепка дня ----------


def cap_min_moves(matches: int) -> int:
    """Сколько ходов нужно, чтобы быть в споре за кепку: половина матчей дня, с округлением вверх."""
    need = Fraction(matches) * CAP_SHARE
    return max(1, -(-need.numerator // need.denominator))


@dataclass(frozen=True)
class DayCap:
    """Кепка игрового дня. ``decided`` — день сыгран и решение принято (даже если кепки нет)."""

    holders: frozenset[int] = frozenset()
    contenders: frozenset[int] = frozenset()
    need_moves: int = 1
    decided: bool = False
    in_play: bool = False  # в споре хватило людей


def day_cap(stats: Mapping[int, tuple[int, int]], *, matches: int, complete: bool) -> DayCap:
    """Кепка дня по ``{игрок: (очки дня, сыгранные ходы)}`` (чистая функция, правило — в докстринге модуля).

    ``matches`` — матчей в дне лиги (без отменённых), ``complete`` — все они сыграны."""
    need = cap_min_moves(matches)
    contenders = frozenset(k for k, (_, moves) in stats.items() if moves >= need)
    if not complete or matches < 1:
        return DayCap(contenders=contenders, need_moves=need)
    if len(contenders) < CAP_MIN_CONTENDERS:
        return DayCap(contenders=contenders, need_moves=need, decided=True)
    average = {k: Fraction(stats[k][0], stats[k][1]) for k in contenders}
    low = min(average.values())
    holders = frozenset() if low == max(average.values()) else frozenset(k for k, v in average.items() if v == low)
    return DayCap(holders=holders, contenders=contenders, need_moves=need, decided=True, in_play=True)


def cap_of_rows(rows: list[DayRow], matches: list[DayMatch]) -> DayCap:
    stats = {r.member.player_key: (r.points, r.moves) for r in rows}
    return day_cap(stats, matches=len(matches), complete=day_complete(matches))


_WINDOW_DAYS = text(f"""
    SELECT (m.starts_at AT TIME ZONE 'Europe/Minsk')::date AS day, bool_and(m.status = 'final') AS complete
    FROM game_matches AS m
    WHERE m.status <> 'cancelled' AND m.starts_at >= :since AND m.starts_at < :until
      {SCOPE_SQL}
    GROUP BY 1
    ORDER BY 1
    """)


async def last_complete_day(session: AsyncSession, league, *, now: datetime) -> date | None:
    """Последний сыгранный игровой день лиги (не позже сегодняшнего): его кепку и носят."""
    until = min(_utc(league.ends_at), day_bounds(game_day(now))[1])
    params = {"since": _utc(league.starts_at), "until": until, **league.match_scope.params}
    done = [r.day for r in (await session.execute(_WINDOW_DAYS, params)).all() if r.complete]
    return done[-1] if done else None


async def window_caps(
    session: AsyncSession, league, *, since: datetime, until: datetime, now: datetime
) -> dict[date, DayCap]:
    """Кепки всех сыгранных дней лиги в окне (``since``–``until`` по началу матча, внутри срока лиги)."""
    since, until = _window(league, since, until)
    if since >= until:
        return {}
    params = {"since": since, "until": until, **league.match_scope.params}
    by_day: dict[date, list[DayMatch]] = {}
    for r in (await session.execute(_DAY_MATCHES, params)).all():
        m = DayMatch(r.id, r.home_team, r.away_team, r.starts_at, r.status, r.home_score, r.away_score)
        by_day.setdefault(game_day(m.starts_at), []).append(m)
    done = {d: ms for d, ms in by_day.items() if day_complete(ms)}
    if not done:
        return {}
    members = await league_members(session, league.id, now=now)
    every = [m for ms in done.values() for m in ms]
    rows = await day_rows(session, league.id, members, every)
    out: dict[date, DayCap] = {}
    for d, ms in done.items():
        ids = {m.id for m in ms}
        day_rows_ = [DayRow(member=r.member, picks={k: v for k, v in r.picks.items() if k in ids}) for r in rows]
        out[d] = cap_of_rows(day_rows_, ms)
    return out


async def current_cap(session: AsyncSession, league, *, now: datetime) -> frozenset[int]:
    """Кто сейчас в кепке: кепка последнего сыгранного дня лиги (нет решения или кепки — никто)."""
    day = await last_complete_day(session, league, now=now)
    if day is None:
        return frozenset()
    caps = await window_caps(session, league, since=day_bounds(day)[0], until=day_bounds(day)[1], now=now)
    return caps[day].holders if day in caps else frozenset()


def scarf_of(row: DayRow, matches: list[DayMatch]) -> dict | None:
    """«В чужом шарфе» за день: ход против своей команды на её матч этого дня. Нет своей команды — нет шарфа."""
    club = row.member.club
    if not club:
        return None
    for m in matches:
        pick = row.picks.get(m.id)
        if pick is None or club not in (m.home, m.away):
            continue
        team = m.home if pick["side"] == "home" else m.away
        if team != club:
            return {"club": club, "picked": team}
    return None


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
        return {"day": None, "prev": None, "next": None, "complete": False, "cap": None, "matches": [], "items": []}
    matches = await day_matches(session, league, day)
    members = await league_members(session, league.id, now=now)
    rows = await day_rows(session, league.id, members, matches)
    prev, nxt = neighbours(days, day)
    cap = cap_of_rows(rows, matches)
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
                "cap": row.member.player_key in cap.holders,
                "in_cap_race": row.member.player_key in cap.contenders,
                "scarf": scarf_of(row, matches),
            }
        )
    return {
        "day": day.isoformat(),
        "prev": None if prev is None else prev.isoformat(),
        "next": None if nxt is None else nxt.isoformat(),
        "complete": day_complete(matches),
        # Кепка дня: решилась ли, разыгрывалась ли (хватило ли людей) и сколько ходов нужно, чтобы быть в споре.
        "cap": {
            "decided": cap.decided,
            "in_play": cap.in_play,
            "need_moves": cap.need_moves,
            "min_players": CAP_MIN_CONTENDERS,
        },
        "matches": [match_out(m, now=now) for m in matches],
        "items": items,
    }


__all__ = [
    "CAP_MIN_CONTENDERS",
    "CAP_SHARE",
    "DayCap",
    "cap_min_moves",
    "cap_of_rows",
    "current_cap",
    "day_cap",
    "last_complete_day",
    "scarf_of",
    "window_caps",
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
