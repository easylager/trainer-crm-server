"""Каталог матчей «Матчи» (client-matches): все лиги на одной странице, фильтры в адресе.

Фильтры: ``team`` (slug команды), ``league`` (khl / extraliga), ``city``, ``arena`` (название с
сайта лиги), ``when`` (upcoming / results). Новая лига — ещё одно значение ``league``, не экран.
Фасеты для шита фильтров считаются по выбранному ``when`` без остальных фильтров.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.extraliga import CLUBS, LEAGUE_EXTRALIGA, enabled_clubs
from src.application.extraliga_home import card
from src.application.hockey_event import enabled as dinamo_enabled, event_href
from src.application.hockey_matches import DINAMO
from src.application.hockey_teams import slug_for, team_card
from src.ingestion.hockey_sources import HCDINAMO_BASE
from src.shared.config import Settings

LEAGUE_KHL = "khl"
LEAGUES = {LEAGUE_KHL: "КХЛ", LEAGUE_EXTRALIGA: "Экстралига"}
AHEAD = timedelta(days=30)
BEHIND = timedelta(hours=3)
RESULTS_BACK = timedelta(days=30)
DINAMO_ARENA = "Минск-Арена"
DINAMO_CITY = "Минск"
_CLUB_BY_NAME = {club.name: club for club in CLUBS.values()}

_ROWS = text("""
    SELECT id, source_match_id, league, home_team, away_team, starts_at, status,
           home_score, away_score, decided_in, arena, city
    FROM hockey_matches
    WHERE status <> 'cancelled' AND starts_at >= :since AND starts_at < :until
      AND ((league = 'extraliga' AND (home_team = ANY(:clubs) OR away_team = ANY(:clubs)))
           OR (league = 'khl' AND :dinamo AND (home_team = :dinamo_name OR away_team = :dinamo_name)))
    ORDER BY starts_at, id
    """)


@dataclass(frozen=True)
class Filters:
    team: str | None = None
    league: str | None = None
    city: str | None = None
    arena: str | None = None
    when: str = "upcoming"


def _norm(value: str | None) -> str:
    return (value or "").strip().lower().replace("ё", "е")


def _place(row: Any) -> tuple[str | None, str | None]:
    """Арена и город матча; у Динамо их нет в базе — дома Минск-Арена, на выезде не знаем."""
    if row.league == LEAGUE_KHL:
        return (DINAMO_ARENA, DINAMO_CITY) if row.home_team == DINAMO else (None, None)
    club = _CLUB_BY_NAME.get(row.home_team)
    return row.arena, row.city or (club.city if club else None)


def _teams(row: Any) -> list[str]:
    return [row.home_team, row.away_team]


def _match(row: Any, f: Filters) -> bool:
    arena, city = _place(row)
    if f.league and row.league != f.league:
        return False
    if f.team and f.team not in {slug_for(t) for t in _teams(row)}:
        return False
    if f.city and _norm(city) != _norm(f.city):
        return False
    return not (f.arena and _norm(arena) != _norm(f.arena))


def _card(row: Any, *, now: datetime) -> dict[str, Any]:
    arena, city = _place(row)
    out = card(row, now=now)
    out.update(league=row.league, league_label=LEAGUES.get(row.league, row.league), arena=arena, city=city)
    if row.league == LEAGUE_KHL and row.home_team != DINAMO:
        # Выезд Динамо: своей страницы матча нет — ведём на страницу клуба.
        raw = (row.source_match_id or "").strip()
        out.update(href=None, external_url=f"{HCDINAMO_BASE}/matches/{raw}/" if raw.isdigit() else None)
    else:
        out["href"] = event_href(row.id)
    return out


def _facets(rows: list[Any], f: Filters) -> dict[str, Any]:
    teams: Counter[str] = Counter()
    cities: Counter[str] = Counter()
    arenas: Counter[str] = Counter()
    leagues: Counter[str] = Counter()
    known = set(_CLUB_BY_NAME) | {DINAMO}
    for row in rows:
        leagues[row.league] += 1
        for t in _teams(row):
            if t in known:
                teams[t] += 1
        arena, city = _place(row)
        if city:
            cities[city] += 1
            if arena and f.city and _norm(city) == _norm(f.city):
                arenas[arena] += 1
    team_list = sorted(teams, key=lambda t: (t != DINAMO, t))
    return {
        "teams": [{**team_card(t), "slug": slug_for(t), "count": teams[t]} for t in team_list],
        "leagues": [{"id": k, "label": LEAGUES.get(k, k), "count": leagues[k]} for k in LEAGUES if leagues[k]],
        "cities": [{"name": c, "count": n} for c, n in sorted(cities.items())],
        "arenas": [{"name": a, "count": n} for a, n in sorted(arenas.items(), key=lambda x: (-x[1], x[0]))],
    }


async def catalog(
    session: AsyncSession, *, now: datetime, filters: Filters, settings: Settings | None = None
) -> dict[str, Any]:
    cfg = settings or Settings()  # type: ignore[call-arg]
    clubs = sorted(enabled_clubs(cfg.extraliga_clubs)) if cfg.extraliga_enabled else []
    results = filters.when == "results"
    since, until = (now - RESULTS_BACK, now) if results else (now - BEHIND, now + AHEAD)
    params = {"since": since, "until": until, "clubs": clubs, "dinamo": dinamo_enabled(cfg), "dinamo_name": DINAMO}
    rows = list((await session.execute(_ROWS, params)).all())
    if results:
        rows = [r for r in reversed(rows) if r.status == "final" and r.home_score is not None]
    else:
        rows = [r for r in rows if not (r.status == "final" and r.starts_at < now - BEHIND)]
    picked = [r for r in rows if _match(r, filters)]
    team = next((t for r in picked for t in _teams(r) if filters.team and slug_for(t) == filters.team), None)
    return {
        "when": "results" if results else "upcoming",
        "filters": {
            "team": filters.team,
            "team_card": team_card(team) if team else None,
            "league": filters.league,
            "league_label": LEAGUES.get(filters.league or ""),
            "city": filters.city,
            "arena": filters.arena,
        },
        "matches": [_card(r, now=now) for r in picked],
        "facets": _facets(rows, filters),
    }


__all__ = ["Filters", "LEAGUES", "catalog"]
