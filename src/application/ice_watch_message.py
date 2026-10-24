"""Тексты колокольчика на карточке катка (TASK-328).

Чистые функции без БД и aiogram: текст проверяется тестом, а не глазами в боте.
Типографика — по craft-guide: ёлочки, неразрывный пробел после предлогов и между числом
и словом, время без ведущего нуля у часа, без emoji.
"""

from __future__ import annotations

import html
from datetime import date, time

from src.shared.public_display import format_public_name

NBSP = " "

_MONTHS_GEN = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

# «в субботу», «во вторник» — винительный падеж с предлогом.
_WEEKDAYS_ACC = (
    f"в{NBSP}понедельник",
    f"во{NBSP}вторник",
    f"в{NBSP}среду",
    f"в{NBSP}четверг",
    f"в{NBSP}пятницу",
    f"в{NBSP}субботу",
    f"в{NBSP}воскресенье",
)

OPEN_SCHEDULE_BUTTON = "Открыть расписание"


def quoted_place_name(raw_name: str) -> str:
    """Имя места в ёлочках, как в заголовке страницы места; HTML-экранировано.

    «Юность» → «Юность»; ХК «Юность» → «ХК „Юность“» (вложенные — лапки).
    """
    name = format_public_name(raw_name) or "Каток"
    if name.startswith("«") and name.endswith("»") and name.count("«") == 1:
        inner = name[1:-1]
    else:
        inner = name.replace("«", "„").replace("»", "“")
    return html.escape(f"«{inner}»", quote=False)


def _day_month(day: date) -> str:
    return f"{day.day}{NBSP}{_MONTHS_GEN[day.month - 1]}"


def _clock(value: time) -> str:
    return f"{value.hour}:{value.minute:02d}"


def format_dates_range(first: date, last: date) -> str:
    """«31 октября», «2–8 ноября», «31 октября – 6 ноября»."""
    if first == last:
        return _day_month(first)
    if (first.year, first.month) == (last.year, last.month):
        return f"{first.day}–{last.day}{NBSP}{_MONTHS_GEN[first.month - 1]}"
    return f"{_day_month(first)}{NBSP}– {_day_month(last)}"


def format_nearest(day: date, starts: time, *, today: date) -> str:
    """«сегодня в 17:00», «завтра в 17:00», «в субботу, 31 октября, 17:00»."""
    if day == today:
        return f"сегодня в{NBSP}{_clock(starts)}"
    if (day - today).days == 1:
        return f"завтра в{NBSP}{_clock(starts)}"
    return f"{_WEEKDAYS_ACC[day.weekday()]}, {_day_month(day)}, {_clock(starts)}"


def compose_new_schedule_message(
    *,
    arena_name: str,
    first_date: date,
    last_date: date,
    nearest_date: date,
    nearest_time: time,
    today: date,
) -> str:
    """Уведомление «у катка появилось новое расписание» (HTML для Telegram)."""
    return (
        f"<b>{quoted_place_name(arena_name)}: новое расписание</b>\n"
        f"Сеансы на{NBSP}{format_dates_range(first_date, last_date)}.\n"
        f"Ближайший{NBSP}— {format_nearest(nearest_date, nearest_time, today=today)}."
    )


def compose_watch_subscribed_reply(arena_name: str) -> str:
    """Ответ бота на ``/start watch_<arena_id>``."""
    return f"Готово. Напишем один раз, когда у{NBSP}{quoted_place_name(arena_name)} появится новое расписание."


def watch_subscribed_button_text(arena_name: str) -> str:
    """Кнопка WebApp: «Открыть «Юность»». Текст кнопки — не HTML."""
    return f"Открыть {html.unescape(quoted_place_name(arena_name))}"
