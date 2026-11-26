"""TASK-452 (этап 5.5): загрузка «обычно» из истории отметок + сетка «Когда свободнее».

Без жёсткого порога данных (решение от 24.11): правило админа из
``session_load`` — prior с весом ``PRIOR_WEIGHT`` отметок; реальные отметки
``ice_checkins.load_level`` за ~8 недель его вытесняют по мере накопления.
При нуле отметок «обычно» равно текущей admin-оценке — фича видна с первого дня.

Ячейка = (каток, день недели, часовая корзина). Оценка::

    (prior·W0 + Σ_ячейки + 0.5·Σ_типа_дня) / (W0 + n_ячейки + 0.5·n_типа_дня)

«Тип дня» — будни/выходные: оценки той же корзины других дней того же типа
подтягивают ячейку с половинным весом. Округление: <1.67 → 1, <2.33 → 2, иначе 3.
prior=None, если правила для ячейки нет; ячейка без отметок и без правила —
«мало данных» (уровень None).

Всё живёт только в путях miniapp под ``redesign_s5``: публичные страницы и
выключенный флаг видят чистую admin-оценку ``typical_load_level`` как раньше.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_checkins import MINSK
from src.application.session_load import (
    LEVEL_BUSY,
    LEVEL_CALM,
    LEVEL_MEDIUM,
    LoadLevel,
    SessionLoadContext,
    TYPICAL_LOAD_SESSION_KINDS,
    load_session_load_context,
    resolve_level_opt,
    _parse_local_time,
)

# ── Константы модели ─────────────────────────────────────────────────────────

# Окно истории — «последние ~8 недель» из спеки.
USUAL_WINDOW_DAYS = 56

# Вес prior'а: правило админа ≈ 4 отметки. Меньше — история быстро ломает
# аккуратно выставленные правила; больше — реальные отметки почти не двигают
# оценку и смысл фичи теряется.
PRIOR_WEIGHT = 4.0

# Отметки той же корзины в другие дни того же типа (будни/выходные) весят вдвое
# меньше своих: пятница ближе к вторнику, чем к субботе, но не то же самое.
DAYTYPE_WEIGHT = 0.5

# Часовые корзины по макету F: подписи строк — репрезентативные часы.
# Границы: утро 06–12, день 12–17, вечер 17–20, поздно 20–06.
BUCKET_LABEL_HOURS = (10, 14, 18, 20)
BUCKET_TIMES = (dt_time(10, 0), dt_time(14, 0), dt_time(18, 0), dt_time(20, 0))

NUM_TO_KEY: dict[int, LoadLevel] = {1: LEVEL_CALM, 2: LEVEL_MEDIUM, 3: LEVEL_BUSY}
KEY_TO_NUM: dict[LoadLevel, int] = {v: k for k, v in NUM_TO_KEY.items()}
NUM_TO_WORD = {1: "свободно", 2: "в меру", 3: "людно"}

_WEEKDAY_ACC = (
    "в понедельник", "во вторник", "в среду", "в четверг",
    "в пятницу", "в субботу", "в воскресенье",
)
_WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

_CACHE_TTL_SEC = 60.0
_cache_mono: float | None = None
_cache_ctx: UsualLoadContext | None = None


def bucket_for_hour(hour: int) -> int:
    """Час начала сеанса → индекс корзины 0..3 (10/14/18/20)."""
    if 6 <= hour < 12:
        return 0
    if 12 <= hour < 17:
        return 1
    if 17 <= hour < 20:
        return 2
    return 3


def daytype_of(weekday: int) -> str:
    """wd — пн..пт, we — сб/вс. Отметки типа дня подтягивают ячейку с полвеса."""
    return "we" if int(weekday) >= 5 else "wd"


def round_level(value: float) -> int:
    """Непрерывная оценка → 1..3: <1.67 свободно, <2.33 в меру, иначе людно."""
    if value < 1.67:
        return 1
    if value < 2.33:
        return 2
    return 3


def blend_value(
    prior: int | None,
    cell_sum: int,
    cell_n: int,
    daytype_sum: int,
    daytype_n: int,
) -> float | None:
    """Взвешенное среднее prior + ячейка + тип дня. ``None`` — данных нет вовсе."""
    if prior is None and cell_n == 0 and daytype_n == 0:
        return None
    num = (prior or 0) * PRIOR_WEIGHT + cell_sum + DAYTYPE_WEIGHT * daytype_sum
    den = (PRIOR_WEIGHT if prior is not None else 0.0) + cell_n + DAYTYPE_WEIGHT * daytype_n
    if den <= 0:
        return None
    return num / den


@dataclass(frozen=True)
class UsualLoadContext:
    """Агрегаты отметок за окно + правила admin-загрузки.

    ``cells[(arena_id, weekday 0..6, bucket)]`` = (Σ уровней, n отметок);
    ``dts[(arena_id, bucket, 'wd'|'we')]`` — то же по типу дня (ячейка входит
    в сумму своего типа — задумано: свои отметки весят 1 + 0.5).
    """

    cells: Mapping[tuple[int, int, int], tuple[int, int]]
    dts: Mapping[tuple[int, int, str], tuple[int, int]]
    totals: Mapping[int, int]
    load: SessionLoadContext


def invalidate_usual_cache() -> None:
    global _cache_mono, _cache_ctx
    _cache_mono = None
    _cache_ctx = None


_USUAL_SQL = """
    SELECT c.arena_id AS arena_id,
           (EXTRACT(ISODOW FROM c.local_date)::int - 1) AS weekday,
           CASE
               WHEN EXTRACT(HOUR FROM s.starts_at_local) >= 20
                 OR EXTRACT(HOUR FROM s.starts_at_local) < 6 THEN 3
               WHEN EXTRACT(HOUR FROM s.starts_at_local) >= 17 THEN 2
               WHEN EXTRACT(HOUR FROM s.starts_at_local) >= 12 THEN 1
               ELSE 0
           END AS bucket,
           SUM(c.load_level)::int AS s,
           COUNT(*)::int AS n
    FROM ice_checkins c
    JOIN ice_sessions s ON s.id = c.session_id
    WHERE c.counts_for_load AND c.load_level IS NOT NULL
      AND c.local_date >= :since
    GROUP BY 1, 2, 3
"""


async def load_usual_context(session: AsyncSession, *, now: datetime | None = None) -> UsualLoadContext:
    """Контекст «обычно»: агрегаты ice_checkins за окно + SessionLoadContext.

    Кэш 60 с, как у ``load_session_load_context``: история движется медленно,
    а запрос — один GROUP BY на страницу катка / вкладку «Лёд».
    """
    global _cache_mono, _cache_ctx
    now_mono = time.monotonic()
    if _cache_ctx is not None and _cache_mono is not None and now_mono - _cache_mono < _CACHE_TTL_SEC:
        return _cache_ctx

    now = now or datetime.now(timezone.utc)
    since = now.astimezone(MINSK).date() - timedelta(days=USUAL_WINDOW_DAYS)
    rows = (await session.execute(text(_USUAL_SQL), {"since": since})).mappings().all()

    cells: dict[tuple[int, int, int], tuple[int, int]] = {}
    dts: dict[tuple[int, int, str], tuple[int, int]] = {}
    totals: dict[int, int] = {}
    for r in rows:
        key = (int(r["arena_id"]), int(r["weekday"]), int(r["bucket"]))
        s, n = int(r["s"]), int(r["n"])
        cells[key] = (s, n)
        totals[key[0]] = totals.get(key[0], 0) + n
        dk = (key[0], key[2], daytype_of(key[1]))
        ps, pn = dts.get(dk, (0, 0))
        dts[dk] = (ps + s, pn + n)

    ctx = UsualLoadContext(
        cells=cells, dts=dts, totals=totals,
        load=await load_session_load_context(session),
    )
    _cache_mono = now_mono
    _cache_ctx = ctx
    return ctx


def _prior_level(
    ctx: UsualLoadContext, *, arena_id: int, weekday: int, starts_at_local: dt_time | str
) -> int | None:
    """prior ячейки — правило админа (+характер катка); None, когда правила нет."""
    character = ctx.load.character_by_arena.get(int(arena_id), "steady")
    level = resolve_level_opt(
        ctx.load.rules,
        arena_id=int(arena_id),
        character=character,
        local_weekday=int(weekday),
        starts_at_local=starts_at_local,
    )
    return KEY_TO_NUM.get(level) if level is not None else None


def usual_level(
    ctx: UsualLoadContext,
    *,
    arena_id: int,
    weekday: int,
    starts_at_local: dt_time | str,
) -> int | None:
    """Blended уровень ячейки (1..3); ``None`` — ни правила, ни отметок.

    prior оценивается на ``starts_at_local``: у сеанса — своё время начала,
    у ячейки сетки — репрезентативный час корзины (сетка грубее сеанса).
    """
    hour = _parse_local_time(starts_at_local).hour
    bucket = bucket_for_hour(hour)
    prior = _prior_level(
        ctx, arena_id=arena_id, weekday=weekday, starts_at_local=starts_at_local
    )
    cell_sum, cell_n = ctx.cells.get((int(arena_id), int(weekday), bucket), (0, 0))
    dt_sum, dt_n = ctx.dts.get((int(arena_id), bucket, daytype_of(weekday)), (0, 0))
    value = blend_value(prior, cell_sum, cell_n, dt_sum, dt_n)
    return round_level(value) if value is not None else None


def usual_fields(
    ctx: UsualLoadContext, *, arena_id: int, weekday: int, starts_at_local: dt_time | str
) -> dict[str, str] | None:
    """``{"key": "calm|medium|busy", "word": "свободно|в меру|людно"}`` или None."""
    level = usual_level(
        ctx, arena_id=arena_id, weekday=weekday, starts_at_local=starts_at_local
    )
    if level is None:
        return None
    return {"key": NUM_TO_KEY[level], "word": NUM_TO_WORD[level]}


def usual_for_session(
    ctx: UsualLoadContext,
    *,
    arena_id: int,
    kind: str,
    local_date: Any,
    starts_at_local: dt_time | str,
) -> dict[str, str] | None:
    """«Обычно» конкретного сеанса — только для видов из ``TYPICAL_LOAD_SESSION_KINDS``."""
    if str(kind or "") not in TYPICAL_LOAD_SESSION_KINDS:
        return None
    if isinstance(local_date, datetime):
        local_date = local_date.date()
    elif not isinstance(local_date, date):
        try:
            local_date = date.fromisoformat(str(local_date)[:10])
        except ValueError:
            return None
    return usual_fields(
        ctx, arena_id=arena_id, weekday=local_date.weekday(), starts_at_local=starts_at_local
    )


def _best_text(cells: list[list[int | None]]) -> str | None:
    """«Свободнее всего — будни в 10:00 и 14:00»: argmin по уровням ячеек."""
    flat = [
        (wd, b, lv)
        for b in range(len(BUCKET_LABEL_HOURS))
        for wd in range(7)
        if (lv := cells[b][wd]) is not None
    ]
    if not flat:
        return None
    low = min(lv for _, _, lv in flat)
    if low == 3:
        return None  # всё известное людно — «свободнее» рекомендовать нечего
    at_min = [(wd, b) for wd, b, lv in flat if lv == low]
    wd_cells = [c for c in at_min if c[0] <= 4]
    we_cells = [c for c in at_min if c[0] >= 5]
    # Обобщаем до типа дня, только когда покрыта реально вся группа
    # (будни ≥3 дней, выходные — и сб, и вс): иначе «выходные» по одной
    # субботе солгало бы про воскресенье. Не хватило — называем дни.
    if len({wd for wd, _ in wd_cells}) >= 3 and len(wd_cells) >= len(we_cells):
        scope, use = "будни", wd_cells
    elif {wd for wd, _ in we_cells} == {5, 6} and len(we_cells) > len(wd_cells):
        scope, use = "выходные", we_cells
    else:
        days = sorted({wd for wd, _ in at_min})
        scope, use = " и ".join(_WEEKDAY_ACC[d] for d in days[:3]), at_min
    hours = [f"{h}:00" for h in sorted({BUCKET_LABEL_HOURS[b] for _, b in use})[:3]]
    hours_text = hours[0] if len(hours) == 1 else ", ".join(hours[:-1]) + " и " + hours[-1]
    lead = "Свободнее всего" if low == 1 else "Спокойнее всего"
    return f"{lead} — {scope} в " + hours_text


def arena_usual_grid(ctx: UsualLoadContext, arena_id: int) -> dict[str, Any] | None:
    """Сетка «Когда свободнее» для страницы катка.

    ``cells[bucket][weekday]`` = уровень 1..3 или ``None`` («мало данных» —
    ни отметок, ни правила). ``None`` всего блока — у катка нет ни одной
    отметки и ни одного правила: показывать нечего.
    """
    arena_id = int(arena_id)
    cells: list[list[int | None]] = []
    has_prior = False
    for b in range(len(BUCKET_LABEL_HOURS)):
        row: list[int | None] = []
        for wd in range(7):
            # prior ячейки — на репрезентативном часе корзины (сетка грубее сеанса).
            prior = _prior_level(
                ctx, arena_id=arena_id, weekday=wd, starts_at_local=BUCKET_TIMES[b]
            )
            if prior is not None:
                has_prior = True
            cell_sum, cell_n = ctx.cells.get((arena_id, wd, b), (0, 0))
            dt_sum, dt_n = ctx.dts.get((arena_id, b, daytype_of(wd)), (0, 0))
            value = blend_value(prior, cell_sum, cell_n, dt_sum, dt_n)
            row.append(round_level(value) if value is not None else None)
        cells.append(row)
    total = int(ctx.totals.get(arena_id, 0))
    if total == 0 and not has_prior:
        return None
    return {
        "total": total,
        "buckets": list(BUCKET_LABEL_HOURS),
        "weekdays": list(_WEEKDAYS_SHORT),
        "cells": cells,
        "best": _best_text(cells),
    }
