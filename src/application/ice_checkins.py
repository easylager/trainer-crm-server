"""TASK-446: «Я здесь» — отметки о льде и загрузка катков (флаг ``redesign_s5``).

Отметка — только пока сеанс идёт (``is_ongoing``): человек физически на льду, и его ответ
про «сколько народу» честный. Загрузка «сейчас» — медиана засчитанных оценок за 40 минут
(``live_load``); одна отметка на (telegram_id, профиль, сеанс); до 3 отметок в сутки на
аккаунт. Серия — недели пн–вс (Минск) подряд с ≥1 отметкой; текущая неделя без отметки
серию до её конца не рвёт.

Чистые функции выше, работа с БД ниже — тестируется отдельно.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MINSK = ZoneInfo("Europe/Minsk")

CHECKIN_KINDS = ("public_skate", "open_ice", "family_skate", "hockey_practice")
STATUS_ACTIVE = "active"
LIVE_WINDOW = timedelta(minutes=40)
EARLY_MINUTES = 15
DAILY_LIMIT = 3
PROMPT_AFTER_START = timedelta(minutes=20)
PROMPT_MIN_LEFT = timedelta(minutes=30)
PROMPT_WINDOW_START = time(8, 0)
PROMPT_WINDOW_END = time(22, 30)
REGULAR_TOLERANCE = timedelta(minutes=60)
REGULAR_LOOKBACK_DAYS = 42
NOT_HERE_MUTE_AFTER = 2
NOT_HERE_MUTE_DAYS = 30
ACCOUNT_MIN_AGE_LOAD = timedelta(days=7)
_FUTURE_SKEW = timedelta(minutes=5)


class CheckinError(Exception):
    """Ошибка отметки с машинным кодом: API отображает в HTTP-статус и поле ``code``."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ── Чистые функции ────────────────────────────────────────────────────────


def season_bounds(day: date) -> tuple[date, date]:
    """Сезон по Минску: 1 сентября – 31 августа."""
    start_year = day.year if (day.month, day.day) >= (9, 1) else day.year - 1
    return date(start_year, 9, 1), date(start_year + 1, 8, 31)


def streak_weeks(dates: Iterable[date], today: date) -> int:
    """Недели пн–вс подряд с ≥1 днём отметки.

    Текущая неделя без отметки серию не рвёт — она ещё не закончилась:
    считаем от прошлой завершённой, если в текущей пусто.
    """
    weeks = {d - timedelta(days=d.weekday()) for d in dates}
    if not weeks:
        return 0
    current_monday = today - timedelta(days=today.weekday())
    cursor = current_monday if current_monday in weeks else current_monday - timedelta(days=7)
    streak = 0
    while cursor in weeks:
        streak += 1
        cursor -= timedelta(days=7)
    return streak


def live_load(reports: Iterable[Mapping[str, Any]], now: datetime) -> dict[str, Any] | None:
    """«Сейчас»: оценки за последние 40 минут, только засчитанные (counts_for_load).

    reports: строки {load_level, created_at, counts_for_load}. Медиана; если есть и
    1 и 3 — 2. Оценка, отличающаяся от медианы остальных на 2 уровня, выбрасывается.
    Возвращает {level, count, last_min} или None.
    """
    cutoff = now - LIVE_WINDOW
    # Серверный created_at может опережать python-now на секунды — не выбрасываем свежую отметку.
    rows = [
        r
        for r in reports
        if r.get("counts_for_load")
        and r.get("load_level") in (1, 2, 3)
        and r.get("created_at") is not None
        and r["created_at"] >= cutoff
        and r["created_at"] <= now + _FUTURE_SKEW
    ]
    if not rows:
        return None
    levels = [int(r["load_level"]) for r in rows]

    def median(xs: list[int]) -> float:
        s = sorted(xs)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    kept = []
    for r in rows:
        others = [int(x["load_level"]) for x in rows if x is not r]
        if others and abs(int(r["load_level"]) - median(others)) >= 2:
            continue  # выброс: единственная оценка на два уровня от остальных — не верим
        kept.append(r)
    if not kept:
        kept = rows  # если «выбросили» все (например, 1 и 3 пополам) — не теряем данные
    levels = sorted(int(r["load_level"]) for r in kept)
    if 1 in levels and 3 in levels:
        level = 2
    else:
        med = median(levels)
        level = int(round(med))
        level = min(3, max(1, level))
    last = max(r["created_at"] for r in kept)
    return {
        "level": level,
        "count": len(kept),
        "last_min": max(0, int((now - last).total_seconds() // 60)),
    }


def is_ongoing(session: Mapping[str, Any], now: datetime) -> bool:
    """Сеанс идёт: start−15мин ≤ now < end, вид из разрешённых, статус active."""
    if str(session.get("status") or "") != STATUS_ACTIVE:
        return False
    if str(session.get("kind") or "") not in CHECKIN_KINDS:
        return False
    start, end = session.get("starts_at_utc"), session.get("ends_at_utc")
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return False
    return start - timedelta(minutes=EARLY_MINUTES) <= now < end


def prompt_due_at(session: Mapping[str, Any]) -> datetime | None:
    """Когда спрашивать «Ты на катке?»: start+20мин, ≥30мин до конца, окно 08:00–22:30 Минск."""
    start, end = session.get("starts_at_utc"), session.get("ends_at_utc")
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return None
    due = start + PROMPT_AFTER_START
    if end - due < PROMPT_MIN_LEFT:
        return None
    local_due = due.astimezone(MINSK)
    if not (PROMPT_WINDOW_START <= local_due.time() <= PROMPT_WINDOW_END):
        return None
    return due


def day_group(local_date: date) -> str:
    """Группа дней для регулярного ритма: будни / суббота / воскресенье."""
    wd = local_date.weekday()
    return "sat" if wd == 5 else "sun" if wd == 6 else "weekday"


def plural_raz(n: int) -> str:
    """«6-й раз за сезон» — порядковый номер для строк."""
    return f"{n}-й раз"


LOAD_WORDS = {1: "Сейчас свободно", 2: "Сейчас народу в меру", 3: "Сейчас людно"}
LOAD_WORDS_SHORT = {1: "свободно", 2: "в меру", 3: "людно"}


def plural_week(n: int) -> str:
    """неделя/недели/недель подряд."""
    n10 = n % 10
    n100 = n % 100
    if n10 == 1 and n100 != 11:
        return "неделя"
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return "недели"
    return "недель"


# ── SQL ───────────────────────────────────────────────────────────────────

_SESSION_SQL = """
    SELECT s.id, s.arena_id, s.kind, s.starts_at_utc, s.ends_at_utc, s.local_date,
           s.starts_at_local, s.ends_at_local, s.status,
           a.name AS arena_name, a.venue_type
    FROM ice_sessions s
    JOIN arenas a ON a.id = s.arena_id
    WHERE s.id = :sid
"""

_REPORTS_SQL = """
    SELECT load_level, created_at, counts_for_load
    FROM ice_checkins
    WHERE session_id = :sid
"""


async def _session_row(session: AsyncSession, session_id: int) -> Mapping[str, Any] | None:
    return (
        (await session.execute(text(_SESSION_SQL), {"sid": int(session_id)})).mappings().first()
    )


async def _account_created_at(session: AsyncSession, telegram_id: int) -> datetime | None:
    """created_at аккаунта (владельца) — порог 7 дней для counts_for_load."""
    return (
        await session.execute(
            text("SELECT MIN(created_at) FROM clients WHERE telegram_id = :t"),
            {"t": int(telegram_id)},
        )
    ).scalar()


async def _checkins_dates(session: AsyncSession, telegram_id: int, profile_id: int | None, season_start: date) -> list[date]:
    return [
        r[0]
        for r in (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT local_date FROM ice_checkins
                    WHERE telegram_id = :t AND COALESCE(profile_id, 0) = :p
                      AND local_date >= :s
                    """
                ),
                {"t": int(telegram_id), "p": int(profile_id or 0), "s": season_start},
            )
        ).all()
    ]


async def me_stats(session: AsyncSession, telegram_id: int, profile_id: int | None, today: date) -> dict[str, Any]:
    """Сезонные дни и серия недель для карточки/ответа."""
    start, _end = season_bounds(today)
    dates = await _checkins_dates(session, telegram_id, profile_id, start)
    streak = streak_weeks(dates, today)
    monday = today - timedelta(days=today.weekday())
    has_this_week = any(d >= monday for d in dates)
    return {"season_days": len(dates), "streak_weeks": streak, "has_this_week": has_this_week}


async def session_live(session: AsyncSession, session_ids: list[int], now: datetime) -> dict[int, dict[str, Any]]:
    """live_load по списку сеансов одним запросом."""
    ids = [int(s) for s in session_ids]
    if not ids:
        return {}
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT session_id, load_level, created_at, counts_for_load
                    FROM ice_checkins WHERE session_id = ANY(:ids)
                    """
                ),
                {"ids": ids},
            )
        )
        .mappings()
        .all()
    )
    by_session: dict[int, list[Mapping[str, Any]]] = {}
    for r in rows:
        by_session.setdefault(int(r["session_id"]), []).append(r)
    out: dict[int, dict[str, Any]] = {}
    for sid, reports in by_session.items():
        live = live_load(reports, now)
        if live is not None:
            out[sid] = live
    return out


async def check_in(
    session: AsyncSession,
    telegram_id: int,
    profile_id: int | None,
    session_id: int,
    source: str,
    load_level: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Отметка «Я здесь». Идемпотентна: повтор по (tg, профиль, сеанс) вернёт существующую."""
    now = now or datetime.now(timezone.utc)
    row = await _session_row(session, session_id)
    if row is None:
        raise CheckinError("unknown_session")
    if not is_ongoing(row, now):
        raise CheckinError("not_ongoing")
    today = now.astimezone(MINSK).date()
    used = (
        await session.execute(
            text(
                """
                SELECT COUNT(DISTINCT session_id) FROM ice_checkins
                WHERE telegram_id = :t AND local_date = :d
                """
            ),
            {"t": int(telegram_id), "d": today},
        )
    ).scalar() or 0
    existing = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, load_level, source, created_at FROM ice_checkins
                    WHERE telegram_id = :t AND COALESCE(profile_id, 0) = :p AND session_id = :s
                    """
                ),
                {"t": int(telegram_id), "p": int(profile_id or 0), "s": int(session_id)},
            )
        )
        .mappings()
        .first()
    )
    if existing is None and int(used) >= DAILY_LIMIT:
        raise CheckinError("daily_limit")
    account_created = await _account_created_at(session, telegram_id)
    counts = bool(account_created and now - account_created >= ACCOUNT_MIN_AGE_LOAD)
    level = int(load_level) if load_level in (1, 2, 3) else None
    if existing is None:
        ins = (
            (
                await session.execute(
                    text(
                        """
                        INSERT INTO ice_checkins
                            (telegram_id, profile_id, session_id, arena_id, local_date,
                             load_level, source, counts_for_load, load_set_at)
                        VALUES (:t, :p, :s, :a, :d, :lv, :src, :counts,
                                CASE WHEN CAST(:lv AS smallint) IS NULL THEN NULL ELSE CAST(:now AS timestamptz) END)
                        ON CONFLICT DO NOTHING
                        RETURNING id, load_level, created_at
                        """
                    ),
                    {
                        "t": int(telegram_id),
                        "p": profile_id,
                        "s": int(session_id),
                        "a": int(row["arena_id"]),
                        "d": today,
                        "lv": level,
                        "src": source,
                        "counts": counts,
                        "now": now,
                    },
                )
            )
            .mappings()
            .first()
        )
        if ins is None:  # гонка — чужой insert уже попал в уникальный индекс
            existing = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, load_level, source, created_at FROM ice_checkins
                            WHERE telegram_id = :t AND COALESCE(profile_id, 0) = :p AND session_id = :s
                            """
                        ),
                        {"t": int(telegram_id), "p": int(profile_id or 0), "s": int(session_id)},
                    )
                )
                .mappings()
                .first()
            )
            checkin_id = int(existing["id"]) if existing else None
        else:
            checkin_id = int(ins["id"])
        # Успешная отметка на катке сбрасывает серию «Я не на катке».
        await session.execute(
            text(
                """
                UPDATE ice_checkin_mutes
                SET not_here_streak = 0, muted_until = NULL
                WHERE telegram_id = :t AND arena_id = :a
                """
            ),
            {"t": int(telegram_id), "a": int(row["arena_id"])},
        )
    else:
        checkin_id = int(existing["id"])
        # Повтор с оценкой, когда раньше не ставили, — засчитываем как set_load.
        if level is not None and existing["load_level"] is None:
            await set_load(session, checkin_id, telegram_id, level, now=now)
    return {"checkin_id": checkin_id, "session_id": int(session_id), "arena_id": int(row["arena_id"])}


async def set_load(
    session: AsyncSession,
    checkin_id: int,
    telegram_id: int,
    level: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Оценка «сколько народу»: пока сеанс идёт — можно переписать (ошибся тапом/передумал);
    после конца — только первую (+40 мин запас на запоздалый тап, повтор — already_set)."""
    now = now or datetime.now(timezone.utc)
    if int(level) not in (1, 2, 3):
        raise CheckinError("bad_level")
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT c.id, c.session_id, c.load_level, s.starts_at_utc, s.ends_at_utc
                    FROM ice_checkins c JOIN ice_sessions s ON s.id = c.session_id
                    WHERE c.id = :id AND c.telegram_id = :t
                    """
                ),
                {"id": int(checkin_id), "t": int(telegram_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise CheckinError("not_found")
    # Оценку дают про «сейчас»: после конца сеанса она ничего не говорит. Запас — 40 минут,
    # окно живой загрузки: чуть опоздал с тапом — всё равно учтём, но только первую оценку.
    ended = now > row["ends_at_utc"]
    if ended and row["load_level"] is not None:
        raise CheckinError("already_set")
    if now > row["ends_at_utc"] + LIVE_WINDOW:
        raise CheckinError("not_ongoing")
    await session.execute(
        text("UPDATE ice_checkins SET load_level = :lv, load_set_at = :now WHERE id = :id"),
        {"lv": int(level), "now": now, "id": int(checkin_id)},
    )
    live = await session_live(session, [int(row["session_id"])], now)
    return {"live": live.get(int(row["session_id"]))}


async def record_intent(
    session: AsyncSession, telegram_id: int, session_id: int, kind: str
) -> None:
    """«Открыл»/«Маршрут» по сеансу сегодня — кандидат на вопрос бота. Идемпотентно."""
    if kind not in ("view", "route"):
        raise CheckinError("bad_kind")
    await session.execute(
        text(
            """
            INSERT INTO ice_checkin_intents (telegram_id, session_id, kind)
            VALUES (:t, :s, :k)
            ON CONFLICT (telegram_id, session_id, kind) DO NOTHING
            """
        ),
        {"t": int(telegram_id), "s": int(session_id), "k": kind},
    )


async def record_helps(session: AsyncSession, viewer_telegram_id: int, session_id: int, now: datetime) -> int:
    """«Помог выбрать»: зритель открыл сеанс, где есть чужие свежие оценки загрузки.

    Засчитываем каждому репортёру по одному разу на (viewer, session): своих отметок
    не считаем, оценки старше 40 минут — тоже. Возвращает число новых строк.
    """
    cutoff = now - LIVE_WINDOW
    res = await session.execute(
        text(
            """
            INSERT INTO ice_checkin_helps (reporter_telegram_id, viewer_telegram_id, session_id, local_date)
            SELECT c.telegram_id, :v, c.session_id, c.local_date
            FROM ice_checkins c
            JOIN ice_sessions s ON s.id = c.session_id
            WHERE c.session_id = :s AND c.counts_for_load AND c.load_level IS NOT NULL
              AND c.telegram_id <> :v
              AND c.created_at >= :cut AND c.created_at <= :now
              AND s.status = 'active' AND s.kind IN ('public_skate','open_ice','family_skate','hockey_practice')
              AND s.starts_at_utc - INTERVAL '15 minutes' <= :now AND s.ends_at_utc > :now
            ON CONFLICT DO NOTHING
            """
        ),
        {"v": int(viewer_telegram_id), "s": int(session_id), "cut": cutoff, "now": now},
    )
    return int(res.rowcount or 0)


async def helped_count(session: AsyncSession, telegram_id: int) -> int:
    return int(
        (
            await session.execute(
                text("SELECT COUNT(*) FROM ice_checkin_helps WHERE reporter_telegram_id = :t"),
                {"t": int(telegram_id)},
            )
        ).scalar()
        or 0
    )


# ── Кандидаты и «на льду» ──────────────────────────────────────────────────


async def candidate_rows(session: AsyncSession, now: datetime) -> list[Mapping[str, Any]]:
    """Сеансы, идущие сейчас, и люди, которым можно спросить «Ты на катке?».

    Причины (приоритет в порядке перечисления):
    - intent: открыл сеанс в приложении сегодня или жал «Маршрут»;
    - home: «Мой каток» = каток сеанса + регулярный ритм (прошлая отметка на этом катке
      в ту же группу дней ±60 мин от начала за последние 6 недель);
    - regular: регулярный ритм без «Моего катка».

    Строки: {telegram_id, session_id, arena_id, reason, due_at} — дедупликация по
    (telegram_id, session_id) с первой причиной по приоритету.
    """
    rows = (
        (
            await session.execute(
                text(
                    """
                    WITH ongoing AS (
                        SELECT s.id, s.arena_id, s.starts_at_utc, s.ends_at_utc, s.local_date,
                               s.starts_at_local
                        FROM ice_sessions s
                        JOIN arenas a ON a.id = s.arena_id
                        LEFT JOIN arena_profiles p ON p.arena_id = a.id
                        WHERE s.status = 'active'
                          AND s.kind IN ('public_skate','open_ice','family_skate','hockey_practice')
                          AND s.starts_at_utc - INTERVAL '15 minutes' <= :now
                          AND s.ends_at_utc > :now
                          AND s.starts_at_utc + INTERVAL '20 minutes' <= :now
                          AND s.ends_at_utc - (s.starts_at_utc + INTERVAL '20 minutes') >= INTERVAL '30 minutes'
                          AND (p.status IS NULL OR p.status = 'published')
                          AND a.is_active AND a.is_confirmed
                    ),
                    intents AS (
                        SELECT i.telegram_id, i.session_id, 'intent' AS reason, 1 AS prio
                        FROM ice_checkin_intents i
                        JOIN ongoing o ON o.id = i.session_id
                        WHERE i.created_at >= ((:now AT TIME ZONE 'Europe/Minsk')::date)::timestamptz
                    ),
                    regulars AS (
                        SELECT DISTINCT c.telegram_id, o.id AS session_id,
                               CASE WHEN pref.home_arena_id = c.arena_id THEN 'home' ELSE 'regular' END AS reason,
                               CASE WHEN pref.home_arena_id = c.arena_id THEN 2 ELSE 3 END AS prio
                        FROM ice_checkins c
                        JOIN ongoing o ON o.arena_id = c.arena_id
                        LEFT JOIN client_account_prefs pref ON pref.account_key = c.telegram_id
                        WHERE c.created_at >= :now - INTERVAL '42 days'
                          AND c.created_at < :now - INTERVAL '1 day'
                          AND CASE EXTRACT(ISODOW FROM c.local_date)::int
                                WHEN 6 THEN 'sat' WHEN 7 THEN 'sun' ELSE 'weekday' END
                            = CASE EXTRACT(ISODOW FROM o.local_date)::int
                                WHEN 6 THEN 'sat' WHEN 7 THEN 'sun' ELSE 'weekday' END
                          AND ABS(EXTRACT(EPOCH FROM (
                                (o.local_date + o.starts_at_local)
                                - (c.local_date + (SELECT starts_at_local FROM ice_sessions WHERE id = c.session_id))
                              ))) <= 3600
                    ),
                    cand AS (
                        SELECT * FROM intents
                        UNION ALL SELECT * FROM regulars
                    )
                    SELECT DISTINCT ON (c.telegram_id, c.session_id)
                           c.telegram_id, c.session_id, o.arena_id, c.reason,
                           o.starts_at_utc + INTERVAL '20 minutes' AS due_at
                    FROM cand c JOIN ongoing o ON o.id = c.session_id
                    ORDER BY c.telegram_id, c.session_id, c.prio
                    """
                ),
                {"now": now},
            )
        )
        .mappings()
        .all()
    )
    return list(rows)


async def _home_arena_ids(session: AsyncSession, telegram_ids: list[int]) -> dict[int, int]:
    if not telegram_ids:
        return {}
    rows = (
        await session.execute(
            text("SELECT account_key, home_arena_id FROM client_account_prefs WHERE account_key = ANY(:ids)"),
            {"ids": [int(t) for t in telegram_ids]},
        )
    ).all()
    return {int(r[0]): int(r[1]) for r in rows if r[1] is not None}


async def on_ice_for(
    session: AsyncSession, telegram_id: int, profile_id: int | None, now: datetime
) -> dict[str, Any] | None:
    """Лучший идущий сеанс для карточки «на катке» на главной.

    Приоритет: уже отмеченный → intent сегодня → «Мой каток» → регулярный ритм.
    """
    rows = (
        (
            await session.execute(
                text(
                    """
                    WITH ongoing AS (
                        SELECT s.id, s.arena_id, s.starts_at_utc, s.ends_at_utc, s.local_date,
                               s.starts_at_local, s.ends_at_local, s.kind,
                               a.name AS arena_name
                        FROM ice_sessions s
                        JOIN arenas a ON a.id = s.arena_id
                        LEFT JOIN arena_profiles p ON p.arena_id = a.id
                        WHERE s.status = 'active'
                          AND s.kind IN ('public_skate','open_ice','family_skate','hockey_practice')
                          AND s.starts_at_utc - INTERVAL '15 minutes' <= :now
                          AND s.ends_at_utc > :now
                          AND (p.status IS NULL OR p.status = 'published')
                          AND a.is_active AND a.is_confirmed
                    ),
                    mine AS (
                        SELECT c.session_id, c.id AS checkin_id, c.load_level, 1 AS prio
                        FROM ice_checkins c JOIN ongoing o ON o.id = c.session_id
                        WHERE c.telegram_id = :t AND COALESCE(c.profile_id, 0) = :p
                    ),
                    intents AS (
                        SELECT i.session_id, NULL::bigint AS checkin_id, NULL::int AS load_level, 2 AS prio
                        FROM ice_checkin_intents i JOIN ongoing o ON o.id = i.session_id
                        WHERE i.telegram_id = :t
                          AND i.created_at >= ((:now AT TIME ZONE 'Europe/Minsk')::date)::timestamptz
                    ),
                    home AS (
                        SELECT o.id AS session_id, NULL::bigint AS checkin_id, NULL::int AS load_level, 3 AS prio
                        FROM ongoing o
                        JOIN client_account_prefs pref ON pref.account_key = :t
                          AND pref.home_arena_id = o.arena_id
                        WHERE EXISTS (
                            SELECT 1 FROM ice_checkins c JOIN ice_sessions ps ON ps.id = c.session_id
                            WHERE c.telegram_id = :t AND c.arena_id = o.arena_id
                              AND c.created_at >= :now - INTERVAL '42 days'
                        )
                    ),
                    regulars AS (
                        SELECT DISTINCT o.id AS session_id, NULL::bigint AS checkin_id, NULL::int AS load_level, 4 AS prio
                        FROM ongoing o
                        JOIN ice_checkins c ON c.telegram_id = :t AND c.arena_id = o.arena_id
                        JOIN ice_sessions ps ON ps.id = c.session_id
                        WHERE c.created_at >= :now - INTERVAL '42 days'
                          AND c.created_at < :now - INTERVAL '1 day'
                          AND CASE EXTRACT(ISODOW FROM c.local_date)::int
                                WHEN 6 THEN 'sat' WHEN 7 THEN 'sun' ELSE 'weekday' END
                            = CASE EXTRACT(ISODOW FROM o.local_date)::int
                                WHEN 6 THEN 'sat' WHEN 7 THEN 'sun' ELSE 'weekday' END
                          AND ABS(EXTRACT(EPOCH FROM (
                                (o.local_date + o.starts_at_local) - (c.local_date + ps.starts_at_local)
                              ))) <= 3600
                    )
                    SELECT * FROM (
                        SELECT * FROM mine
                        UNION ALL SELECT * FROM intents
                        UNION ALL SELECT * FROM home
                        UNION ALL SELECT * FROM regulars
                    ) c
                    JOIN ongoing o ON o.id = c.session_id
                    ORDER BY c.prio, o.starts_at_utc
                    LIMIT 1
                    """
                ),
                {"t": int(telegram_id), "p": int(profile_id or 0), "now": now},
            )
        )
        .mappings()
        .first()
    )
    if rows is None:
        return None
    session_id = int(rows["session_id"])
    live = (await session_live(session, [session_id], now)).get(session_id)
    return {
        "session_id": session_id,
        "arena_id": int(rows["arena_id"]),
        "arena_name": rows["arena_name"],
        "kind": rows["kind"],
        "starts_at_utc": rows["starts_at_utc"],
        "ends_at_utc": rows["ends_at_utc"],
        "starts_local": str(rows["starts_at_local"])[:5],
        "ends_local": str(rows["ends_at_local"])[:5],
        "local_date": rows["local_date"],
        "minutes_left": max(0, int((rows["ends_at_utc"] - now).total_seconds() // 60)),
        "checked_in": rows["checkin_id"] is not None,
        "checkin_id": int(rows["checkin_id"]) if rows["checkin_id"] is not None else None,
        "load_level": rows["load_level"],
        "live": live,
    }
