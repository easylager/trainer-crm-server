"""Игра «Кто кого»: ход на матч, закрытие на старте, очки по официальному итогу, общая таблица (TASK-297).

Ход — сторона (``home`` / ``away``) или точный счёт; счёт задаёт сторону, ничьих нет. Менять можно
до начала по расписанию; перенос матча сдвигает срок сам (время живёт в ``hockey_matches``).
Очки: точный счёт — 5, угадан победитель — 1, иначе 0. Не суммируются. Считаются одним запросом
из итога матча, поэтому повторный итог или ручная правка дают те же очки, а не двойные.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_slices_sql import SCOPE_SQL
from src.ingestion.hockey_sources import MINSK_TZ

# Очки как в прогнозах FIFA (владелец, 2026-10-19): каждая угаданная часть счёта — отдельно,
# точный счёт — сумма всех. Возможные итоги: 0, 10, 20, 30, 50.
POINTS_WINNER = 20
POINTS_DIFF = 10
POINTS_GOALS = 10
POINTS_EXACT = POINTS_WINNER + POINTS_DIFF + 2 * POINTS_GOALS
POINTS_VALUES = (0, 10, 20, 30, 50)
SIDE_HOME = "home"
SIDE_AWAY = "away"
MAX_GOALS = 20
DEFAULT_PLAYER_NAME = "Игрок"
# Ходы закрываются за минуту до старта по серверному времени: клиентский таймер — только подсказка.
PICK_CLOSES_BEFORE = timedelta(seconds=60)

logger = logging.getLogger(__name__)


class PicksClosed(Exception):
    """Матч начался, отменён или уже сыгран — ход не принимается."""


class DoubleUnavailable(Exception):
    """Козырь нельзя: нет хода на матч или козырь этой недели уже на начавшемся матче."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Pick:
    match_id: int
    player_key: int
    side: str
    home_score: int | None
    away_score: int | None
    points: int | None
    doubled: bool = False


@dataclass(frozen=True)
class Standing:
    rank: int
    player_key: int
    display_name: str
    points: int
    exact: int
    played: int
    correct: int = 0


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def season_start(now: datetime) -> datetime:
    """Сезон КХЛ — с 1 августа по 31 июля, по минскому календарю."""
    local = _utc(now).astimezone(MINSK_TZ)
    year = local.year if local.month >= 8 else local.year - 1
    return datetime(year, 8, 1, tzinfo=MINSK_TZ).astimezone(timezone.utc)


# Гонка месяца (PDEC-027, TASK-334): таблицы считают календарный месяц по Минску, 1-го все с нуля.
# До первой гонки таблицы живут по-старому — сезоном до её начала.
FIRST_RACE_MONTH = date(2026, 11, 1)
MONTHS = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


@dataclass(frozen=True)
class RaceWindow:
    """Окно таблиц: матчи с ``since`` (включительно) до ``until`` (не включая) по времени начала."""

    since: datetime
    until: datetime
    title: str
    monthly: bool


def month_bounds(day: date) -> tuple[datetime, datetime]:
    """Начало месяца и начало следующего — минская полночь, в UTC."""
    start = datetime(day.year, day.month, 1, tzinfo=MINSK_TZ)
    nxt = datetime(day.year + (day.month == 12), day.month % 12 + 1, 1, tzinfo=MINSK_TZ)
    return start.astimezone(timezone.utc), nxt.astimezone(timezone.utc)


def race_window(now: datetime) -> RaceWindow:
    local = _utc(now).astimezone(MINSK_TZ).date()
    if local.replace(day=1) >= FIRST_RACE_MONTH:
        since, until = month_bounds(local)
        return RaceWindow(since=since, until=until, title=MONTHS[local.month - 1], monthly=True)
    first, _ = month_bounds(FIRST_RACE_MONTH)
    return RaceWindow(since=season_start(now), until=first, title="сезон", monthly=False)


def normalize_pick(
    side: str | None, home_score: int | None, away_score: int | None
) -> tuple[str, int | None, int | None]:
    """Привести ход к виду для записи. ``ValueError`` — с текстом для человека."""
    if (home_score is None) != (away_score is None):
        raise ValueError("Счёт — это два числа")
    if home_score is not None and away_score is not None:
        if not (0 <= home_score <= MAX_GOALS and 0 <= away_score <= MAX_GOALS):
            raise ValueError(f"Счёт от 0 до {MAX_GOALS}")
        if home_score == away_score:
            raise ValueError("В хоккее ничьих нет")
        derived = SIDE_HOME if home_score > away_score else SIDE_AWAY
        if side is not None and side != derived:
            raise ValueError("Счёт и победитель не совпадают")
        return derived, home_score, away_score
    if side not in (SIDE_HOME, SIDE_AWAY):
        raise ValueError("Выберите команду")
    return side, None, None


_PLAYER_UPSERT = text("""
    INSERT INTO hockey_players (player_key, display_name)
    VALUES (:player_key, :display_name)
    ON CONFLICT (player_key) DO UPDATE
    SET display_name = EXCLUDED.display_name, updated_at = now()
    WHERE hockey_players.display_name IS DISTINCT FROM EXCLUDED.display_name
    """)

# FOR SHARE: перенос матча (UPDATE) и ход не обгоняют друг друга — срок читается по уже записанному времени.
_MATCH_OPEN = text("SELECT status, starts_at FROM game_matches WHERE id = :match_id FOR SHARE")

_PICK_UPSERT = text("""
    INSERT INTO hockey_picks (match_id, player_key, side, home_score, away_score)
    VALUES (:match_id, :player_key, :side, :home_score, :away_score)
    ON CONFLICT (match_id, player_key) DO UPDATE
    SET side = EXCLUDED.side, home_score = EXCLUDED.home_score, away_score = EXCLUDED.away_score,
        points = NULL, scored_at = NULL, updated_at = now(), picked_at = now()
    RETURNING match_id, player_key, side, home_score, away_score, points, doubled
    """)

# Пересчёт из итога: только где итога ещё не считали или итог поправили позже подсчёта.
_SCORE_FINALS = text("""
    UPDATE hockey_picks AS p
    SET points =
            CASE WHEN p.side = CASE WHEN m.home_score > m.away_score THEN 'home' ELSE 'away' END
                 THEN :winner ELSE 0 END
            + CASE WHEN p.home_score IS NULL THEN 0 ELSE
                  CASE WHEN p.home_score - p.away_score = m.home_score - m.away_score THEN :diff ELSE 0 END
                + CASE WHEN p.home_score = m.home_score THEN :goals ELSE 0 END
                + CASE WHEN p.away_score = m.away_score THEN :goals ELSE 0 END
              END,
        scored_at = :now
    FROM game_matches AS m
    WHERE m.id = p.match_id
      AND m.status = 'final'
      AND (p.scored_at IS NULL OR p.scored_at < m.finalized_at)
    """)

_UNSCORE_CANCELLED = text("""
    UPDATE hockey_picks AS p
    SET points = NULL, scored_at = :now
    FROM game_matches AS m
    WHERE m.id = p.match_id AND m.status = 'cancelled' AND p.points IS NOT NULL
    """)

# Отмена (в том числе техническое поражение) возвращает козырь игроку: флаг снимается вместе с очками.
_RELEASE_CANCELLED_TRUMPS = text("""
    UPDATE hockey_picks AS p
    SET doubled = false, trump_week = NULL, updated_at = :now
    FROM game_matches AS m
    WHERE m.id = p.match_id AND m.status = 'cancelled' AND p.doubled
    """)

_PLAYER_MATCHES = text(f"""
    SELECT m.id, m.home_team, m.away_team, m.starts_at, m.status, m.league,
           m.home_score, m.away_score, m.decided_in,
           m.live_home_score, m.live_away_score, m.live_at,
           (SELECT hm.previous_starts_at FROM hockey_matches AS hm WHERE hm.id = m.id) AS previous_starts_at,
           p.side AS pick_side, p.home_score AS pick_home_score, p.away_score AS pick_away_score,
           p.points AS pick_points, COALESCE(p.doubled, false) AS pick_doubled,
           (SELECT COUNT(*) FROM hockey_picks x WHERE x.match_id = m.id AND x.side = 'home')::int AS home_picks,
           (SELECT COUNT(*) FROM hockey_picks x WHERE x.match_id = m.id AND x.side = 'away')::int AS away_picks
    FROM game_matches AS m
    LEFT JOIN hockey_picks AS p ON p.match_id = m.id AND p.player_key = :player_key
    WHERE m.status <> 'cancelled' AND m.starts_at >= :since
      {SCOPE_SQL}
    ORDER BY m.starts_at
    LIMIT :limit
    """)


async def make_pick(
    session: AsyncSession,
    *,
    player_key: int,
    display_name: str,
    match_id: int,
    side: str | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
    now: datetime,
) -> Pick:
    """Записать или заменить ход игрока. Срок проверяется здесь, на сервере, а не в интерфейсе."""
    side, home_score, away_score = normalize_pick(side, home_score, away_score)
    match = (await session.execute(_MATCH_OPEN, {"match_id": match_id})).one_or_none()
    if match is None:
        raise LookupError(match_id)
    if not pick_open(match.status, match.starts_at, now):
        raise PicksClosed(match_id)
    name = (display_name or "").strip()[:40] or DEFAULT_PLAYER_NAME
    await session.execute(_PLAYER_UPSERT, {"player_key": player_key, "display_name": name})
    row = (
        await session.execute(
            _PICK_UPSERT,
            {
                "match_id": match_id,
                "player_key": player_key,
                "side": side,
                "home_score": home_score,
                "away_score": away_score,
            },
        )
    ).one()
    return Pick(**row._mapping)


def pick_open(status: str, starts_at: datetime, now: datetime) -> bool:
    """Ход принимается только на несыгранный матч и не позже, чем за минуту до старта."""
    return status == "scheduled" and _utc(now) < _utc(starts_at) - PICK_CLOSES_BEFORE


def pick_points(
    *, side: str, home_score: int | None, away_score: int | None, result_home: int, result_away: int
) -> int:
    """Очки хода — те же правила, что в SQL _SCORE_FINALS (для тестов и объяснений).

    Победитель — 20; при счёте ещё разница шайб — 10, шайбы хозяев — 10, шайбы гостей — 10.
    Шайбы засчитываются и при неугаданном победителе: угадавший часть не уходит с нулём.
    """
    winner = SIDE_HOME if result_home > result_away else SIDE_AWAY
    points = POINTS_WINNER if side == winner else 0
    if home_score is None or away_score is None:
        return points
    if home_score - away_score == result_home - result_away:
        points += POINTS_DIFF
    if home_score == result_home:
        points += POINTS_GOALS
    if away_score == result_away:
        points += POINTS_GOALS
    return points


async def score_finished_matches(session: AsyncSession, *, now: datetime) -> int:
    """Начислить очки по всем сыгранным матчам, где их ещё нет или итог поправили. Сколько ходов задето."""
    params = {"winner": POINTS_WINNER, "diff": POINTS_DIFF, "goals": POINTS_GOALS, "now": _utc(now)}
    result = await session.execute(_SCORE_FINALS, params)
    scored = getattr(result, "rowcount", 0) or 0
    await session.execute(_UNSCORE_CANCELLED, {"now": _utc(now)})
    await session.execute(_RELEASE_CANCELLED_TRUMPS, {"now": _utc(now)})
    return int(scored)


# Козырь недели ×2 (PDEC-031): один на игрока и неделю пн-вс по Минску, ставится на матч с ходом до его
# начала. Со стартом матча закреплён. Отмена возвращает козырь; перенос оставляет на матче (realign_trumps).
_WEEK_TRUMPS = text("""
    SELECT p.match_id, m.status, m.starts_at
    FROM hockey_picks AS p
    JOIN game_matches AS m ON m.id = p.match_id
    WHERE p.player_key = :player_key AND p.trump_week = :week
    FOR UPDATE OF p
    """)

_SET_TRUMP = text("""
    UPDATE hockey_picks SET doubled = :on, trump_week = :week, updated_at = now()
    WHERE player_key = :player_key AND match_id = :match_id
    RETURNING match_id
    """)


def _trump_started(status: str, starts_at: datetime, now: datetime) -> bool:
    return status != "scheduled" or _utc(now) >= _utc(starts_at)


async def set_double(session: AsyncSession, *, player_key: int, match_id: int, on: bool, now: datetime) -> int | None:
    """Поставить или снять козырь. Возвращает матч недели, на котором козырь стоит после вызова (или ``None``)."""
    from src.application.hockey_slices import week_start

    match = (await session.execute(_MATCH_OPEN, {"match_id": match_id})).one_or_none()
    if match is None:
        raise LookupError(match_id)
    if _trump_started(match.status, match.starts_at, now):
        raise PicksClosed(match_id)
    week = week_start(match.starts_at)
    current = [
        r
        for r in (await session.execute(_WEEK_TRUMPS, {"player_key": player_key, "week": week})).all()
        # Козырь на отменённом матче уже свободен (цикл мог ещё не снять флаг).
        if r.status != "cancelled"
    ]
    if not on:
        if any(r.match_id == match_id for r in current):
            await session.execute(
                _SET_TRUMP, {"player_key": player_key, "match_id": match_id, "on": False, "week": None}
            )
            return None
        return next((r.match_id for r in current), None)
    for r in current:
        if r.match_id == match_id:
            return match_id
        if _trump_started(r.status, r.starts_at, now):
            raise DoubleUnavailable("used")
    for r in current:
        await session.execute(_SET_TRUMP, {"player_key": player_key, "match_id": r.match_id, "on": False, "week": None})
    try:
        async with session.begin_nested():
            moved = (
                await session.execute(
                    _SET_TRUMP, {"player_key": player_key, "match_id": match_id, "on": True, "week": week}
                )
            ).one_or_none()
    except IntegrityError:
        # Две вкладки одновременно: уникальный индекс (игрок, неделя) пропустил только одну.
        raise DoubleUnavailable("used") from None
    if moved is None:
        raise DoubleUnavailable("no_pick")
    return match_id


_MY_DOUBLES = text("""
    SELECT p.trump_week AS week, p.match_id, m.status, m.starts_at
    FROM hockey_picks AS p
    JOIN game_matches AS m ON m.id = p.match_id
    WHERE p.player_key = :player_key AND p.trump_week = ANY(:weeks) AND m.status <> 'cancelled'
    ORDER BY p.trump_week
    """)


async def my_doubles(session: AsyncSession, *, player_key: int, now: datetime, weeks_ahead: int = 1) -> list[dict]:
    """Козыри игрока на текущую и следующие недели: на каком матче и закреплён ли (матч начался)."""
    from src.application.hockey_slices import week_start

    first = week_start(now)
    weeks = [first + timedelta(days=7 * i) for i in range(weeks_ahead + 1)]
    placed = {r.week: r for r in (await session.execute(_MY_DOUBLES, {"player_key": player_key, "weeks": weeks})).all()}
    out = []
    for week in weeks:
        row = placed.get(week)
        out.append(
            {
                "week_start": week.isoformat(),
                "match_id": None if row is None else row.match_id,
                "locked": False if row is None else _trump_started(row.status, row.starts_at, now),
            }
        )
    return out


async def my_double(session: AsyncSession, *, player_key: int, now: datetime) -> dict | None:
    """Козырь игрока в текущей неделе: на каком матче и закреплён ли он (матч начался)."""
    current = (await my_doubles(session, player_key=player_key, now=now, weeks_ahead=0))[0]
    return {"match_id": current["match_id"], "locked": current["locked"], "week_start": current["week_start"]}


_PICKS_AFTER_CLOSE = text("""
    DELETE FROM hockey_picks
    WHERE match_id = :match_id AND picked_at >= :closes_at
    RETURNING player_key
    """)

_MATCH_TRUMPS = text("""
    SELECT player_key, trump_week FROM hockey_picks WHERE match_id = :match_id AND doubled FOR UPDATE
    """)

_WEEK_TAKEN = text("""
    SELECT 1 FROM hockey_picks WHERE player_key = :player_key AND trump_week = :week AND match_id <> :match_id
    """)


async def on_match_moved(session: AsyncSession, *, match_id: int, starts_at: datetime) -> dict[str, list[int]]:
    """Матч перенесён на ``starts_at``: ходы, сделанные уже после нового срока закрытия, аннулируются
    (игроков вернуть, чтобы сообщить «матч перенесён, ход не принят»); козырь следует за матчем в новую
    неделю, а если там у игрока уже стоит козырь — возвращается ему. Возвращает ``voided`` и ``released``."""
    from src.application.hockey_slices import week_start

    voided = [
        r.player_key
        for r in (
            await session.execute(
                _PICKS_AFTER_CLOSE, {"match_id": match_id, "closes_at": _utc(starts_at) - PICK_CLOSES_BEFORE}
            )
        ).all()
    ]
    week = week_start(starts_at)
    released: list[int] = []
    for r in (await session.execute(_MATCH_TRUMPS, {"match_id": match_id})).all():
        if r.trump_week == week:
            continue
        busy = (
            await session.execute(_WEEK_TAKEN, {"player_key": r.player_key, "week": week, "match_id": match_id})
        ).first()
        target = None if busy else week
        await session.execute(
            _SET_TRUMP,
            {"player_key": r.player_key, "match_id": match_id, "on": target is not None, "week": target},
        )
        if busy:
            released.append(r.player_key)
    if voided or released:
        logger.info("hockey match %s moved: voided=%s released=%s", match_id, voided, released)
    return {"voided": voided, "released": released}


# ---------- живой счёт ----------

_SET_LIVE = text("""
    UPDATE hockey_matches
    SET live_home_score = :home, live_away_score = :away, live_at = :now
    WHERE id = :match_id AND status IN ('scheduled', 'review')
    """)


async def set_live_score(session: AsyncSession, *, match_id: int, home: int, away: int, now: datetime) -> bool:
    """Текущий счёт идущего матча (опрос раз в 15 минут в день матча). Итог и его сверку не трогает."""
    result = await session.execute(_SET_LIVE, {"match_id": match_id, "home": home, "away": away, "now": _utc(now)})
    return bool(getattr(result, "rowcount", 0))


def live_points(
    *, side: str, home_score: int | None, away_score: int | None, live_home: int, live_away: int, doubled: bool
) -> int | None:
    """Очки, если матч закончится так, как сейчас. При равном счёте победитель неизвестен — ``None``."""
    if live_home == live_away:
        return None
    return pick_points(
        side=side, home_score=home_score, away_score=away_score, result_home=live_home, result_away=live_away
    ) * (2 if doubled else 1)


def _scope(club: str | None, league: str | None):
    from src.application.hockey_slices import Scope

    return Scope(clubs=(club,) if club else None, league=league)


async def standings(
    session: AsyncSession, *, now: datetime, limit: int = 50, club: str | None = None, period: str | None = None
) -> list[Standing]:
    """Таблица среза «клуб × период». По умолчанию — «Все · Сезон»."""
    from src.application.hockey_slices import parse_period, slice_rows

    rows = await slice_rows(session, scope=_scope(club, None), period=parse_period(period, now))
    return [Standing(**r.__dict__) for r in rows[:limit]]


async def player_standing(
    session: AsyncSession, player_key: int, *, now: datetime, club: str | None = None, period: str | None = None
) -> Standing | None:
    from src.application.hockey_slices import parse_period, slice_rows

    rows = await slice_rows(session, scope=_scope(club, None), period=parse_period(period, now))
    mine = next((r for r in rows if r.player_key == player_key), None)
    return None if mine is None else Standing(**mine.__dict__)


async def player_matches(
    session: AsyncSession,
    player_key: int,
    *,
    since: datetime,
    limit: int = 20,
    club: str | None = None,
    league: str | None = None,
) -> list[dict]:
    """Матчи с ходом игрока и тем, сколько людей за каждую сторону. Отменённые не показываем.

    ``club`` — только матчи клуба (дома и в гостях), ``league`` — ``khl`` (Динамо) или ``extraliga``.
    """
    params = {"player_key": player_key, "since": _utc(since), "limit": limit, **_scope(club, league).params}
    return [dict(r._mapping) for r in (await session.execute(_PLAYER_MATCHES, params)).all()]


__all__ = [
    "FIRST_RACE_MONTH",
    "MONTHS",
    "PICK_CLOSES_BEFORE",
    "POINTS_DIFF",
    "POINTS_EXACT",
    "POINTS_GOALS",
    "POINTS_VALUES",
    "POINTS_WINNER",
    "pick_points",
    "Pick",
    "DoubleUnavailable",
    "PicksClosed",
    "RaceWindow",
    "Standing",
    "live_points",
    "make_pick",
    "my_double",
    "my_doubles",
    "month_bounds",
    "normalize_pick",
    "on_match_moved",
    "pick_open",
    "player_matches",
    "player_standing",
    "race_window",
    "score_finished_matches",
    "season_start",
    "set_double",
    "set_live_score",
    "standings",
]
