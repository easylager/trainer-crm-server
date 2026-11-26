"""TASK-451 (5.4): значки волны 1 (флаг ``redesign_s5``).

Шесть значков: вводный «Вышел на лёд» (первая отметка сезона), Серии
«Не растаял» / «Крепкий лёд» / «Вечная мерзлота» (3/5/10 недель пн–вс подряд
с ≥1 отметкой, время Минска) и Сезон «Разогрелся» / «Завсегдатай» (10/25 дней
с отметкой за сезон 1 сен–31 авг).

Считается всё из дат отметок (``ice_checkins._checkins_dates`` — тот же источник,
что у ``me_stats``); вручение идемпотентное: уникальный индекс
``uq_ice_badges_tg_profile_key_season`` не даёт дублей даже в гонке.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application import ice_checkins as ic

logger = logging.getLogger(__name__)

# ── Каталог значков ──────────────────────────────────────────────────────

BADGES: tuple[dict[str, Any], ...] = (
    {"key": "first_ice", "name": "Вышел на лёд", "name_gen": "Выхода на лёд", "family": "intro", "total": 1},
    {"key": "streak_3", "name": "Не растаял", "name_gen": "Не растаял", "family": "streak", "total": 3},
    {"key": "streak_5", "name": "Крепкий лёд", "name_gen": "Крепкого льда", "family": "streak", "total": 5},
    {"key": "streak_10", "name": "Вечная мерзлота", "name_gen": "Вечной мерзлоты", "family": "streak", "total": 10},
    {"key": "days_10", "name": "Разогрелся", "name_gen": "Разогрелся", "family": "season", "total": 10},
    {"key": "days_25", "name": "Завсегдатай", "name_gen": "Завсегдатая", "family": "season", "total": 25},
)
BY_KEY: dict[str, dict[str, Any]] = {b["key"]: b for b in BADGES}
BADGE_KEYS: frozenset[str] = frozenset(BY_KEY)

_BADGE_WORD = {"streak": ("неделя", "недели", "недель"), "season": ("день", "дня", "дней")}


def _plural(n: int, forms: tuple[str, str, str]) -> str:
    n100 = n % 100
    n10 = n % 10
    if n10 == 1 and n100 != 11:
        return forms[0]
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return forms[1]
    return forms[2]


def remaining_word(family: str, n: int) -> str:
    """«одна неделя» / «2 недели» / «4 дня» — форма для строки «осталось»."""
    return f"{n} {_plural(n, _BADGE_WORD[family])}" if family in _BADGE_WORD else str(n)


# ── Чистые функции ───────────────────────────────────────────────────────


def progress_map(dates: list[date], today: date) -> dict[str, int]:
    """Сырой прогресс по каждому значку: недели серии / дни сезона / первый шаг."""
    days = len(dates)
    streak = ic.streak_weeks(dates, today)
    return {
        "first_ice": min(days, 1),
        "streak_3": min(streak, 3),
        "streak_5": min(streak, 5),
        "streak_10": min(streak, 10),
        "days_10": min(days, 10),
        "days_25": min(days, 25),
    }


def earned_keys(prog: Mapping[str, int]) -> set[str]:
    """Ключи значков, чьё условие выполнено по прогрессу."""
    return {b["key"] for b in BADGES if int(prog.get(b["key"]) or 0) >= int(b["total"])}


def next_in_family(key: str, prog: Mapping[str, int]) -> dict | None:
    """«Дальше»: следующий уровень той же семьи, который ещё не открыт."""
    cur = BY_KEY.get(key)
    if cur is None:
        return None
    for b in BADGES:
        if b["family"] != cur["family"] or int(b["total"]) <= int(cur["total"]):
            continue
        done = min(int(prog.get(b["key"]) or 0), int(b["total"]))
        if done < int(b["total"]):
            return {"key": b["key"], "name": b["name"], "name_gen": b["name_gen"],
                    "remaining": int(b["total"]) - done,
                    "family": b["family"], "total": int(b["total"]), "done": done}
    return None


def closest_unearned(prog: Mapping[str, int], earned: set[str]) -> dict | None:
    """«Ближе всего»: не открытый значок с максимальной долей прогресса.

    Ничья — раньше в каталоге (порядок ``BADGES``: первый шаг, серии, сезон).
    """
    best: dict | None = None
    best_ratio = -1.0
    for b in BADGES:
        if b["key"] in earned:
            continue
        done = min(int(prog.get(b["key"]) or 0), int(b["total"]))
        if done >= int(b["total"]):
            continue  # условие выполнено — считаем вручённым, «0 осталось» не пишем
        ratio = done / int(b["total"])
        if ratio > best_ratio:
            best_ratio = ratio
            best = {"key": b["key"], "name": b["name"], "name_gen": b["name_gen"], "family": b["family"],
                    "total": int(b["total"]), "done": done,
                    "remaining": int(b["total"]) - done}
    return best


def _next_for_sheet(key: str, prog: Mapping[str, int], earned: set[str]) -> dict | None:
    """«Дальше» под значком листа: следующий уровень семьи, иначе ближайший закрытый."""
    nxt = next_in_family(key, prog)
    if nxt is not None:
        return {k: nxt[k] for k in ("key", "name", "name_gen", "family", "remaining")}
    closest = closest_unearned(prog, earned | {key})
    if closest is None:
        return None
    return {k: closest[k] for k in ("key", "name", "name_gen", "family", "remaining")}


def badge_payload(key: str, *, earned_at: datetime | None, prog: Mapping[str, int]) -> dict:
    """Публичная форма значка: ``earned``/``earned_at``/``progress{done,total}``."""
    b = BY_KEY[key]
    total = int(b["total"])
    done = min(int(prog.get(key) or 0), total)
    if earned_at is not None:
        done = total
    return {
        "key": key,
        "name": b["name"],
        "name_gen": b["name_gen"],
        "family": b["family"],
        "total": total,
        "earned": earned_at is not None,
        "earned_at": earned_at.isoformat() if earned_at is not None else None,
        "progress": {"done": done, "total": total},
    }


# ── Работа с БД ──────────────────────────────────────────────────────────


def _p0(profile_id: int | None) -> int:
    return int(profile_id or 0)


async def _earned_rows(
    session: AsyncSession, telegram_id: int, profile_id: int | None, season_start: date | None = None
) -> dict[str, datetime]:
    """{badge_key: earned_at} за сезон (``None`` — все сезоны)."""
    sql = """
        SELECT badge_key, earned_at FROM ice_badges
        WHERE telegram_id = :t AND COALESCE(profile_id, 0) = :p
    """
    params: dict[str, Any] = {"t": int(telegram_id), "p": _p0(profile_id)}
    if season_start is not None:
        sql += " AND season = :s"
        params["s"] = season_start
    rows = (
        (await session.execute(text(sql), params)).mappings().all()
    )
    return {str(r["badge_key"]): r["earned_at"] for r in rows}


async def evaluate_and_award(
    session: AsyncSession, telegram_id: int, profile_id: int | None, today: date
) -> list[dict]:
    """Проверить условия по свежим отметкам и вручить недостающее. Идемпотентно.

    Возвращает payload'ы только что вручённых (в порядке каталога) — их показывает
    лист вручения. Повторный вызов за тот же сезон новых значков не создаёт.
    """
    season_start, _end = ic.season_bounds(today)
    dates = await ic._checkins_dates(session, telegram_id, profile_id, season_start)
    prog = progress_map(dates, today)
    want = earned_keys(prog)
    have = set(await _earned_rows(session, telegram_id, profile_id, season_start))
    new = [b["key"] for b in BADGES if b["key"] in want and b["key"] not in have]
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for key in new:
        ins = (
            await session.execute(
                text(
                    """
                    INSERT INTO ice_badges (telegram_id, profile_id, badge_key, season, earned_at)
                    VALUES (:t, :p, :k, :s, :now)
                    ON CONFLICT DO NOTHING
                    RETURNING earned_at
                    """
                ),
                {"t": int(telegram_id), "p": profile_id, "k": key, "s": season_start, "now": now},
            )
        ).scalar()
        # ins None = гонка/повтор — строка уже есть, второй раз не «вручаем».
        if ins is None:
            continue
        payload = badge_payload(key, earned_at=ins, prog=prog)
        payload["next"] = _next_for_sheet(key, prog, have | set(new))
        out.append(payload)
    return out


async def badges_payload(
    session: AsyncSession, telegram_id: int, profile_id: int | None, today: date
) -> list[dict]:
    """Все 6 значков текущего сезона для экрана «Я»: состояние + прогресс."""
    season_start, _end = ic.season_bounds(today)
    dates = await ic._checkins_dates(session, telegram_id, profile_id, season_start)
    prog = progress_map(dates, today)
    earned = await _earned_rows(session, telegram_id, profile_id, season_start)
    return [
        badge_payload(b["key"], earned_at=earned.get(b["key"]), prog=prog)
        for b in BADGES
    ]


async def pending_badges(
    session: AsyncSession, telegram_id: int, profile_id: int | None, today: date
) -> list[dict]:
    """Вручённые, но не показанные (``shown_at IS NULL``) — лист при открытии."""
    season_start, _end = ic.season_bounds(today)
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT badge_key, earned_at FROM ice_badges
                    WHERE telegram_id = :t AND COALESCE(profile_id, 0) = :p
                      AND season = :s AND shown_at IS NULL
                    ORDER BY earned_at, id
                    """
                ),
                {"t": int(telegram_id), "p": _p0(profile_id), "s": season_start},
            )
        )
        .mappings()
        .all()
    )
    dates = await ic._checkins_dates(session, telegram_id, profile_id, season_start)
    prog = progress_map(dates, today)
    earned_now = {str(r["badge_key"]) for r in rows}
    out = []
    for r in rows:
        payload = badge_payload(str(r["badge_key"]), earned_at=r["earned_at"], prog=prog)
        payload["next"] = _next_for_sheet(str(r["badge_key"]), prog, earned_now)
        out.append(payload)
    return out


async def mark_shown(
    session: AsyncSession,
    telegram_id: int,
    profile_id: int | None,
    keys: list[str],
    now: datetime | None = None,
) -> int:
    """Лист вручения показан — проставить ``shown_at`` вручённым без показа."""
    valid = [k for k in keys if k in BADGE_KEYS]
    if not valid:
        return 0
    res = await session.execute(
        text(
            """
            UPDATE ice_badges SET shown_at = :now
            WHERE telegram_id = :t AND COALESCE(profile_id, 0) = :p
              AND badge_key = ANY(:keys) AND shown_at IS NULL
            """
        ),
        {"t": int(telegram_id), "p": _p0(profile_id), "keys": valid, "now": now or datetime.now(timezone.utc)},
    )
    return int(res.rowcount or 0)


# ── «Серия под угрозой»: ближайший значок ────────────────────────────────


def nearest_line(prog: Mapping[str, int], earned: set[str]) -> str | None:
    """Строка «До „Крепкого льда“ — одна неделя» для сообщения «Серия под угрозой»."""
    nxt = closest_unearned(prog, earned | {"first_ice"})
    if nxt is None:
        return None
    if nxt["family"] == "streak":
        return f"До «{nxt['name_gen']}» — {remaining_word('streak', nxt['remaining'])}"
    if nxt["family"] == "season":
        return f"До «{nxt['name_gen']}» — {remaining_word('season', nxt['remaining'])}"
    return f"До «{nxt['name_gen']}» — {nxt['remaining']}"
