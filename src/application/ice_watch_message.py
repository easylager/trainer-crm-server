"""Тексты колокольчика на карточке катка (TASK-328).

Чистые функции без БД и aiogram: текст проверяется тестом, а не глазами в боте.
Типографика — по craft-guide: ёлочки, неразрывный пробел после предлогов и между числом
и словом, время без ведущего нуля у часа, без emoji.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
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

_WEEKDAYS_NOM = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")

OPEN_SCHEDULE_BUTTON = "Открыть расписание"
CANCEL_WATCH_BUTTON = "Отменить рассылку"
WATCH_OFF_PREFIX = "iwatch_off:"


def open_ice_in_city_button(city_name: str | None) -> str:
    """Кнопка к ответу на подписку: «Лёд в Минске».

    Падеж — из ``city_locative``. Нет формы — «Лёд в городе …», без кривого склонения.
    """
    from src.shared.city_locative import city_locative

    raw = (city_name or "").strip()
    public = format_public_name(raw) if raw else ""
    loc = (city_locative(public) or city_locative(raw)) if raw else None
    if loc:
        return f"Лёд в{NBSP}{loc}"
    if public:
        return f"Лёд в городе{NBSP}{public}"
    return OPEN_SCHEDULE_BUTTON


def place_name(raw_name: str) -> str:
    """Имя места как в заголовке страницы места на сайте; HTML-экранировано.

    Без своих кавычек поверх: «ЛД «Гранд Каньон Айс»» остаётся как есть,
    «Каток хк "Юность"» → «Каток ХК «Юность»».
    """
    return html.escape(format_public_name(raw_name) or "Каток", quote=False)


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
        f"<b>{place_name(arena_name)}: новое расписание</b>\n"
        f"Сеансы на{NBSP}{format_dates_range(first_date, last_date)}.\n"
        f"Ближайший{NBSP}— {format_nearest(nearest_date, nearest_time, today=today)}."
    )


def compose_watch_subscribed_reply(arena_name: str) -> str:
    """Ответ бота на ``/start watch_<arena_id>``; кнопка — ``open_ice_in_city_button``.

    Имя в именительном (как «…: новое расписание»): без «за» и кривого склонения катка.
    """
    name = place_name(arena_name)
    shown = name if name.startswith("«") and name.endswith("»") else f"«{name}»"
    return f"<b>{shown}: следим</b>\nНапишем, когда расписание обновится."


@dataclass(frozen=True)
class WatchSession:
    """Сеанс для письма подписчику: день, время и цены как на странице катка (цены — в копейках)."""

    day: date
    starts: time
    ends: time | None = None
    kind: str = "public_skate"
    price_adult: int | None = None
    price_child: int | None = None
    price_rental: int | None = None
    price: int | None = None
    currency: str = "BYN"


_SHOWN_PER_MESSAGE = 8
_CURRENCY = {"BYN": "BYN", "RUB": "₽"}


def _money(minor: int, currency: str) -> str:
    whole, cents = divmod(int(minor), 100)
    value = f"{whole}" if not cents else f"{whole},{cents:02d}"
    return f"{value}{NBSP}{_CURRENCY.get(currency, currency)}"


def _prices(s: WatchSession) -> tuple[tuple[str, int], ...]:
    tiers = (("взрослый", s.price_adult), ("детский", s.price_child), ("прокат", s.price_rental))
    named = tuple((label, int(v)) for label, v in tiers if v is not None)
    if named:
        return named
    return (("", int(s.price)),) if s.price is not None else ()


def _price_text(prices: tuple[tuple[str, int], ...], currency: str) -> str:
    return " · ".join(f"{label}{NBSP}{_money(v, currency)}" if label else _money(v, currency) for label, v in prices)


def _day_title(day: date, *, today: date) -> str:
    """«Сегодня, 20 ноября», «Завтра, 21 ноября», «Суббота, 22 ноября»."""
    if day == today:
        head = "Сегодня"
    elif (day - today).days == 1:
        head = "Завтра"
    else:
        head = _WEEKDAYS_NOM[day.weekday()]
    return f"{head}, {_day_month(day)}"


def _interval(s: WatchSession) -> str:
    return f"{_clock(s.starts)}–{_clock(s.ends)}" if s.ends else _clock(s.starts)


def compose_schedule_change_message(
    *,
    arena_name: str,
    added: list[WatchSession],
    removed: list[WatchSession],
    today: date,
    city_name: str | None = None,
    address: str | None = None,
) -> str:
    """Письмо подписчику катка: что появилось и что отменили (HTML для Telegram).

    Шапка — место, город и адрес; новые сеансы — по дням, с временем начала и конца. Одинаковые цены — одной строкой
    под списком, разные — в строке сеанса. Больше восьми — «и ещё N». Кнопки: ``OPEN_SCHEDULE_BUTTON`` и
    ``CANCEL_WATCH_BUTTON`` (callback).
    """
    where = " · ".join(
        html.escape(bit, quote=False) for bit in (format_public_name(city_name or ""), (address or "").strip()) if bit
    )
    parts = [f"<b>{place_name(arena_name)}</b>"] + ([where] if where else [])
    if added:
        shown = added[:_SHOWN_PER_MESSAGE]
        kinds = {s.kind for s in shown}
        parts += ["", "<b>Новые сеансы массового катания</b>" if kinds == {"public_skate"} else "<b>Новые сеансы</b>"]
        price_sets = {(_prices(s), s.currency) for s in shown}
        common = len(price_sets) == 1 and next(iter(price_sets))[0]
        day: date | None = None
        for s in shown:
            if s.day != day:
                day = s.day
                parts.append(_day_title(s.day, today=today))
            line = _interval(s)
            if not common and _prices(s):
                line += f" · {_price_text(_prices(s), s.currency)}"
            parts.append(line)
        if len(added) > len(shown):
            parts.append(f"и ещё {len(added) - len(shown)}")
        if common:
            currency = next(iter(price_sets))[1]
            parts += ["", f"Цена: {_price_text(next(iter(price_sets))[0], currency)}"]
    if removed:
        shown_r = removed[:_SHOWN_PER_MESSAGE]
        parts += ["", "<b>Отменили</b>"]
        parts += [f"{_day_title(s.day, today=today)}, {_clock(s.starts)}" for s in shown_r]
        if len(removed) > len(shown_r):
            parts.append(f"и ещё {len(removed) - len(shown_r)}")
    return "\n".join(parts)


def watch_off_callback_data(watch_id: int) -> str:
    return f"{WATCH_OFF_PREFIX}{int(watch_id)}"


def parse_watch_off_callback(data: str | None) -> int | None:
    raw = data or ""
    if not raw.startswith(WATCH_OFF_PREFIX):
        return None
    tail = raw[len(WATCH_OFF_PREFIX) :]
    return int(tail) if tail.isdigit() and 0 < int(tail) < 2**31 else None
