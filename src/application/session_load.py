"""Типичная загрузка сеанса по правилам дня и часа (TASK-290)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LoadLevel = str  # calm | medium | busy

LEVEL_CALM: LoadLevel = "calm"
LEVEL_MEDIUM: LoadLevel = "medium"
LEVEL_BUSY: LoadLevel = "busy"
LOAD_LEVELS: tuple[LoadLevel, ...] = (LEVEL_CALM, LEVEL_MEDIUM, LEVEL_BUSY)

LOAD_LABELS: dict[LoadLevel, str] = {
    LEVEL_CALM: "Свободно",
    LEVEL_MEDIUM: "Средне",
    LEVEL_BUSY: "Людно",
}

# Слово уровня живёт в «Выбранном сеансе» и в доступном имени; на квадрате — только черточки.
LOAD_PLAN_LINES: dict[LoadLevel, str] = {
    LEVEL_CALM: "Обычно свободно в это время",
    LEVEL_MEDIUM: "Обычно народу в меру",
    LEVEL_BUSY: "Обычно людно в это время",
}


def load_meter_html(level: object) -> str:
    """Три черточки шкалы. Неизвестный уровень — пустая строка, без заглушки."""
    if not isinstance(level, str) or level not in LOAD_PLAN_LINES:
        return ""
    return (
        f'<span class="b-load" data-level="{level}" role="img" aria-label="{LOAD_PLAN_LINES[level]}">'
        "<i></i><i></i><i></i></span>"
    )


TYPICAL_LOAD_SESSION_KINDS = frozenset({"public_skate", "open_ice", "hockey_practice"})

DAY_MON_THU = "mon_thu"
DAY_FRI = "fri"
DAY_SAT = "sat"
DAY_SUN = "sun"

_SCOPE_ALL = "all"
_SCOPE_CHARACTER = "character"
_SCOPE_ARENA = "arena"

_CACHE_TTL_SEC = 60.0
_cache_mono: float | None = None
_cache_ctx: SessionLoadContext | None = None


@dataclass(frozen=True)
class LoadRule:
    id: int
    scope: str
    character: str | None
    arena_id: int | None
    day_group: str
    starts_from: dt_time
    starts_before: dt_time | None
    level: LoadLevel
    source: str

    @property
    def specificity(self) -> int:
        if self.scope == _SCOPE_ARENA:
            return 3
        if self.scope == _SCOPE_CHARACTER:
            return 2
        return 1

    def interval_minutes(self) -> int:
        end = self.starts_before or dt_time(23, 59, 59)
        start_m = self.starts_from.hour * 60 + self.starts_from.minute
        end_m = end.hour * 60 + end.minute
        if end_m <= start_m and self.starts_before is None:
            return 24 * 60 - start_m
        width = end_m - start_m
        return max(width, 1)


@dataclass(frozen=True)
class SessionLoadContext:
    rules: tuple[LoadRule, ...]
    character_by_arena: dict[int, str]


def invalidate_session_load_cache() -> None:
    global _cache_mono, _cache_ctx
    _cache_mono = None
    _cache_ctx = None


def weekday_to_day_group(weekday: int) -> str:
    if weekday <= 3:
        return DAY_MON_THU
    if weekday == 4:
        return DAY_FRI
    if weekday == 5:
        return DAY_SAT
    return DAY_SUN


def _parse_local_time(value: Any) -> dt_time:
    if isinstance(value, dt_time):
        return value.replace(tzinfo=None)
    if isinstance(value, datetime):
        return value.time().replace(tzinfo=None)
    text_val = str(value or "").strip()
    if not text_val:
        return dt_time(0, 0)
    parts = text_val.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    return dt_time(hour, minute)


def _time_in_interval(starts_at_local: dt_time, starts_from: dt_time, starts_before: dt_time | None) -> bool:
    if starts_at_local < starts_from:
        return False
    if starts_before is None:
        return True
    return starts_at_local < starts_before


def _shift_level(level: LoadLevel, character: str) -> LoadLevel:
    if character == "quiet":
        if level == LEVEL_BUSY:
            return LEVEL_MEDIUM
        if level == LEVEL_MEDIUM:
            return LEVEL_CALM
        return LEVEL_CALM
    if character == "hot":
        if level == LEVEL_CALM:
            return LEVEL_MEDIUM
        if level == LEVEL_MEDIUM:
            return LEVEL_BUSY
        return LEVEL_BUSY
    return level


def resolve_level(
    rules: Sequence[LoadRule],
    *,
    arena_id: int,
    character: str,
    local_weekday: int,
    starts_at_local: dt_time | str,
) -> LoadLevel:
    """Самое конкретное правило + сдвиг характера, если победило не правило арены."""
    start = _parse_local_time(starts_at_local)
    day_group = weekday_to_day_group(int(local_weekday))
    matching: list[LoadRule] = []
    for rule in rules:
        if rule.day_group != day_group:
            continue
        if not _time_in_interval(start, rule.starts_from, rule.starts_before):
            continue
        if rule.scope == _SCOPE_ARENA and rule.arena_id != int(arena_id):
            continue
        if rule.scope == _SCOPE_CHARACTER and rule.character != character:
            continue
        matching.append(rule)

    if not matching:
        return LEVEL_MEDIUM

    def sort_key(r: LoadRule) -> tuple[int, int]:
        return (r.specificity, -r.interval_minutes())

    winner = max(matching, key=sort_key)
    level = winner.level
    if winner.scope == _SCOPE_ARENA and winner.arena_id == int(arena_id):
        return level
    return _shift_level(level, character)


def typical_load_fields(
    ctx: SessionLoadContext,
    *,
    arena_id: int,
    kind: str,
    local_date: date | str,
    starts_at_local: dt_time | str,
) -> dict[str, str] | None:
    if kind not in TYPICAL_LOAD_SESSION_KINDS:
        return None
    # Публичная страница не должна падать из-за шкалы: нет дня или часа — нет уровня.
    if not str(starts_at_local or "").strip():
        return None
    if isinstance(local_date, datetime):
        local_date = local_date.date()
    elif not isinstance(local_date, date):
        try:
            local_date = date.fromisoformat(str(local_date)[:10])
        except ValueError:
            return None
    character = ctx.character_by_arena.get(int(arena_id), "steady")
    level = resolve_level(
        ctx.rules,
        arena_id=int(arena_id),
        character=character,
        local_weekday=local_date.weekday(),
        starts_at_local=starts_at_local,
    )
    return {
        "typical_load_level": level,
        "typical_load_label": LOAD_LABELS[level],
    }


def attach_typical_load(session: dict[str, Any], ctx: SessionLoadContext) -> None:
    fields = typical_load_fields(
        ctx,
        arena_id=int(session["arena_id"]),
        kind=str(session.get("kind") or ""),
        local_date=session.get("local_date") or "",
        starts_at_local=session.get("starts_at_local") or "",
    )
    if fields:
        session.update(fields)


def attach_typical_load_many(sessions: Iterable[dict[str, Any]], ctx: SessionLoadContext) -> None:
    for item in sessions:
        attach_typical_load(item, ctx)


async def load_session_load_context(session: AsyncSession) -> SessionLoadContext:
    global _cache_mono, _cache_ctx
    now = time.monotonic()
    if _cache_ctx is not None and _cache_mono is not None and now - _cache_mono < _CACHE_TTL_SEC:
        return _cache_ctx

    # Один запрос на правила и нестандартные характеры: страница места не платит лишним
    # обращением к БД (TASK-197), а «steady» — значение по умолчанию и в выборку не входит.
    rows = (
        await session.execute(
            text(
                """
                SELECT 'rule' AS row_kind, id, scope, character, arena_id, day_group,
                       starts_from, starts_before, level, source
                FROM session_load_rules
                UNION ALL
                SELECT 'character', NULL, NULL, load_character, arena_id, NULL,
                       NULL::time, NULL::time, NULL, NULL
                FROM arena_profiles
                WHERE load_character <> 'steady'
                """
            )
        )
    ).fetchall()
    rules = tuple(
        LoadRule(
            id=int(r[1]),
            scope=str(r[2]),
            character=str(r[3]) if r[3] is not None else None,
            arena_id=int(r[4]) if r[4] is not None else None,
            day_group=str(r[5]),
            starts_from=r[6],
            starts_before=r[7],
            level=str(r[8]),
            source=str(r[9]),
        )
        for r in sorted((r for r in rows if r[0] == "rule"), key=lambda r: int(r[1]))
    )
    character_by_arena = {int(r[4]): str(r[3]) for r in rows if r[0] == "character"}
    ctx = SessionLoadContext(rules=rules, character_by_arena=character_by_arena)
    _cache_mono = now
    _cache_ctx = ctx
    return ctx


async def enrich_sessions_with_typical_load(
    session: AsyncSession, sessions: Iterable[dict[str, Any]]
) -> None:
    ctx = await load_session_load_context(session)
    attach_typical_load_many(sessions, ctx)


async def enrich_arena_day_payload(session: AsyncSession, days: list[dict[str, Any]]) -> None:
    ctx = await load_session_load_context(session)
    for day in days:
        attach_typical_load_many(day.get("sessions") or [], ctx)
