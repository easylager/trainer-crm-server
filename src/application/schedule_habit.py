"""Привычка катка выкладывать расписание — наблюдение по волнам (TASK-329).

Дату мы не обещаем: карточка говорит «обычно выкладывает расписание по пятницам».
Чистые функции без БД.

``schedule_habit(waves, tz)`` → ``{level, weekday}``:

* ``day`` — ≥3 волн в ≥3 разных ISO-неделях и ≥75% из них в один день недели W;
  ``weekday`` = W (0 — понедельник … 6 — воскресенье).
* ``week`` — иначе ≥2 волн и медиана промежутков 5–9 дней; ``weekday`` = ``None``.
* ``none`` — всё остальное: мало волн, разброс, «скользящее окно» (медиана
  промежутков ≤2 дней — новые дни добавляются каждую ночь).

Функции передаются волны окна (``waves_in_window``: последние 42 дня от ``now``).
``seed`` — точка отсчёта, а не публикация, и не считается. Волны ближе 6 ч к
предыдущей учтённой сливаются в одну (тот же порог, что у восстановления по журналу
прогонов): источник, выложивший неделю двумя заходами за час, — одна публикация.
Дни недели и промежутки считаются по датам в поясе катка.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from statistics import median
from typing import Any, Iterable
from zoneinfo import ZoneInfo

SOURCE_SEED = "seed"

WINDOW = timedelta(days=42)
MERGE_WITHIN = timedelta(hours=6)

DAY_MIN_WAVES = 3
DAY_MIN_ISO_WEEKS = 3
# 75% — как дробь, чтобы граница считалась без плавающей точки.
DAY_SHARE_NUM = 3
DAY_SHARE_DEN = 4

WEEK_MIN_WAVES = 2
WEEK_GAP_MIN_DAYS = 5
WEEK_GAP_MAX_DAYS = 9
SLIDING_GAP_MAX_DAYS = 2

LEVEL_DAY = "day"
LEVEL_WEEK = "week"
LEVEL_NONE = "none"

_DEFAULT_TZ = "Europe/Minsk"


@dataclass(frozen=True)
class ScheduleWave:
    detected_at: datetime
    source: str


def no_habit() -> dict[str, Any]:
    return {"level": LEVEL_NONE, "weekday": None}


def resolve_zone(tz: str | tzinfo | None) -> tzinfo:
    if isinstance(tz, tzinfo):
        return tz
    name = str(tz or "").strip() or _DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 — кривой пояс в профиле не должен ронять карточку
        return ZoneInfo(_DEFAULT_TZ)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def window_start(now: datetime) -> datetime:
    return _aware(now) - WINDOW


def waves_in_window(waves: Iterable[ScheduleWave], *, now: datetime) -> list[ScheduleWave]:
    """Волны за последние 42 дня до ``now`` включительно (будущие — нет)."""
    now = _aware(now)
    start = now - WINDOW
    return [w for w in waves if w.detected_at is not None and start <= _aware(w.detected_at) <= now]


def wave_days(waves: Iterable[ScheduleWave], tz: str | tzinfo | None) -> list[date]:
    """Даты волн в поясе катка, без seed, слитые по 6 ч, по возрастанию."""
    zone = resolve_zone(tz)
    moments = sorted(
        _aware(w.detected_at)
        for w in waves
        if w.source != SOURCE_SEED and w.detected_at is not None
    )
    kept: list[datetime] = []
    for moment in moments:
        if kept and moment - kept[-1] < MERGE_WITHIN:
            continue
        kept.append(moment)
    return [moment.astimezone(zone).date() for moment in kept]


def _iso_week(day: date) -> tuple[int, int]:
    iso = day.isocalendar()
    return iso[0], iso[1]


def schedule_habit(waves: Iterable[ScheduleWave], tz: str | tzinfo | None) -> dict[str, Any]:
    days = wave_days(waves, tz)
    if len(days) < WEEK_MIN_WAVES:
        return no_habit()
    gaps = [(later - earlier).days for earlier, later in zip(days, days[1:])]
    typical_gap = median(gaps)
    if typical_gap <= SLIDING_GAP_MAX_DAYS:
        return no_habit()

    if len(days) >= DAY_MIN_WAVES and len({_iso_week(d) for d in days}) >= DAY_MIN_ISO_WEEKS:
        weekday, count = Counter(d.weekday() for d in days).most_common(1)[0]
        if count * DAY_SHARE_DEN >= len(days) * DAY_SHARE_NUM:
            return {"level": LEVEL_DAY, "weekday": weekday}

    if WEEK_GAP_MIN_DAYS <= typical_gap <= WEEK_GAP_MAX_DAYS:
        return {"level": LEVEL_WEEK, "weekday": None}
    return no_habit()
