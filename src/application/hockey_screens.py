"""Данные экранов игры «Кто кого», которых не хватало API срезов (TASK-334, S5).

- ``clubs_catalog`` — клубы для фильтра таблицы и новой лиги;
- ``match_movement`` — «куда сдвинулась»: место до и после итога матча в каждом срезе и лиге игрока;
- ``fan_profile`` — карточка болельщика: серия, короны, звания сезона, дуэли.

Ничего не пишет: только читает ходы, короны и звания.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.extraliga import CLUBS
from src.application.hockey_game import POINTS_EXACT, POINTS_WINNER
from src.application.hockey_slices import (
    DINAMO,
    KIND_MONTH,
    Row,
    club_scope,
    crown_eligible,
    league_rows,
    league_scope,
    month_period,
    scope_has_match,
    season_label,
    season_period,
    slice_rows,
)
from src.application.hockey_teams import team_card
from src.ingestion.hockey_sources import MINSK_TZ

MOVEMENT_LIMIT = 4
DUELS_LIMIT = 3


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ---------- клубы ----------


def clubs_catalog() -> list[dict]:
    """Динамо-Минск и клубы Экстралиги: имя — как в ходах и таблицах, остальное — карточка команды."""
    names = [DINAMO] + [club.name for club in CLUBS.values()]
    out = []
    for name in names:
        card = team_card(name)
        out.append({**card, "league": "khl" if name == DINAMO else "extraliga"})
    return out


# ---------- «Куда сдвинулась» ----------

_MATCH = text("""
    SELECT id, home_team, away_team, starts_at, status, league FROM game_matches WHERE id = :match_id
    """)

_MATCH_PICKS = text("""
    SELECT player_key, points * (1 + doubled::int) AS pts, (points = :exact) AS is_exact
    FROM hockey_picks WHERE match_id = :match_id AND points IS NOT NULL
    """)

_PLAYER_LEAGUES = text("""
    SELECT l.id, l.name, l.scope, l.clubs, l.starts_at, l.ends_at, mb.joined_at
    FROM hockey_leagues AS l
    JOIN hockey_league_members AS mb ON mb.league_id = l.id AND mb.player_key = :player_key
    """)

_LEFT_IN_SLICE = text("""
    SELECT COUNT(*)::int FROM game_matches AS m
    WHERE m.status IN ('scheduled', 'review') AND m.starts_at >= :since AND m.starts_at < :until
      AND (CAST(:club AS text) IS NULL OR m.home_team = :club OR m.away_team = :club)
    """)


def rank_without(rows: list[Row], taken: dict[int, tuple[int, int]]) -> dict[int, int]:
    """Места в срезе без одного матча: ``taken`` — игрок → (очки, точный) этого матча. Ход на матч — одно «сыграно»."""
    adjusted = []
    for r in rows:
        pts, exact = taken.get(r.player_key, (0, 0))
        played = r.played - (1 if r.player_key in taken else 0)
        if played <= 0:
            continue
        adjusted.append((r.player_key, r.points - pts, r.exact - exact, played))
    adjusted.sort(key=lambda x: (-x[1], -x[2], x[3]))
    ranks: dict[int, int] = {}
    prev, place = None, 0
    for index, (key, points, exact, played) in enumerate(adjusted, start=1):
        if (points, exact, played) != prev:
            place, prev = index, (points, exact, played)
        ranks[key] = place
    return ranks


async def match_movement(session: AsyncSession, *, player_key: int, match_id: int, now: datetime) -> dict | None:
    """Места игрока до и после итога матча: клубы матча и «все» × месяц и сезон, плюс лиги.

    ``None`` — матча нет. Пустой ``items`` — у игрока нет оценённого хода или срезы меньше трёх игроков с очками.
    """
    match = (await session.execute(_MATCH, {"match_id": match_id})).one_or_none()
    if match is None:
        return None
    picks = (await session.execute(_MATCH_PICKS, {"match_id": match_id, "exact": POINTS_EXACT})).all()
    taken = {p.player_key: (int(p.pts), 1 if p.is_exact else 0) for p in picks}
    if player_key not in taken:
        return {"match_id": match_id, "items": []}
    starts = _utc(match.starts_at)
    month = month_period(starts.astimezone(MINSK_TZ).date())
    season = season_period(starts)
    found: list[dict] = []
    for club in (match.home_team, match.away_team, None):
        for period in (month, season):
            rows = await slice_rows(session, scope=club_scope(club), period=period)
            if not crown_eligible(rows):
                continue
            after = next((r for r in rows if r.player_key == player_key), None)
            if after is None:
                continue
            before = rank_without(rows, taken).get(player_key)
            leader = rows[0].points
            item = {
                "kind": "slice",
                "club": club,
                "period": period.key,
                "period_title": period.title,
                "rank_before": before,
                "rank_after": after.rank,
                "players": len(rows),
                "crown": period.kind == KIND_MONTH and after.rank == 1,
                "to_crown": max(0, leader - after.points),
            }
            if period.kind == KIND_MONTH:
                left = await session.execute(
                    _LEFT_IN_SLICE, {"since": period.since, "until": period.until, "club": club}
                )
                item["left"] = int(left.scalar_one())
                item["ends_at"] = period.until.isoformat()
            found.append(item)
    for lg in (await session.execute(_PLAYER_LEAGUES, {"player_key": player_key})).all():
        scope = league_scope(lg.scope, lg.clubs)
        if not scope_has_match(scope, home=match.home_team, away=match.away_team, match_league=match.league):
            continue
        if not (_utc(lg.starts_at) <= starts < _utc(lg.ends_at)) or starts < _utc(lg.joined_at):
            continue
        rows = await league_rows(session, league_id=lg.id, scope=scope, since=lg.starts_at, until=lg.ends_at)
        after = next((r for r in rows if r.player_key == player_key), None)
        if len(rows) < 2 or after is None:
            continue
        found.append(
            {
                "kind": "league",
                "league_id": lg.id,
                "league_name": lg.name,
                "rank_before": _league_rank_before(rows, taken, player_key),
                "rank_after": after.rank,
                "players": len(rows),
                "crown": after.rank == 1 and crown_eligible(rows),
            }
        )
    # Сначала то, что сдвинулось сильнее; при равенстве — порядок срезов выше.
    order = {id(x): i for i, x in enumerate(found)}
    found.sort(
        key=lambda x: (
            -((x["rank_before"] - x["rank_after"]) if x["rank_before"] is not None else x["players"]),
            order[id(x)],
        )
    )
    return {"match_id": match_id, "points": taken[player_key][0], "items": found[:MOVEMENT_LIMIT]}


def _league_rank_before(rows: list[Row], taken: dict[int, tuple[int, int]], player_key: int) -> int | None:
    """Лига: участник с нулём виден и без ходов, поэтому «до» считаем по тем же участникам, а не отбрасываем их."""
    adjusted = []
    for r in rows:
        pts, exact = taken.get(r.player_key, (0, 0))
        had = r.player_key in taken
        adjusted.append((r.player_key, r.points - pts, r.exact - exact, r.played - (1 if had else 0)))
    adjusted.sort(key=lambda x: (-x[1], -x[2], x[3]))
    prev, place = None, 0
    for index, (key, points, exact, played) in enumerate(adjusted, start=1):
        if (points, exact, played) != prev:
            place, prev = index, (points, exact, played)
        if key == player_key:
            return place
    return None


# ---------- карточка болельщика ----------

_SCORED = text("""
    SELECT p.points, m.home_team, m.away_team, m.starts_at
    FROM hockey_picks AS p JOIN game_matches AS m ON m.id = p.match_id
    WHERE p.player_key = :player_key AND p.points IS NOT NULL AND m.status = 'final'
    ORDER BY m.starts_at, m.id
    """)

_CROWNS = text("""
    SELECT c.kind, c.club, c.league_id, l.name AS league_name, c.period_start, c.points
    FROM hockey_crowns AS c LEFT JOIN hockey_leagues AS l ON l.id = c.league_id
    WHERE c.player_key = :player_key
    ORDER BY c.period_start DESC, c.id DESC
    """)

_TITLES = text("""
    SELECT season, club FROM hockey_titles WHERE player_key = :player_key ORDER BY awarded_at DESC, id DESC
    """)

_DUELS = text("""
    SELECT o.player_key AS other_key, pl.display_name,
           SUM((a.points * (1 + a.doubled::int) > o.points * (1 + o.doubled::int))::int)::int AS won,
           SUM((a.points * (1 + a.doubled::int) < o.points * (1 + o.doubled::int))::int)::int AS lost
    FROM hockey_picks AS a
    JOIN hockey_picks AS o ON o.match_id = a.match_id AND o.player_key <> a.player_key
    JOIN game_matches AS m ON m.id = a.match_id
    JOIN hockey_players AS pl ON pl.player_key = o.player_key
    WHERE a.player_key = :player_key AND a.points IS NOT NULL AND o.points IS NOT NULL
      AND m.status = 'final' AND m.starts_at >= :since AND m.starts_at < :until
      AND o.player_key IN (
          SELECT mb2.player_key FROM hockey_league_members AS mb1
          JOIN hockey_league_members AS mb2 ON mb2.league_id = mb1.league_id
          WHERE mb1.player_key = :player_key AND mb2.player_key <> :player_key)
    GROUP BY o.player_key, pl.display_name
    HAVING SUM((a.points * (1 + a.doubled::int) <> o.points * (1 + o.doubled::int))::int) > 0
    ORDER BY SUM((a.points * (1 + a.doubled::int) <> o.points * (1 + o.doubled::int))::int) DESC, pl.display_name
    LIMIT :limit
    """)

_NAME = text("SELECT display_name FROM hockey_players WHERE player_key = :player_key")


def streaks(points: list[int]) -> tuple[int, int]:
    """Серия — угаданные победители подряд (20+): текущая и лучшая. Мимо обрывает."""
    best = run = 0
    for p in points:
        run = run + 1 if p >= POINTS_WINNER else 0
        best = max(best, run)
    return run, best


def favorite_club(scored) -> str | None:
    """Клуб, на чьи матчи игрок ходил чаще всего в сезоне (при равенстве — по алфавиту)."""
    counts: dict[str, int] = {}
    for r in scored:
        for club in (r.home_team, r.away_team):
            counts[club] = counts.get(club, 0) + 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


async def fan_profile(session: AsyncSession, *, player_key: int, now: datetime) -> dict:
    name = (await session.execute(_NAME, {"player_key": player_key})).scalar_one_or_none()
    season = season_period(now)
    scored = [r for r in (await session.execute(_SCORED, {"player_key": player_key})).all()]
    in_season = [r for r in scored if season.since <= _utc(r.starts_at) < season.until]
    current, best = streaks([int(r.points) for r in scored])
    club = favorite_club(in_season)

    async def place(for_club: str | None) -> dict | None:
        rows = await slice_rows(session, scope=club_scope(for_club), period=season)
        mine = next((r for r in rows if r.player_key == player_key), None)
        if mine is None:
            return None
        return {
            "club": for_club,
            "rank": mine.rank,
            "players": len(rows),
            "points": mine.points,
            "exact": mine.exact,
            "played": mine.played,
            "correct_percent": round(100 * mine.correct / mine.played) if mine.played else None,
            "to_first": max(0, rows[0].points - mine.points),
        }

    overall = await place(None)
    club_place = await place(club) if club else None
    crowns = []
    for c in (await session.execute(_CROWNS, {"player_key": player_key})).all():
        start = _utc(c.period_start).astimezone(MINSK_TZ).date()
        crowns.append(
            {
                "kind": c.kind,
                "club": c.club,
                "league_id": c.league_id,
                "league_name": c.league_name,
                "period": f"{start.year:04d}-{start.month:02d}",
            }
        )
    titles = [
        {"season": t.season, "club": t.club} for t in (await session.execute(_TITLES, {"player_key": player_key})).all()
    ]
    duels = [
        {"display_name": d.display_name, "won": d.won, "lost": d.lost}
        for d in (
            await session.execute(
                _DUELS,
                {"player_key": player_key, "since": season.since, "until": season.until, "limit": DUELS_LIMIT},
            )
        ).all()
    ]
    return {
        "display_name": name,
        "season": season_label(season.since),
        "club": None if club is None else team_card(club),
        "played": overall["played"] if overall else 0,
        "correct_percent": overall["correct_percent"] if overall else None,
        "exact": overall["exact"] if overall else 0,
        "streak": current,
        "best_streak": best,
        "overall": overall,
        "club_place": club_place,
        "crowns": crowns,
        "titles": titles,
        "duels": duels,
    }


__all__ = ["clubs_catalog", "fan_profile", "favorite_club", "match_movement", "rank_without", "streaks"]
