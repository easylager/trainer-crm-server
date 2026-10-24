"""Когда каток выложит новое расписание — простое обещание по волнам (TASK-329).

Чистая функция без БД. Вход — волны публикации катка (``ice_schedule_waves``),
сегодняшняя дата катка и его часовой пояс. Выход — ``{level, date, week}``:

* ``day`` — каток выкладывает расписание в один и тот же день недели W:
  ≥3 волн в ≥3 разных ISO-неделях, ≥75% из них в W, последняя тоже в W.
  ``date`` — ближайший W строго после последней волны (= последняя + 7 дней);
  если он уже прошёл (``date < today``) — обещание сорвано, молчим.
* ``week`` — ритм примерно недельный: ≥2 волн, медиана промежутков 5–9 дней.
  Ожидаем последнюю + 7 дней; прошло — молчим. ``week`` = ``this``/``next``
  по ISO-неделе относительно ``today`` (дальше цель не бывает). ``date`` не отдаём:
  день здесь не обещан.
* ``none`` — всё остальное, в том числе «скользящее окно» (медиана ≤2 дней:
  новые дни добавляются каждую ночь) и мало данных.

Учитываются волны за последние 42 дня (``[today − 41, today]`` по дате катка),
кроме ``seed`` — это точка отсчёта, а не публикация. Волны ближе 6 ч к
предыдущей учтённой сливаются в одну (тот же порог, что у восстановления по
журналу прогонов): источник, выложивший неделю двумя заходами за час, — одна
публикация, а не две.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from statistics import median
from typing import Any, Iterable
from zoneinfo import ZoneInfo

SOURCE_SEED = "seed"

WINDOW_DAYS = 42
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

EXPECTED_PERIOD = timedelta(days=7)

LEVEL_DAY = "day"
LEVEL_WEEK = "week"
LEVEL_NONE = "none"
WEEK_THIS = "this"
WEEK_NEXT = "next"

_DEFAULT_TZ = "Europe/Minsk"


@dataclass(frozen=True)
class ScheduleWave:
    detected_at: datetime
    source: str


def no_promise() -> dict[str, Any]:
    return {"level": LEVEL_NONE, "date": None, "week": None}


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


def _iso_week(day: date) -> tuple[int, int]:
    iso = day.isocalendar()
    return iso[0], iso[1]


def _week_relation(target: date, today: date) -> str:
    """``this``/``next`` по ISO-неделе.

    Цель всегда в ``[today, today + 7]``: последняя волна не позже ``today`` (будущие
    отброшены), цель = она + 7, прошедшая цель отсекается раньше. Поэтому дальше
    следующей недели цель не бывает, и третьего исхода («иначе none») нет.
    """
    return WEEK_THIS if _iso_week(target) == _iso_week(today) else WEEK_NEXT


def wave_days(waves: Iterable[ScheduleWave], *, today: date, tz: str | tzinfo | None) -> list[date]:
    """Даты волн (по поясу катка) в окне 42 дней, без seed, слитые по 6 ч, по возрастанию."""
    zone = resolve_zone(tz)
    window_start = today - timedelta(days=WINDOW_DAYS - 1)
    moments = sorted(
        _aware(w.detected_at)
        for w in waves
        if w.source != SOURCE_SEED and w.detected_at is not None
    )
    kept: list[datetime] = []
    for moment in moments:
        local_day = moment.astimezone(zone).date()
        if local_day < window_start or local_day > today:
            continue
        if kept and moment - kept[-1] < MERGE_WITHIN:
            continue
        kept.append(moment)
    return [moment.astimezone(zone).date() for moment in kept]


def schedule_promise(
    waves: Iterable[ScheduleWave], today: date, tz: str | tzinfo | None
) -> dict[str, Any]:
    days = wave_days(waves, today=today, tz=tz)
    if len(days) < WEEK_MIN_WAVES:
        return no_promise()
    gaps = [(later - earlier).days for earlier, later in zip(days, days[1:])]
    typical_gap = median(gaps)
    if typical_gap <= SLIDING_GAP_MAX_DAYS:
        return no_promise()

    last = days[-1]
    if len(days) >= DAY_MIN_WAVES and len({_iso_week(d) for d in days}) >= DAY_MIN_ISO_WEEKS:
        weekday, count = Counter(d.weekday() for d in days).most_common(1)[0]
        if count * DAY_SHARE_DEN >= len(days) * DAY_SHARE_NUM and last.weekday() == weekday:
            promised = last + EXPECTED_PERIOD  # ближайший W строго после последней волны
            if promised < today:
                return no_promise()
            week = _week_relation(promised, today)
            return {"level": LEVEL_DAY, "date": promised, "week": week}

    if WEEK_GAP_MIN_DAYS <= typical_gap <= WEEK_GAP_MAX_DAYS:
        expected = last + EXPECTED_PERIOD
        if expected < today:
            return no_promise()
        week = _week_relation(expected, today)
        return {"level": LEVEL_WEEK, "date": None, "week": week}
    return no_promise()
