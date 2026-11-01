"""Короны и звания «Кто кого»: закрытие срезов, финал месяца, итоги (TASK-334, PDEC-031).

Гонка — календарный месяц по Минску (общий для всех клубов). Таблицы считаются на лету
(``hockey_slices``); здесь хранится то, что не должно меняться задним числом:

- корона — (период, клуб или «все», лига или нет, игрок): первое место среза «месяц × все» и
  «месяц × клуб» после последнего матча среза; у лиги — по месяцам сезонной лиги и в конце срока.
  Порог: в срезе хотя бы 3 игрока с очками; ничья по очкам, точным и ходам — корона каждому лидеру;
  с нулём очков короны нет;
- звание сезона — «Знаток сезона 2026/27» (все) и «Знаток <клуба> 2026/27» первому месту после финала сезона.

Срез закрывается один раз (``hockey_closures``): повтор ничего не пишет. Закрытие ждёт:
1. все матчи среза сыграны или отменены (матч на ручной проверке держит срез не дольше 72 часов
   после конца периода — потом срез закрывается без него);
2. окно исправления итога: 7 суток после итога последнего матча среза (или ручное подтверждение);
3. календарь прочитан в последние три недели периода — иначе последние матчи могли быть не видны.
После закрытия поправка итога меняет очки в таблицах, но не корону.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_game import FIRST_RACE_MONTH, MONTHS, month_bounds, race_window, season_start
from src.application.hockey_matches import DINAMO
from src.application.hockey_slices import (
    SCOPE_SQL,
    KIND_MONTH as PERIOD_MONTH,
    Period,
    Scope,
    club_scope,
    crown_eligible,
    crown_leaders,
    month_period,
    season_label,
    season_period,
    slice_rows,
    with_points,
)
from src.ingestion.hockey_sources import MINSK_TZ

logger = logging.getLogger(__name__)

KIND_MONTH = "month"
POINTS_RULE = "fifa_v1"
# Итог месяца висит на главной сутки после закрытия гонки, пока его не открыли.
RESULT_WINDOW = timedelta(hours=24)
# Окно исправления итога: корона пишется, когда он прошёл (решение 2026-11-01, Q4).
CORRECTION_WINDOW = timedelta(days=7)
# Матч на ручной проверке не держит срез вечно: через 72 часа после конца периода срез закрывается без него.
GIVE_UP_AFTER = timedelta(hours=72)
# Сайт клуба показывает календарь примерно на 4 недели вперёд: прочитанный за 3 недели до конца
# периода, он видит последний матч периода. Раньше — финал не называем и срез не закрываем.
CALENDAR_COVERS_END = timedelta(days=21)
# Звания сезона — только с первого сезона игры, прошлые сезоны задним числом не выдаём.
FIRST_TITLE_SEASON = 2026
# Старый порог лиги из двух участников заменён общим порогом из трёх игроков с очками (PDEC-031).
LEAGUE_CROWN_MIN_MEMBERS = 3


@dataclass(frozen=True)
class Race:
    id: int
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


_RACE_COLUMNS = "id, kind, title, starts_at, ends_at, points_rule, calendar_synced_at, closed_at"

_INSERT_RACE = text("""
    INSERT INTO hockey_races (kind, title, starts_at, ends_at, points_rule)
    VALUES (:kind, :title, :starts_at, :ends_at, :points_rule)
    ON CONFLICT (kind, starts_at) DO NOTHING
    """)

_RACE_AT = text(f"SELECT {_RACE_COLUMNS} FROM hockey_races WHERE kind = :kind AND starts_at = :starts_at")

_RACE_BY_ID = text(f"SELECT {_RACE_COLUMNS} FROM hockey_races WHERE id = :race_id")

# Календарь прочитан: все периоды, чей конец уже в трёх неделях (или позади), этим чтением покрыты.
_SYNCED = text("""
    UPDATE hockey_races SET calendar_synced_at = :now
    WHERE ends_at - CAST(:covers AS INTERVAL) <= :now
    """)

_OPEN_RACES = text(f"""
    SELECT {_RACE_COLUMNS} FROM hockey_races
    WHERE starts_at >= :first AND starts_at < :now
    ORDER BY starts_at
    """)

_LAST_SYNC = text("SELECT MAX(calendar_synced_at) FROM hockey_races")

# Состояние всех срезов периода одним запросом: у каждого клуба и у «Все» (club IS NULL).
_SLICE_STATES = text("""
    WITH mm AS (
        SELECT m.id, m.status, m.starts_at, m.finalized_at, c.club
        FROM game_matches AS m
        CROSS JOIN LATERAL (VALUES (m.home_team), (m.away_team), (CAST(NULL AS text))) AS c(club)
        WHERE m.starts_at >= :since AND m.starts_at < :until
          AND (CAST(:mleague AS text) IS NULL OR m.league = CAST(:mleague AS text))
    )
    SELECT club,
           COUNT(*) FILTER (WHERE status IN ('scheduled', 'review')
                              AND NOT (CAST(:give_up AS boolean) AND starts_at < :now))::int AS open_n,
           COUNT(*) FILTER (WHERE status = 'final')::int AS finals,
           MAX(COALESCE(finalized_at, starts_at)) FILTER (WHERE status = 'final') AS last_final_at
    FROM mm GROUP BY club
    """)

# То же для лиги: набор команд задан Scope.
_SCOPE_STATE = text(f"""
    SELECT COUNT(*) FILTER (WHERE m.status IN ('scheduled', 'review')
                              AND NOT (CAST(:give_up AS boolean) AND m.starts_at < :now))::int AS open_n,
           COUNT(*) FILTER (WHERE m.status = 'final')::int AS finals,
           MAX(COALESCE(m.finalized_at, m.starts_at)) FILTER (WHERE m.status = 'final') AS last_final_at
    FROM game_matches AS m
    WHERE m.starts_at >= :since AND m.starts_at < :until
      {SCOPE_SQL}
    """)

_CLOSED = text("""
    SELECT kind, period_start, club, league_id FROM hockey_closures
    WHERE period_start >= :first AND kind = ANY(:kinds)
    """)

_INSERT_CLOSURE = text("""
    INSERT INTO hockey_closures (kind, period_start, club, league_id, manual, closed_at)
    VALUES (:kind, :period_start, :club, :league_id, :manual, :now)
    ON CONFLICT (kind, period_start, COALESCE(club, ''), COALESCE(league_id, 0)) DO NOTHING
    RETURNING id
    """)

_SET_CROWNED = text("UPDATE hockey_closures SET crowned = :crowned WHERE id = :id")

_INSERT_CROWN = text("""
    INSERT INTO hockey_crowns (race_id, league_id, player_key, points, exact, played,
                               club, kind, period_start, period_end)
    VALUES (:race_id, :league_id, :player_key, :points, :exact, :played, :club, :kind, :period_start, :period_end)
    ON CONFLICT (kind, period_start, COALESCE(club, ''), COALESCE(league_id, 0), player_key) DO NOTHING
    """)

_INSERT_TITLE = text("""
    INSERT INTO hockey_titles (season, club, player_key, points, exact, played)
    VALUES (:season, :club, :player_key, :points, :exact, :played)
    ON CONFLICT (season, COALESCE(club, ''), player_key) DO NOTHING
    """)

_CLOSE_RACE = text("UPDATE hockey_races SET closed_at = :now WHERE id = :race_id AND closed_at IS NULL")


def _race(record) -> Race:
    return Race(**record._mapping)


async def race_by_id(session: AsyncSession, race_id: int) -> Race | None:
    record = (await session.execute(_RACE_BY_ID, {"race_id": race_id})).one_or_none()
    return None if record is None else _race(record)


async def ensure_month_race(session: AsyncSession, *, now: datetime) -> Race | None:
    """Гонка месяца, в котором ``now``; до первой гонки — ``None``."""
    window = race_window(now)
    if not window.monthly:
        return None
    params = {
        "kind": KIND_MONTH,
        "title": window.title,
        "starts_at": window.since,
        "ends_at": window.until,
        "points_rule": POINTS_RULE,
    }
    await session.execute(_INSERT_RACE, params)
    return _race((await session.execute(_RACE_AT, params)).one())


async def ensure_races(session: AsyncSession, *, now: datetime) -> Race | None:
    """Текущая гонка и все прошлые с первой: если цикл молчал, прошлые месяцы всё равно закроются."""
    current = await ensure_month_race(session, now=now)
    if current is None:
        return None
    day = FIRST_RACE_MONTH
    here = current.starts_at.astimezone(MINSK_TZ).date()
    while day < here:
        await ensure_month_race(session, now=month_bounds(day)[0])
        day = month_bounds(day)[1].astimezone(MINSK_TZ).date()
    return current


async def mark_calendar_synced(session: AsyncSession, *, now: datetime) -> None:
    """Календарь прочитан: периоды, чей конец уже виден, получают отметку «календарь покрывает конец»."""
    await ensure_month_race(session, now=now)
    await session.execute(_SYNCED, {"now": _utc(now), "covers": CALENDAR_COVERS_END})


def _ready(state, *, now: datetime, covers: bool) -> bool:
    """Срез можно закрывать: всё сыграно, календарь покрывает конец, окно исправления итога прошло."""
    if state is None or state.open_n or not state.finals or not covers:
        return False
    return _utc(now) >= _utc(state.last_final_at) + CORRECTION_WINDOW


async def _award(
    session: AsyncSession,
    *,
    kind: str,
    race_id: int | None,
    period_start: datetime,
    period_end: datetime,
    club: str | None,
    league_id: int | None,
    rows,
    now: datetime,
    manual: bool = False,
) -> int | None:
    """Закрыть срез и записать короны. ``None`` — срез уже был закрыт (ничего не пишем)."""
    closure = (
        await session.execute(
            _INSERT_CLOSURE,
            {
                "kind": kind,
                "period_start": period_start,
                "club": club,
                "league_id": league_id,
                "manual": manual,
                "now": _utc(now),
            },
        )
    ).scalar_one_or_none()
    if closure is None:
        return None
    leaders = crown_leaders(rows)
    for r in leaders:
        await session.execute(
            _INSERT_CROWN,
            {
                "race_id": race_id,
                "league_id": league_id,
                "player_key": r.player_key,
                "points": r.points,
                "exact": r.exact,
                "played": r.played,
                "club": club,
                "kind": kind,
                "period_start": period_start,
                "period_end": period_end,
            },
        )
    await session.execute(_SET_CROWNED, {"id": closure, "crowned": len(leaders)})
    return closure


async def _closed_set(session: AsyncSession, *, kinds: list[str], first: datetime) -> set[tuple]:
    rows = (await session.execute(_CLOSED, {"first": first, "kinds": kinds})).all()
    return {(r.kind, _utc(r.period_start), r.club, r.league_id) for r in rows}


async def _close_months(session: AsyncSession, *, now: datetime, closed: list[int]) -> None:
    first, _ = month_bounds(FIRST_RACE_MONTH)
    done = await _closed_set(session, kinds=["month"], first=first)
    for record in (await session.execute(_OPEN_RACES, {"first": first, "now": _utc(now)})).all():
        race = _race(record)
        covers = race.calendar_synced_at is not None and race.calendar_synced_at >= race.ends_at - CALENDAR_COVERS_END
        give_up = _utc(now) >= race.ends_at + GIVE_UP_AFTER
        params = {"since": race.starts_at, "until": race.ends_at, "give_up": give_up, "now": _utc(now), "mleague": None}
        states = {r.club: r for r in (await session.execute(_SLICE_STATES, params)).all()}
        period = Period(PERIOD_MONTH, race.starts_at, race.ends_at, "", race.title)
        for club, state in states.items():
            if (KIND_MONTH, _utc(race.starts_at), club, None) in done or not _ready(state, now=now, covers=covers):
                continue
            rows = await slice_rows(session, scope=club_scope(club), period=period)
            closure = await _award(
                session,
                kind=KIND_MONTH,
                race_id=race.id,
                period_start=race.starts_at,
                period_end=race.ends_at,
                club=club,
                league_id=None,
                rows=rows,
                now=now,
            )
            if closure is not None:
                closed.append(closure)
                if club is None:
                    await session.execute(_CLOSE_RACE, {"race_id": race.id, "now": _utc(now)})


_ACTIVE_LEAGUES = text("""
    SELECT id, scope, clubs, term_kind, starts_at, ends_at FROM hockey_leagues
    WHERE starts_at < :now
    ORDER BY id
    """)


async def _close_leagues(session: AsyncSession, *, now: datetime, closed: list[int]) -> None:
    """Короны лиг: по месяцам сезонной лиги и в конце срока любой лиги."""
    from src.application.hockey_leagues import League, league_table_rows
    from src.application.hockey_slices import league_scope

    first, _ = month_bounds(FIRST_RACE_MONTH)
    done = await _closed_set(session, kinds=["league_month", "league_term"], first=first)
    last_sync = (await session.execute(_LAST_SYNC)).scalar_one_or_none()
    for lg in (await session.execute(_ACTIVE_LEAGUES, {"now": _utc(now)})).all():
        league = League(
            id=lg.id,
            name="",
            invite_code="",
            owner_key=0,
            scope=lg.scope,
            clubs=tuple(lg.clubs or ()),
            term_kind=lg.term_kind,
            starts_at=lg.starts_at,
            ends_at=lg.ends_at,
        )
        scope: Scope = league_scope(lg.scope, league.clubs)

        async def state_of(since: datetime, until: datetime):
            params = {
                "since": since,
                "until": until,
                "give_up": _utc(now) >= until + GIVE_UP_AFTER,
                "now": _utc(now),
                **scope.params,
            }
            return (await session.execute(_SCOPE_STATE, params)).one()

        if lg.term_kind == "season":
            day = max(FIRST_RACE_MONTH, _utc(lg.starts_at).astimezone(MINSK_TZ).date().replace(day=1))
            while True:
                since, until = month_bounds(day)
                if since >= _utc(lg.ends_at) or until > _utc(now):
                    break
                if ("league_month", since, None, lg.id) not in done:
                    covers = last_sync is not None and _utc(last_sync) >= until - CALENDAR_COVERS_END
                    state = await state_of(max(since, _utc(lg.starts_at)), until)
                    if _ready(state, now=now, covers=covers):
                        rows = await league_table_rows(session, league, period=month_period(day))
                        closure = await _award(
                            session,
                            kind="league_month",
                            race_id=(
                                await session.execute(_RACE_AT, {"kind": KIND_MONTH, "starts_at": since})
                            ).scalar_one_or_none(),
                            period_start=since,
                            period_end=until,
                            club=None,
                            league_id=lg.id,
                            rows=rows,
                            now=now,
                        )
                        if closure is not None:
                            closed.append(closure)
                day = until.astimezone(MINSK_TZ).date()
        if _utc(lg.ends_at) <= _utc(now) and ("league_term", _utc(lg.starts_at), None, lg.id) not in done:
            covers = last_sync is not None and _utc(last_sync) >= _utc(lg.ends_at) - CALENDAR_COVERS_END
            state = await state_of(_utc(lg.starts_at), _utc(lg.ends_at))
            # Лига без единого сыгранного матча в сроке закрывается без корон, не дожидаясь окна исправления.
            empty = covers and not state.open_n and not state.finals
            if empty or _ready(state, now=now, covers=covers):
                rows = await league_table_rows(session, league)
                closure = await _award(
                    session,
                    kind="league_term",
                    race_id=None,
                    period_start=_utc(lg.starts_at),
                    period_end=_utc(lg.ends_at),
                    club=None,
                    league_id=lg.id,
                    rows=rows,
                    now=now,
                )
                if closure is not None:
                    closed.append(closure)


async def _close_seasons(session: AsyncSession, *, now: datetime, closed: list[int]) -> None:
    """Звания сезона: после конца сезона и окна исправления итога последнего матча."""
    last_sync = (await session.execute(_LAST_SYNC)).scalar_one_or_none()
    for probe in (_utc(now), _utc(now) - timedelta(days=366)):
        season = season_period(probe)
        if season.until > _utc(now) or season.since.astimezone(MINSK_TZ).year < FIRST_TITLE_SEASON:
            continue
        done = await _closed_set(session, kinds=["season"], first=season.since)
        params = {
            "since": season.since,
            "until": season.until,
            "give_up": _utc(now) >= season.until + GIVE_UP_AFTER,
            "now": _utc(now),
            "mleague": None,
        }
        covers = last_sync is not None and _utc(last_sync) >= season.until - CALENDAR_COVERS_END
        for state in (await session.execute(_SLICE_STATES, params)).all():
            if ("season", season.since, state.club, None) in done or not _ready(state, now=now, covers=covers):
                continue
            closure = (
                await session.execute(
                    _INSERT_CLOSURE,
                    {
                        "kind": "season",
                        "period_start": season.since,
                        "club": state.club,
                        "league_id": None,
                        "manual": False,
                        "now": _utc(now),
                    },
                )
            ).scalar_one_or_none()
            if closure is None:
                continue
            rows = await slice_rows(session, scope=club_scope(state.club), period=season)
            leaders = crown_leaders(rows)
            for r in leaders:
                await session.execute(
                    _INSERT_TITLE,
                    {
                        "season": season_label(season.since),
                        "club": state.club,
                        "player_key": r.player_key,
                        "points": r.points,
                        "exact": r.exact,
                        "played": r.played,
                    },
                )
            await session.execute(_SET_CROWNED, {"id": closure, "crowned": len(leaders)})
            closed.append(closure)


async def close_due_races(session: AsyncSession, *, now: datetime) -> list[int]:
    """Закрыть готовые срезы: короны месяцев (все и клубы), короны лиг, звания сезона. Идемпотентно.

    Возвращает номера новых закрытий. Повторный вызов ничего не пишет.
    """
    closed: list[int] = []
    await _close_months(session, now=now, closed=closed)
    await _close_leagues(session, now=now, closed=closed)
    await _close_seasons(session, now=now, closed=closed)
    return closed


async def confirm_close_month(
    session: AsyncSession, *, period_start: datetime, club: str | None, now: datetime
) -> int | None:
    """Ручное подтверждение админа: закрыть срез месяца сразу, не дожидаясь окна исправления итога.

    ``None`` — срез уже закрыт. Матч, которого ещё нет в итогах, подтверждение не обходит: срез с
    несыгранными матчами не закрывается и вручную."""
    race = _race((await session.execute(_RACE_AT, {"kind": KIND_MONTH, "starts_at": period_start})).one())
    params = {
        "since": race.starts_at,
        "until": race.ends_at,
        "give_up": _utc(now) >= race.ends_at + GIVE_UP_AFTER,
        "now": _utc(now),
        "mleague": None,
    }
    state = next((r for r in (await session.execute(_SLICE_STATES, params)).all() if r.club == club), None)
    if state is None or state.open_n:
        raise ValueError("в срезе есть несыгранные матчи")
    period = Period(PERIOD_MONTH, race.starts_at, race.ends_at, "", race.title)
    rows = await slice_rows(session, scope=club_scope(club), period=period)
    closure = await _award(
        session,
        kind=KIND_MONTH,
        race_id=race.id,
        period_start=race.starts_at,
        period_end=race.ends_at,
        club=club,
        league_id=None,
        rows=rows,
        now=now,
        manual=True,
    )
    if closure is not None and club is None:
        await session.execute(_CLOSE_RACE, {"race_id": race.id, "now": _utc(now)})
    return closure


# ---------- финал месяца (Динамо): для строки на главной и напоминаний ----------

_LAST_MATCH = text("""
    SELECT id FROM kk_matches
    WHERE starts_at >= :since AND starts_at < :until
      AND (home_team = :club OR away_team = :club)
      AND status <> 'cancelled'
    ORDER BY starts_at DESC, id DESC
    LIMIT 1
    """)

_RACE_COUNTS = text("""
    SELECT COUNT(*) FILTER (WHERE status = 'final')::int AS played,
           COUNT(*) FILTER (WHERE status <> 'cancelled')::int AS known
    FROM kk_matches
    WHERE starts_at >= :since AND starts_at < :until AND (home_team = :club OR away_team = :club)
    """)


def _calendar_covers_end(race: Race) -> bool:
    return race.calendar_synced_at is not None and race.calendar_synced_at >= race.ends_at - CALENDAR_COVERS_END


async def race_final_match_id(session: AsyncSession, race: Race | None, *, club: str = DINAMO) -> int | None:
    """Последний матч Динамо в месяце — финал месяца. Пока календарь не видел конец месяца, финала не называем."""
    if race is None or not _calendar_covers_end(race):
        return None
    params = {"since": race.starts_at, "until": race.ends_at, "club": club}
    return (await session.execute(_LAST_MATCH, params)).scalar_one_or_none()


async def current_race(session: AsyncSession, *, now: datetime) -> Race | None:
    """Гонка текущего месяца без записи в базу (её создаёт цикл матчей)."""
    window = race_window(now)
    if not window.monthly:
        return None
    record = (
        await session.execute(_RACE_AT, {"kind": KIND_MONTH, "starts_at": window.since})
    ).one_or_none()
    return None if record is None else _race(record)


async def race_summary(session: AsyncSession, *, now: datetime, club: str = DINAMO) -> dict:
    """Шапка таблиц: какой месяц, сколько матчей Динамо сыграно из известных, какой матч — финал."""
    window = race_window(now)
    counts = (await session.execute(_RACE_COUNTS, {"since": window.since, "until": window.until, "club": club})).one()
    race = await current_race(session, now=now)
    return {
        "title": window.title,
        "monthly": window.monthly,
        "ends_at": window.until.isoformat(),
        "played": counts.played,
        "known": counts.known,
        "final_match_id": await race_final_match_id(session, race, club=club),
    }


# ---------- короны: счётчики, стена, итоги ----------

_CROWN_COUNTS = text("""
    SELECT player_key, COUNT(*)::int AS crowns FROM hockey_crowns
    WHERE (CAST(:league_id AS BIGINT) IS NULL AND league_id IS NULL) OR league_id = CAST(:league_id AS BIGINT)
    GROUP BY player_key
    """)

_WALL = text("""
    SELECT c.period_start, c.race_id, pl.display_name, c.player_key
    FROM hockey_crowns AS c
    JOIN hockey_players AS pl ON pl.player_key = c.player_key
    WHERE c.league_id = :league_id AND c.kind = 'league_month' AND c.period_start >= :first
    ORDER BY c.period_start, pl.display_name, c.player_key
    """)

_WALL_CLOSED = text("""
    SELECT period_start FROM hockey_closures
    WHERE kind = 'league_month' AND league_id = :league_id AND period_start >= :first
    """)

_FRESH_RESULT = text(f"""
    SELECT {", ".join("r." + c for c in _RACE_COLUMNS.split(", "))}
    FROM hockey_races AS r
    WHERE r.closed_at IS NOT NULL AND r.closed_at > :since_closed
      AND NOT EXISTS (SELECT 1 FROM hockey_race_seen AS s WHERE s.race_id = r.id AND s.player_key = :player_key)
      AND EXISTS (
          SELECT 1 FROM hockey_picks AS p
          JOIN game_matches AS m ON m.id = p.match_id
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
    WHERE c.race_id = :race_id AND c.kind IN ('month', 'league_month')
      AND COALESCE(c.club, '') = COALESCE(CAST(:club AS text), '')
      AND ((CAST(:league_id AS BIGINT) IS NULL AND c.league_id IS NULL) OR c.league_id = CAST(:league_id AS BIGINT))
    ORDER BY pl.display_name, c.player_key
    """)


async def crown_counts(session: AsyncSession, *, league_id: int | None) -> dict[int, int]:
    """Сколько корон у каждого: в лиге — короны этой лиги, без лиги — короны общей таблицы (одним запросом)."""
    rows = (await session.execute(_CROWN_COUNTS, {"league_id": league_id})).all()
    return {r.player_key: r.crowns for r in rows}


def _season_months(first: date, last: date) -> list[tuple[datetime, str]]:
    out: list[tuple[datetime, str]] = []
    day = max(first, FIRST_RACE_MONTH).replace(day=1)
    while day <= last:
        since, until = month_bounds(day)
        out.append((since, MONTHS[day.month - 1]))
        day = until.astimezone(MINSK_TZ).date()
    return out


async def league_crown_wall(session: AsyncSession, *, league_id: int, now: datetime) -> list[dict]:
    """Стена корон лиги: месяцы срока, у каждого — статус и чемпионы лиги."""
    lg = (
        await session.execute(
            text("SELECT starts_at, ends_at FROM hockey_leagues WHERE id = :id"), {"id": league_id}
        )
    ).one_or_none()
    if lg is None:
        return []
    first = max(month_bounds(FIRST_RACE_MONTH)[0], _utc(lg.starts_at))
    winners: dict[datetime, dict] = {}
    for r in (await session.execute(_WALL, {"league_id": league_id, "first": first})).all():
        item = winners.setdefault(_utc(r.period_start), {"race_id": r.race_id, "winners": []})
        item["winners"].append({"player_key": r.player_key, "display_name": r.display_name})
    closed = {_utc(r.period_start) for r in (await session.execute(_WALL_CLOSED, {"league_id": league_id, "first": first})).all()}
    current = race_window(now).since
    last = min(_utc(lg.ends_at), _utc(now) + timedelta(days=366)).astimezone(MINSK_TZ).date()
    wall: list[dict] = []
    for since, title in _season_months(_utc(lg.starts_at).astimezone(MINSK_TZ).date(), last):
        if since >= _utc(lg.ends_at):
            break
        known = winners.get(since)
        if since in closed:
            state = "crowned" if known else "empty"
        elif since == current:
            state = "running"
        elif since < current:
            state = "counting"
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


async def fresh_race_result(session: AsyncSession, *, player_key: int, now: datetime) -> Race | None:
    """Гонка, закрытая за последние сутки, в которой игрок набирал очки и итоги ещё не открывал."""
    params = {"player_key": player_key, "since_closed": _utc(now) - RESULT_WINDOW}
    record = (await session.execute(_FRESH_RESULT, params)).one_or_none()
    return None if record is None else _race(record)


async def mark_race_seen(session: AsyncSession, *, player_key: int, race_id: int, now: datetime) -> None:
    await session.execute(_MARK_SEEN, {"player_key": player_key, "race_id": race_id, "now": _utc(now)})


async def race_winners(
    session: AsyncSession, *, race_id: int, league_id: int | None, club: str | None = None
) -> list[dict]:
    rows = (await session.execute(_WINNERS, {"race_id": race_id, "league_id": league_id, "club": club})).all()
    return [dict(r._mapping) for r in rows]


async def leader_line(session: AsyncSession, *, player_key: int, now: datetime) -> dict | None:
    """Строка под финалом месяца — в лучшей лиге игрока: кто впереди и на сколько."""
    from src.application.hockey_leagues import league_table, player_leagues

    leagues = [x for x in await player_leagues(session, player_key=player_key, now=now) if x.members > 1 and x.active]
    if not leagues:
        return None
    best = min(leagues, key=lambda x: (x.my_rank, -x.my_points, x.id))
    rows = await league_table(session, league_id=best.id, player_key=player_key, now=now, period=month_period(
        _utc(now).astimezone(MINSK_TZ).date()))
    me = next(r for r in rows if r.player_key == player_key)
    others = [r for r in rows if r.player_key != player_key]
    if not others or not any(r.points for r in rows):
        return None
    top = max(others, key=lambda r: (r.points, r.exact))
    if me.points > top.points or (me.points == top.points and me.exact > top.exact):
        return {"league_name": best.name, "leader": None, "gap": me.points - top.points, "me_leading": True}
    return {
        "league_name": best.name,
        "leader": top.display_name,
        "gap": top.points - me.points,
        "me_leading": False,
    }


async def race_result(session: AsyncSession, *, player_key: int, race: Race) -> dict:
    """Итоги месяца для игрока: лучшая лига (или общая таблица «Все · месяц»), место, подиум, чемпионы."""
    from src.application.hockey_leagues import league_table, player_leagues

    period = Period(PERIOD_MONTH, race.starts_at, race.ends_at, "", race.title)
    leagues = [x for x in await player_leagues(session, player_key=player_key, now=race.starts_at) if x.members > 1]
    league = min(leagues, key=lambda x: (x.my_rank, -x.my_points, x.id)) if leagues else None
    if league is not None:
        rows = await league_table(
            session, league_id=league.id, player_key=player_key, now=race.starts_at, period=period
        )
    else:
        rows = await slice_rows(session, scope=club_scope(None), period=period)
    winners = await race_winners(session, race_id=race.id, league_id=league.id if league else None)
    crowned = {w["player_key"] for w in winners}
    me = next((r for r in rows if r.player_key == player_key), None)
    leader_points = rows[0].points if rows else 0
    return {
        "race_id": race.id,
        "title": race.title,
        "league": None if league is None else {"id": league.id, "name": league.name},
        "won": player_key in crowned,
        "rank": None if me is None else me.rank,
        "points": 0 if me is None else me.points,
        "gap": None if me is None else leader_points - me.points,
        "winners": [w["display_name"] for w in winners],
        "podium": [
            {
                "rank": r.rank,
                "display_name": r.display_name,
                "points": r.points,
                "crown": r.player_key in crowned,
                "is_me": r.player_key == player_key,
            }
            for r in rows[:3]
        ],
    }


_LEAGUE_NAME = text("SELECT name FROM hockey_leagues WHERE id = :league_id")


async def crown_card_data(session: AsyncSession, *, race_id: int, league_id: int | None) -> dict | None:
    """Что нарисовать на карточке короны: месяц, где (лига или общая), чемпионы. Гонка не закрыта — ничего."""
    race = await race_by_id(session, race_id)
    if race is None or (league_id is None and race.closed_at is None):
        return None
    if league_id is None:
        where = "общая таблица"
    else:
        name = (await session.execute(_LEAGUE_NAME, {"league_id": league_id})).scalar_one_or_none()
        if name is None:
            return None
        where = f"«{name}»"
    winners = await race_winners(session, race_id=race_id, league_id=league_id)
    if league_id is not None and not winners:
        return None
    return {
        "title": race.title,
        "where": where,
        "winners": [w["display_name"] for w in winners],
        "points": winners[0]["points"] if winners else 0,
    }


__all__ = [
    "CORRECTION_WINDOW",
    "GIVE_UP_AFTER",
    "KIND_MONTH",
    "LEAGUE_CROWN_MIN_MEMBERS",
    "POINTS_RULE",
    "RESULT_WINDOW",
    "Race",
    "close_due_races",
    "confirm_close_month",
    "crown_card_data",
    "crown_counts",
    "current_race",
    "ensure_month_race",
    "ensure_races",
    "fresh_race_result",
    "leader_line",
    "league_crown_wall",
    "mark_calendar_synced",
    "mark_race_seen",
    "race_by_id",
    "race_final_match_id",
    "race_result",
    "race_summary",
    "race_winners",
]
