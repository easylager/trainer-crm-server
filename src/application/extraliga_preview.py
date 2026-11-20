"""«Перед матчем» для страницы матча Экстралиги (TASK-340, экран 12 холста) и матча Динамо.

У Динамо (source='hcdinamo') место и очки — таблица КХЛ, кого смотреть — снимок ``dinamo_stats``;
форма — только у Динамо: матчей соперника с другими клубами у нас нет.

Место и очки — из ``hockey_standings``; форма и прошлая встреча — из наших же сыгранных матчей;
кого смотреть — снимок страницы матча; серии голов — протокол последнего матча команды.
Всё, чего нет, просто не попадает в ответ: страница рисует только то, что есть.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_matches import DINAMO

FORM_SIZE = 5
# От скольких матчей подряд серия голов — повод сказать о ней.
STREAK_FROM = 3

# Буква — победа или поражение, приписка — как решён матч: «о» — овертайм, «б» — буллиты.
_SUFFIX = {"regulation": "", "ot": "о", "so": "б"}

_MATCH = text("""
    SELECT id, source, league, home_team, away_team, starts_at, arena, details
    FROM hockey_matches WHERE id = :id AND source IN ('hockeyby', 'hcdinamo')
    """)

_STANDING = text("SELECT place, points, games FROM hockey_standings WHERE league = :league AND team = :team")

_PLAYED = text("""
    SELECT id, home_team, away_team, home_score, away_score, decided_in, starts_at, arena, details
    FROM hockey_matches
    WHERE source = :source AND status = 'final' AND starts_at < :before
      AND (home_team = :team OR away_team = :team)
    ORDER BY starts_at DESC
    LIMIT :limit
    """)

_LAST_MEETING = text("""
    SELECT id, home_team, away_team, home_score, away_score, decided_in, starts_at, arena, details
    FROM hockey_matches
    WHERE source = :source AND status = 'final' AND starts_at < :before
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


async def _team_block(session: AsyncSession, team: str, *, record: Any, side: str, history: bool = True) -> dict:
    """``history`` выключен у соперника Динамо: у нас только его матчи с Динамо — это не форма."""
    before, details = record.starts_at, record.details
    standing = (await session.execute(_STANDING, {"league": record.league, "team": team})).one_or_none()
    params = {"source": record.source, "team": team, "before": before, "limit": FORM_SIZE}
    recent = [_played(r) for r in (await session.execute(_PLAYED, params)).all()] if history else []
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
    khl = record.source == "hcdinamo"
    home = await _team_block(
        session, record.home_team, record=record, side="home", history=not khl or record.home_team == DINAMO
    )
    away = await _team_block(
        session, record.away_team, record=record, side="away", history=not khl or record.away_team == DINAMO
    )
    meeting_params = {"source": record.source, "a": record.home_team, "b": record.away_team, "before": before}
    last = (await session.execute(_LAST_MEETING, meeting_params)).one_or_none()
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


# ---------- «Перед матчем» в игре «Кто кого» ----------

MEETINGS_SIZE = 3

_MEETINGS = text("""
    SELECT id, home_team, away_team, home_score, away_score, decided_in, starts_at, arena, details
    FROM hockey_matches
    WHERE source = :source AND status = 'final' AND starts_at < :before
      AND ((home_team = :a AND away_team = :b) OR (home_team = :b AND away_team = :a))
    ORDER BY starts_at DESC
    LIMIT :limit
    """)


def _score_out(m: _Played) -> dict:
    return {
        "home_team": m.home_team,
        "away_team": m.away_team,
        "home_score": m.home_score,
        "away_score": m.away_score,
        "decided_in": m.decided_in,
        "starts_at": m.starts_at.astimezone(timezone.utc).isoformat(),
    }


async def _game_team(session: AsyncSession, record: Any, team: str, *, history: bool) -> dict | None:
    out: dict = {}
    standing = (await session.execute(_STANDING, {"league": record.league, "team": team})).one_or_none()
    if standing is not None:
        out["place"] = standing.place
        out["points"] = standing.points
    if history:
        params = {"source": record.source, "team": team, "before": record.starts_at, "limit": FORM_SIZE}
        recent = [_played(r) for r in (await session.execute(_PLAYED, params)).all()]
        if recent:
            # Старые слева, свежий справа — как читают форму.
            out["form"] = [
                {
                    "mark": form_mark(m, team),
                    "win": form_mark(m, team).startswith("В"),
                    "opponent": m.away_team if m.home_team == team else m.home_team,
                    "home": m.home_team == team,
                    **_score_out(m),
                }
                for m in reversed(recent)
            ]
    return out or None


# Ходы игрока на сыгранные матчи команды в этой лиге: победитель — сторона хода совпала с итогом,
# «в точку» — совпал точный счёт (как +50 в ``verdict``). Считаются только посчитанные ходы (points есть).
_MY_HISTORY = text("""
    SELECT COUNT(*)::int AS total,
           COUNT(*) FILTER (WHERE p.side = CASE WHEN m.home_score > m.away_score THEN 'home' ELSE 'away' END)::int AS winner,
           COUNT(*) FILTER (WHERE p.home_score = m.home_score AND p.away_score = m.away_score)::int AS exact
    FROM hockey_picks AS p JOIN hockey_matches AS m ON m.id = p.match_id
    WHERE p.player_key = :player_key AND m.status = 'final' AND m.league = :league
      AND m.id <> :match_id AND p.points IS NOT NULL
      AND (m.home_team = :team OR m.away_team = :team)
    """)

# Меньше двух ходов — не история, а случай.
MY_HISTORY_MIN = 2


async def game_preview(session: AsyncSession, match_id: int, *, player_key: int | None = None) -> dict:
    """Экран матча «Кто кого»: место в таблице, последние 5 и до трёх личных встреч — только то, что есть.

    Пустой части нет в ответе; нет ничего — пустой словарь. У соперника Динамо формы нет: в КХЛ мы храним
    только матчи Динамо, и «форма» соперника была бы одними матчами с Динамо — это неправда.
    """
    record = (await session.execute(_MATCH, {"id": match_id})).one_or_none()
    if record is None:
        return {}
    khl = record.source == "hcdinamo"
    out: dict = {}
    for side in ("home", "away"):
        team = getattr(record, f"{side}_team")
        block = await _game_team(session, record, team, history=not khl or team == DINAMO) or {}
        if player_key is not None:
            mine = (
                await session.execute(
                    _MY_HISTORY,
                    {"player_key": player_key, "league": record.league, "match_id": record.id, "team": team},
                )
            ).one()
            if mine.total >= MY_HISTORY_MIN:
                block["mine"] = {"total": mine.total, "winner": mine.winner, "exact": mine.exact}
        if block:
            out[side] = block
    params = {
        "source": record.source,
        "a": record.home_team,
        "b": record.away_team,
        "before": record.starts_at,
        "limit": MEETINGS_SIZE,
    }
    meetings = [_score_out(_played(r)) for r in (await session.execute(_MEETINGS, params)).all()]
    if meetings:
        out["meetings"] = meetings
    return out


__all__ = ["form_mark", "game_preview", "match_preview", "winning_goal"]
