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

Капитан вечера (TASK-432, владелец 2026-11-19) — больше всех очков за вечер среди тех же, кто в споре за кепку,
кроме тех, кто в кепке: награда за то, что ходил на все матчи и угадывал. Ничья по сумме — капитанов несколько;
у всех поровну — капитана нет. Право капитана — в ``hockey_league_captain``.

Пороги — константы ниже: владелец пересмотрит их через пару недель.

Жесты: «Стук клюшкой» и «2 минуты» (2 минуты штрафа). Один жест от человека человеку за игровой день в лиге,
можно сменить или снять; только когда день лиги сыгран, себе нельзя, оба — участники. Пушей за жесты нет —
их видно в лиге: в строке вечера и в таблице месяца («4 мин штрафа · 3 кепки»).
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

GESTURE_STICK, GESTURE_PEN = "stick", "pen"
GESTURES = (GESTURE_STICK, GESTURE_PEN)
PENALTY_MINUTES = 2  # «2 минуты» — столько минут штрафа


class GestureRefused(ValueError):
    """Жест нельзя: себе, не участнику, неизвестный (текст — для человека)."""


class DayNotPlayed(Exception):
    """День лиги ещё не сыгран (или это не день лиги): жесты — только после последнего матча дня."""


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
    captains: frozenset[int] = frozenset()  # капитан вечера (TASK-432): больше всех очков за вечер
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
    # Капитан — по сумме: награда за то, что ходил и угадывал. В кепке капитаном не бывают; все равны — капитана нет.
    totals = {k: stats[k][0] for k in contenders - holders}
    captains: frozenset[int] = frozenset()
    if holders or len(set(totals.values())) > 1:
        best = max(totals.values())
        captains = frozenset(k for k, v in totals.items() if v == best)
    return DayCap(
        holders=holders, contenders=contenders, captains=captains, need_moves=need, decided=True, in_play=True
    )


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


# ---------- жесты ----------

_DAY_GESTURES = text("""
    SELECT g.from_key, g.to_key, g.kind, g.skin, pl.display_name AS from_name
    FROM hockey_league_gestures AS g
    JOIN hockey_players AS pl ON pl.player_key = g.from_key
    WHERE g.league_id = :league_id AND g.day = :day
      AND g.from_key IN (SELECT player_key FROM hockey_league_members WHERE league_id = :league_id)
    ORDER BY g.created_at, g.from_key
    """)

_UPSERT_GESTURE = text("""
    INSERT INTO hockey_league_gestures (league_id, day, from_key, to_key, kind)
    VALUES (:league_id, :day, :from_key, :to_key, :kind)
    ON CONFLICT (league_id, day, from_key, to_key) DO UPDATE SET kind = EXCLUDED.kind, updated_at = now()
    """)

_DROP_GESTURE = text("""
    DELETE FROM hockey_league_gestures
    WHERE league_id = :league_id AND day = :day AND from_key = :from_key AND to_key = :to_key
    """)

_MEMBER_BY_PID = text("""
    SELECT pl.player_key FROM hockey_league_members AS mb
    JOIN hockey_players AS pl ON pl.player_key = mb.player_key
    WHERE mb.league_id = :league_id AND pl.public_id = :pid
    """)

# Полученные жесты за дни окна: только от тех, кто ещё в лиге (ушёл — его жесты в лиге не видны).
_PERIOD_GESTURES = text("""
    SELECT g.to_key, g.kind, COUNT(*)::int AS n
    FROM hockey_league_gestures AS g
    WHERE g.league_id = :league_id AND g.day >= :first AND g.day <= :last
      AND g.from_key IN (SELECT player_key FROM hockey_league_members WHERE league_id = :league_id)
    GROUP BY g.to_key, g.kind
    """)


def gestures_enabled() -> bool:
    """Жесты вечера включены настройкой ``KK_GESTURES_ENABLED`` (по умолчанию выключены)."""
    from src.shared.config import Settings

    return bool(Settings().kk_gestures_enabled)  # type: ignore[call-arg]


async def day_gestures(session: AsyncSession, league_id: int, day: date) -> list[dict]:
    rows = await session.execute(_DAY_GESTURES, {"league_id": league_id, "day": day})
    return [dict(r._mapping) for r in rows.all()]


async def set_gesture(
    session: AsyncSession, *, league, from_key: int, to_pid: str, day: date, kind: str | None, now: datetime
) -> str | None:
    """Дать, сменить (``kind``) или снять (``None``) жест участнику за игровой день. Участие ``from_key`` проверяет
    вызывающий. ``GestureRefused`` — себе, не участнику, неизвестный жест; ``DayNotPlayed`` — день не сыгран."""
    if kind is not None and kind not in GESTURES:
        raise GestureRefused("Такого жеста нет")
    to_key = (await session.execute(_MEMBER_BY_PID, {"league_id": league.id, "pid": to_pid})).scalar_one_or_none()
    if to_key is None:
        raise GestureRefused("Этого человека нет в лиге")
    if to_key == from_key:
        raise GestureRefused("Себе жест не дают")
    if game_day(now) < day or not day_complete(await day_matches(session, league, day)):
        raise DayNotPlayed(day)
    params = {"league_id": league.id, "day": day, "from_key": from_key, "to_key": to_key}
    if kind is None:
        await session.execute(_DROP_GESTURE, params)
    else:
        await session.execute(_UPSERT_GESTURE, {**params, "kind": kind})
    return kind


@dataclass(frozen=True)
class PeriodMarks:
    """Жесты и кепки участника за период: для строки таблицы месяца."""

    penalty_minutes: int = 0
    sticks: int = 0
    caps: int = 0


async def period_marks(
    session: AsyncSession, league, *, since: datetime, until: datetime, now: datetime
) -> dict[int, PeriodMarks]:
    """Минуты штрафа, стуки клюшкой и кепки дня за окно (по началу матча, внутри срока лиги)."""
    since, until = _window(league, since, until)
    if since >= until:
        return {}
    first, last = game_day(since), game_day(until - timedelta(microseconds=1))
    pens: dict[int, int] = {}
    sticks: dict[int, int] = {}
    params = {"league_id": league.id, "first": first, "last": last}
    rows = (await session.execute(_PERIOD_GESTURES, params)).all() if gestures_enabled() else []
    for r in rows:
        (pens if r.kind == GESTURE_PEN else sticks)[r.to_key] = r.n
    caps: dict[int, int] = {}
    for cap in (await window_caps(session, league, since=since, until=until, now=now)).values():
        for key in cap.holders:
            caps[key] = caps.get(key, 0) + 1
    keys = set(pens) | set(sticks) | set(caps)
    return {
        k: PeriodMarks(penalty_minutes=PENALTY_MINUTES * pens.get(k, 0), sticks=sticks.get(k, 0), caps=caps.get(k, 0))
        for k in keys
    }


# ---------- строка про кепку в вечерней сводке ----------

_DAY_FINALS = text(f"""
    SELECT m.id, m.status, m.finalized_at
    FROM game_matches AS m
    WHERE m.status <> 'cancelled' AND m.starts_at >= :since AND m.starts_at < :until
      {SCOPE_SQL}
    """)


def _player_leagues_sql():
    from src.application.hockey_leagues import _LEAGUE_COLUMNS

    cols = ", ".join(f"l.{c.strip()}" for c in _LEAGUE_COLUMNS.split(","))
    return text(f"""
        SELECT {cols} FROM hockey_leagues AS l
        JOIN hockey_league_members AS mb ON mb.league_id = l.id AND mb.player_key = :player_key
        WHERE l.starts_at <= :now AND l.ends_at > :since
        ORDER BY mb.joined_at, l.id
        """)


async def closing_match(session: AsyncSession, league, day: date) -> int | None:
    """Матч, которым день лиги закончился (последний по времени итога), — если все матчи дня сыграны."""
    since, until = _window(league, *day_bounds(day))
    if since >= until:
        return None
    params = {"since": since, "until": until, **league.match_scope.params}
    rows = (await session.execute(_DAY_FINALS, params)).all()
    if not rows or any(r.status != "final" for r in rows):
        return None
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return max(rows, key=lambda r: (_utc(r.finalized_at) if r.finalized_at else epoch, r.id)).id


@dataclass(frozen=True)
class CapNews:
    """Кепка дня решилась в лиге, и итог этого игрока закрыл день: строка в его вечерней сводке."""

    league_id: int
    league_name: str
    day: date
    holders: tuple[str, ...]  # имена, «я» — первым
    mine: bool
    captain: bool = False  # этот игрок — капитан вечера: строка «выдай экипировку» (TASK-432)
    # Готовое предложение капитану (выдача в один тап): pid, имя, вещь, «4 из 4», ответка ли.
    offer: dict | None = None


async def cap_news(
    session: AsyncSession, *, player_key: int, matches: list[dict], now: datetime, cache: dict
) -> list[CapNews]:
    """Лиги игрока, где кепка дня решилась матчем из этой сводки (``matches``: id, home_team, away_team,
    starts_at, league). Строки нет, если кепку не разыграли или день закрыл матч, которого в сводке нет."""
    from src.application.hockey_leagues import _league
    from src.application.hockey_slices import scope_has_match

    now = _utc(now)
    ids = {m["match_id"] for m in matches}
    params = {"player_key": player_key, "now": now, "since": now - timedelta(days=2)}
    out: list[CapNews] = []
    for record in (await session.execute(_player_leagues_sql(), params)).all():
        league = _league(record)
        days = {
            game_day(m["starts_at"])
            for m in matches
            if scope_has_match(
                league.match_scope, home=m["home_team"], away=m["away_team"], match_league=m.get("league") or "khl"
            )
        }
        for day in sorted(days):
            key = (league.id, day)
            if key not in cache:
                cache[key] = None
                closing = await closing_match(session, league, day)
                if closing is not None:
                    caps = await window_caps(
                        session, league, since=day_bounds(day)[0], until=day_bounds(day)[1], now=now
                    )
                    members = {m.player_key: m.display_name for m in await league_members(session, league.id, now=now)}
                    cap = caps.get(day)
                    if cap is not None and (cap.holders or cap.captains):
                        cache[key] = (
                            closing,
                            cap.holders,
                            members,
                            await _open_captains(session, league, day, cap, now),
                        )
            found = cache[key]
            if found is None or found[0] not in ids:
                continue
            _, holders, members, captains = found
            names = sorted(members.get(k, "") for k in holders if k != player_key)
            offer = None
            captain = player_key in captains and _captain_on(league.id)
            if captain:
                offer = await _captain_offer(session, league, day, player_key, members, now)
            if not holders and not captain:
                continue  # ни кепки, ни права капитана у этого игрока — строки нет, и кнопки «Вечер» тоже
            out.append(
                CapNews(
                    league_id=league.id,
                    league_name=league.name,
                    day=day,
                    holders=tuple((["ты"] if player_key in holders else []) + names),
                    mine=player_key in holders,
                    captain=captain,
                    offer=offer,
                )
            )
    return out


def _captain_on(league_id: int) -> bool:
    from src.application.hockey_league_captain import captain_enabled

    return captain_enabled(league_id)


async def _captain_offer(
    session: AsyncSession, league, day: date, player_key: int, members: dict[int, str], now: datetime
) -> dict | None:
    from src.application.hockey_league_captain import evening_state, suggest

    state = await evening_state(session, league, day, now=now)
    if not state.current or state.award is not None:
        return None  # вечер уже не последний или выдача уже есть — предлагать в один тап нечего
    hint = await suggest(session, league, state, player_key)
    if hint is None:
        return None
    row = next(r for r in state.rows if r.member.player_key == hint.to_key)
    return {
        "pid": row.member.pid,
        "name": members.get(hint.to_key, row.member.display_name),
        "me": hint.to_key == player_key,
        "item": hint.item,
        "hits": row.hits,
        "matches": len(state.matches),
        "revenge": hint.revenge_item is not None,
    }


async def _open_captains(session: AsyncSession, league, day: date, cap: DayCap, now: datetime) -> frozenset[int]:
    """Капитаны, у которых право выдать ещё открыто: лига идёт, и никто из капитанов вечера ещё не выдал."""
    from src.application.hockey_league_captain import day_award

    if _utc(league.ends_at) <= _utc(now):
        return frozenset()
    award = await day_award(session, league.id, day)
    if award is not None and award.captain_key in cap.captains:
        return frozenset()  # уже выдано — звать некого
    return cap.captains


def neighbours(days: list[date], day: date) -> tuple[date | None, date | None]:
    before = [d for d in days if d < day]
    after = [d for d in days if d > day]
    return (before[-1] if before else None), (after[0] if after else None)


def _sort_key(row: DayRow, me: int) -> tuple:
    return (row.member.player_key != me, -row.points, -row.moves, row.member.display_name, row.member.player_key)


async def league_evening(session: AsyncSession, *, league, player_key: int, now: datetime, day: date | None) -> dict:
    """«Вечер» лиги за день ``day`` (``None`` — по умолчанию). Участие проверяет вызывающий."""
    from src.application.hockey_league_captain import captain_enabled, evening_state, suggest

    now = _utc(now)
    today = game_day(now)
    days = visible_days(await league_days(session, league), today)
    if day not in days:  # не задан или не день лиги (чужая дата, будущий день) — вечер по умолчанию
        day = days[-1] if days else None
    if day is None:
        return {
            "day": None,
            "prev": None,
            "next": None,
            "complete": False,
            "gestures_on": gestures_enabled(),
            "captain_on": captain_enabled(league.id),
            "captain": None,
            "cap": None,
            "matches": [],
            "items": [],
        }
    matches = await day_matches(session, league, day)
    members = await league_members(session, league.id, now=now)
    rows = await day_rows(session, league.id, members, matches)
    prev, nxt = neighbours(days, day)
    cap = cap_of_rows(rows, matches)
    complete = day_complete(matches)
    gestures_on = gestures_enabled()
    gestures = await day_gestures(session, league.id, day) if gestures_on else []
    # Право капитана (TASK-432): голова каждого, капитаны вечера и выдача (только действительная).
    captain_on = captain_enabled(league.id)
    state = await evening_state(session, league, day, now=now, rows=rows, matches=matches)
    award = state.award if captain_on else None
    pids = {r.member.player_key: r.member.pid for r in rows}
    right = (
        captain_on
        and state.current
        and player_key in cap.captains
        and (award is None or award.captain_key == player_key)
    )
    hint = await suggest(session, league, state, player_key) if right else None
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
                "captain": row.member.player_key in cap.captains,
                "head": state.head(row.member.player_key, enabled=captain_on),
                "in_cap_race": row.member.player_key in cap.contenders,
                "scarf": scarf_of(row, matches),
                # Жесты этой строке: от кого и какой (``from_me`` — мой); ``my_gesture`` — что дал я. Себе — нельзя.
                "gestures": [
                    {
                        "kind": g["kind"],
                        "skin": g["skin"],
                        "from": g["from_name"],
                        "from_me": g["from_key"] == player_key,
                    }
                    for g in gestures
                    if g["to_key"] == row.member.player_key
                ],
                "my_gesture": next(
                    (
                        g["kind"]
                        for g in gestures
                        if g["from_key"] == player_key and g["to_key"] == row.member.player_key
                    ),
                    None,
                ),
                "can_gesture": gestures_on and complete and not mine,
            }
        )
    return {
        "day": day.isoformat(),
        "prev": None if prev is None else prev.isoformat(),
        "next": None if nxt is None else nxt.isoformat(),
        "complete": complete,
        "gestures_on": gestures_on,
        "captain_on": captain_on,
        # Право капитана: ``right`` — я капитан этого вечера и могу выдать или поменять; ``award`` — что выдано.
        "captain": {
            "right": right,
            # Что предложить сразу (кому и что; ``revenge`` — ответка: эту вещь получатель раньше выдавал мне).
            "suggest": None
            if hint is None
            else {"to": pids[hint.to_key], "item": hint.item, "revenge": hint.revenge_item},
            "award": None
            if award is None
            else {
                "to": pids[award.to_key],
                "item": award.item,
                "from": award.captain_name,
                "from_me": award.captain_key == player_key,
                "at": _utc(award.updated_at).isoformat(),
                "current": state.current,
            },
        },
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
    "CapNews",
    "cap_news",
    "closing_match",
    "GESTURES",
    "PENALTY_MINUTES",
    "DayNotPlayed",
    "GestureRefused",
    "PeriodMarks",
    "day_gestures",
    "gestures_enabled",
    "period_marks",
    "set_gesture",
    "CAP_MIN_CONTENDERS",
    "CAP_SHARE",
    "DayCap",
    "cap_min_moves",
    "cap_of_rows",
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
