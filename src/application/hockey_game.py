"""Игра «Кто кого»: ход на матч, закрытие на старте, очки по официальному итогу, общая таблица (TASK-297).

Ход — сторона (``home`` / ``away``) или точный счёт; счёт задаёт сторону, ничьих нет. Менять можно
до начала по расписанию; перенос матча сдвигает срок сам (время живёт в ``hockey_matches``).
Очки: точный счёт — 5, угадан победитель — 1, иначе 0. Не суммируются. Считаются одним запросом
из итога матча, поэтому повторный итог или ручная правка дают те же очки, а не двойные.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


class PicksClosed(Exception):
    """Матч начался, отменён или уже сыгран — ход не принимается."""


@dataclass(frozen=True)
class Pick:
    match_id: int
    player_key: int
    side: str
    home_score: int | None
    away_score: int | None
    points: int | None


@dataclass(frozen=True)
class Standing:
    rank: int
    player_key: int
    display_name: str
    points: int
    exact: int
    played: int


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def season_start(now: datetime) -> datetime:
    """Сезон КХЛ — с 1 августа по 31 июля, по минскому календарю."""
    local = _utc(now).astimezone(MINSK_TZ)
    year = local.year if local.month >= 8 else local.year - 1
    return datetime(year, 8, 1, tzinfo=MINSK_TZ).astimezone(timezone.utc)


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

_MATCH_OPEN = text("SELECT status, starts_at FROM hockey_matches WHERE id = :match_id")

_PICK_UPSERT = text("""
    INSERT INTO hockey_picks (match_id, player_key, side, home_score, away_score)
    VALUES (:match_id, :player_key, :side, :home_score, :away_score)
    ON CONFLICT (match_id, player_key) DO UPDATE
    SET side = EXCLUDED.side, home_score = EXCLUDED.home_score, away_score = EXCLUDED.away_score,
        points = NULL, scored_at = NULL, updated_at = now()
    RETURNING match_id, player_key, side, home_score, away_score, points
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
    FROM hockey_matches AS m
    WHERE m.id = p.match_id
      AND m.status = 'final'
      AND (p.scored_at IS NULL OR p.scored_at < m.finalized_at)
    """)

_UNSCORE_CANCELLED = text("""
    UPDATE hockey_picks AS p
    SET points = NULL, scored_at = :now
    FROM hockey_matches AS m
    WHERE m.id = p.match_id AND m.status = 'cancelled' AND p.points IS NOT NULL
    """)

_STANDINGS = text("""
    WITH totals AS (
        SELECT p.player_key,
               SUM(p.points)::int AS points,
               COUNT(*) FILTER (WHERE p.points = :exact)::int AS exact,
               COUNT(*)::int AS played
        FROM hockey_picks AS p
        JOIN hockey_matches AS m ON m.id = p.match_id
        WHERE p.points IS NOT NULL AND m.starts_at >= :season_start
        GROUP BY p.player_key
    ), ranked AS (
        SELECT t.*, pl.display_name,
               RANK() OVER (ORDER BY t.points DESC, t.exact DESC)::int AS rank
        FROM totals AS t
        JOIN hockey_players AS pl ON pl.player_key = t.player_key
    )
    SELECT rank, player_key, display_name, points, exact, played
    FROM ranked
    WHERE (CAST(:player_key AS BIGINT) IS NULL OR player_key = CAST(:player_key AS BIGINT))
    ORDER BY rank, display_name, player_key
    LIMIT :limit
    """)

_PLAYER_MATCHES = text("""
    SELECT m.id, m.home_team, m.away_team, m.starts_at, m.status,
           m.home_score, m.away_score, m.decided_in,
           p.side AS pick_side, p.home_score AS pick_home_score, p.away_score AS pick_away_score,
           p.points AS pick_points,
           (SELECT COUNT(*) FROM hockey_picks x WHERE x.match_id = m.id AND x.side = 'home')::int AS home_picks,
           (SELECT COUNT(*) FROM hockey_picks x WHERE x.match_id = m.id AND x.side = 'away')::int AS away_picks
    FROM hockey_matches AS m
    LEFT JOIN hockey_picks AS p ON p.match_id = m.id AND p.player_key = :player_key
    WHERE m.status <> 'cancelled' AND m.starts_at >= :since
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
    if match.status != "scheduled" or _utc(now) >= _utc(match.starts_at):
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
    return int(scored)


async def standings(session: AsyncSession, *, now: datetime, limit: int = 50) -> list[Standing]:
    params = {"exact": POINTS_EXACT, "season_start": season_start(now), "player_key": None, "limit": limit}
    return [Standing(**r._mapping) for r in (await session.execute(_STANDINGS, params)).all()]


async def player_standing(session: AsyncSession, player_key: int, *, now: datetime) -> Standing | None:
    params = {"exact": POINTS_EXACT, "season_start": season_start(now), "player_key": player_key, "limit": 1}
    record = (await session.execute(_STANDINGS, params)).one_or_none()
    return None if record is None else Standing(**record._mapping)


async def player_matches(
    session: AsyncSession,
    player_key: int,
    *,
    since: datetime,
    limit: int = 20,
) -> list[dict]:
    """Матчи с ходом игрока и тем, сколько людей за каждую сторону. Отменённые не показываем."""
    params = {"player_key": player_key, "since": _utc(since), "limit": limit}
    return [dict(r._mapping) for r in (await session.execute(_PLAYER_MATCHES, params)).all()]


__all__ = [
    "POINTS_DIFF",
    "POINTS_EXACT",
    "POINTS_GOALS",
    "POINTS_VALUES",
    "POINTS_WINNER",
    "pick_points",
    "Pick",
    "PicksClosed",
    "Standing",
    "make_pick",
    "normalize_pick",
    "player_matches",
    "player_standing",
    "score_finished_matches",
    "season_start",
    "standings",
]
