"""«Перед матчем» для страницы матча Экстралиги (TASK-340, экран 12 холста).

Место и очки — из ``hockey_standings``; форма и прошлая встреча — из наших же сыгранных матчей;
кого смотреть — снимок страницы матча; серии голов — протокол последнего матча команды.
Всё, чего нет, просто не попадает в ответ: страница рисует только то, что есть.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

FORM_SIZE = 5
# От скольких матчей подряд серия голов — повод сказать о ней.
STREAK_FROM = 3

# Буква — победа или поражение, приписка — как решён матч: «о» — овертайм, «б» — буллиты.
_SUFFIX = {"regulation": "", "ot": "о", "so": "б"}

_MATCH = text("""
    SELECT id, home_team, away_team, starts_at, arena, details
    FROM hockey_matches WHERE id = :id AND source = 'hockeyby'
    """)

_STANDING = text("SELECT place, points, games FROM hockey_standings WHERE league = 'extraliga' AND team = :team")

_PLAYED = text("""
    SELECT id, home_team, away_team, home_score, away_score, decided_in, starts_at, arena, details
    FROM hockey_matches
    WHERE source = 'hockeyby' AND status = 'final' AND starts_at < :before
      AND (home_team = :team OR away_team = :team)
    ORDER BY starts_at DESC
    LIMIT :limit
    """)

_LAST_MEETING = text("""
    SELECT id, home_team, away_team, home_score, away_score, decided_in, starts_at, arena, details
    FROM hockey_matches
    WHERE source = 'hockeyby' AND status = 'final' AND starts_at < :before
      AND ((home_team = :a AND away_team = :b) OR (home_team = :b AND away_team = :a))
    ORDER BY starts_at DESC
    LIMIT 1
    """)


@dataclass(frozen=True)
class _Played:
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    decided_in: str
    starts_at: datetime
    arena: str | None
    details: dict | None


def _played(record) -> _Played:
    return _Played(
        record.home_team,
        record.away_team,
        record.home_score,
        record.away_score,
        record.decided_in,
        record.starts_at,
        record.arena,
        record.details,
    )


def form_mark(m: _Played, team: str) -> str:
    """«В», «П», «Во», «По», «Вб», «Пб» — как на экране 12."""
    mine, theirs = (m.home_score, m.away_score) if m.home_team == team else (m.away_score, m.home_score)
    return ("В" if mine > theirs else "П") + _SUFFIX.get(m.decided_in, "")


def winning_goal(m: _Played) -> dict | None:
    """Шайба, после которой победитель забил на одну больше, чем проигравший за весь матч.

    Буллиты — победной шайбы в протоколе нет (её добавляет счёт), поэтому None.
    """
    if m.decided_in == "so" or not m.details:
        return None
    winner = "home" if m.home_score > m.away_score else "away"
    loser_total = min(m.home_score, m.away_score)
    count = 0
    for goal in m.details.get("goals") or []:
        if goal.get("side") != winner:
            continue
        count += 1
        if count == loser_total + 1:
            return goal
    return None


def _minute(clock: str) -> int:
    """«62:25» → 63-я минута."""
    mm = int(clock.split(":")[0])
    return mm + 1


def _streaks(m: _Played, team: str) -> list[dict]:
    if not m.details:
        return []
    side = "home" if m.home_team == team else "away"
    out: dict[str, int] = {}
    for goal in m.details.get("goals") or []:
        if goal.get("side") == side and (goal.get("streak") or 0) >= STREAK_FROM:
            out[goal["scorer"]] = max(out.get(goal["scorer"], 0), int(goal["streak"]))
    return [{"player": name, "matches": n} for name, n in out.items()]


async def _team_block(session: AsyncSession, team: str, *, before: datetime, details: dict | None, side: str) -> dict:
    standing = (await session.execute(_STANDING, {"team": team})).one_or_none()
    recent = [
        _played(r) for r in (await session.execute(_PLAYED, {"team": team, "before": before, "limit": FORM_SIZE})).all()
    ]
    snapshot = (details or {}).get(side) or {}
    return {
        "team": team,
        "place": standing.place if standing else None,
        "points": standing.points if standing else None,
        "games": standing.games if standing else None,
        # Старые слева, свежий справа — как читают форму.
        "form": [form_mark(m, team) for m in reversed(recent)],
        "leaders": {
            "forwards": (snapshot.get("forwards") or [])[:2],
            "goalie": (snapshot.get("goalies") or [None])[0],
        },
        "streaks": _streaks(recent[0], team) if recent else [],
    }


async def match_preview(session: AsyncSession, match_id: int) -> dict | None:
    record = (await session.execute(_MATCH, {"id": match_id})).one_or_none()
    if record is None:
        return None
    before = record.starts_at
    home = await _team_block(session, record.home_team, before=before, details=record.details, side="home")
    away = await _team_block(session, record.away_team, before=before, details=record.details, side="away")
    last = (
        await session.execute(_LAST_MEETING, {"a": record.home_team, "b": record.away_team, "before": before})
    ).one_or_none()
    meeting = None
    if last is not None:
        m = _played(last)
        goal = winning_goal(m)
        winner = m.home_team if m.home_score > m.away_score else m.away_team
        meeting = {
            "home_team": m.home_team,
            "away_team": m.away_team,
            "home_score": m.home_score,
            "away_score": m.away_score,
            "decided_in": m.decided_in,
            "starts_at": m.starts_at.astimezone(timezone.utc).isoformat(),
            "same_arena": bool(m.arena and record.arena and m.arena == record.arena),
            "winner": winner,
            "loser": m.away_team if winner == m.home_team else m.home_team,
            "winning_goal": {"scorer": goal["scorer"], "minute": _minute(goal["minute"])} if goal else None,
        }
    return {"home": home, "away": away, "last_meeting": meeting}


__all__ = ["form_mark", "match_preview", "winning_goal"]
