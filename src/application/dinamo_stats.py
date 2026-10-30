"""Таблица КХЛ и лидеры Динамо с hcdinamo.by для «Перед матчем» и «Кого смотреть» на матчах Динамо.

Таблица ложится в ``hockey_standings`` (league='khl'). Лидеры — снимок в ``details[сторона Динамо]``
ещё не сыгранных матчей Динамо, в том же виде, что снимок со страницы матча Экстралиги: блок не
пропадает, когда матч начался. Статистики игроков соперника у клуба нет — его сторона пустая.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_matches import DINAMO, Fetch
from src.ingestion.hockey_sources import (
    HCDINAMO_STANDINGS_URL,
    HCDINAMO_STATS_URL,
    parse_hcdinamo_leaders,
    parse_hcdinamo_standings,
)

# Идущий матч тоже получает свежий снимок, пока не стал финалом.
LIVE_BACK = timedelta(hours=6)

_UPSERT_STANDING = text("""
    INSERT INTO hockey_standings (league, team, place, games, points, updated_at)
    VALUES ('khl', :team, :place, :games, :points, :now)
    ON CONFLICT (league, team) DO UPDATE
    SET place = EXCLUDED.place, games = EXCLUDED.games, points = EXCLUDED.points, updated_at = EXCLUDED.updated_at
    """)
_UPCOMING = text("""
    SELECT id, home_team, details FROM hockey_matches
    WHERE source = 'hcdinamo' AND status NOT IN ('final', 'cancelled') AND starts_at >= :since
    """)
_SET_DETAILS = text("UPDATE hockey_matches SET details = CAST(:details AS jsonb) WHERE id = :id")


async def sync_dinamo_stats(session: AsyncSession, fetch: Fetch, *, now: datetime) -> dict[str, int]:
    standings = parse_hcdinamo_standings(await fetch(HCDINAMO_STANDINGS_URL))
    leaders = parse_hcdinamo_leaders(await fetch(HCDINAMO_STATS_URL))
    if not standings and not (leaders["forwards"] or leaders["goalies"]):
        raise ValueError("hcdinamo: ни таблица КХЛ, ни статистика Динамо не разобраны")
    for s in standings:
        await session.execute(
            _UPSERT_STANDING, {"team": s.team, "place": s.place, "games": s.games, "points": s.points, "now": now}
        )
    updated = 0
    if leaders["forwards"] or leaders["goalies"]:
        for row in (await session.execute(_UPCOMING, {"since": now - LIVE_BACK})).all():
            details = dict(row.details or {})
            details["home" if row.home_team == DINAMO else "away"] = leaders
            await session.execute(_SET_DETAILS, {"id": row.id, "details": json.dumps(details, ensure_ascii=False)})
            updated += 1
    return {"standings": len(standings), "leaders_matches": updated}


__all__ = ["sync_dinamo_stats"]
