"""Строка «Кто кого» на главной: итог, пока его не открыли, или ближайший матч (TASK-299).

Итог важнее приглашения. Итог живёт сутки после ``finalized_at`` и гаснет, когда игрок его открыл.
Приглашение — ближайший ещё не начавшийся матч, до него не больше 48 часов.
Три последних сыгранных матча без хода прячут приглашение. Новичок без единого хода его видит.

Домашний матч — событие, а не только игра (TASK-304): пропуски его не прячут, а идущий домашний
матч держится в слоте до трёх часов после начала (``mode = "live"``). Скрывший «Кто кого»
видит только домашние матчи — выездные есть лишь в игре.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_event import enabled as hockey_enabled
from src.application.hockey_event import event_href, is_home, kk_hidden
from src.application.hockey_matches import DINAMO
from src.application.hockey_races import current_race, fresh_race_result, race_final_match_id, race_result
from src.application.hockey_game import POINTS_EXACT, race_window
from src.application.hockey_teams import team_card

RESULT_WINDOW = timedelta(hours=24)
# Выездной матч — строка игры за двое суток. Домашний — событие, на него договариваются заранее:
# он занимает слот главной за 14 дней (владелец 2026-10-20) и важнее выездного в это время.
BEFORE_WINDOW = timedelta(hours=48)
HOME_AHEAD = timedelta(days=14)
MISSED_STREAK = 3
LIVE_WINDOW = timedelta(hours=3)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def suppress_upcoming(*, had_pick: bool, last_finals_picked: list[bool]) -> bool:
    """Три пропуска подряд. Пустая история — это вход в игру, а не пропуски."""
    if not had_pick:
        return False
    recent = last_finals_picked[:MISSED_STREAK]
    return len(recent) >= MISSED_STREAK and not any(recent)


def choose_mode(*, unseen_result: bool, upcoming: bool, suppress: bool) -> str | None:
    if unseen_result:
        return "result"
    if upcoming and not suppress:
        return "before"
    return None


def _pick(row) -> dict | None:
    if row["pick_side"] is None:
        return None
    return {
        "side": row["pick_side"],
        "home_score": row["pick_home_score"],
        "away_score": row["pick_away_score"],
        "points": row["pick_points"],
        "doubled": bool(row["pick_doubled"]),
    }


def _match(row, *, now: datetime) -> dict:
    starts_at = _utc(row["starts_at"])
    played = row["status"] == "final"
    return {
        "id": row["id"],
        "home_team": row["home_team"],
        "away_team": row["away_team"],
        "home": team_card(row["home_team"]),
        "away": team_card(row["away_team"]),
        "starts_at": starts_at.isoformat(),
        "status": row["status"],
        "open": row["status"] == "scheduled" and now < starts_at,
        "result": (
            {
                "home_score": row["home_score"],
                "away_score": row["away_score"],
                "decided_in": row["decided_in"],
            }
            if played
            else None
        ),
    }


_UNSEEN_RESULT = text("""
    SELECT m.id, m.home_team, m.away_team, m.starts_at, m.status,
           m.home_score, m.away_score, m.decided_in,
           p.side AS pick_side, p.home_score AS pick_home_score, p.away_score AS pick_away_score,
           p.points AS pick_points, COALESCE(p.doubled, false) AS pick_doubled
    FROM hockey_picks AS p
    JOIN hockey_matches AS m ON m.id = p.match_id
    WHERE p.player_key = :player_key
      AND m.status = 'final'
      AND m.finalized_at IS NOT NULL
      AND m.finalized_at >= :since
      AND p.result_seen_at IS NULL
    ORDER BY m.finalized_at DESC, m.id DESC
    LIMIT 1
    """)

_UPCOMING = text("""
    SELECT m.id, m.home_team, m.away_team, m.starts_at, m.status,
           m.home_score, m.away_score, m.decided_in,
           p.side AS pick_side, p.home_score AS pick_home_score, p.away_score AS pick_away_score,
           p.points AS pick_points, COALESCE(p.doubled, false) AS pick_doubled
    FROM hockey_matches AS m
    LEFT JOIN hockey_picks AS p ON p.match_id = m.id AND p.player_key = :player_key
    WHERE m.status = 'scheduled' AND m.starts_at > :now AND m.starts_at <= :until
      AND (CAST(:home AS text) IS NULL OR m.home_team = :home)
    ORDER BY m.starts_at, m.id
    LIMIT 1
    """)

_LIVE_HOME = text("""
    SELECT m.id, m.home_team, m.away_team, m.starts_at, m.status,
           m.home_score, m.away_score, m.decided_in,
           p.side AS pick_side, p.home_score AS pick_home_score, p.away_score AS pick_away_score,
           p.points AS pick_points, COALESCE(p.doubled, false) AS pick_doubled
    FROM hockey_matches AS m
    LEFT JOIN hockey_picks AS p ON p.match_id = m.id AND p.player_key = :player_key
    WHERE m.home_team = :home AND m.status IN ('scheduled', 'review')
      AND m.starts_at <= :now AND m.starts_at > :since
    ORDER BY m.starts_at DESC, m.id DESC
    LIMIT 1
    """)

_HAD_PICK = text("SELECT EXISTS(SELECT 1 FROM hockey_picks WHERE player_key = :player_key)")

_LAST_FINALS = text("""
    SELECT (p.id IS NOT NULL) AS picked
    FROM hockey_matches AS m
    LEFT JOIN hockey_picks AS p ON p.match_id = m.id AND p.player_key = :player_key
    WHERE m.status = 'final'
    ORDER BY m.finalized_at DESC NULLS LAST, m.starts_at DESC, m.id DESC
    LIMIT :limit
    """)

# То же место, что в таблице лиги: очки гонки за матчи после вступления, при равенстве — точные счета.
# Лучшая лига — меньший rank.
_BEST_PLACE = text("""
    WITH my AS (
        SELECT l.id AS league_id, l.name AS league_name
        FROM hockey_leagues AS l
        JOIN hockey_league_members AS me ON me.league_id = l.id AND me.player_key = :player_key
    ),
    totals AS (
        SELECT mb.league_id, mb.player_key,
               COALESCE(SUM(p.points * (1 + p.doubled::int)), 0)::int AS points,
               COALESCE(COUNT(p.points) FILTER (WHERE p.points = :exact), 0)::int AS exact
        FROM hockey_league_members AS mb
        JOIN my ON my.league_id = mb.league_id
        LEFT JOIN hockey_picks AS p ON p.player_key = mb.player_key AND p.points IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM hockey_matches AS m
                WHERE m.id = p.match_id AND m.starts_at >= GREATEST(:since, mb.joined_at) AND m.starts_at < :until
            )
        GROUP BY mb.league_id, mb.player_key
    ),
    ranked AS (
        SELECT league_id, player_key,
               RANK() OVER (PARTITION BY league_id ORDER BY points DESC, exact DESC)::int AS rank
        FROM totals
    )
    SELECT my.league_name, ranked.rank
    FROM ranked
    JOIN my ON my.league_id = ranked.league_id
    WHERE ranked.player_key = :player_key
    ORDER BY ranked.rank, my.league_name
    LIMIT 1
    """)

_MARK_SEEN = text("""
    UPDATE hockey_picks
    SET result_seen_at = :now
    WHERE player_key = :player_key AND match_id = :match_id AND result_seen_at IS NULL
    """)


async def _best_place(session: AsyncSession, player_key: int, *, at: datetime) -> dict | None:
    """Место в лучшей лиге в гонке, где был матч ``at``: итог матча 30-го смотрят и 1-го числа."""
    window = race_window(at)
    row = (
        await session.execute(
            _BEST_PLACE,
            {"player_key": player_key, "exact": POINTS_EXACT, "since": window.since, "until": window.until},
        )
    ).one_or_none()
    if row is None:
        return None
    return {"league_name": row.league_name, "rank": row.rank}


def _event_fields(row) -> dict:
    """Домашний матч — событие: слот ведёт на его страницу. Выездной остаётся прежним (TASK-304)."""
    home = is_home(row["home_team"])
    fields: dict = {"is_home": home}
    if home and hockey_enabled():
        fields["event_href"] = event_href(row["id"])
    return fields


def _suppressed(upcoming, *, hidden: bool, had_pick: bool, finals: list[bool]) -> bool:
    if upcoming is None:
        return False
    row = upcoming._mapping
    if is_home(row["home_team"]) and hockey_enabled():
        return False  # событие: зовут и тех, кто не играет
    if hidden:
        return True
    # Уже сходил на ближайший матч (например, из Telegram) — это не пропуск, строку показываем.
    return suppress_upcoming(had_pick=had_pick, last_finals_picked=finals) and row["pick_side"] is None


async def hub_card(session: AsyncSession, player_key: int, *, now: datetime) -> dict:
    now = _utc(now)
    hidden = await kk_hidden(session, player_key)
    # Итог месяца важнее итога матча: в нём уже есть финал (TASK-334).
    if not hidden:
        race = await fresh_race_result(session, player_key=player_key, now=now)
        if race is not None:
            return {"mode": "race_result", "race": await race_result(session, player_key=player_key, race=race)}
    final_id = await race_final_match_id(session, await current_race(session, now=now))
    result = (
        None
        if hidden
        else (
            await session.execute(_UNSEEN_RESULT, {"player_key": player_key, "since": now - RESULT_WINDOW})
        ).one_or_none()
    )
    if result is None:
        live = (
            await session.execute(
                _LIVE_HOME, {"player_key": player_key, "home": DINAMO, "now": now, "since": now - LIVE_WINDOW}
            )
        ).one_or_none()
        if live is not None and hockey_enabled():
            return {
                "mode": "live",
                "match": {**_match(live._mapping, now=now), "race_final": live._mapping["id"] == final_id},
                "my_pick": _pick(live._mapping),
                **_event_fields(live._mapping),
            }
    had_pick = bool((await session.execute(_HAD_PICK, {"player_key": player_key})).scalar_one())
    finals = [
        bool(row.picked)
        for row in (await session.execute(_LAST_FINALS, {"player_key": player_key, "limit": MISSED_STREAK})).all()
    ]
    upcoming = None
    if hockey_enabled():
        upcoming = (
            await session.execute(
                _UPCOMING, {"player_key": player_key, "now": now, "until": now + HOME_AHEAD, "home": DINAMO}
            )
        ).one_or_none()
    if upcoming is None:
        upcoming = (
            await session.execute(
                _UPCOMING, {"player_key": player_key, "now": now, "until": now + BEFORE_WINDOW, "home": None}
            )
        ).one_or_none()
    mode = choose_mode(
        unseen_result=result is not None,
        upcoming=upcoming is not None,
        # Уже сходил на ближайший матч (например, из Telegram) — это не пропуск, строку показываем.
        suppress=_suppressed(upcoming, hidden=hidden, had_pick=had_pick, finals=finals),
    )
    if mode == "result" and result is not None:
        pick = _pick(result._mapping)
        return {
            "mode": "result",
            "match": {**_match(result._mapping, now=now), "race_final": result._mapping["id"] == final_id},
            "my_pick": pick,
            # Базовые очки — по ним слова «в точку»; ×2 в my_pick.doubled, наклейка умножит (TASK-335).
            "points": None if pick is None else pick["points"],
            "place": await _best_place(session, player_key, at=_utc(result._mapping["starts_at"])),
            **_event_fields(result._mapping),
        }
    if mode == "before" and upcoming is not None:
        return {
            "mode": "before",
            "match": {**_match(upcoming._mapping, now=now), "race_final": upcoming._mapping["id"] == final_id},
            "my_pick": _pick(upcoming._mapping),
            **_event_fields(upcoming._mapping),
        }
    return {"mode": None}


async def mark_result_seen(session: AsyncSession, *, player_key: int, match_id: int, now: datetime) -> None:
    """Отметить, что игрок открыл итог своего хода. Чужого и отсутствующего хода нет — ничего не пишем."""
    await session.execute(_MARK_SEEN, {"player_key": player_key, "match_id": match_id, "now": _utc(now)})


__all__ = [
    "BEFORE_WINDOW",
    "HOME_AHEAD",
    "LIVE_WINDOW",
    "MISSED_STREAK",
    "RESULT_WINDOW",
    "choose_mode",
    "hub_card",
    "mark_result_seen",
    "suppress_upcoming",
]
