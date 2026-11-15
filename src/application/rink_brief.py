"""TASK-424: строка-ответ у расписания катка и штамп «Проверено DD.MM».

Чистые функции от сеансов, которые уже лежат в ``load_place_view`` (сегодня + 6 дней).
Строка-ответ попадает в сниппет поисковика и живёт там неделями, поэтому в ней нет
«сегодня», «завтра» и дат — только то, что верно, пока не поменялась сама сетка.

Правила честности (PDEC-030):
- каждое число — из сеансов; нет данных — нет фразы;
- дни недели называем, только если сеансы опубликованы на всю неделю вперёд и про
  сегодняшний день недели что-то известно (уже начавшиеся сеансы в окно не попадают);
  иначе — только длительность и время начала;
- штамп ставим только на свежие данные: с сайта катка — не старше 48 ч и не «stale»,
  ручное расписание — правка не старше 3 дней.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.application.ice_city_day import format_price_minor, plural_ru

# Города, где у катков есть строка-ответ и штамп. Регионы ранжируются хорошо как есть —
# их страницы не меняются ни на байт, пока здесь не появится их слаг.
RINK_BRIEF_CITIES: frozenset[str] = frozenset({"minsk"})

WEEK_DAYS = 7
BRIEF_MAX = 150
AUTO_FRESH = timedelta(hours=48)
MANUAL_FRESH = timedelta(days=3)
_MINSK = ZoneInfo("Europe/Minsk")

_DOW = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_EVENING_FROM = 17 * 60
_MORNING_BEFORE = 12 * 60


def brief_enabled(city_slug: str) -> bool:
    return city_slug in RINK_BRIEF_CITIES


# ── разбор сеансов ─────────────────────────────────────────────────────────


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _minutes(value: Any) -> int | None:
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    raw = str(value or "").strip()
    head, _, tail = raw.partition(":")
    if not head.isdigit() or len(tail) < 2 or not tail[:2].isdigit():
        return None
    return int(head) * 60 + int(tail[:2])


def _clock(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d}"


@dataclass(frozen=True)
class _Slot:
    day: date
    start: int
    duration: int | None


def _slots(rows: Sequence[Mapping[str, Any]], *, today: date) -> list[_Slot]:
    out: list[_Slot] = []
    last = today + timedelta(days=WEEK_DAYS - 1)
    for row in rows:
        day = _as_date(row.get("local_date"))
        start = _minutes(row.get("starts_at_local"))
        if day is None or start is None or not today <= day <= last:
            continue
        end = _minutes(row.get("ends_at_local"))
        dur = end - start if end is not None else None
        out.append(_Slot(day=day, start=start, duration=dur if dur and 0 < dur <= 360 else None))
    return out


def flatten_days(days: Sequence[Mapping[str, Any]] | None) -> list[Mapping[str, Any]]:
    return [s for d in days or [] for s in d.get("sessions") or []]


# ── части фразы ─────────────────────────────────────────────────────────────


def _days_phrase(weekdays: set[int]) -> tuple[str, bool]:
    """(фраза, ключевая ли): «каждый день» / «по будням» — ключевые, «пн и ср–вс» — список."""
    if weekdays == set(range(7)):
        return "каждый день", True
    if weekdays == set(range(5)):
        return "по будням", True
    if weekdays == {5, 6}:
        return "по выходным", True
    ordered = sorted(weekdays)
    runs: list[list[int]] = []
    for wd in ordered:
        if runs and wd == runs[-1][-1] + 1:
            runs[-1].append(wd)
        else:
            runs.append([wd])
    items: list[str] = []
    for run in runs:
        if len(run) >= 3:
            items.append(f"{_DOW[run[0]]}–{_DOW[run[-1]]}")
        else:
            items.extend(_DOW[wd] for wd in run)
    if len(items) == 1:
        return items[0], False
    return f"{', '.join(items[:-1])} и {items[-1]}", False


def _duration_phrase(slots: Sequence[_Slot]) -> str:
    durations = sorted({s.duration for s in slots if s.duration})
    if not durations:
        return ""
    if len(durations) == 1:
        n = durations[0]
        return f"{n} {plural_ru(n, 'минуту', 'минуты', 'минут')}"
    return f"{durations[0]}–{durations[-1]} минут"


def _starts_phrase(slots: Sequence[_Slot], *, today: date, joiner: str = "и") -> str:
    starts = sorted({s.start for s in slots})
    by_day: dict[date, set[int]] = {}
    for s in slots:
        by_day.setdefault(s.day, set()).add(s.start)
    full = [v for d, v in by_day.items() if d != today]
    same_grid = bool(full) and all(v == set(starts) for v in full) and by_day.get(today, set()) <= set(starts)
    steps = {b - a for a, b in zip(starts, starts[1:])}
    if same_grid and len(starts) >= 4 and len(steps) == 1:
        step = steps.pop()
        if step == 60:
            return f"каждый час с {_clock(starts[0])} до {_clock(starts[-1])}"
        if 30 <= step <= 180:
            return f"каждые {step} минут с {_clock(starts[0])} до {_clock(starts[-1])}"
    if len(starts) <= 3:
        labels = [_clock(m) for m in starts]
        if len(labels) == 1:
            return f"в {labels[0]}"
        return f"в {', '.join(labels[:-1])} {joiner} {labels[-1]}"
    return f"начало с {_clock(starts[0])} до {_clock(starts[-1])}"


def _part_of_day(slots: Sequence[_Slot]) -> str:
    starts = [s.start for s in slots]
    if starts and min(starts) >= _EVENING_FROM:
        return "только вечером"
    if starts and max(starts) < _MORNING_BEFORE:
        return "только утром"
    return ""


def _upper(text: str) -> str:
    return text[:1].upper() + text[1:]


# ── строка-ответ ────────────────────────────────────────────────────────────


def _weekly_line(slots: Sequence[_Slot], *, today: date) -> str | None:
    """Фраза с днями недели — только при полной публикации и известном сегодняшнем дне."""
    by_day = Counter(s.day for s in slots)
    if today + timedelta(days=WEEK_DAYS - 1) not in by_day or today not in by_day:
        return None
    weekdays = {d.weekday() for d in by_day}
    days, keyword = _days_phrase(weekdays)
    counts = [n for d, n in by_day.items() if d != today]
    dur = _duration_phrase(slots)
    by = f" по {dur}" if dur else ""
    lo, hi = min(counts), max(counts)
    if lo == hi and by_day[today] <= hi:
        n = hi
        if n == 1:
            starts = _starts_phrase(slots, today=today, joiner="или")
            return f"{_upper(days)} — один сеанс в день{by}, {starts}."
        starts = _starts_phrase(slots, today=today)
        word = plural_ru(n, "сеанс", "сеанса", "сеансов")
        if keyword:
            return f"{_upper(days)} {n} {word}{by} — {starts}."
        return f"{_upper(days)}: {n} {word} в день{by} — {starts}."
    word = plural_ru(hi, "сеанс", "сеанса", "сеансов")
    part = _part_of_day(slots)
    head = f"{_upper(days)}, {part}" if part else _upper(days)
    starts = _starts_phrase(slots, today=today)
    return f"{head}: {lo}–{hi} {word} в день{by}, {starts}."


def _partial_line(slots: Sequence[_Slot], *, today: date) -> str:
    dur = _duration_phrase(slots)
    starts = _starts_phrase(slots, today=today)
    if dur:
        return f"Сеансы по {dur} — {starts}."
    if starts.startswith("начало "):
        return f"Сеансы начинаются {starts.removeprefix('начало ')}."
    if starts.startswith("в "):
        return f"Сеансы начинаются {starts}."
    return f"Сеансы {starts}."


def schedule_line(rows: Sequence[Mapping[str, Any]], *, today: date) -> str | None:
    """«Каждый день 13 сеансов по 45 минут — каждый час с 10:15 до 22:15.» или ``None``."""
    slots = _slots(rows, today=today)
    if not slots:
        return None
    for build in (_weekly_line, _partial_line):
        line = build(slots, today=today)
        if line and len(line) <= BRIEF_MAX:
            return line
    return None


def ohm_line(rows: Sequence[Mapping[str, Any]], *, today: date) -> str | None:
    """Та же строка для вкладки ОХМ: «ОХМ: пн, вт, чт и вс — один сеанс в день…»."""
    line = schedule_line(rows, today=today)
    if not line:
        return None
    return f"ОХМ: {line[:1].lower()}{line[1:]}"


def weekend_price_note(rows: Sequence[Mapping[str, Any]], *, currency: str) -> str | None:
    """«В сб и вс взрослый — 11 BYN.» — только если цена выходных отличается от будней."""
    weekday: set[int] = set()
    weekend: set[int] = set()
    for row in rows:
        day = _as_date(row.get("local_date"))
        price = row.get("price_adult_minor")
        if price is None:
            price = row.get("price_minor")
        if day is None or price is None:
            continue
        (weekend if day.weekday() >= 5 else weekday).add(int(price))
    if not weekday or not weekend or min(weekday) == min(weekend):
        return None
    prefix = "от " if len(weekend) > 1 else ""
    return f"В сб и вс взрослый — {prefix}{format_price_minor(min(weekend), currency)}."


# ── штамп свежести ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProofStamp:
    day_label: str  # «16.11» — по Минску
    source_url: str | None  # сайт катка: только у расписания, которое мы снимаем с сайта


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def proof_stamp(freshness: Mapping[str, Any] | None, *, now: datetime) -> ProofStamp | None:
    """Штамп для свежего расписания, иначе ``None`` (несвежее чиним, а не подписываем)."""
    if not isinstance(freshness, Mapping):
        return None
    observed = _as_utc(freshness.get("schedule_observed_at"))
    if observed is None:
        return None
    moment = _as_utc(now)
    if moment is None:
        return None
    age = moment - observed
    if age < -timedelta(minutes=5):  # часы источника впереди — не верим
        return None
    auto = bool(freshness.get("schedule_auto"))
    if auto and (freshness.get("schedule_stale") or age > AUTO_FRESH):
        return None
    if not auto and age > MANUAL_FRESH:
        return None
    local = observed.astimezone(_MINSK).date()
    source = str(freshness.get("source_url") or "").strip() if auto else ""
    return ProofStamp(day_label=f"{local.day:02d}.{local.month:02d}", source_url=source or None)


SEASON_NO_DATE_LINE = "Дату открытия мы пока не знаем."


__all__ = [
    "BRIEF_MAX",
    "ProofStamp",
    "RINK_BRIEF_CITIES",
    "SEASON_NO_DATE_LINE",
    "brief_enabled",
    "flatten_days",
    "ohm_line",
    "proof_stamp",
    "schedule_line",
    "weekend_price_note",
]
