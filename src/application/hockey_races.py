"""Гонка месяца «Кто кого»: гонки, короны, финал месяца, итоги (TASK-334, PDEC-027).

Гонка = клуб + период + правило очков. Пока клуб один (Динамо-Минск) и вид один — календарный месяц
по Минску. Таблицы гонки считаются на лету по окну дат (``hockey_game.race_window``); здесь хранится
только то, что не должно меняться задним числом: сама гонка (с правилом очков) и короны.

Корона — первое место после того, как посчитан последний матч месяца: в общей таблице и в каждой
лиге клуба, где больше одного участника. Ничья по очкам и точным — корона каждому лидеру. С нулём
очков короны нет. Пересчёт очков корону не трогает: её пишут один раз, при закрытии гонки.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_game import (
    FIRST_RACE_MONTH,
    MONTHS,
    POINTS_EXACT,
    month_bounds,
    race_window,
    season_start,
)
from src.application.hockey_matches import DINAMO
from src.ingestion.hockey_sources import MINSK_TZ

KIND_MONTH = "month"
POINTS_RULE = "fifa_v1"
# Итог месяца висит на главной сутки после закрытия гонки, пока его не открыли.
RESULT_WINDOW = timedelta(hours=24)
# Лига на одного — не соревнование: корону лиги даём, когда в ней хотя бы двое.
LEAGUE_CROWN_MIN_MEMBERS = 2
# Стена корон: регулярка КХЛ стартует в сентябре, плей-офф заканчивается в апреле.
SEASON_FIRST_MONTH = 9
SEASON_LAST_MONTH = 4


@dataclass(frozen=True)
class Race:
    id: int
    club: str
    kind: str
    title: str
    starts_at: datetime
    ends_at: datetime
    points_rule: str
    calendar_synced_at: datetime | None
    closed_at: datetime | None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


_RACE_COLUMNS = "id, club, kind, title, starts_at, ends_at, points_rule, calendar_synced_at, closed_at"

_INSERT_RACE = text("""
    INSERT INTO hockey_races (club, kind, title, starts_at, ends_at, points_rule)
    VALUES (:club, :kind, :title, :starts_at, :ends_at, :points_rule)
    ON CONFLICT (club, kind, starts_at) DO NOTHING
    """)

_RACE_AT = text(f"""
    SELECT {_RACE_COLUMNS} FROM hockey_races
    WHERE club = :club AND kind = :kind AND starts_at = :starts_at
    """)

_RACE_BY_ID = text(f"SELECT {_RACE_COLUMNS} FROM hockey_races WHERE id = :race_id")

_SYNCED = text("UPDATE hockey_races SET calendar_synced_at = :now WHERE id = :race_id")

_DUE = text(f"""
    SELECT {_RACE_COLUMNS} FROM hockey_races
    WHERE closed_at IS NULL AND ends_at <= :now
    ORDER BY starts_at
    FOR UPDATE SKIP LOCKED
    """)

# Матч гонки, у которого ещё нет итога, держит гонку открытой: и не начавшийся, и на ручной проверке.
_UNFINISHED = text("""
    SELECT 1 FROM hockey_matches
    WHERE starts_at >= :since AND starts_at < :until
      AND (home_team = :club OR away_team = :club)
      AND status IN ('scheduled', 'review')
    LIMIT 1
    """)

_GLOBAL_CROWNS = text("""
    WITH totals AS (
        SELECT p.player_key,
               SUM(p.points)::int AS points,
               COUNT(*) FILTER (WHERE p.points = :exact)::int AS exact
        FROM hockey_picks AS p
        JOIN hockey_matches AS m ON m.id = p.match_id
        WHERE p.points IS NOT NULL AND m.starts_at >= :since AND m.starts_at < :until
          AND (m.home_team = :club OR m.away_team = :club)
        GROUP BY p.player_key
    ), ranked AS (
        SELECT t.*, RANK() OVER (ORDER BY t.points DESC, t.exact DESC) AS rk FROM totals AS t
    )
    INSERT INTO hockey_crowns (race_id, league_id, player_key, points, exact)
    SELECT :race_id, NULL, player_key, points, exact FROM ranked WHERE rk = 1 AND points > 0
    ON CONFLICT (race_id, COALESCE(league_id, 0), player_key) DO NOTHING
    """)

_LEAGUE_CROWNS = text("""
    WITH leagues AS (
        SELECT l.id FROM hockey_leagues AS l
        JOIN hockey_league_members AS mb ON mb.league_id = l.id
        WHERE l.club = :club
        GROUP BY l.id
        HAVING COUNT(*) >= :min_members
    ), totals AS (
        SELECT mb.league_id, p.player_key,
               SUM(p.points)::int AS points,
               COUNT(*) FILTER (WHERE p.points = :exact)::int AS exact
        FROM hockey_league_members AS mb
        JOIN leagues AS lg ON lg.id = mb.league_id
        JOIN hockey_picks AS p ON p.player_key = mb.player_key AND p.points IS NOT NULL
        JOIN hockey_matches AS m ON m.id = p.match_id
        WHERE m.starts_at >= GREATEST(:since, mb.joined_at) AND m.starts_at < :until
          AND (m.home_team = :club OR m.away_team = :club)
        GROUP BY mb.league_id, p.player_key
    ), ranked AS (
        SELECT t.*, RANK() OVER (PARTITION BY t.league_id ORDER BY t.points DESC, t.exact DESC) AS rk
        FROM totals AS t
    )
    INSERT INTO hockey_crowns (race_id, league_id, player_key, points, exact)
    SELECT :race_id, league_id, player_key, points, exact FROM ranked WHERE rk = 1 AND points > 0
    ON CONFLICT (race_id, COALESCE(league_id, 0), player_key) DO NOTHING
    """)

_CLOSE = text("UPDATE hockey_races SET closed_at = :now WHERE id = :race_id")

_LAST_MATCH = text("""
    SELECT id FROM hockey_matches
    WHERE starts_at >= :since AND starts_at < :until
      AND (home_team = :club OR away_team = :club)
      AND status <> 'cancelled'
    ORDER BY starts_at DESC, id DESC
    LIMIT 1
    """)

_CROWN_COUNTS = text("""
    SELECT player_key, COUNT(*)::int AS crowns FROM hockey_crowns
    WHERE (CAST(:league_id AS INTEGER) IS NULL AND league_id IS NULL) OR league_id = CAST(:league_id AS INTEGER)
    GROUP BY player_key
    """)

_WALL = text("""
    SELECT r.id, r.title, r.starts_at, r.closed_at, pl.display_name, c.player_key
    FROM hockey_races AS r
    LEFT JOIN hockey_crowns AS c ON c.race_id = r.id AND c.league_id = :league_id
    LEFT JOIN hockey_players AS pl ON pl.player_key = c.player_key
    WHERE r.club = :club AND r.kind = :kind AND r.starts_at >= :season_start
    ORDER BY r.starts_at, pl.display_name, c.player_key
    """)

_FRESH_RESULT = text(f"""
    SELECT {", ".join("r." + c for c in _RACE_COLUMNS.split(", "))}
    FROM hockey_races AS r
    WHERE r.club = :club AND r.closed_at IS NOT NULL AND r.closed_at > :since_closed
      AND NOT EXISTS (SELECT 1 FROM hockey_race_seen AS s WHERE s.race_id = r.id AND s.player_key = :player_key)
      AND EXISTS (
          SELECT 1 FROM hockey_picks AS p
          JOIN hockey_matches AS m ON m.id = p.match_id
          WHERE p.player_key = :player_key AND p.points IS NOT NULL
            AND m.starts_at >= r.starts_at AND m.starts_at < r.ends_at
      )
    ORDER BY r.closed_at DESC
    LIMIT 1
    """)

_MARK_SEEN = text("""
    INSERT INTO hockey_race_seen (player_key, race_id, seen_at) VALUES (:player_key, :race_id, :now)
    ON CONFLICT (player_key, race_id) DO NOTHING
    """)

_WINNERS = text("""
    SELECT c.player_key, pl.display_name, c.points, c.exact
    FROM hockey_crowns AS c
    JOIN hockey_players AS pl ON pl.player_key = c.player_key
    WHERE c.race_id = :race_id
      AND ((CAST(:league_id AS INTEGER) IS NULL AND c.league_id IS NULL) OR c.league_id = CAST(:league_id AS INTEGER))
    ORDER BY pl.display_name, c.player_key
    """)


def _race(record) -> Race:
    return Race(**record._mapping)


async def race_by_id(session: AsyncSession, race_id: int) -> Race | None:
    record = (await session.execute(_RACE_BY_ID, {"race_id": race_id})).one_or_none()
    return None if record is None else _race(record)


async def ensure_month_race(session: AsyncSession, *, now: datetime, club: str = DINAMO) -> Race | None:
    """Гонка месяца, в котором ``now``; до первой гонки — ``None``."""
    window = race_window(now)
    if not window.monthly:
        return None
    params = {
        "club": club,
        "kind": KIND_MONTH,
        "title": window.title,
        "starts_at": window.since,
        "ends_at": window.until,
        "points_rule": POINTS_RULE,
    }
    await session.execute(_INSERT_RACE, params)
    return _race((await session.execute(_RACE_AT, params)).one())


async def ensure_races(session: AsyncSession, *, now: datetime, club: str = DINAMO) -> Race | None:
    """Текущая гонка и прошлая: если цикл молчал на стыке месяцев, прошлый месяц всё равно закроется."""
    current = await ensure_month_race(session, now=now, club=club)
    if current is not None:
        await ensure_month_race(session, now=current.starts_at - timedelta(seconds=1), club=club)
    return current


async def mark_calendar_synced(session: AsyncSession, *, now: datetime, club: str = DINAMO) -> None:
    """Календарь прочитан в этом месяце — сайт клуба показывает месяц целиком, финал месяца известен."""
    race = await ensure_month_race(session, now=now, club=club)
    if race is not None:
        await session.execute(_SYNCED, {"race_id": race.id, "now": _utc(now)})


async def close_due_races(session: AsyncSession, *, now: datetime) -> list[int]:
    """Закрыть гонки, у которых прошёл месяц и посчитан каждый матч: записать короны. Идемпотентно."""
    closed: list[int] = []
    for record in (await session.execute(_DUE, {"now": _utc(now)})).all():
        race = _race(record)
        window = {"since": race.starts_at, "until": race.ends_at, "club": race.club}
        if (await session.execute(_UNFINISHED, window)).first():
            continue
        params = {**window, "race_id": race.id, "exact": POINTS_EXACT}
        await session.execute(_GLOBAL_CROWNS, params)
        await session.execute(_LEAGUE_CROWNS, {**params, "min_members": LEAGUE_CROWN_MIN_MEMBERS})
        await session.execute(_CLOSE, {"race_id": race.id, "now": _utc(now)})
        closed.append(race.id)
    return closed


async def race_final_match_id(session: AsyncSession, race: Race | None) -> int | None:
    """Последний матч гонки — финал месяца. Пока календарь месяца не прочитан, финала не называем."""
    if race is None or race.calendar_synced_at is None:
        return None
    params = {"since": race.starts_at, "until": race.ends_at, "club": race.club}
    return (await session.execute(_LAST_MATCH, params)).scalar_one_or_none()


async def crown_counts(session: AsyncSession, *, league_id: int | None) -> dict[int, int]:
    """Сколько корон у каждого: в лиге — короны этой лиги, без лиги — короны общей таблицы."""
    rows = (await session.execute(_CROWN_COUNTS, {"league_id": league_id})).all()
    return {r.player_key: r.crowns for r in rows}


def _season_months(now: datetime) -> list[tuple[datetime, str]]:
    """Месяцы сезона с сентября (или с первой гонки) по апрель — клетки стены корон."""
    start = season_start(now).astimezone(MINSK_TZ).date()
    day = max(date(start.year, SEASON_FIRST_MONTH, 1), FIRST_RACE_MONTH)
    out: list[tuple[datetime, str]] = []
    while True:
        since, until = month_bounds(day)
        out.append((since, MONTHS[day.month - 1]))
        if day.month == SEASON_LAST_MONTH:
            return out
        day = until.astimezone(MINSK_TZ).date()


async def league_crown_wall(session: AsyncSession, *, league_id: int, now: datetime, club: str = DINAMO) -> list[dict]:
    """Стена корон лиги: месяцы сезона, у каждого — статус и чемпионы лиги."""
    params = {"league_id": league_id, "club": club, "kind": KIND_MONTH, "season_start": season_start(now)}
    by_start: dict[datetime, dict] = {}
    for r in (await session.execute(_WALL, params)).all():
        item = by_start.setdefault(
            _utc(r.starts_at), {"race_id": r.id, "closed": r.closed_at is not None, "winners": []}
        )
        if r.player_key is not None:
            item["winners"].append({"player_key": r.player_key, "display_name": r.display_name})
    current = race_window(now).since
    wall: list[dict] = []
    for since, title in _season_months(now):
        known = by_start.get(since)
        if known and known["closed"]:
            state = "crowned" if known["winners"] else "empty"
        elif since == current:
            state = "running"
        elif since < current:
            state = "counting" if known else "empty"
        else:
            state = "ahead"
        wall.append(
            {
                "title": title,
                "state": state,
                "race_id": known["race_id"] if known else None,
                "winners": known["winners"] if known else [],
            }
        )
    return wall


async def fresh_race_result(
    session: AsyncSession, *, player_key: int, now: datetime, club: str = DINAMO
) -> Race | None:
    """Гонка, закрытая за последние сутки, в которой игрок набирал очки и итоги ещё не открывал."""
    params = {"club": club, "player_key": player_key, "since_closed": _utc(now) - RESULT_WINDOW}
    record = (await session.execute(_FRESH_RESULT, params)).one_or_none()
    return None if record is None else _race(record)


async def mark_race_seen(session: AsyncSession, *, player_key: int, race_id: int, now: datetime) -> None:
    await session.execute(_MARK_SEEN, {"player_key": player_key, "race_id": race_id, "now": _utc(now)})


async def race_winners(session: AsyncSession, *, race_id: int, league_id: int | None) -> list[dict]:
    rows = (await session.execute(_WINNERS, {"race_id": race_id, "league_id": league_id})).all()
    return [dict(r._mapping) for r in rows]


__all__ = [
    "KIND_MONTH",
    "LEAGUE_CROWN_MIN_MEMBERS",
    "POINTS_RULE",
    "RESULT_WINDOW",
    "Race",
    "close_due_races",
    "crown_counts",
    "ensure_month_race",
    "ensure_races",
    "fresh_race_result",
    "league_crown_wall",
    "mark_calendar_synced",
    "mark_race_seen",
    "race_by_id",
    "race_final_match_id",
    "race_winners",
]
