"""
Окна времени каталога и «умный дефолт» (TASK-146, Q-006).

Человек открывает каталог не «вообще», а с вопросом «куда сегодня вечером?» или
«что на выходных?». Умный дефолт отвечает на этот вопрос сам — по дню недели и часу
в Минске, без истории клиента (честно и не трогает персональные данные, Q-008):

* до 21:00 — «Сегодня вечером» (с 16:00 или с текущего момента), в том числе в пятницу;
* после 21:00 — «Завтра»;
* с пятницы 21:00 до воскресенья 21:00 — «В выходные».

«В выходные» — суббота и воскресенье, без пятничного вечера. Пятница в окне давала
карточку «Сегодня 16:15» под этим чипом: формально верно, а для человека —
обман, он читает чип как субботу. Пятничный вечер честно живёт в «Сегодня вечером».

Окна считаются здесь, на сервере, а клиент получает уже готовые ключ и подпись:
один источник правды, и подпись чипа всегда совпадает с тем, что реально отфильтровано.

Если в окне ничего нет, лента не пустеет: показываем ближайшее, что реально есть, и
честно говорим «в это время сеансов нет» (это делает ``list_public_ice_arenas``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from src.shared.copy_ru import t
from src.shared.notification_hours import NOTIFICATION_TZ

WHEN_KEYS = ("auto", "today_evening", "today", "tomorrow", "weekend", "any")

_DAY_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DAY_HORIZON_DAYS = 14

_EVENING_FROM = time(16, 0)
_LATE = time(21, 0)

_WEEKDAYS_SHORT_RU = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
_MONTHS_SHORT_RU = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")


@dataclass(frozen=True)
class TimeWindow:
    key: str
    label: str
    starts_at: datetime  # UTC, включительно
    ends_at: datetime  # UTC, не включительно
    local_date: str | None = None  # YYYY-MM-DD для key == "day"

    def as_payload(self) -> dict[str, str]:
        payload = {
            "key": self.key,
            "label": self.label,
            "from": self.starts_at.isoformat(),
            "to": self.ends_at.isoformat(),
        }
        if self.local_date:
            payload["date"] = self.local_date
        return payload


def auto_window_key(now: datetime) -> str:
    """Ключ умного дефолта по местному времени (правила — в докстринге модуля)."""
    local = now.astimezone(ZoneInfo(NOTIFICATION_TZ))
    weekday = local.weekday()  # 0 = понедельник
    t = local.time()
    is_weekend_stretch = (weekday == 4 and t >= _LATE) or weekday == 5 or (weekday == 6 and t < _LATE)
    if is_weekend_stretch:
        return "weekend"
    if t >= _LATE:
        return "tomorrow"
    return "today_evening"


def resolve_window(raw: str | None, now: datetime | None = None) -> TimeWindow | None:
    """``None`` — без окна (любое время). Неизвестный ключ — тоже без окна, не ошибка."""
    now = now or datetime.now(timezone.utc)
    key = (raw or "").strip().lower()
    if key in ("", "any") or key not in WHEN_KEYS:
        return None
    if key == "auto":
        key = auto_window_key(now)
    tz = ZoneInfo(NOTIFICATION_TZ)
    local = now.astimezone(tz)
    today = local.date()

    def at(day, hh_mm: time) -> datetime:
        return datetime.combine(day, hh_mm, tzinfo=tz).astimezone(timezone.utc)

    end_of_today = at(today + timedelta(days=1), time(0, 0))
    if key == "today":
        return TimeWindow("today", t("when.today"), now, end_of_today)
    if key == "today_evening":
        return TimeWindow(
            "today_evening", t("when.evening"), max(now, at(today, _EVENING_FROM)), end_of_today
        )
    if key == "tomorrow":
        tomorrow = today + timedelta(days=1)
        return TimeWindow(
            "tomorrow",
            t("when.tomorrow"),
            at(tomorrow, time(0, 0)),
            at(tomorrow + timedelta(days=1), time(0, 0)),
        )
    # weekend: суббота 00:00 — конец воскресенья; уже идут выходные — с текущего момента.
    if today.weekday() in (5, 6):
        saturday = today - timedelta(days=today.weekday() - 5)
    else:
        saturday = today + timedelta(days=5 - today.weekday())
    monday = saturday + timedelta(days=2)
    return TimeWindow(
        "weekend", t("when.weekend"), max(now, at(saturday, time(0, 0))), at(monday, time(0, 0))
    )


def _minsk_today(now: datetime) -> date:
    return now.astimezone(ZoneInfo(NOTIFICATION_TZ)).date()


def day_window_label(target: date, today: date) -> str:
    if target == today + timedelta(days=1):
        return t("when.tomorrow")
    wd = _WEEKDAYS_SHORT_RU[target.weekday()]
    return f"{wd}, {target.day} {_MONTHS_SHORT_RU[target.month - 1]}"


def parse_calendar_day(raw: str | None, now: datetime | None = None) -> date | None:
    """Календарный день YYYY-MM-DD в горизонте каталога (сегодня … +14 дней)."""
    now = now or datetime.now(timezone.utc)
    text = (raw or "").strip()
    m = _DAY_ISO_RE.match(text)
    if not m:
        return None
    try:
        target = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    today = _minsk_today(now)
    if target < today or target > today + timedelta(days=_DAY_HORIZON_DAYS):
        return None
    return target


def resolve_day_window(target: date, now: datetime | None = None) -> TimeWindow:
    now = now or datetime.now(timezone.utc)
    tz = ZoneInfo(NOTIFICATION_TZ)
    today = _minsk_today(now)
    label = day_window_label(target, today)

    def at(day: date, hh_mm: time) -> datetime:
        return datetime.combine(day, hh_mm, tzinfo=tz).astimezone(timezone.utc)

    start = at(target, time(0, 0))
    if target == today:
        start = now
    end = at(target + timedelta(days=1), time(0, 0))
    return TimeWindow("day", label, start, end, local_date=target.isoformat())


def resolve_list_window(
    when: str | None,
    day: str | None = None,
    now: datetime | None = None,
) -> TimeWindow | None:
    """Окно для ленты: ``day`` (конкретный будний день) важнее ``when``."""
    now = now or datetime.now(timezone.utc)
    parsed = parse_calendar_day(day, now)
    if parsed is not None:
        today = _minsk_today(now)
        if parsed == today + timedelta(days=1):
            return resolve_window("tomorrow", now)
        return resolve_day_window(parsed, now)
    return resolve_window(when, now)
