"""Срезы «команда × период» игры «Кто кого»: таблицы, места, вершины, «Если угадаешь» (TASK-334, PDEC-031).

Одна глобальная таблица смотрится срезами. Срез = клуб (или «Все») × период (сезон или месяц по Минску).
Клубный срез — фильтр по участию клуба (дома или в гостях), поэтому матч между двумя клубами входит в
оба клубных среза, но в «Все» считается один раз: «Все» считается по матчам, а не суммой срезов.

Место: очки → точные → меньше ходов. Ходы — только оценённые (отменённые не в счёт, нулевые — в счёт).
В срезе только те, у кого есть хотя бы один оценённый ход: «ты» без ходов в срезе — ``None``, а не строка с нулём.
Козырь ×2 удваивает очки хода в суммах; «точный» — по базовым очкам хода, поэтому козырь число точных не меняет.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_cache import aggregates, personal_aggregates
from src.application.hockey_game import (
    FIRST_RACE_MONTH,
    MONTHS,
    POINTS_EXACT,
    POINTS_WINNER,
    month_bounds,
    season_start,
)
from src.application.hockey_slices_sql import SCOPE_SQL
from src.ingestion.hockey_sources import MINSK_TZ

DINAMO = "Динамо-Минск"
KIND_SEASON = "season"
KIND_MONTH = "month"
# Корона и вершина среза («все», клуб) — только там, где соревнуются хотя бы трое с очками.
CROWN_MIN_PLAYERS = 3
# Лига друзей — закрытый круг: корону разыгрывают уже двое с очками. PDEC-031 ставил лигам общий порог из
# трёх; 2026-11-11 владелец вернул лигам порог из двоих (минимума ходов за период нет).
LEAGUE_CROWN_MIN_MEMBERS = 2
PEAK_MIN_MOVES = 3
PEAKS_LIMIT = 3
# «Таблица» открывается на лучшей вершине, только если там соревнуются хотя бы десятеро с очками.
TABLE_START_MIN_PLAYERS = 10
NEIGHBORS = 2
_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")
# Годы вне этого окна — мусор из запроса: date/astimezone на краях календаря падают OverflowError (500).
MIN_YEAR, MAX_YEAR = 2020, 2100


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Period:
    kind: str  # season | month
    since: datetime  # включительно, по времени начала матча
    until: datetime  # не включая
    key: str  # "season" или "2026-11"
    title: str  # "сезон 2026/27" или "ноябрь"


def season_label(since: datetime) -> str:
    year = since.astimezone(MINSK_TZ).year
    return f"{year}/{(year + 1) % 100:02d}"


def season_period(now: datetime) -> Period:
    since = season_start(now)
    until = datetime(since.astimezone(MINSK_TZ).year + 1, 8, 1, tzinfo=MINSK_TZ).astimezone(timezone.utc)
    return Period(KIND_SEASON, since, until, KIND_SEASON, f"сезон {season_label(since)}")


def month_period(day: date) -> Period:
    since, until = month_bounds(day)
    return Period(KIND_MONTH, since, until, f"{day.year:04d}-{day.month:02d}", MONTHS[day.month - 1])


def current_month_period(now: datetime) -> Period:
    return month_period(_utc(now).astimezone(MINSK_TZ).date())


def parse_period(raw: str | None, now: datetime) -> Period:
    """``season`` (по умолчанию), ``month`` (текущий) или ``2026-11``. ``ValueError`` — неизвестное значение."""
    value = (raw or KIND_SEASON).strip().lower()
    if value == KIND_SEASON:
        return season_period(now)
    if value == KIND_MONTH:
        return current_month_period(now)
    found = _PERIOD_RE.match(value)
    if found and 1 <= int(found.group(2)) <= 12 and MIN_YEAR <= int(found.group(1)) <= MAX_YEAR:
        return month_period(date(int(found.group(1)), int(found.group(2)), 1))
    raise ValueError(f"unknown period: {raw!r}")


def week_start(starts_at: datetime) -> date:
    """Понедельник недели матча по Минску: неделя козыря — пн-вс."""
    local = _utc(starts_at).astimezone(MINSK_TZ).date()
    return date.fromordinal(local.toordinal() - local.weekday())


@dataclass(frozen=True)
class Scope:
    """Какие матчи считаются: клубы (дом или гости) и/или лига источника."""

    clubs: tuple[str, ...] | None = None
    league: str | None = None  # 'khl' | 'extraliga'

    @property
    def params(self) -> dict:
        return {"clubs": list(self.clubs) if self.clubs else None, "mleague": self.league}


ALL = Scope()


def match_clubs(home: str, away: str, league: str | None) -> tuple[str | None, ...]:
    """Срезы, в которых матч считается: клубы Экстралиги и Динамо-Минск, плюс «все» (``None``).

    Соперники Динамо по КХЛ в срез по клубу не попадают: таблиц по ним нет (как и корон, см. ``crown_clubs``).
    """
    clubs = [c for c in (home, away) if league == "extraliga" or c == DINAMO]
    return (*clubs, None)


def club_scope(club: str | None) -> Scope:
    return ALL if not club else Scope(clubs=(club,))


@dataclass(frozen=True)
class Row:
    rank: int
    player_key: int
    display_name: str
    points: int
    exact: int
    played: int
    correct: int


_ROWS = text(f"""
    WITH totals AS (
        SELECT p.player_key,
               SUM(p.points * (1 + p.doubled::int))::int AS points,
               COUNT(*) FILTER (WHERE p.points = :exact)::int AS exact,
               COUNT(*)::int AS played,
               COUNT(*) FILTER (WHERE p.points >= :winner)::int AS correct
        FROM hockey_picks AS p
        JOIN game_matches AS m ON m.id = p.match_id
        WHERE p.points IS NOT NULL AND m.status = 'final'
          AND m.starts_at >= :since AND m.starts_at < :until
          {SCOPE_SQL}
        GROUP BY p.player_key
    )
    SELECT RANK() OVER (ORDER BY t.points DESC, t.exact DESC, t.played ASC)::int AS rank,
           t.player_key, pl.display_name, t.points, t.exact, t.played, t.correct
    FROM totals AS t
    JOIN hockey_players AS pl ON pl.player_key = t.player_key
    ORDER BY rank, pl.display_name, t.player_key
    """)

# Таблица лиги: участники с нулём видны сразу, очки — за матчи после вступления.
_LEAGUE_ROWS = text(f"""
    WITH members AS (
        SELECT player_key, joined_at FROM hockey_league_members WHERE league_id = :league_id
    ), totals AS (
        SELECT p.player_key,
               SUM(p.points * (1 + p.doubled::int))::int AS points,
               COUNT(*) FILTER (WHERE p.points = :exact)::int AS exact,
               COUNT(*)::int AS played,
               COUNT(*) FILTER (WHERE p.points >= :winner)::int AS correct
        FROM hockey_picks AS p
        JOIN members AS me ON me.player_key = p.player_key
        JOIN game_matches AS m ON m.id = p.match_id
        WHERE p.points IS NOT NULL AND m.status = 'final'
          AND m.starts_at >= GREATEST(:since, me.joined_at) AND m.starts_at < :until
          {SCOPE_SQL}
        GROUP BY p.player_key
    )
    SELECT RANK() OVER (ORDER BY COALESCE(t.points, 0) DESC, COALESCE(t.exact, 0) DESC,
                                 COALESCE(t.played, 0) ASC)::int AS rank,
           mb.player_key, pl.display_name,
           COALESCE(t.points, 0) AS points, COALESCE(t.exact, 0) AS exact,
           COALESCE(t.played, 0) AS played, COALESCE(t.correct, 0) AS correct
    FROM members AS mb
    JOIN hockey_players AS pl ON pl.player_key = mb.player_key
    LEFT JOIN totals AS t ON t.player_key = mb.player_key
    ORDER BY rank, pl.display_name, mb.player_key
    """)


def _base_params(period: Period, scope: Scope) -> dict:
    return {
        "since": period.since,
        "until": period.until,
        "exact": POINTS_EXACT,
        "winner": POINTS_WINNER,
        **scope.params,
    }


async def slice_rows(session: AsyncSession, *, scope: Scope, period: Period) -> list[Row]:
    """Весь срез: все игроки с оценённым ходом, по местам."""
    rows = (await session.execute(_ROWS, _base_params(period, scope))).all()
    return [Row(**r._mapping) for r in rows]


@dataclass(frozen=True)
class SliceTable:
    """Кэшируемая таблица среза: строки по местам и поиск строки игрока без прохода по всем."""

    rows: list[Row]
    by_key: dict[int, Row]


def _cacheable_scope(scope: Scope) -> bool:
    """Кэшируем только срезы известных клубов: произвольная строка ``club`` из запроса не должна плодить ключи."""
    if not scope.clubs:
        return True
    from src.application.extraliga import CLUBS
    from src.application.hockey_teams import TEAMS

    known = set(TEAMS) | {club.name for club in CLUBS.values()}
    return all(c in known for c in scope.clubs)


async def slice_table_cached(session: AsyncSession, *, scope: Scope, period: Period) -> SliceTable:
    """``slice_rows`` с коротким кэшем и single-flight: для запросов API, где допустима задержка ≤ TTL.

    Списки и словарь общие — только читать. Фоновые пересчёты (короны, уведомления) берут ``slice_rows``."""

    async def compute() -> SliceTable:
        rows = await slice_rows(session, scope=scope, period=period)
        return SliceTable(rows=rows, by_key={r.player_key: r for r in rows})

    key = ("slice", scope.clubs, scope.league, period.since, period.until)
    return await aggregates.get_or_compute(
        key, compute, weight=lambda t: len(t.rows), cacheable=_cacheable_scope(scope)
    )


async def slice_rows_cached(session: AsyncSession, *, scope: Scope, period: Period) -> list[Row]:
    return (await slice_table_cached(session, scope=scope, period=period)).rows


async def slice_row_of(session: AsyncSession, *, scope: Scope, period: Period, player_key: int) -> Row | None:
    """Строка одного игрока в срезе (место считается по всему срезу, но он берётся из кэша)."""
    return (await slice_table_cached(session, scope=scope, period=period)).by_key.get(player_key)


async def league_rows(
    session: AsyncSession, *, league_id: int, scope: Scope, since: datetime, until: datetime
) -> list[Row]:
    period = Period(KIND_MONTH, _utc(since), _utc(until), "", "")
    params = {**_base_params(period, scope), "league_id": league_id}
    return [Row(**r._mapping) for r in (await session.execute(_LEAGUE_ROWS, params)).all()]


def with_points(rows: list[Row]) -> list[Row]:
    return [r for r in rows if r.points > 0]


def crown_eligible(rows: list[Row], *, min_players: int = CROWN_MIN_PLAYERS) -> bool:
    """Корона возможна: хотя бы ``min_players`` с очками (ходящий с нулём не считается).

    Срезы «все» и «клуб» — порог по умолчанию (трое), лиги — ``LEAGUE_CROWN_MIN_MEMBERS`` (двое)."""
    return len(with_points(rows)) >= min_players


def crown_leaders(rows: list[Row], *, min_players: int = CROWN_MIN_PLAYERS) -> list[Row]:
    """Лидеры, которым положена корона: порог ``min_players``, ничья по всем критериям — всем, ноль очков — никому."""
    if not crown_eligible(rows, min_players=min_players):
        return []
    top = min(r.rank for r in rows)
    return [r for r in rows if r.rank == top and r.points > 0]


def better_than(points: int, exact: int, played: int, other: Row) -> bool:
    """``other`` стоит выше (очки, точные, меньше ходов)."""
    return (other.points, other.exact, -other.played) > (points, exact, -played)


def hypothetical_rank(rows: list[Row], player_key: int, *, add_points: int, add_exact: int, add_played: int) -> int:
    """Место игрока, если к его строке (или к нулю) добавить очки; остальные не меняются."""
    mine = next((r for r in rows if r.player_key == player_key), None)
    points = (mine.points if mine else 0) + add_points
    exact = (mine.exact if mine else 0) + add_exact
    played = (mine.played if mine else 0) + add_played
    return 1 + sum(1 for r in rows if r.player_key != player_key and better_than(points, exact, played, r))


def correct_percent(row: Row | None) -> int | None:
    if row is None or row.played == 0:
        return None
    return round(100 * row.correct / row.played)


async def crown_totals(
    session: AsyncSession, *, league_id: int | None = None, player_keys: Iterable[int] | None = None
) -> dict[int, int]:
    """Число корон у игроков одним запросом — ВСЕ их короны (месяцы, клубы, лиги).

    Значок у имени один на всё приложение: в хабе, таблице, лиге и профиле он считает одно и то же.
    ``league_id`` оставлен для совместимости вызовов и на счёт не влияет. ``player_keys`` — только эти
    игроки (те, кого экран реально показывает): без него читается вся таблица корон.
    """
    if player_keys is None:
        stmt = text("SELECT player_key, COUNT(*)::int AS crowns FROM hockey_crowns GROUP BY player_key")
        params: dict = {}
    else:
        keys = sorted(set(player_keys))
        if not keys:
            return {}
        stmt = text(
            "SELECT player_key, COUNT(*)::int AS crowns FROM hockey_crowns"
            " WHERE player_key = ANY(:keys) GROUP BY player_key"
        )
        params = {"keys": keys}
    return {r.player_key: r.crowns for r in (await session.execute(stmt, params)).all()}


def shown_keys(rows: list[Row], player_key: int | None, *, limit: int) -> set[int]:
    """Чьи строки таблицы увидит игрок: верх, он сам и соседи — для ``crown_totals(player_keys=...)``."""
    keys = {r.player_key for r in rows[:limit]}
    if player_key is not None:
        mine = next((i for i, r in enumerate(rows) if r.player_key == player_key), None)
        if mine is not None:
            keys |= {r.player_key for r in rows[max(0, mine - NEIGHBORS) : mine + NEIGHBORS + 1]}
    return keys


def _row_out(row: Row, *, me: int | None, crowns: dict[int, int]) -> dict:
    return {
        "rank": row.rank,
        "display_name": row.display_name,
        "points": row.points,
        "exact": row.exact,
        "played": row.played,
        "correct_percent": correct_percent(row),
        "crowns": crowns.get(row.player_key, 0),
        "is_me": row.player_key == me,
    }


def table_view(
    rows: list[Row],
    *,
    player_key: int | None,
    crowns: dict[int, int],
    limit: int,
    crown_possible: bool,
) -> dict:
    """Ответ таблицы среза: верх, «ты» с соседями, «до короны N». ``me`` — ``None``, если в срезе игрок не ходил."""
    mine = next((r for r in rows if r.player_key == player_key), None)
    leader_points = rows[0].points if rows else 0
    neighbors: list[dict] = []
    if mine is not None:
        at = rows.index(mine)
        neighbors = [
            _row_out(r, me=player_key, crowns=crowns) for r in rows[max(0, at - NEIGHBORS) : at + NEIGHBORS + 1]
        ]
    return {
        "items": [_row_out(r, me=player_key, crowns=crowns) for r in rows[:limit]],
        "me": None if mine is None else _row_out(mine, me=player_key, crowns=crowns),
        "neighbors": neighbors,
        "players": len(rows),
        "players_with_points": len(with_points(rows)),
        "crown_open": crown_possible and crown_eligible(rows),
        # Сколько очков до первого места (ничья по очкам — тоже корона, поэтому «до короны» без «+1»).
        "to_crown": None if mine is None else max(0, leader_points - mine.points),
    }


# ---------- «Твои вершины» ----------

_PEAKS = text("""
    WITH scored AS (
        SELECT p.player_key, p.points * (1 + p.doubled::int) AS pts,
               (p.points = :exact) AS is_exact, (p.points >= :winner) AS is_ok,
               m.home_team, m.away_team, m.league AS match_league,
               to_char(m.starts_at AT TIME ZONE 'Europe/Minsk', 'YYYY-MM') AS month_key,
               m.starts_at
        FROM hockey_picks AS p
        JOIN game_matches AS m ON m.id = p.match_id
        WHERE p.points IS NOT NULL AND m.status = 'final' AND m.starts_at >= :season_since AND m.starts_at < :season_until
    ), expanded AS (
        SELECT s.player_key, c.club, per.period, s.pts, s.is_exact, s.is_ok
        FROM scored AS s
        CROSS JOIN LATERAL (VALUES (s.home_team), (s.away_team), (CAST(NULL AS text))) AS c(club)
        CROSS JOIN LATERAL (VALUES ('season'), (s.month_key)) AS per(period)
        WHERE c.club IS NULL OR s.match_league = 'extraliga' OR c.club = :dinamo
    ), totals AS (
        SELECT club, period, player_key, SUM(pts)::int AS points,
               COUNT(*) FILTER (WHERE is_exact)::int AS exact, COUNT(*)::int AS played
        FROM expanded GROUP BY club, period, player_key
    ), ranked AS (
        SELECT t.*, RANK() OVER (PARTITION BY club, period
                                 ORDER BY points DESC, exact DESC, played ASC)::int AS rank,
               COUNT(*) FILTER (WHERE points > 0) OVER (PARTITION BY club, period)::int AS with_points,
               COUNT(*) OVER (PARTITION BY club, period)::int AS players
        FROM totals AS t
    )
    SELECT club, period, rank, points, exact, played, with_points, players
    FROM ranked WHERE player_key = :player_key
    """)


# Запрос вершин ранжирует весь сезон (все клубы × месяцы) и тяжелее любой таблицы среза: пик не должен
# превращаться в десятки одновременных таких запросов и занимать весь пул соединений. Лишние ждут здесь,
# ещё не взяв соединение.
_PEAKS_PARALLEL = 2
_peaks_gate: asyncio.Semaphore | None = None
_peaks_gate_loop: asyncio.AbstractEventLoop | None = None


def _gate() -> asyncio.Semaphore:
    global _peaks_gate, _peaks_gate_loop
    loop = asyncio.get_running_loop()
    if _peaks_gate is None or _peaks_gate_loop is not loop:
        _peaks_gate, _peaks_gate_loop = asyncio.Semaphore(_PEAKS_PARALLEL), loop
    return _peaks_gate


async def peaks(session: AsyncSession, *, player_key: int, now: datetime) -> list[dict]:
    """Три вершины игрока — лучшие из ``_ranked_slices``."""
    return [_public_peak(r) for r in (await _ranked_slices(session, player_key=player_key, now=now))[:PEAKS_LIMIT]]


async def table_start(session: AsyncSession, *, player_key: int, now: datetime) -> dict | None:
    """Срез, на котором открывается «Таблица»: лучшая вершина, где хотя бы десятеро с очками. Нет — общая таблица."""
    for r in await _ranked_slices(session, player_key=player_key, now=now):
        if r["with_points"] >= TABLE_START_MIN_PLAYERS:
            return {"club": r["club"], "period": r["period"]}
    return None


def _public_peak(r: dict) -> dict:
    return {k: v for k, v in r.items() if k != "with_points"}


async def _ranked_slices(session: AsyncSession, *, player_key: int, now: datetime) -> list[dict]:
    """Все годные срезы игрока от лучшего места, с коротким кэшем по игроку (внутри сезона от ``now`` не зависят)."""
    season = season_period(now)

    async def compute() -> list[dict]:
        async with _gate():
            return await _peaks_uncached(session, player_key=player_key, now=now)

    return await personal_aggregates.get_or_compute(
        ("peaks", player_key, season.since, season.until), compute, weight=lambda items: 1 + len(items)
    )


async def _peaks_uncached(session: AsyncSession, *, player_key: int, now: datetime) -> list[dict]:
    """Срезы от лучшего места к худшему — среди тех, где игрок играл и где есть кого обгонять.

    Срез годится, если в нём хотя бы трое с очками и у игрока не меньше трёх ходов. Сравнение —
    по доле «место / размер» (первый из 40 лучше первого из 4), при равенстве — большой срез выше.
    """
    season = season_period(now)
    params = {
        "player_key": player_key,
        "exact": POINTS_EXACT,
        "winner": POINTS_WINNER,
        "dinamo": DINAMO,
        "season_since": season.since,
        "season_until": season.until,
    }
    found = []
    for r in (await session.execute(_PEAKS, params)).all():
        if r.with_points < CROWN_MIN_PLAYERS or r.played < PEAK_MIN_MOVES:
            continue
        found.append(r)
    found.sort(key=lambda r: (r.rank / r.players, -r.players, r.club or "", r.period))
    out = []
    for r in found:
        period = season if r.period == KIND_SEASON else parse_period(r.period, now)
        out.append(
            {
                "club": r.club,
                "period": r.period,
                "period_title": period.title,
                "rank": r.rank,
                "players": r.players,
                "points": r.points,
                "exact": r.exact,
                "played": r.played,
                "with_points": r.with_points,
            }
        )
    return out


# ---------- «Если угадаешь» (в коде — stakes) ----------

_PICK_FOR_STAKES = text("""
    SELECT p.doubled, p.side, p.home_score, p.away_score, m.home_team, m.away_team, m.starts_at, m.status, m.league
    FROM game_matches AS m
    LEFT JOIN hockey_picks AS p ON p.match_id = m.id AND p.player_key = :player_key
    WHERE m.id = :match_id
    """)

_PLAYER_LEAGUES = text("""
    SELECT l.id, l.name, l.scope, l.clubs, l.starts_at, l.ends_at, mb.joined_at
    FROM hockey_leagues AS l
    JOIN hockey_league_members AS mb ON mb.league_id = l.id AND mb.player_key = :player_key
    """)

STAKES_LIMIT = 3


def league_scope(scope: str, clubs: list[str] | tuple[str, ...]) -> Scope:
    if scope == "all":
        return ALL
    if scope == "extraliga":
        return Scope(league="extraliga")
    if scope == "dinamo":
        return Scope(clubs=(DINAMO,))
    return Scope(clubs=tuple(clubs))


def scope_has_match(scope: Scope, *, home: str, away: str, match_league: str) -> bool:
    if scope.league is not None and scope.league != match_league:
        return False
    return scope.clubs is None or home in scope.clubs or away in scope.clubs


async def stakes(session: AsyncSession, *, player_key: int, match_id: int, now: datetime) -> dict | None:
    """Что даст угаданный победитель: места в срезах матча и в лигах игрока «сейчас → если угадаешь».

    Оценка по текущим таблицам: чужие ходы на матчи, которые ещё не сыграны, неизвестны, поэтому места
    называются условно («сейчас 3-й, если угадаешь — 1-й»), а не как обещание. Срезы меньше трёх игроков
    с очками не показываются: корона и «вершина» там невозможны.
    """
    match = (await session.execute(_PICK_FOR_STAKES, {"player_key": player_key, "match_id": match_id})).one_or_none()
    if match is None:
        return None
    mult = 2 if match.doubled else 1
    add = POINTS_WINNER * mult
    if match.status != "scheduled":
        # Сыгранный (или отменённый) матч уже в таблицах: очки победителя второй раз не добавляем.
        return {"match_id": match_id, "points_if_winner": add, "doubled": bool(match.doubled), "items": []}
    month = month_period(_utc(match.starts_at).astimezone(MINSK_TZ).date())
    season = season_period(match.starts_at)
    out: list[dict] = []
    for club in match_clubs(match.home_team, match.away_team, match.league):
        for period in (month, season):
            rows = await slice_rows_cached(session, scope=club_scope(club), period=period)
            if not crown_eligible(rows):
                continue
            now_rank = next((r.rank for r in rows if r.player_key == player_key), None)
            if_rank = hypothetical_rank(rows, player_key, add_points=add, add_exact=0, add_played=1)
            out.append(
                {
                    "kind": "slice",
                    "club": club,
                    "period": period.key,
                    "period_title": period.title,
                    "rank_now": now_rank,
                    "rank_if": if_rank,
                    "players": len(rows),
                    "crown": period.kind == KIND_MONTH and if_rank == 1,
                }
            )
    for lg in (await session.execute(_PLAYER_LEAGUES, {"player_key": player_key})).all():
        scope = league_scope(lg.scope, lg.clubs)
        if not scope_has_match(scope, home=match.home_team, away=match.away_team, match_league=match.league):
            continue
        if not (_utc(lg.starts_at) <= _utc(match.starts_at) < _utc(lg.ends_at)) or _utc(match.starts_at) < _utc(
            lg.joined_at
        ):
            continue
        rows = await league_rows(session, league_id=lg.id, scope=scope, since=lg.starts_at, until=lg.ends_at)
        if len(rows) < 2:
            continue
        now_rank = next((r.rank for r in rows if r.player_key == player_key), None)
        if_rank = hypothetical_rank(rows, player_key, add_points=add, add_exact=0, add_played=1)
        out.append(
            {
                "kind": "league",
                "league_id": lg.id,
                "league_name": lg.name,
                "rank_now": now_rank,
                "rank_if": if_rank,
                "players": len(rows),
                "crown": if_rank == 1 and crown_eligible(rows, min_players=LEAGUE_CROWN_MIN_MEMBERS),
            }
        )
    # Показываем только срезы, где угаданный победитель что-то меняет; сильнее всего — выше.
    changed = [x for x in out if x["rank_now"] is None or x["rank_if"] < x["rank_now"]]
    changed.sort(key=lambda x: (x["rank_if"], x["kind"], x["players"] * -1))
    return {
        "match_id": match_id,
        "points_if_winner": add,
        "doubled": bool(match.doubled),
        "items": changed[:STAKES_LIMIT],
    }


__all__ = [
    "ALL",
    "CROWN_MIN_PLAYERS",
    "DINAMO",
    "FIRST_RACE_MONTH",
    "KIND_MONTH",
    "MAX_YEAR",
    "MIN_YEAR",
    "KIND_SEASON",
    "LEAGUE_CROWN_MIN_MEMBERS",
    "Period",
    "Row",
    "Scope",
    "SliceTable",
    "club_scope",
    "match_clubs",
    "correct_percent",
    "crown_eligible",
    "crown_leaders",
    "crown_totals",
    "current_month_period",
    "hypothetical_rank",
    "league_rows",
    "league_scope",
    "month_period",
    "parse_period",
    "peaks",
    "season_label",
    "season_period",
    "shown_keys",
    "slice_row_of",
    "slice_rows",
    "slice_rows_cached",
    "slice_table_cached",
    "stakes",
    "table_view",
    "week_start",
    "with_points",
]
