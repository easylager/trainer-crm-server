"""Лиги друзей «Кто кого»: создать, вступить по ссылке, таблица лиги, выйти (TASK-298).

Таблица лиги — очки участников в текущей гонке (месяц, TASK-334) за матчи, начавшиеся после их
вступления (владелец 2026-10-26):
лига — соревнование с момента, когда вы в ней встретились, без форы за прошлые недели. Поэтому в лиге
и в общей таблице у человека могут быть разные числа. Участник без очков стоит в таблице с нулём —
друг, который только что вступил, виден сразу.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_game import DEFAULT_PLAYER_NAME, POINTS_EXACT, POINTS_WINNER, race_window

NAME_MAX = 28
MAX_MEMBERS = 100
MAX_LEAGUES_PER_PLAYER = 20
# Без похожих символов (0/O, 1/I/L): код читают с экрана и диктуют голосом.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 8


class LeagueFull(Exception):
    """В лиге уже максимум участников."""


class TooManyLeagues(Exception):
    """Игрок уже в максимуме лиг."""


@dataclass(frozen=True)
class League:
    id: int
    name: str
    invite_code: str
    owner_key: int


@dataclass(frozen=True)
class LeagueSummary:
    id: int
    name: str
    invite_code: str
    is_owner: bool
    members: int
    my_rank: int
    my_points: int


@dataclass(frozen=True)
class LeagueRow:
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


def clean_name(name: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise ValueError("Назовите лигу")
    if len(cleaned) > NAME_MAX:
        raise ValueError(f"Название до {NAME_MAX} символов")
    return cleaned


def new_invite_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


def normalize_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


_PLAYER_UPSERT = text("""
    INSERT INTO hockey_players (player_key, display_name)
    VALUES (:player_key, :display_name)
    ON CONFLICT (player_key) DO NOTHING
    """)

_COUNT_MY_LEAGUES = text("SELECT COUNT(*) FROM hockey_league_members WHERE player_key = :player_key")

_INSERT_LEAGUE = text("""
    INSERT INTO hockey_leagues (name, owner_key, invite_code)
    VALUES (:name, :owner_key, :invite_code)
    RETURNING id, name, invite_code, owner_key
    """)

_ADD_MEMBER = text("""
    INSERT INTO hockey_league_members (league_id, player_key)
    VALUES (:league_id, :player_key)
    ON CONFLICT DO NOTHING
    """)

_LEAGUE_BY_CODE = text("""
    SELECT id, name, invite_code, owner_key FROM hockey_leagues WHERE invite_code = :code
    """)

_LEAGUE_BY_ID = text("""
    SELECT id, name, invite_code, owner_key FROM hockey_leagues WHERE id = :league_id
    """)

_LEAGUE_BY_ID_LOCK = text("""
    SELECT id, name, invite_code, owner_key FROM hockey_leagues WHERE id = :league_id FOR UPDATE
    """)

_IS_MEMBER = text("""
    SELECT 1 FROM hockey_league_members WHERE league_id = :league_id AND player_key = :player_key
    """)

_MEMBER_COUNT = text("SELECT COUNT(*) FROM hockey_league_members WHERE league_id = :league_id")

_REMOVE_MEMBER = text("""
    DELETE FROM hockey_league_members WHERE league_id = :league_id AND player_key = :player_key
    """)

_NEXT_OWNER = text("""
    SELECT player_key FROM hockey_league_members
    WHERE league_id = :league_id ORDER BY joined_at, player_key LIMIT 1
    """)

_SET_OWNER = text("UPDATE hockey_leagues SET owner_key = :owner_key, updated_at = now() WHERE id = :league_id")

_DELETE_LEAGUE = text("DELETE FROM hockey_leagues WHERE id = :league_id")

_RENAME = text("UPDATE hockey_leagues SET name = :name, updated_at = now() WHERE id = :league_id")

# Очки каждого участника за матчи гонки, начавшиеся после его вступления; у кого их нет — ноль.
_LEAGUE_TABLE = text("""
    WITH members AS (
        SELECT player_key, joined_at FROM hockey_league_members WHERE league_id = :league_id
    ), totals AS (
        SELECT p.player_key,
               SUM(p.points * (1 + p.doubled::int))::int AS points,
               COUNT(*) FILTER (WHERE p.points = :exact)::int AS exact,
               COUNT(*)::int AS played
        FROM hockey_picks AS p
        JOIN members AS me ON me.player_key = p.player_key
        JOIN kk_matches AS m ON m.id = p.match_id
        WHERE p.points IS NOT NULL AND m.starts_at >= GREATEST(:since, me.joined_at) AND m.starts_at < :until
        GROUP BY p.player_key
    )
    SELECT RANK() OVER (ORDER BY COALESCE(t.points, 0) DESC, COALESCE(t.exact, 0) DESC)::int AS rank,
           mb.player_key, pl.display_name,
           COALESCE(t.points, 0) AS points, COALESCE(t.exact, 0) AS exact, COALESCE(t.played, 0) AS played
    FROM members AS mb
    JOIN hockey_players AS pl ON pl.player_key = mb.player_key
    LEFT JOIN totals AS t ON t.player_key = mb.player_key
    ORDER BY rank, pl.display_name, mb.player_key
    """)

_MY_LEAGUES = text("""
    SELECT l.id, l.name, l.invite_code, (l.owner_key = :player_key) AS is_owner,
           (SELECT COUNT(*) FROM hockey_league_members x WHERE x.league_id = l.id)::int AS members
    FROM hockey_leagues AS l
    JOIN hockey_league_members AS me ON me.league_id = l.id AND me.player_key = :player_key
    ORDER BY me.joined_at, l.id
    """)

_PREVIEW_NAMES = text("""
    SELECT pl.display_name FROM hockey_league_members AS mb
    JOIN hockey_players AS pl ON pl.player_key = mb.player_key
    WHERE mb.league_id = :league_id ORDER BY mb.joined_at, mb.player_key LIMIT :limit
    """)

# Кто из друзей (участников моих лиг) за какую сторону. Счёт друзей не раскрываем — только сторону.
_FRIENDS_PICKS = text("""
    SELECT DISTINCT p.match_id, p.side, p.player_key, pl.display_name
    FROM hockey_picks AS p
    JOIN hockey_players AS pl ON pl.player_key = p.player_key
    WHERE p.match_id = ANY(:match_ids)
      AND p.player_key <> :player_key
      AND p.player_key IN (
          SELECT f.player_key FROM hockey_league_members AS f
          WHERE f.league_id IN (SELECT league_id FROM hockey_league_members WHERE player_key = :player_key)
      )
    ORDER BY p.match_id, p.side, pl.display_name, p.player_key
    """)


async def _ensure_player(session: AsyncSession, player_key: int, display_name: str) -> None:
    name = (display_name or "").strip()[:40] or DEFAULT_PLAYER_NAME
    await session.execute(_PLAYER_UPSERT, {"player_key": player_key, "display_name": name})


async def _check_league_quota(session: AsyncSession, player_key: int) -> None:
    count = (await session.execute(_COUNT_MY_LEAGUES, {"player_key": player_key})).scalar_one()
    if count >= MAX_LEAGUES_PER_PLAYER:
        raise TooManyLeagues(player_key)


async def create_league(session: AsyncSession, *, owner_key: int, owner_name: str, name: str) -> League:
    """Новая лига; создатель — первый участник. Код приглашения уникален, коллизию повторяем."""
    name = clean_name(name)
    await _ensure_player(session, owner_key, owner_name)
    await _check_league_quota(session, owner_key)
    for _ in range(5):
        try:
            async with session.begin_nested():
                row = (
                    await session.execute(
                        _INSERT_LEAGUE, {"name": name, "owner_key": owner_key, "invite_code": new_invite_code()}
                    )
                ).one()
        except IntegrityError:
            continue
        league = League(**row._mapping)
        await session.execute(_ADD_MEMBER, {"league_id": league.id, "player_key": owner_key})
        return league
    raise RuntimeError("не удалось выдать код приглашения")


async def league_by_code(session: AsyncSession, code: str) -> League | None:
    record = (await session.execute(_LEAGUE_BY_CODE, {"code": normalize_code(code)})).one_or_none()
    return None if record is None else League(**record._mapping)


async def join_by_code(session: AsyncSession, *, player_key: int, display_name: str, code: str) -> League:
    """Вступить по коду. Повторный переход по той же ссылке ничего не меняет."""
    found = await league_by_code(session, code)
    if found is None:
        raise LookupError(code)
    # Лочим строку лиги: двое одновременно не превысят лимит участников.
    league = League(**(await session.execute(_LEAGUE_BY_ID_LOCK, {"league_id": found.id})).one()._mapping)
    await _ensure_player(session, player_key, display_name)
    if (await session.execute(_IS_MEMBER, {"league_id": league.id, "player_key": player_key})).first():
        return league
    if (await session.execute(_MEMBER_COUNT, {"league_id": league.id})).scalar_one() >= MAX_MEMBERS:
        raise LeagueFull(league.id)
    await _check_league_quota(session, player_key)
    await session.execute(_ADD_MEMBER, {"league_id": league.id, "player_key": player_key})
    return league


async def _member_league(session: AsyncSession, league_id: int, player_key: int, *, lock: bool = True) -> League:
    stmt = _LEAGUE_BY_ID_LOCK if lock else _LEAGUE_BY_ID
    record = (await session.execute(stmt, {"league_id": league_id})).one_or_none()
    if record is None:
        raise LookupError(league_id)
    if not (await session.execute(_IS_MEMBER, {"league_id": league_id, "player_key": player_key})).first():
        raise PermissionError(league_id)
    return League(**record._mapping)


async def leave_league(session: AsyncSession, *, league_id: int, player_key: int) -> str:
    """Выйти. Ушёл владелец — лига переходит к самому раннему участнику; ушёл последний — лиги нет."""
    league = await _member_league(session, league_id, player_key)
    await session.execute(_REMOVE_MEMBER, {"league_id": league_id, "player_key": player_key})
    next_owner = (await session.execute(_NEXT_OWNER, {"league_id": league_id})).scalar_one_or_none()
    if next_owner is None:
        await session.execute(_DELETE_LEAGUE, {"league_id": league_id})
        return "deleted"
    if league.owner_key == player_key:
        await session.execute(_SET_OWNER, {"league_id": league_id, "owner_key": next_owner})
        return "owner_moved"
    return "left"


async def rename_league(session: AsyncSession, *, league_id: int, player_key: int, name: str) -> League:
    league = await _member_league(session, league_id, player_key)
    if league.owner_key != player_key:
        raise PermissionError(league_id)
    name = clean_name(name)
    await session.execute(_RENAME, {"league_id": league_id, "name": name})
    return League(id=league.id, name=name, invite_code=league.invite_code, owner_key=league.owner_key)


async def league_table(session: AsyncSession, *, league_id: int, player_key: int, now: datetime) -> list[LeagueRow]:
    """Таблица лиги — только для участника."""
    await _member_league(session, league_id, player_key, lock=False)
    window = race_window(now)
    params = {"league_id": league_id, "exact": POINTS_EXACT, "since": window.since, "until": window.until}
    return [LeagueRow(**r._mapping) for r in (await session.execute(_LEAGUE_TABLE, params)).all()]


# ---------- звания в таблице лиги (владелец 2026-10-20) ----------
# Одно на человека: шутим над ходом, а не над человеком. Всё — из готовых ходов.
# Если подходит несколько — берём самое яркое по этому порядку.
TITLE_ORDER = ("cap", "scarf", "vanga", "streak", "optimist")
VANGA_MIN = 2
STREAK_MIN = 3
OPTIMIST_MARGIN = 2
OPTIMIST_MIN_PICKS = 2

_TITLE_PICKS = text("""
    SELECT p.player_key, m.id AS match_id, m.starts_at, m.status, m.home_team, p.side, p.points,
           p.home_score AS pick_home, p.away_score AS pick_away
    FROM hockey_picks AS p
    JOIN kk_matches AS m ON m.id = p.match_id
    WHERE p.player_key IN (SELECT player_key FROM hockey_league_members WHERE league_id = :league_id)
      AND m.starts_at >= :since
    ORDER BY m.starts_at, m.id
    """)

_NEXT_MATCH = text("""
    SELECT id FROM kk_matches WHERE status = 'scheduled' AND starts_at > :now
    ORDER BY starts_at, id LIMIT 1
    """)


def _dinamo_side(home_team: str) -> str:
    from src.application.hockey_matches import DINAMO

    return "home" if home_team == DINAMO else "away"


def _plural(n: int, one: str, few: str, many: str) -> str:
    m10, m100 = n % 10, n % 100
    if m10 == 1 and m100 != 11:
        return one
    if 2 <= m10 <= 4 and not 12 <= m100 <= 14:
        return few
    return many


def pick_titles(picks: list[dict], *, next_match_id: int | None) -> dict[int, dict[str, str]]:
    """Звания участников лиги по их ходам за сезон (чистая функция, ходы — по времени матча).

    - cap «Кепка позора» — меньше всех очков за последний сыгранный матч лиги; если очки у всех
      равные — кепки нет. Висит, пока не сыграют следующий матч.
    - scarf «В чужом шарфе» — ход против Динамо на ближайший матч;
    - vanga «Ванга» — единственный лидер лиги по точным счетам, от VANGA_MIN точных;
    - streak «Чуйка» — победитель угадан STREAK_MIN+ сыгранных матчей подряд;
    - optimist «Вечный оптимист» — в среднем ставит Динамо +OPTIMIST_MARGIN и больше.
    """
    found: dict[int, dict[str, dict[str, str]]] = {}

    def give(player: int, key: str, label: str, detail: str = "") -> None:
        found.setdefault(player, {})[key] = {"id": key, "label": label, "detail": detail}

    scored = [p for p in picks if p["status"] == "final" and p["points"] is not None]
    if scored:
        last_match = scored[-1]["match_id"]
        last = [p for p in scored if p["match_id"] == last_match]
        if len(last) >= 2:
            low = min(p["points"] for p in last)
            if low < max(p["points"] for p in last):
                for p in last:
                    if p["points"] == low:
                        give(p["player_key"], "cap", "Кепка позора", f"{low} {_plural(low, 'очко', 'очка', 'очков')}")

    if next_match_id is not None:
        for p in picks:
            if p["match_id"] == next_match_id and p["side"] and p["side"] != _dinamo_side(p["home_team"]):
                give(p["player_key"], "scarf", "В чужом шарфе")

    exact: dict[int, int] = {}
    for p in scored:
        if p["points"] == POINTS_EXACT:
            exact[p["player_key"]] = exact.get(p["player_key"], 0) + 1
    if exact:
        best = max(exact.values())
        leaders = [k for k, v in exact.items() if v == best]
        if len(leaders) == 1 and best >= VANGA_MIN:
            give(leaders[0], "vanga", "Ванга", f"{best} {_plural(best, 'точный', 'точных', 'точных')}")

    by_player: dict[int, list[dict]] = {}
    for p in scored:
        by_player.setdefault(p["player_key"], []).append(p)
    for player, rows in by_player.items():
        run = 0
        for p in reversed(rows):
            if p["points"] < POINTS_WINNER:
                break
            run += 1
        if run >= STREAK_MIN:
            give(player, "streak", "Чуйка", f"{run} подряд")

    margins: dict[int, list[int]] = {}
    for p in picks:
        if p.get("pick_home") is None or p.get("pick_away") is None:
            continue
        dinamo_home = _dinamo_side(p["home_team"]) == "home"
        ours, theirs = (p["pick_home"], p["pick_away"]) if dinamo_home else (p["pick_away"], p["pick_home"])
        margins.setdefault(p["player_key"], []).append(ours - theirs)
    for player, values in margins.items():
        if len(values) >= OPTIMIST_MIN_PICKS and sum(values) / len(values) >= OPTIMIST_MARGIN:
            give(player, "optimist", "Вечный оптимист")

    return {player: next(titles[k] for k in TITLE_ORDER if k in titles) for player, titles in found.items()}


async def league_titles(session: AsyncSession, *, league_id: int, now: datetime) -> dict[int, dict[str, str]]:
    now = _utc(now)
    picks = [
        dict(r._mapping)
        for r in (await session.execute(_TITLE_PICKS, {"league_id": league_id, "since": race_window(now).since})).all()
    ]
    if not picks:
        return {}
    next_id = (await session.execute(_NEXT_MATCH, {"now": now})).scalar_one_or_none()
    return pick_titles(picks, next_match_id=next_id)


async def player_leagues(session: AsyncSession, *, player_key: int, now: datetime) -> list[LeagueSummary]:
    out: list[LeagueSummary] = []
    for record in (await session.execute(_MY_LEAGUES, {"player_key": player_key})).all():
        rows = await league_table(session, league_id=record.id, player_key=player_key, now=now)
        mine = next(r for r in rows if r.player_key == player_key)
        out.append(
            LeagueSummary(
                id=record.id,
                name=record.name,
                invite_code=record.invite_code,
                is_owner=bool(record.is_owner),
                members=record.members,
                my_rank=mine.rank,
                my_points=mine.points,
            )
        )
    return out


async def league_preview(session: AsyncSession, code: str, *, names: int = 6) -> dict | None:
    """Для приглашения: название, сколько людей и первые имена. Без таблицы и без ключей игроков."""
    league = await league_by_code(session, code)
    if league is None:
        return None
    members = (await session.execute(_MEMBER_COUNT, {"league_id": league.id})).scalar_one()
    shown = (await session.execute(_PREVIEW_NAMES, {"league_id": league.id, "limit": names})).scalars().all()
    return {"name": league.name, "invite_code": league.invite_code, "members": int(members), "names": list(shown)}


async def friends_picks(
    session: AsyncSession, *, player_key: int, match_ids: list[int]
) -> dict[int, dict[str, list[str]]]:
    """Друзья на половинках карточки матча: имена за каждую сторону, без их счёта и без меня."""
    out: dict[int, dict[str, list[str]]] = {mid: {"home": [], "away": []} for mid in match_ids}
    if not match_ids:
        return out
    params = {"player_key": player_key, "match_ids": list(match_ids)}
    for r in (await session.execute(_FRIENDS_PICKS, params)).all():
        out[r.match_id][r.side].append(r.display_name)
    return out


# Счета друзей открываются со стартом матча (TASK-335): до начала — только сторона (friends_picks).
_FRIENDS_MOVES = text("""
    SELECT DISTINCT p.match_id, p.player_key, pl.display_name, p.side, p.home_score, p.away_score,
           p.doubled, p.points
    FROM hockey_picks AS p
    JOIN hockey_players AS pl ON pl.player_key = p.player_key
    JOIN kk_matches AS m ON m.id = p.match_id
    WHERE p.match_id = ANY(:match_ids)
      AND p.player_key <> :player_key
      AND (m.status <> 'scheduled' OR m.starts_at <= :now)
      AND p.player_key IN (
          SELECT f.player_key FROM hockey_league_members AS f
          WHERE f.league_id IN (SELECT league_id FROM hockey_league_members WHERE player_key = :player_key)
      )
    ORDER BY p.match_id, pl.display_name, p.player_key
    """)


async def friends_moves(
    session: AsyncSession, *, player_key: int, match_ids: list[int], now: datetime
) -> dict[int, list[dict]]:
    """Ходы друзей на начавшиеся матчи: сторона, счёт, ×2 и очки (уже с ×2), когда посчитаны."""
    out: dict[int, list[dict]] = {mid: [] for mid in match_ids}
    if not match_ids:
        return out
    params = {"player_key": player_key, "match_ids": list(match_ids), "now": _utc(now)}
    for r in (await session.execute(_FRIENDS_MOVES, params)).all():
        out[r.match_id].append(
            {
                "display_name": r.display_name,
                "side": r.side,
                "home_score": r.home_score,
                "away_score": r.away_score,
                "doubled": bool(r.doubled),
                "points": None if r.points is None else r.points * (2 if r.doubled else 1),
            }
        )
    return out


__all__ = [
    "League",
    "LeagueFull",
    "LeagueRow",
    "LeagueSummary",
    "MAX_LEAGUES_PER_PLAYER",
    "MAX_MEMBERS",
    "TooManyLeagues",
    "clean_name",
    "create_league",
    "friends_moves",
    "friends_picks",
    "join_by_code",
    "league_by_code",
    "league_preview",
    "league_table",
    "leave_league",
    "new_invite_code",
    "normalize_code",
    "player_leagues",
    "rename_league",
]
