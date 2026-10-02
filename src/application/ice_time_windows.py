"""
Окна времени каталога и «умный дефолт» (TASK-146, Q-006).

Человек открывает каталог не «вообще», а с вопросом «куда сегодня вечером?» или
«что на выходных?». Умный дефолт отвечает на этот вопрос сам — по дню недели и часу
в Минске, без истории клиента (честно и не трогает персональные данные, Q-008):

* будни (пн–чт) до 21:00 — «Сегодня вечером» (с 16:00 или с текущего момента);
* после 21:00 — «Завтра»;
* с четверга 16:00 до воскресенья 21:00 — «Выходные» (пятница вечер — воскресенье).

Окна считаются здесь, на сервере, а клиент получает уже готовые ключ и подпись:
один источник правды, и подпись чипа всегда совпадает с тем, что реально отфильтровано.

Если в окне ничего нет, лента не пустеет: показываем ближайшее, что реально есть, и
честно говорим «в это время сеансов нет» (это делает ``list_public_ice_arenas``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from src.shared.notification_hours import NOTIFICATION_TZ

WHEN_KEYS = ("auto", "today_evening", "today", "tomorrow", "weekend", "any")

_EVENING_FROM = time(16, 0)
_LATE = time(21, 0)


@dataclass(frozen=True)
class TimeWindow:
    key: str
    label: str
    starts_at: datetime  # UTC, включительно
    ends_at: datetime  # UTC, не включительно

    def as_payload(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "from": self.starts_at.isoformat(),
            "to": self.ends_at.isoformat(),
        }


def auto_window_key(now: datetime) -> str:
    """Ключ умного дефолта по местному времени (правила — в докстринге модуля)."""
    local = now.astimezone(ZoneInfo(NOTIFICATION_TZ))
    weekday = local.weekday()  # 0 = понедельник
    t = local.time()
    is_weekend_stretch = (weekday == 3 and t >= _EVENING_FROM) or weekday in (4, 5) or (weekday == 6 and t < _LATE)
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
        return TimeWindow("today", "Сегодня", now, end_of_today)
    if key == "today_evening":
        return TimeWindow("today_evening", "Сегодня вечером", max(now, at(today, _EVENING_FROM)), end_of_today)
    if key == "tomorrow":
        tomorrow = today + timedelta(days=1)
        return TimeWindow("tomorrow", "Завтра", at(tomorrow, time(0, 0)), at(tomorrow + timedelta(days=1), time(0, 0)))
    # weekend: пятница с 16:00 — конец воскресенья; уже идут выходные — с текущего момента.
    days_to_friday = (4 - today.weekday()) % 7
    if today.weekday() in (5, 6):
        days_to_friday = -(today.weekday() - 4)
    friday = today + timedelta(days=days_to_friday)
    monday = friday + timedelta(days=3)
    return TimeWindow("weekend", "Выходные", max(now, at(friday, _EVENING_FROM)), at(monday, time(0, 0)))
