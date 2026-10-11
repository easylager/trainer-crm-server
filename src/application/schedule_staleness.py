"""Как пользователю показать, что расписание арены устарело (TASK-180).

Правила свежести (пороги, якорь «последний удачный прогон») — ``src/ingestion/freshness.py``;
здесь — слова и загрузка полей для SSR-страниц, которые выбирают сеансы своим SQL
(``/ice/{город}/today``, ``/c/``, ``/p/``, тизер хаба), а не через публичное API.

Три уровня:

* ``fresh`` — показываем как есть;
* ``stale`` (> 6 ч без удачного прогона) — сеансы показываем как есть.
  Каталог не пишет, что расписание могло измениться: показанное время и есть ответ;
* ``very_stale`` (> 72 ч) — сеансы **не** выдаём за расписание:
  «Расписание не обновлялось 4 дня — уточните по телефону».

Арены без парсера (ручные сеансы) всегда ``fresh`` — так решено в TASK-180.
Все даты — по Минску. Те же строки собирает фронт (``arena-card-model.js``,
``ice-tab-model.js``); тексты держать в паре.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_session_use_cases import STATUS_ACTIVE

MINSK_TZ = ZoneInfo("Europe/Minsk")

LEVEL_FRESH = "fresh"
LEVEL_STALE = "stale"
LEVEL_VERY_STALE = "very_stale"

_MONTHS_SHORT = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")

# Короткая метка для каталога. Пустая: показанное расписание не сопровождаем оговоркой.
STALE_SHORT = ""
UNCONFIRMED_HEADING = "Расписание не подтверждено"


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def staleness_level(freshness: Mapping[str, Any] | None) -> str:
    fresh = freshness or {}
    if not fresh.get("schedule_stale"):
        return LEVEL_FRESH
    if fresh.get("schedule_very_stale"):
        return LEVEL_VERY_STALE
    return LEVEL_STALE


def minsk_days_between(earlier: datetime, now: datetime) -> int:
    """Календарные сутки по Минску между моментами (а не по UTC — TASK-180 AC-3)."""
    a = earlier.astimezone(MINSK_TZ).date()
    b = now.astimezone(MINSK_TZ).date()
    return (b - a).days


def checked_at_label(observed: Any, *, now: datetime) -> str:
    """«сегодня в 09:10» / «вчера в 18:40» / «3 окт в 18:40» — по Минску."""
    moment = _parse_dt(observed)
    if moment is None:
        return ""
    local = moment.astimezone(MINSK_TZ)
    hhmm = f"{local.hour:02d}:{local.minute:02d}"
    days = minsk_days_between(moment, now)
    if days <= 0:
        return f"сегодня в {hhmm}"
    if days == 1:
        return f"вчера в {hhmm}"
    return f"{local.day} {_MONTHS_SHORT[local.month - 1]} в {hhmm}"


def _plural_days(n: int) -> str:
    n_abs = abs(int(n))
    mod10, mod100 = n_abs % 10, n_abs % 100
    if mod10 == 1 and mod100 != 11:
        return f"{n_abs} день"
    if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
        return f"{n_abs} дня"
    return f"{n_abs} дней"


def stale_note(freshness: Mapping[str, Any] | None, *, now: datetime) -> str:
    """Каталог не оговаривает свежесть сеансов строкой. Пусто всегда.

    Уровень ``stale`` по-прежнему считается (флаг API, алерты). ``now`` оставлен,
    чтобы вызовы со страниц не менялись.
    """
    del freshness, now
    return ""


def _ask_tail(*, has_phone: bool, has_site: bool) -> str:
    if has_phone:
        return " — уточните по телефону"
    if has_site:
        return " — уточните на сайте катка"
    return " — уточните у катка"


def very_stale_note(
    freshness: Mapping[str, Any] | None,
    *,
    now: datetime,
    has_phone: bool = True,
    has_site: bool = False,
) -> str:
    """Строка для ``very_stale``: «Расписание не обновлялось 4 дня — уточните по телефону»."""
    if staleness_level(freshness) != LEVEL_VERY_STALE:
        return ""
    tail = _ask_tail(has_phone=has_phone, has_site=has_site)
    observed = _parse_dt((freshness or {}).get("schedule_observed_at"))
    if observed is None:
        return UNCONFIRMED_HEADING + tail
    days = max(1, minsk_days_between(observed, now))
    return f"Расписание не обновлялось {_plural_days(days)}{tail}"


async def load_arena_freshness(
    session: AsyncSession, arena_ids: Iterable[int], *, now: datetime
) -> dict[int, dict[str, Any]]:
    """``freshness`` (как в публичном API) для арен одним запросом, на момент ``now``.

    Тот же расчёт, что ``arena_public_use_cases._schedule_freshness``: якорь — последний
    удачный прогон парсера, создание задания или самое свежее ``observed_at`` текущих сеансов.
    """
    ids = sorted({int(i) for i in arena_ids})
    if not ids:
        return {}
    from src.ingestion.freshness import schedule_freshness_fields

    rows = (
        await session.execute(
            text(
                """
                SELECT a.id AS arena_id,
                       COALESCE(ipj.is_enabled, false) AS job_enabled,
                       ipj.last_ok_at, ipj.config, ipj.created_at AS job_created_at,
                       (
                           SELECT MAX(s.observed_at) FROM ice_sessions s
                           WHERE s.arena_id = a.id AND s.status = :st
                             AND s.kind IN ('public_skate', 'open_ice')
                             AND s.starts_at_utc > :now
                             AND (s.valid_until IS NULL OR s.valid_until >= :now)
                       ) AS sessions_observed_at
                FROM arenas a
                LEFT JOIN ice_parser_jobs ipj ON ipj.arena_id = a.id
                WHERE a.id = ANY(:ids)
                """
            ),
            {"ids": ids, "now": now, "st": STATUS_ACTIVE},
        )
    ).mappings()
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        config = row["config"]
        out[int(row["arena_id"])] = schedule_freshness_fields(
            has_enabled_job=bool(row["job_enabled"]),
            last_ok_at=row["last_ok_at"],
            sessions_observed_at=row["sessions_observed_at"],
            config=config if isinstance(config, Mapping) else None,
            now=now,
            created_at=row["job_created_at"],
        )
    return out


__all__ = [
    "LEVEL_FRESH",
    "LEVEL_STALE",
    "LEVEL_VERY_STALE",
    "STALE_SHORT",
    "UNCONFIRMED_HEADING",
    "checked_at_label",
    "load_arena_freshness",
    "minsk_days_between",
    "stale_note",
    "staleness_level",
    "very_stale_note",
]
