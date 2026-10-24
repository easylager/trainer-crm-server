"""
Публичная страница места — каток, зал, магазин (TASK-146).

Это главный вирусный артефакт каталога. Его открывают три разных человека, и
страница обязана работать для всех трёх с первого ответа сервера, без JS:

* **получатель пересланной ссылки** — у него нет ни бота, ни приложения, часто
  чужой мессенджер (Viber, WhatsApp). Ему нужно: что, когда, сколько стоит, где.
  Если ссылка пришла с конкретным сеансом (``?s=``), этот сеанс — первое, что он
  видит. Если сеанс уже прошёл — честно говорим это и показываем ближайшие;
* **поисковик** — страница отвечает на «массовое катание <каток> расписание»:
  серверный HTML, ``schema.org`` разметка (IceRink/Store + Event на сеансы);
* **тот, кто хочет переслать дальше** — ряд «Поделиться» прямо на странице,
  во все мессенджеры. Цепочка не обрывается на первом получателе.

Структура общая для всех типов (шапка → статус → действия → контакты → доверие),
но середина своя: у льда — расписание по дням, у магазина — услуги, у зала — часы.
Пустая секция не рисуется вовсе: нет данных — нет обещания (тот же принцип, что
tier A/B/C в ``arena_public_use_cases``).

Рендер — подстановка в статический шаблон ``static/share/place.html``, как у
«Лёд сегодня» (``ice_city_day_page``).
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_public_use_cases import (
    get_public_arena_card,
    public_arena_session_days,
)
from src.application.client_share_message import share_body_for_native_share_dialog
from src.application.ice_city_day import format_price_minor, plural_ru
from src.shared.schema_org_event import enrich_ice_session_event
from src.application.arena_profile import (
    has_known_hours,
    hours_groups,
    intervals_for_weekday,
    opening_hours_schema_org,
)
from src.application.ice_city_day import city_slug
from src.application.place_links import join_public_origin, place_query
from src.shared.phone_guard import is_valid_public_phone
from src.shared.arena_schedule_mode import (
    PHONE_LINE,
    SCHEDULE_MODE_PHONE,
    SCHEDULE_MODE_SEASON_CLOSED,
    normalize_schedule_mode,
    season_closed_user_line,
)
from src.shared.copy_ru import t
from src.shared.html_template import fill_placeholders, html_lang_for_country, json_for_script, safe_external_url
from src.shared.public_display import (
    display_host,
    format_clock,
    format_phone_display,
    invite_cta_when,
    format_place_address,
    format_public_name,
    format_street_address,
    sentence_when,
    short_day_word,
)
from src.shared.venue_types import has_public_skating

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "place.html"

#: Сколько дней расписания показывает страница. Неделя — горизонт «планирую выходные».
SCHEDULE_DAYS = 7
#: Сколько дней ищем выбранный сеанс (?s=). Шит «Поделиться» предлагает сеансы из ленты
#: карточки (две недели) — сеанс через 10 дней не должен выглядеть «уже прошедшим».
FOCUS_LOOKUP_DAYS = 14

_WEEKDAYS_SHORT = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
_WEEKDAYS_FULL = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)
_MONTHS_SHORT = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
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
_MONTHS_PREP = (
    "январе",
    "феврале",
    "марте",
    "апреле",
    "мае",
    "июне",
    "июле",
    "августе",
    "сентябре",
    "октябре",
    "ноябре",
    "декабре",
)

#: Услуги магазина — тайлы с короткой подписью, а не просто теги.
_SHOP_SERVICES: tuple[tuple[str, str, str, str], ...] = (
    ("retail", "shop", "Розница", "Коньки, защита, форма"),
    ("skate_sharpening", "sharpen", "Заточка", "Лезвия под ваш стиль катания"),
    ("skate_molding", "skate", "Формовка", "Ботинок по форме стопы"),
    ("blade_profiling", "sharpen", "Профилирование", "Профиль лезвия под игрока"),
    ("foot_scan", "person", "3D-скан стопы", "Точный подбор размера"),
    ("skate_rental", "skate", "Прокат", "Коньки на время"),
    ("repair", "repair", "Ремонт", "Коньки, клюшки, форма"),
)
_SHOP_DISCIPLINES: tuple[tuple[str, str], ...] = (
    ("discipline_hockey", "Хоккей"),
    ("discipline_figure", "Фигурное"),
    ("discipline_roller", "Ролики"),
)
_SCHEMA_TYPES = {
    "ice": "IceRink",
    "gym": "ExerciseGym",
    "choreo": "SportsActivityLocation",
    "pool": "PublicSwimmingPool",
    "outdoor": "SportsActivityLocation",
    "other": "SportsActivityLocation",
    "shop": "SportingGoodsStore",
}


# ---------------------------------------------------------------------------
# Время и цены словами
# ---------------------------------------------------------------------------


def _parse_iso_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _parse_iso_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def day_label(day: date, *, today: date) -> str:
    """«Сегодня» / «Завтра» / «Сб, 4 окт»."""
    if day == today:
        return "Сегодня"
    if day == today + timedelta(days=1):
        return "Завтра"
    return f"{_WEEKDAYS_SHORT[day.weekday()]}, {day.day} {_MONTHS_SHORT[day.month - 1]}"


def day_heading(day: date, *, today: date) -> str:
    """Заголовок группы в расписании: «Сегодня, пятница» / «Суббота, 4 октября»."""
    weekday = _WEEKDAYS_FULL[day.weekday()]
    if day == today:
        return f"Сегодня, {weekday.lower()}"
    if day == today + timedelta(days=1):
        return f"Завтра, {weekday.lower()}"
    return f"{weekday}, {day.day} {_MONTHS_GEN[day.month - 1]}"


def absolute_day_label(day: date) -> str:
    """«Пт, 2 окт» — без «сегодня»: для того, что живёт в чужом кэше дольше суток."""
    return f"{_WEEKDAYS_SHORT[day.weekday()]}, {day.day} {_MONTHS_SHORT[day.month - 1]}"


def slot_when(slot: Mapping[str, Any], *, today: date, absolute: bool = False) -> str:
    """«Сегодня, 20:30» / «Сб, 4 окт, 20:30».

    ``absolute=True`` — для og:title, картинки и текста шеринга. Telegram кэширует
    превью ссылки на дни, а сообщение в чате читают и назавтра: «сегодня» там
    превращается в неправду. «Пт, 2 окт» остаётся верным всегда.
    """
    day = _parse_iso_date(slot.get("local_date"))
    hhmm = str(slot.get("starts_at_local") or "")[:5]
    if day is None:
        return hhmm
    label = absolute_day_label(day) if absolute else day_label(day, today=today)
    return f"{label}, {hhmm}" if hhmm else label


def slot_price(slot: Mapping[str, Any]) -> str:
    """Цена взрослого билета. Неизвестна — пустая строка, а не «0» и не «уточняйте»."""
    currency = str(slot.get("currency_code") or "BYN")
    minor = slot.get("price_adult_minor")
    if minor is None:
        minor = slot.get("price_minor")
    return format_price_minor(minor, currency)


def slot_plan_prices(slot: Mapping[str, Any]) -> tuple[list[tuple[str, str]], str]:
    """Цены билета колонками: подпись и сумма. Примечание — отдельно, не в сетке."""
    currency = str(slot.get("currency_code") or "BYN")
    parts: list[tuple[str, str]] = []
    adult = slot.get("price_adult_minor")
    if adult is None:
        adult = slot.get("price_minor")
    if adult is not None:
        parts.append(("Взрослый", format_price_minor(adult, currency)))
    if slot.get("price_child_minor") is not None:
        parts.append(("Детский", format_price_minor(slot["price_child_minor"], currency)))
    if slot.get("price_rental_minor") is not None:
        parts.append(("Прокат", format_price_minor(slot["price_rental_minor"], currency)))
    return parts, str(slot.get("price_note") or "").strip()


def slot_price_lines(slot: Mapping[str, Any]) -> list[str]:
    currency = str(slot.get("currency_code") or "BYN")
    lines: list[str] = []
    adult = slot.get("price_adult_minor")
    if adult is None:
        adult = slot.get("price_minor")
    if adult is not None:
        lines.append(f"Взрослый — {format_price_minor(adult, currency)}")
    if slot.get("price_child_minor") is not None:
        lines.append(f"Детский — {format_price_minor(slot['price_child_minor'], currency)}")
    if slot.get("price_rental_minor") is not None:
        lines.append(f"Прокат коньков — {format_price_minor(slot['price_rental_minor'], currency)}")
    note = str(slot.get("price_note") or "").strip()
    if note:
        lines.append(note)
    return lines


SOON_MAX_MINUTES = 120


def minutes_until_start(slot: Mapping[str, Any], *, now: datetime) -> int | None:
    """Минуты до начала, если сеанс ещё впереди и не дальше двух часов."""
    starts = _parse_iso_dt(slot.get("starts_at_utc"))
    if starts is None:
        return None
    minutes = int((starts - now).total_seconds() // 60)
    if minutes <= 0 or minutes > SOON_MAX_MINUTES:
        return None
    return minutes


def soon_html(slot: Mapping[str, Any], *, now: datetime) -> str:
    """Точка и «через N мин» у ближайшего сеанса. Дальше двух часов — пусто, остаётся время."""
    minutes = minutes_until_start(slot, now=now)
    starts = _parse_iso_dt(slot.get("starts_at_utc"))
    if minutes is None or starts is None:
        return ""
    return (
        f'<span class="b-soon" data-starts="{_esc(starts.isoformat())}">'
        f'<i class="b-soon__dot" aria-hidden="true"></i>'
        f'<span class="b-soon__label">через {minutes} мин</span></span>'
    )


def plan_status_seats(note: object) -> str:
    """Короткая подпись остатка в строке статуса. Предупреждение остаётся целиком."""
    from src.application.session_load import live_seats_plan_line

    line = live_seats_plan_line(note)
    if line.startswith("Осталось ") and " — " not in line:
        return line.removeprefix("Осталось ")
    return line


def starts_in_label(slot: Mapping[str, Any], *, now: datetime) -> str:
    """«Через 40 минут» — только если до начала меньше трёх часов."""
    starts = _parse_iso_dt(slot.get("starts_at_utc"))
    if starts is None:
        return ""
    minutes = int((starts - now).total_seconds() // 60)
    if minutes <= 0 or minutes > 180:
        return ""
    if minutes < 60:
        return f"Через {minutes} {plural_ru(minutes, 'минуту', 'минуты', 'минут')}"
    hours, rest = divmod(minutes, 60)
    if rest < 10:
        return f"Через {hours} {plural_ru(hours, 'час', 'часа', 'часов')}"
    return f"Через {hours} ч {rest} мин"


def _hhmm_in_interval(hhmm: str, open_: str, close: str) -> bool:
    if close > open_:
        return open_ <= hhmm < close
    return hhmm >= open_ or hhmm < close


def open_now_label(card: Mapping[str, Any], *, now: datetime) -> str:
    """«открыто до 22:00» / «откроется в 10:00» / «Сегодня выходной»."""
    tz = ZoneInfo(str(card.get("timezone") or "Europe/Minsk"))
    local = now.astimezone(tz)
    hours = card.get("opening_hours")
    if not has_known_hours(hours):
        return ""
    intervals = intervals_for_weekday(hours, local.weekday())
    if not intervals:
        return "Сегодня выходной"
    hhmm = local.strftime("%H:%M")
    for open_, close in intervals:
        if _hhmm_in_interval(hhmm, open_, close):
            return f"открыто до {format_clock(close)}"
    for open_, _close in intervals:
        if hhmm < open_:
            return f"откроется в {format_clock(open_)}"
    return "Сегодня уже закрыто"


# ---------------------------------------------------------------------------
# Модель страницы
# ---------------------------------------------------------------------------


async def load_place_view(
    session: AsyncSession,
    arena_ref: str,
    *,
    session_id: int | None = None,
    now: datetime | None = None,
    city_id: int | None = None,
) -> dict[str, Any] | None:
    """Карточка места + неделя расписания + выбранный сеанс. ``None`` — места нет в каталоге."""
    card = await get_public_arena_card(session, arena_ref, city_id=city_id)
    if card is None:
        return None
    now = now or datetime.now(timezone.utc)
    tz = ZoneInfo(str(card.get("timezone") or "Europe/Minsk"))
    today = now.astimezone(tz).date()

    lookup_days: list[dict[str, Any]] = []
    schedule_note = ""
    schedule_mode = normalize_schedule_mode(card.get("schedule_mode"))
    if _skating(card) and schedule_mode == SCHEDULE_MODE_PHONE:
        schedule_note = PHONE_LINE
    elif _skating(card) and schedule_mode == SCHEDULE_MODE_SEASON_CLOSED:
        reopen = _parse_iso_date(card.get("schedule_reopen_date"))
        schedule_note = season_closed_user_line(
            reopen_date=reopen,
            note=card.get("schedule_mode_note"),
        )
    if _skating(card) and schedule_mode not in (SCHEDULE_MODE_PHONE, SCHEDULE_MODE_SEASON_CLOSED):
        lookup_days = await public_arena_session_days(
            session,
            int(card["id"]),
            date_from=today,
            date_to=today + timedelta(days=FOCUS_LOOKUP_DAYS - 1),
        )

    focus = None
    focus_missing = False
    week_end = today + timedelta(days=SCHEDULE_DAYS - 1)
    days = [d for d in lookup_days if (_parse_iso_date(d.get("local_date")) or today) <= week_end]
    if session_id is not None:
        for day in lookup_days:
            for slot in day.get("sessions") or []:
                if int(slot["id"]) == int(session_id):
                    focus = slot
        # Ссылку открыли позже, чем сеанс начался (или он за пределами недели) — это
        # нормальная жизнь пересланной ссылки, а не ошибка. Говорим как есть.
        focus_missing = focus is None

    all_slots = [s for d in days for s in d.get("sessions") or []]
    next_slot = all_slots[0] if all_slots else None
    ohm_days: list[dict[str, Any]] = []
    if _skating(card):
        ohm_lookup = await public_arena_session_days(
            session,
            int(card["id"]),
            date_from=today,
            date_to=today + timedelta(days=FOCUS_LOOKUP_DAYS - 1),
            kinds=("hockey_practice",),
            include_in_progress=True,
        )
        ohm_days = [d for d in ohm_lookup if (_parse_iso_date(d.get("local_date")) or today) <= week_end]
        if session_id is not None and focus is None:
            for day in ohm_lookup:
                for slot in day.get("sessions") or []:
                    if int(slot["id"]) == int(session_id):
                        focus = slot
            focus_missing = focus is None
    trainers: list[dict[str, Any]] = []
    if int(card.get("trainer_count") or 0) > 0:
        from src.application.site_trainers import load_site_trainers

        trainers, _total = await load_site_trainers(session, arena_id=int(card["id"]))
    return {
        "card": card,
        "trainers": trainers,
        "days": days,
        "ohm_days": ohm_days,
        "focus": focus,
        "focus_missing": focus_missing,
        "next_slot": next_slot,
        "session_count": len(all_slots),
        "schedule_note": schedule_note,
        "today": today,
        "now": now,
    }


def status_badge(view: Mapping[str, Any]) -> tuple[str, str] | None:
    """(вид, текст) для бейджа под названием. Вид: live | soon | closed | open | shut."""
    card = view["card"]
    today: date = view["today"]
    now: datetime = view["now"]
    if _skating(card):
        mode = normalize_schedule_mode(card.get("schedule_mode"))
        # «По телефону» без рабочего номера — противоречие на одной странице (TASK-276).
        if mode == SCHEDULE_MODE_PHONE and is_valid_public_phone(str(card.get("phone") or "")):
            return "closed", PHONE_LINE
        if mode == SCHEDULE_MODE_SEASON_CLOSED:
            reopen = _parse_iso_date(card.get("schedule_reopen_date"))
            return "closed", season_closed_user_line(
                reopen_date=reopen,
                note=card.get("schedule_mode_note"),
            )
        if card.get("in_season") is False:
            start = card.get("season_start_month")
            if start:
                return "closed", f"Сезон закрыт · откроется в {_MONTHS_PREP[int(start) - 1]}"
            return "closed", "Сезон закрыт"
        lines: list[str] = []
        nxt = view.get("next_slot")
        if nxt is not None:
            when = _sentence_when_slot(nxt, today=today)
            if when:
                lines.append(f"{t('kind.public_skate')}: {when}")
        ohm = _first_shown_slot(view.get("ohm_days"))
        if ohm is not None:
            when = _sentence_when_slot(ohm, today=today)
            if when:
                lines.append(f"{t('kind.hockey_practice')}: {when}")
        if lines:
            kind = "live" if any("сегодня" in line for line in lines) else "soon"
            return kind, "\n".join(lines)
    label = open_now_label(card, now=now)
    if label:
        return ("open" if label.startswith("Открыто") else "shut"), label
    return None


def _skating(card: Mapping[str, Any]) -> bool:
    return has_public_skating(card.get("venue_type"))


def _city(card: Mapping[str, Any]) -> str:
    return str(card.get("city_name") or "").strip()


def _sentence_when_slot(slot: Mapping[str, Any], *, today: date) -> str:
    day = _parse_iso_date(slot.get("local_date"))
    hhmm = str(slot.get("starts_at_local") or "")[:5]
    if day is None:
        return hhmm
    return sentence_when(day, hhmm, today=today)


def _first_shown_slot(days: Any) -> Mapping[str, Any] | None:
    for day in days or []:
        if not isinstance(day, Mapping):
            continue
        for slot in day.get("sessions") or []:
            if isinstance(slot, Mapping):
                return slot
    return None


def _where(card: Mapping[str, Any]) -> str:
    district = str(card.get("district") or "").strip()
    street = format_place_address(str(card.get("address") or ""), city=_city(card))
    return " · ".join(p for p in (district, street) if p)


def _services(card: Mapping[str, Any]) -> list[str]:
    amenities = card.get("amenities") or {}
    return [title for key, _i, title, _s in _SHOP_SERVICES if amenities.get(key) is True]


_SESSION_KIND_COPY_KEYS: dict[str, str] = {
    "public_skate": "kind.public_skate",
    "open_ice": "kind.public_skate",
    "hockey_practice": "kind.hockey_practice",
}


def session_kind_label(slot: Mapping[str, Any] | None) -> str:
    """Человекочитаемый тип сеанса для карточки шеринга и блока «выбранный сеанс»."""
    if slot is None:
        return ""
    custom = str(slot.get("session_label") or "").strip()
    key = _SESSION_KIND_COPY_KEYS.get(str(slot.get("kind") or "").strip())
    kind = t(key) if key else ""
    # Зал («Большая арена») не говорит, что это ОХМ, — тип впереди: «ОХМ · Большая арена».
    if custom and key == "kind.hockey_practice" and kind.lower() not in custom.lower():
        return f"{kind} · {custom}"
    return custom or kind


def invite_share_hook(view: Mapping[str, Any]) -> str:
    """Короткий текст приглашения — без даты и цены (они на og/story-картинке)."""
    if _skating(view["card"]):
        return "Погнали кататься?"
    return "Сходим сюда?"


def page_title(view: Mapping[str, Any], *, invite: bool = False) -> str:
    card = view["card"]
    name = format_public_name(str(card.get("name") or ""))
    city = _city(card)
    focus = view.get("focus")
    if focus is not None:
        when = slot_when(focus, today=view["today"], absolute=True)
        head = f"{when} · {name}"
        return f"Погнали кататься? {head}" if invite else head
    if invite:
        return f"Погнали? {name}"
    vt = card.get("venue_type")
    if has_public_skating(vt):
        # Ключевые слова в начале title; бренд как у домена — иначе Google режет до
        # официального имени арены и сниппет тянет short_description из «О катке».
        if city:
            return f"Массовое катание — {name}, {city} | Glideclub"
        return f"Массовое катание — {name} | Glideclub"
    if vt == "shop":
        services = ", ".join(s.lower() for s in _services(card))
        tail = f" — {services}" if services else " — магазин для катания"
        return f"{name}, {city}{tail}" if city else f"{name}{tail}"
    noun = str(card.get("venue_noun") or "")
    return f"{name}, {city} — {noun.lower()}" if city and noun else name


def og_description(view: Mapping[str, Any]) -> str:
    """Факты для og:description. «Сегодня» сюда не попадает: превью кэширует мессенджер."""
    card = view["card"]
    bits: list[str] = []
    focus = view.get("focus")
    if focus is not None:
        price = slot_price(focus)
        if price:
            bits.append(price)
    elif _skating(card):
        nxt = view.get("next_slot")
        if nxt is not None:
            bits.append(slot_when(nxt, today=view["today"], absolute=True))
        elif view.get("session_count"):
            n = int(view["session_count"])
            bits.append(f"{n} {plural_ru(n, 'сеанс', 'сеанса', 'сеансов')} массового катания на неделе")
    services = _services(card) if card.get("venue_type") == "shop" else []
    if services:
        bits.append(" · ".join(services))
    where = _where(card)
    if where:
        bits.append(where)
    if not bits:
        bits.append(f"{card.get('venue_noun') or 'Место'} в каталоге Glide")
    return " · ".join(bits)


def search_description(view: Mapping[str, Any]) -> str:
    """meta description для поисковика — без дат и счётчиков.

    og:description живёт в кэше мессенджера дни и честно называет ближайший сеанс.
    Поисковик держит описание неделями: «Ср, 14 окт, 17:15» в ноябре читается как
    заброшенный сайт. Здесь — то, что верно всю неделю: что за место и где оно.
    """
    card = view["card"]
    if view.get("focus") is not None:
        return og_description(view)
    if _skating(card):
        from src.application.place_visit_blocks import search_bits

        slots = [s for d in view.get("days") or [] for s in d.get("sessions") or []]
        bits = search_bits(_place_visit(view), currency=str(card.get("currency_code") or "BYN"), slots=slots)
        head = "Расписание массового катания на неделю, цены и как добраться"
        if bits:
            head = "Расписание массового катания на неделю. " + ". ".join(bits)
    elif card.get("venue_type") == "shop":
        head = " · ".join(_services(card)) or "Магазин для катания"
    else:
        head = f"{card.get('venue_noun') or 'Место'}: адрес, телефон и как добраться"
    where = _where(card).replace(" · ", ", ")
    return f"{head}. {where}." if where else f"{head}."


# ---------------------------------------------------------------------------
# Сообщение для «Поделиться»
# ---------------------------------------------------------------------------


def compose_place_share_message(view: Mapping[str, Any], *, page_url: str, invite: bool = False) -> str:
    """
    Полный текст: ссылка первой строкой, затем 2–3 строки фактов.

    Контракт тот же, что у ``/ice/share`` и ``share-trainer`` (``share_text`` со
    ссылкой первой строкой), поэтому фронт работает через тот же
    ``openTelegramShareUrlFromMiniApp``.

    Тон «Позвать с собой» — вопрос, а не реклама: человек зовёт друга, а не
    пересылает объявление. Дата, цена и адрес — на og/story-картинке, в
    ``share_body`` при invite только короткий вопрос.
    """
    card = view["card"]
    today: date = view["today"]
    name = str(card.get("name") or "")
    slot = view.get("focus") or view.get("next_slot")
    url = (page_url or "").strip()
    if invite:
        hook = invite_share_hook(view)
        return f"{url}\n\n{hook}" if url else hook
    lines: list[str] = []
    if _skating(card):
        lines.append(f"{name} — массовое катание")
    else:
        lines.append(f"{name} — {str(card.get('venue_noun') or '').lower()}".rstrip(" —"))
    if slot is not None and _skating(card):
        when = slot_when(slot, today=today, absolute=True)
        price = slot_price(slot)
        lines.append(f"{when}" + (f" · {price}" if price else ""))
    services = _services(card) if card.get("venue_type") == "shop" else []
    if services:
        lines.append(" · ".join(services))
    where = _where(card)
    if where:
        lines.append(where)
    url = (page_url or "").strip()
    return url + "\n\n" + "\n".join(lines) if url else "\n".join(lines)


def share_payload(view: Mapping[str, Any], *, page_url: str, invite: bool = False) -> dict[str, str]:
    text = compose_place_share_message(view, page_url=page_url, invite=invite)
    return {
        "share_url": page_url,
        "share_text": text,
        "share_body": share_body_for_native_share_dialog(text, page_url),
    }


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


def _esc(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def _out_of_season(card: Mapping[str, Any]) -> bool:
    """Зимняя площадка вне сезона (``in_season``) или явный режим «сезон закрыт»."""
    if normalize_schedule_mode(card.get("schedule_mode")) == SCHEDULE_MODE_SEASON_CLOSED:
        return True
    return card.get("in_season") is False


def _rental_section_title(card: Mapping[str, Any], hours: Mapping[str, Any]) -> str:
    """Minikatok продаёт услуги площадки. Остальной прайс — прокат, пока не сказано иначе."""
    explicit = str(hours.get("rental_title") or "").strip()
    if explicit:
        return explicit
    blob = f"{card.get('name') or ''} {card.get('website_url') or ''}".casefold()
    if "minikatok" in blob:
        return "Услуги"
    return "Прокат инвентаря"


def _display_host(url: str) -> str:
    """Домен без пути: «https://chizhovka-arena.by/tickets» → «chizhovka-arena.by»."""
    return display_host(url)


def zovi_entry_path(view: Mapping[str, Any]) -> str | None:
    """Ссылка «Позвать открыткой». ``None`` — ссылки нет.

    Выбранный сеанс (``?s=`` и он найден) важнее ближайшего из тех, что страница
    уже показывает. Не каток или пустое расписание — без ссылки.
    """
    card = view.get("card") or {}
    if not isinstance(card, Mapping) or not _skating(card):
        return None
    session_id = _zovi_session_id(view)
    if session_id is None:
        return None
    return f"/zovi?s={session_id}&via=place"


def _zovi_session_id(view: Mapping[str, Any]) -> int | None:
    focus = view.get("focus")
    if isinstance(focus, Mapping) and focus.get("id") is not None:
        return int(focus["id"])
    best: tuple[str, str, int] | None = None
    shown = list(view.get("days") or []) + list(view.get("ohm_days") or [])
    for day in shown:
        if not isinstance(day, Mapping):
            continue
        for slot in day.get("sessions") or []:
            if not isinstance(slot, Mapping) or slot.get("id") is None:
                continue
            key = (
                str(slot.get("local_date") or day.get("local_date") or ""),
                str(slot.get("starts_at_local") or ""),
                int(slot["id"]),
            )
            if best is None or key < best:
                best = key
    return None if best is None else best[2]


_SHARE_ICONS = {
    "tg": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" '
        'd="M21.5 4.4 2.6 11.6c-1.3.5-1.2 1.2-.2 1.5l4.8 1.5 11.1-7c.5-.3 1-.1.6.2l-9 8.1-.3 4.6'
        'c.5 0 .7-.2 1-.5l2.3-2.2 4.8 3.5c.9.5 1.5.2 1.7-.8l3.1-14.7c.3-1.3-.5-1.9-1.6-1.4z"/></svg>'
    ),
    "vb": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="'
        'M11.4 0C9.473.028 5.333.344 3.02 2.467 1.302 4.187.696 6.7.633 9.817.57 12.933.4'
        '88 18.776 6.12 20.36h.003l-.004 2.416s-.037.977.61 1.177c.777.242 1.234-.5 1.98-'
        '1.302.407-.44.972-1.084 1.397-1.58 3.85.326 6.812-.416 7.15-.525.776-.252 5.176-'
        '.816 5.892-6.657.74-6.02-.36-9.83-2.34-11.546-.596-.55-3.006-2.3-8.375-2.323 0 0'
        '-.395-.025-1.037-.017zm.058 1.693c.545-.004.88.017.88.017 4.542.02 6.717 1.388 7'
        '.222 1.846 1.675 1.435 2.53 4.868 1.906 9.897v.002c-.604 4.878-4.174 5.184-4.832'
        ' 5.395-.28.09-2.882.737-6.153.524 0 0-2.436 2.94-3.197 3.704-.12.12-.26.167-.352'
        '.144-.13-.033-.166-.188-.165-.414l.02-4.018c-4.762-1.32-4.485-6.292-4.43-8.895.0'
        '54-2.604.543-4.738 1.996-6.173 1.96-1.773 5.474-2.018 7.11-2.03zm.38 2.602c-.167'
        ' 0-.303.135-.304.302 0 .167.133.303.3.305 1.624.01 2.946.537 4.028 1.592 1.073 1'
        '.046 1.62 2.468 1.633 4.334.002.167.14.3.307.3.166-.002.3-.138.3-.304-.014-1.984'
        '-.618-3.596-1.816-4.764-1.19-1.16-2.692-1.753-4.447-1.765zm-3.96.695c-.19-.032-.'
        '4.005-.616.117l-.01.002c-.43.247-.816.562-1.146.932-.002.004-.006.004-.008.008-.'
        '267.323-.42.638-.46.948-.008.046-.01.093-.007.14 0 .136.022.27.065.4l.013.01c.13'
        '5.48.473 1.276 1.205 2.604.42.768.903 1.5 1.446 2.186.27.344.56.673.87.984l.132.'
        '132c.31.308.64.6.984.87.686.543 1.418 1.027 2.186 1.447 1.328.733 2.126 1.07 2.6'
        '04 1.206l.01.014c.13.042.265.064.402.063.046.002.092 0 .138-.008.31-.036.627-.19'
        '.948-.46.004 0 .003-.002.008-.005.37-.33.683-.72.93-1.148l.003-.01c.225-.432.15-'
        '.842-.18-1.12-.004 0-.698-.58-1.037-.83-.36-.255-.73-.492-1.113-.71-.51-.285-1.0'
        '32-.106-1.248.174l-.447.564c-.23.283-.657.246-.657.246-3.12-.796-3.955-3.955-3.9'
        '55-3.955s-.037-.426.248-.656l.563-.448c.277-.215.456-.737.17-1.248-.217-.383-.45'
        '4-.756-.71-1.115-.25-.34-.826-1.033-.83-1.035-.137-.165-.31-.265-.502-.297zm4.49'
        '.88c-.158.002-.29.124-.3.282-.01.167.115.312.282.324 1.16.085 2.017.466 2.645 1.'
        '15.63.688.93 1.524.906 2.57-.002.168.13.306.3.31.166.003.305-.13.31-.297.025-1.1'
        '75-.334-2.193-1.067-2.994-.74-.81-1.777-1.253-3.05-1.346h-.024zm.463 1.63c-.16.0'
        '02-.29.127-.3.287-.008.167.12.31.288.32.523.028.875.175 1.113.422.24.245.388.62.'
        '416 1.164.01.167.15.295.318.287.167-.008.295-.15.287-.317-.03-.644-.215-1.178-.5'
        '8-1.557-.367-.378-.893-.574-1.52-.607h-.018z'
        '"/></svg>'
    ),
    "wa": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" '
        'd="M12 3.2A8.7 8.7 0 0 0 4.4 16.3L3.2 20.8l4.6-1.2A8.7 8.7 0 1 0 12 3.2zm5 12.2c-.2.6-1.2 1.1'
        "-1.7 1.2-.4.1-1 .1-1.6-.1-.4-.1-.8-.3-1.4-.5-2.4-1-4-3.4-4.1-3.6-.1-.2-1.1-1.5-1.1-2.8"
        " 0-1.3.7-2 .9-2.2.2-.3.5-.3.7-.3h.5c.2 0 .4 0 .5.4.2.5.7 1.7.7 1.8.1.1 0 .3-.1.4l-.3.4"
        "c-.1.1-.2.3-.1.5.1.3.6 1 1.4 1.6 1 .8 1.8 1.1 2 .1.1 0 .3-.2.4-.3l.4-.5c.1-.2.3-.1.5-.1"
        '.2 0 1.4.7 1.6.8.2.1.4.2.4.3.1.2 0 .7-.2 1.3z"/></svg>'
    ),
    "vk": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" '
        'd="M4.2 7.2h2.3c.1 2.4 1.1 3.8 2 3.8.5 0 .8-.2.8-1.6V7.2h2.2v2.4c0 1.5.7 1.8 1.2.8.7-1.2'
        " 1.1-3.2 1.1-3.2h2.2s.2 1.2-1 2.8c-.8 1.1-1.1 1.4-.3 2.4.7.9 1.7 1.7 1.7 1.7h-2.3s-.6-.7"
        '-1.4-1.6c-.5-.6-.8-.8-1.1-.5-.4.4-.4 1.2-.4 1.2v.9H9.6c-3.4 0-5.3-2.3-5.4-6.1z"/></svg>'
    ),
    "copy": (
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="9" y="9" width="13" height="13" rx="2"></rect>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>'
    ),
}


def _share_icon(kind: str, label: str, href: str, *, blank: bool) -> str:
    opened = ' rel="noopener" target="_blank"' if blank else ""
    return (
        f'<a class="share__icon share__icon--{kind}" href="{_esc(href)}"{opened} aria-label="{_esc(label)}">'
        f"{_SHARE_ICONS[kind]}</a>"
    )


def _share_html(
    share: Mapping[str, str],
    *,
    venue_type: str = "ice",
    telegram_link_only: bool = False,
    story_image_url: str | None = None,
    zovi_path: str | None = None,
) -> str:
    """Ряд «Поделиться». Подборка в Telegram — только url (превью из og), без text=."""
    del venue_type
    url = share["share_url"]
    body = share["share_body"]
    full = f"{body}\n{url}" if body else url
    tg = f"https://t.me/share/url?url={quote(url, safe='')}"
    if not telegram_link_only and body:
        tg += f"&text={quote(body, safe='')}"
    wa = f"https://wa.me/?text={quote(full, safe='')}"
    viber = f"viber://forward?text={quote(full, safe='')}"
    vk = f"https://vk.com/share.php?url={quote(url, safe='')}"
    more: list[str] = []
    if story_image_url:
        more.append(
            f'<a class="share__story" href="{_esc(story_image_url)}" download="glide-story.png">{_esc(t("share.story"))}</a>'
        )
    if zovi_path:
        more.append(f'<a href="{_esc(zovi_path)}">{_esc(t("share.card"))}</a>')
    more_html = f'<p class="share__more">{"".join(more)}</p>' if more else ""
    return (
        f'<section class="share" aria-label="{t("cta.invite_friends")}">'
        f'<p class="share__title">{_esc(t("cta.invite_friends"))}</p>'
        '<div class="share__row">'
        + _share_icon("tg", "Telegram", tg, blank=True)
        + _share_icon("vb", "Viber", viber, blank=False)
        + _share_icon("wa", "WhatsApp", wa, blank=True)
        + _share_icon("vk", "VK", vk, blank=True)
        + (
            f'<button class="share__icon share__icon--copy" type="button" data-copy="{_esc(full)}" '
            f'aria-label="Скопировать">{_SHARE_ICONS["copy"]}</button>'
        )
        + "</div>"
        + more_html
        + "</section>"
    )


def _json_ld(view: Mapping[str, Any], *, canonical_url: str, image_url: str) -> str:
    card = view["card"]
    place: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": _SCHEMA_TYPES.get(str(card.get("venue_type") or "ice"), "Place"),
        "name": card.get("name"),
        "url": canonical_url,
        "image": image_url,
    }
    address = {
        "@type": "PostalAddress",
        "streetAddress": card.get("address") or None,
        "addressLocality": _city(card) or None,
    }
    place["address"] = {k: v for k, v in address.items() if v}
    if card.get("latitude") is not None and card.get("longitude") is not None:
        place["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": card["latitude"],
            "longitude": card["longitude"],
        }
    if card.get("phone"):
        place["telephone"] = card["phone"]
    schema_hours = opening_hours_schema_org(card.get("opening_hours"))
    if schema_hours:
        place["openingHours"] = schema_hours[0] if len(schema_hours) == 1 else schema_hours
    events = []
    arena_name = str(card.get("name") or "")
    street = str(card.get("address") or "").strip()
    for day in view.get("days") or []:
        for slot in day.get("sessions") or []:
            kind_label = session_kind_label(slot) or t("kind.public_skate")
            slot_url = canonical_url + place_query(session_id=int(slot["id"]))
            event: dict[str, Any] = {
                "@type": "Event",
                "name": f"{kind_label} — {arena_name}",
                "startDate": slot.get("starts_at_utc"),
                "endDate": slot.get("ends_at_utc"),
                "eventStatus": "https://schema.org/EventScheduled",
                "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
                "url": slot_url,
                "location": {"@type": "Place", "name": arena_name, "address": place["address"]},
            }
            adult = slot.get("price_adult_minor")
            if adult is not None:
                event["offers"] = {
                    "@type": "Offer",
                    "price": f"{int(adult) / 100:.2f}",
                    "priceCurrency": slot.get("currency_code") or "BYN",
                    "url": slot_url,
                }
            enrich_ice_session_event(
                event,
                arena_name=arena_name,
                page_url=slot_url,
                image_url=image_url,
                short_description=str(card.get("short_description") or "") or None,
                address=street or None,
                session_label=kind_label,
                slot=slot,
            )
            events.append(event)
            if len(events) >= 10:
                break
        if len(events) >= 10:
            break
    if events:
        place["event"] = events
    if _skating(card):
        from src.application.place_visit_blocks import json_ld_extras

        skate_slots = [s for d in view.get("days") or [] for s in d.get("sessions") or []]
        place.update(
            json_ld_extras(
                _place_visit(view), currency=str(card.get("currency_code") or "BYN"), slots=skate_slots
            )
        )
    # </script> или <!-- внутри JSON закрыли бы тег раньше времени — экранируем < > &.
    return json_for_script(place)


_B_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "b.html"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _share_asset_version() -> str:
    """Один ?v= на css и js дока: правка скрипта тоже сбрасывает кэш."""
    import hashlib

    digest = hashlib.sha256()
    for rel in ("static/share/place-share.css", "static/share/place-share.js"):
        path = _REPO_ROOT / rel
        digest.update(rel.encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"0")
    return digest.hexdigest()[:10]


PLACE_SHARE_VERSION = _share_asset_version()


def _webapp_bundle_version() -> str:
    try:
        text = (_REPO_ROOT / "static" / "webapp" / "arena.html").read_text(encoding="utf-8")
    except OSError:
        return "0"
    match = re.search(r"minsk-time\.js\?v=(\d+)", text)
    return match.group(1) if match else "0"


def _effective_pick_session(view: Mapping[str, Any]) -> Mapping[str, Any] | None:
    focus = view.get("focus")
    if isinstance(focus, Mapping):
        return focus
    nxt = view.get("next_slot")
    return nxt if isinstance(nxt, Mapping) else None


def _nojs_messenger_row(share: Mapping[str, str]) -> str:
    """Простые ссылки мессенджеров под выбранным билетом (без JS)."""
    url = share["share_url"]
    body = share.get("share_body") or ""
    full = f"{body}\n{url}" if body else url
    tg = f"https://t.me/share/url?url={quote(url, safe='')}"
    if body:
        tg += f"&text={quote(body, safe='')}"
    links = (
        ("Telegram", tg, True),
        ("Viber", f"viber://forward?text={quote(full, safe='')}", False),
        ("WhatsApp", f"https://wa.me/?text={quote(full, safe='')}", True),
    )
    row = "".join(
        f'<a href="{_esc(href)}"' + (' rel="noopener" target="_blank"' if blank else "") + f">{_esc(label)}</a>"
        for label, href, blank in links
    )
    row += f'<button type="button" data-copy="{_esc(full)}">Скопировать</button>'
    # <noscript>: с JS браузер блок не рисует вовсе. Раньше он стоял ячейкой сетки
    # билетов, пока отложенный place-share.js не скрывал его, — и билеты прыгали (CLS).
    return f'<noscript><div class="place-share-fallback">{row}</div></noscript>'


def _place_has_share_dock(view: Mapping[str, Any]) -> bool:
    """Есть ли у страницы своя нижняя панель «Позвать»: тогда «Приложение» живёт в ней."""
    return _effective_pick_session(view) is not None and _skating(view["card"])


def _place_share_bar_html(view: Mapping[str, Any], *, invite: bool, telegram_url: str | None = None) -> str:
    from src.application.style_b import app_button_html

    pick = _effective_pick_session(view)
    if not _place_has_share_dock(view):
        # Позвать некуда — внизу общая кнопка «Приложение» из подвала сайта.
        return ""
    when = invite_cta_when(
        _parse_iso_date(pick.get("local_date")),
        str(pick.get("starts_at_local") or ""),
        today=view["today"],
    )
    label = f"Позвать на {when}" if when else "Позвать с собой"
    tg = app_button_html(telegram_url, floating=False) if telegram_url else ""
    # Без Telegram-ссылки панели без JS показывать нечего — как раньше, ждёт скрипт.
    dock_hidden = "" if tg else " hidden"
    return (
        f'<div class="place-share-dock" id="placeShareDock"{dock_hidden}>'
        '<div class="place-share-dock__inner"><div class="place-share-dock__row">'
        # «Позвать» hidden до скрипта: без JS ей нечего открыть — под выбранным сеансом свои ссылки.
        f'<button type="button" class="place-share-dock__btn" id="placeShareBtn" hidden>{_esc(label)}</button>'
        f"{tg}</div></div></div>"
    )


def _place_share_scripts_html(
    view: Mapping[str, Any], *, invite: bool, base_path: str, telegram_url: str | None
) -> str:
    pick = _effective_pick_session(view)
    if pick is None or not _skating(view["card"]):
        return ""
    card = view["card"]
    pick_day = _parse_iso_date(pick.get("local_date"))
    boot = {
        "ref": str(card["id"]),
        "placeName": format_public_name(str(card.get("name") or "")),
        "timezone": str(card.get("timezone") or "Europe/Minsk"),
        "today": view["today"].isoformat(),
        "days": view.get("days") or [],
        "ohmDays": view.get("ohm_days") or [],
        "sessionId": int(pick["id"]),
        "focusDay": pick_day.isoformat() if pick_day else "",
        "sessionMissing": bool(view.get("focus_missing")),
        "invite": invite,
        "basePath": base_path,
        "telegramCta": telegram_url or "",
    }
    wv = _webapp_bundle_version()
    pv = PLACE_SHARE_VERSION
    return (
        f'<script type="application/json" id="place-share-data">{json_for_script(boot)}</script>\n'
        f'<script>window.__PLACE_SHARE__=JSON.parse(document.getElementById("place-share-data").textContent);</script>\n'
        f'<link rel="stylesheet" href="/webapp/mini-app-share-sheet.css?v={_esc(wv)}" />\n'
        f'<link rel="stylesheet" href="/static/share/place-share.css?v={_esc(pv)}" />\n'
        f'<script defer src="/webapp/minsk-time.js?v={_esc(wv)}"></script>\n'
        f'<script defer src="/webapp/public-display-model.js?v={_esc(wv)}"></script>\n'
        f'<script defer src="/webapp/arena-card-model.js?v={_esc(wv)}"></script>\n'
        f'<script defer src="/webapp/mini-app-share-sheet.js?v={_esc(wv)}"></script>\n'
        f'<script defer src="/static/share/place-share.js?v={_esc(pv)}"></script>'
    )


def _place_hub_footer_links(*, city: str, city_page_url: str | None, public_skate: bool) -> str:
    """Внутренние ссылки: городской хаб и корень. «Массовое катание» — только у катков."""
    if not city_page_url or not city:
        return '<a href="/">Массовое катание по Беларуси</a>' if public_skate else '<a href="/">Каталог Glideclub</a>'
    from src.shared.city_locative import city_locative

    where = city_locative(city)
    if public_skate:
        hub = f"Массовое катание в {where}" if where else f"Массовое катание — {format_public_name(city)}"
    else:
        hub = f"Каталог в {where}" if where else f"Каталог — {format_public_name(city)}"
    return (
        f'<a href="{_esc(city_page_url)}">{_esc(hub)}</a>'
        ' · <a href="/">Все города</a>'
    )


def _place_site_footer(city_link: str, *, telegram_href: str | None, own_dock: bool = False) -> str:
    from src.application.public_site_footer import render_site_footer_html

    return render_site_footer_html(
        context_html=city_link, telegram_href=telegram_href, show_app_button=not own_dock
    )


def render_place_page(
    view: Mapping[str, Any],
    *,
    canonical_url: str,
    base_path: str,
    og_image_url: str,
    story_image_url: str,
    cta_url: str | None,
    city_page_url: str | None,
    share: Mapping[str, str],
    invite: bool = False,
    share_src: str | None = None,
    country: str | None = None,
) -> str:
    card = view["card"]
    title = page_title(view, invite=invite)
    base_url = join_public_origin(canonical_url, "/").rstrip("/") if canonical_url else ""
    body = render_place_body_b(
        view,
        base_path=base_path,
        base_url=base_url,
        invite=invite,
        cta_url=cta_url,
        share=share,
        story_image_url=story_image_url,
    )
    city = _city(card)
    city_link = _place_hub_footer_links(
        city=city,
        city_page_url=city_page_url,
        public_skate=has_public_skating(card.get("venue_type")),
    )
    # Ссылка с ?s= / ?i= — та же страница; в индекс идёт только каноническая.
    robots = "noindex, follow" if (view.get("focus") is not None or invite or bool(share_src)) else "index, follow"

    from src.application.public_analytics import public_analytics_head_html_from_settings
    from src.application.public_web_cta import public_page_view_beacon_script
    from src.application.style_b import COMPONENTS_VERSION, STYLE_VERSION, TOKENS_VERSION, public_fonts_head_html
    from src.shared.glide_city_cookie import glide_city_pin_script

    html = _B_TEMPLATE_PATH.read_text(encoding="utf-8")
    lang, og_locale = html_lang_for_country(country if country is not None else card.get("country"))
    replacements = {
        "__OG_TITLE__": _esc(title),
        "__OG_DESCRIPTION__": _esc(og_description(view)),
        "__DESCRIPTION__": _esc(search_description(view)),
        "__CANONICAL__": _esc(canonical_url),
        "__OG_URL__": _esc(share["share_url"]),
        "__OG_IMAGE__": _esc(og_image_url),
        "__LANG__": lang,
        "__OG_LOCALE__": og_locale,
        "__ROBOTS__": robots,
        "__HEAD_EXTRA__": "",
        "__JSONLD__": _json_ld(view, canonical_url=canonical_url, image_url=og_image_url),
        "__PUBLIC_FONTS_HEAD__": public_fonts_head_html(),
        "__PUBLIC_ANALYTICS_HEAD__": public_analytics_head_html_from_settings(),
        "__TOKENS_V__": TOKENS_VERSION,
        "__STYLE_V__": STYLE_VERSION,
        "__COMPONENTS_V__": COMPONENTS_VERSION,
        "__SITE_FOOTER__": _place_site_footer(
            city_link, telegram_href=cta_url, own_dock=_place_has_share_dock(view)
        ),
        "__BODY__": body,
        "__PLACE_SHARE_BAR__": _place_share_bar_html(view, invite=invite, telegram_url=cta_url),
        "__PLACE_SHARE_SCRIPTS__": _place_share_scripts_html(
            view, invite=invite, base_path=base_path, telegram_url=cta_url
        ),
        "__PAGE_VIEW_BEACON__": public_page_view_beacon_script(
            surface="place_page",
            city_id=int(card.get("city_id") or 0) or None,
            arena_id=int(card.get("id") or card.get("arena_id") or 0) or None,
        ),
        "__GLIDE_CITY_PIN__": glide_city_pin_script(city_slug(city) if city else ""),
    }
    from src.application.style_b import b_press_script_html, telegram_dock_script_html

    replacements["__B_PRESS_SCRIPT__"] = b_press_script_html()
    replacements["__TG_DOCK_SCRIPT__"] = telegram_dock_script_html()
    if robots.startswith("index") and city:
        from src.application.place_links import breadcrumb_script

        replacements["__BODY__"] += breadcrumb_script(
            canonical_url,
            [
                ("Glideclub", "/"),
                (format_public_name(city), f"/c/{city_slug(city)}"),
                (format_public_name(str(card.get("name") or "")), canonical_url),
            ],
        )
    page_html = fill_placeholders(html, replacements)
    if _effective_pick_session(view) is not None and _skating(card):
        page_html = page_html.replace("<body class=\"b\">", '<body class="b has-place-share">', 1)
    return page_html


# ── TASK-246 · стиль B «Лёд и свет» (доска «B · Место») ──────────────────────

_B_AMENITIES: tuple[tuple[str, str, str], ...] = (
    ("skate_rental", "skate", "Прокат коньков"),
    ("skate_sharpening", "sharpen", "Заточка"),
    ("locker_rooms", "locker", "Раздевалки"),
    ("cafe", "cafe", "Кафе"),
    ("parking", "parking", "Парковка"),
    ("accessibility", "person", "Доступная среда"),
)


def _sentence(text: str) -> str:
    """Заметка катка как предложение: с заглавной, без двойной точки."""
    body = str(text or "").strip().rstrip(".;")
    if not body:
        return ""
    return body[0].upper() + body[1:] + "."


def _b_where(card: Mapping[str, Any]) -> str:
    """«ул. Ташкентская, 19 · Заводской район» — без города: он в пилюле «‹ Минск»."""
    street = format_street_address(str(card.get("address") or ""), city=_city(card))
    district = str(card.get("district") or "").strip()
    if district and _city(card) and district.casefold() == _city(card).casefold():
        district = ""
    return " · ".join(x for x in (street, district) if x)


def _b_status(view: Mapping[str, Any]) -> str:
    """Статус места строкой в герое: закрыто на сезон, только по телефону, открыто сейчас.

    Ближайшие сеансы («Массовое катание: завтра, 9:00») здесь не повторяем — расписание ниже.
    """
    badge = status_badge(view)
    if not badge or badge[0] in ("live", "soon"):
        return ""
    kind, text = badge
    return f'<span class="b-hero__status b-hero__status--{_esc(kind)}"><i></i>{_esc(text)}</span>'


def _b_hero_chips(card: Mapping[str, Any], links: Mapping[str, Any]) -> str:
    """Маршрут · Телефон · Сайт · колокольчик — на обложке, как в Mini App. Нет данных — нет чипа."""
    from src.application.catalog_icons import icon_svg

    chips: list[str] = []
    if links.get("route"):
        href, blank = links["route"]
        attrs = ' rel="noopener nofollow" target="_blank"' if blank else ' rel="nofollow"'
        chips.append(f'<a class="b-pill b-pill--chip" href="{_esc(href)}"{attrs}>{icon_svg("route")}{_esc(t("cta.route"))}</a>')
    if links.get("tel"):
        chips.append(
            f'<a class="b-pill b-pill--chip" href="{_esc(links["tel"])}" '
            f'data-catalog-phone-beacon="{_esc(links.get("tel_beacon"))}">{icon_svg("phone")}Телефон</a>'
        )
    site = safe_external_url(card.get("website_url"))
    if site:
        chips.append(
            f'<a class="b-pill b-pill--chip" href="{_esc(site)}" rel="noopener nofollow" target="_blank">'
            f'{icon_svg("globe")}Сайт</a>'
        )
    # TASK-330: колокольчик на обложке ставит ту же подписку, что и блок пустой карточки, —
    # через бота (/start watch_<id>); без неё — прежняя ссылка в мини-апп.
    bell_href = links.get("watch") or links.get("bell")
    if bell_href:
        chips.append(
            f'<a class="b-pill b-pill--icon b-pill--chip tg-out" href="{_esc(bell_href)}" rel="nofollow" '
            f'aria-label="{_esc(t("schedule.bell_hint"))} в\u00a0Telegram">{icon_svg("bell")}</a>'
        )
    return f'<div class="b-hero__chips">{"".join(chips)}</div>' if chips else ""


def _b_hero(card: Mapping[str, Any], *, status_html: str = "", chips_html: str = "") -> str:
    from src.application.style_b import back_pill, brand_link, hero_html, media_url

    hero_media = card.get("hero") if isinstance(card.get("hero"), Mapping) else None
    photo = media_url(hero_media, size="card") or media_url(hero_media, size="hero")
    photo_variants = None
    if hero_media and isinstance(hero_media.get("variants"), Mapping):
        photo_variants = hero_media.get("variants")
    toned = bool(hero_media.get("display_tone")) if hero_media else False
    city_name = _city(card)
    bar = ""
    if city_name:
        bar = back_pill(f"/c/{city_slug(city_name)}", format_public_name(city_name))
    bar += brand_link(end=True)
    where = _b_where(card)
    name = format_public_name(str(card.get("name") or ""))
    from src.shared.public_view_transitions import place_vt_name

    return hero_html(
        title=name,
        sub_html=_esc(where) if where else "",
        photo_url=photo,
        photo_alt=name,
        toned=toned,
        bar_html=bar,
        variant="place",
        extra_html=status_html + chips_html,
        photo_variants=photo_variants,
        vt_name=place_vt_name(str(card.get("slug") or "")),
    )


def _b_call(card: Mapping[str, Any], links: Mapping[str, Any], *, dark: bool = True) -> str:
    tel = links.get("tel")
    if not tel:
        return ""
    from src.application.catalog_icons import icon_svg

    klass = "b-call b-call--dark" if dark else "b-call"
    number = format_phone_display(str(card.get("phone") or "").split(";")[0])
    return (
        f'<a class="{klass}" href="{_esc(tel)}" data-catalog-phone-beacon="{_esc(links.get("tel_beacon"))}">'
        f'{icon_svg("phone")}<span class="b-call__num">{_esc(number)}</span></a>'
    )


def _b_price_floor(slots: list[Mapping[str, Any]]) -> tuple[str, str]:
    """Цена в шапке блока и «базовая» цена билетов: ``("от 11 BYN", "11 BYN")``.

    Раньше шапка брала самую частую цену недели: в DiaMond city выходные по 12 BYN
    перевешивали будни по 11 — и над сегодняшними билетами по 11 стояло «12 BYN».
    Теперь — минимум недели, с «от», если цены разные; билет пишет свою цену, только
    когда она выше минимума.
    """
    priced: list[tuple[int, str]] = []
    for slot in slots:
        minor = slot.get("price_adult_minor")
        if minor is None:
            minor = slot.get("price_minor")
        if minor is not None:
            priced.append((int(minor), slot_price(slot)))
    if not priced:
        return "", ""
    floor = min(priced)[1]
    varies = len({label for _, label in priced}) > 1
    return (f"от {floor}" if varies else floor), floor


def _b_ticket(
    slot: Mapping[str, Any],
    *,
    vt_session_id: int | None,
    base_path: str,
    invite: bool,
    focused: bool,
    common_price: str,
    nojs_share: Mapping[str, str] | None = None,
    dark: bool = False,
    soon: str = "",
) -> str:
    from src.shared.public_view_transitions import session_time_vt_style

    start = format_clock(str(slot.get("starts_at_local") or ""))
    end = format_clock(str(slot.get("ends_at_local") or ""))
    sub_bits = [f"до {end}"] if end else []
    price = slot_price(slot)
    if price and price != common_price:
        sub_bits.append(price)
    sub = f'<span class="b-ticket__sub">{_esc(" · ".join(sub_bits))}</span>' if sub_bits else ""
    href = base_path + place_query(session_id=int(slot["id"]), invite=invite)
    klass = "b-ticket" + (" b-ticket--dark" if dark else "") + (" b-ticket--picked" if focused else "")
    sid = int(slot["id"])
    vt = session_time_vt_style(sid) if vt_session_id is not None and sid == vt_session_id else ""
    from src.application.session_load import live_seats_html, load_meter_html

    # Живой остаток кассы важнее «обычно»: вместе они говорили бы одно и то же.
    meter = live_seats_html(slot.get("capacity_note")) or load_meter_html(slot.get("typical_load_level"))
    ticket = (
        f'<a class="{klass}" href="{_esc(href)}" rel="nofollow" data-session-id="{sid}">'
        f'<span class="b-ticket__time"{vt}>{_esc(start)}</span>{meter}{soon}{sub}</a>'
    )
    if focused and nojs_share is not None:
        ticket += _nojs_messenger_row(nojs_share)
    return ticket


def _b_schedule_site_link(card: Mapping[str, Any]) -> str:
    site = safe_external_url(card.get("website_url"))
    if not site:
        return ""
    host = _display_host(site)
    return (
        f'<a class="b-link" href="{_esc(site)}" rel="noopener nofollow" target="_blank">'
        f"{_esc(host or site)}</a>"
    )


def _b_buy(links: Mapping[str, Any]) -> str:
    """Wide ticket button. ``links['tickets']`` is ``(href, open_in_new_tab)``."""
    pair = links.get("tickets")
    if not pair:
        return ""
    from src.application.catalog_icons import icon_svg

    href, blank = pair
    attrs = ' rel="noopener nofollow" target="_blank"' if blank else ' rel="nofollow"'
    return (
        f'<a class="b-btn b-btn--wide b-buy" href="{_esc(href)}"{attrs}>'
        f'{_esc(t("place.tickets_buy"))}{icon_svg("external")}</a>'
    )


def schedule_wait_lines(card: Mapping[str, Any]) -> tuple[str, str]:
    """TASK-330: (надзаголовок, заголовок) пустой карточки — привычка катка, без дат.

    Та же логика, что ``scheduleWaitView`` в Mini App (arena-card-model.js), один словарь.
    """
    raw = card.get("schedule_habit")
    habit: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    level = habit.get("level")
    weekday = habit.get("weekday")
    if level == "day" and isinstance(weekday, int) and not isinstance(weekday, bool) and 0 <= weekday <= 6:
        return t("schedule.wait_kicker"), t("schedule.habit_day", day=t(f"schedule.dow_{weekday}"))
    if level == "week":
        return t("schedule.wait_kicker"), t("schedule.habit_week")
    return "", t("schedule.wait_none")


def _schedule_waits(card: Mapping[str, Any]) -> bool:
    """Каток расписание ведёт, а сеансов нет — пустой карточке есть что сказать (TASK-330)."""
    mode = normalize_schedule_mode(card.get("schedule_mode"))
    return card.get("schedule_tracked") is True and mode not in (SCHEDULE_MODE_PHONE, SCHEDULE_MODE_SEASON_CLOSED)


def _b_schedule_wait(card: Mapping[str, Any], links: Mapping[str, Any]) -> str:
    """TASK-330: привычка катка и колокольчик в Telegram (бот ставит его по /start watch_<id>)."""
    from src.application.catalog_icons import icon_svg

    kicker, headline = schedule_wait_lines(card)
    watch = links.get("watch")
    kicker_html = f'<p class="b-wait__kicker">{_esc(kicker)}</p>' if kicker else ""
    bell = ""
    if watch:
        bell = (
            f'<p class="b-wait__sub">{_esc(t("schedule.wait_sub"))}</p>'
            f'<a class="b-btn b-btn--accent b-btn--wide b-wait__cta" href="{_esc(watch)}" rel="nofollow">'
            f'{icon_svg("bell")}{_esc(t("schedule.bell_site_cta"))}</a>'
            f'<p class="b-wait__note">{_esc(t("schedule.bell_note"))}</p>'
        )
    return f'<div class="b-wait">{kicker_html}<p class="b-wait__title">{_esc(headline)}</p>{bell}</div>'


def _b_schedule_when_empty(card: Mapping[str, Any], links: Mapping[str, Any], *, title: str) -> str:
    """Тело пустого блока. Секцию рисует ``_b_schedule``, иначе заголовок дублируется."""
    del title
    if _schedule_waits(card):
        # Касса и телефон остаются под колокольчиком: они полезны и без расписания.
        return f"{_b_schedule_wait(card, links)}{_b_buy(links)}{_b_call(card, links)}"
    buy = _b_buy(links)
    call = _b_call(card, links)
    if call:
        return f"{buy}{call}"
    site_link = _b_schedule_site_link(card)
    if buy or site_link:
        # Пока сеансов нет, касса всё равно открыта: кнопка покупки важнее отсылки «смотрите на сайте».
        note = "" if buy else f'<p class="b-text">{_esc(t("place.site_schedule"))}</p>'
        return f"{buy}{note}{site_link}"
    return ""


def _sessions_by_date(days: list[Mapping[str, Any]]) -> dict[date, list[Mapping[str, Any]]]:
    by_date: dict[date, list[Mapping[str, Any]]] = {}
    for day in days:
        d = _parse_iso_date(day.get("local_date"))
        if d is not None and day.get("sessions"):
            by_date[d] = list(day.get("sessions") or [])
    return by_date


def _b_day_strip(
    view: Mapping[str, Any],
    by_date: Mapping[date, list[Mapping[str, Any]]],
    *,
    frag_prefix: str,
    base_path: str,
    invite: bool,
    common: str,
    dark: bool = False,
) -> str:
    """Полоса дней недели и билеты дня — без JS (#якорь + :target), как в Mini App.

    Одна функция для массового катания и ОХМ: у каждой полосы свой префикс якоря, выбор
    сеанса общий — кнопка «Позвать» берёт любой билет со страницы.
    """
    today = view["today"]
    now = view.get("now")
    soon_id: int | None = None
    soon_best: int | None = None
    if isinstance(now, datetime):
        for slots in by_date.values():
            for slot in slots:
                minutes = minutes_until_start(slot, now=now)
                if minutes is None:
                    continue
                if soon_best is None or minutes < soon_best:
                    soon_best = minutes
                    soon_id = int(slot["id"])
    focus = view.get("focus")
    pick = _effective_pick_session(view)
    focus_id = int(focus["id"]) if focus is not None else None
    pick_id = int(pick["id"]) if pick is not None else None
    default_day = min(by_date)
    prefer = view.get("prefer_dates")
    if prefer:
        # TASK-326: хаб города открыт в окне с главной — первый день окна, где есть сеансы.
        in_window = [d for d in sorted(by_date) if prefer[0] <= d <= prefer[1]]
        if in_window:
            default_day = in_window[0]
    if focus_id is not None:
        for d, slots in by_date.items():
            if any(int(s["id"]) == focus_id for s in slots):
                default_day = d
    sched_bits: list[str] = []
    for offset in range(SCHEDULE_DAYS):
        d = today + timedelta(days=offset)
        label = short_day_word(d, today=today)
        slots = by_date.get(d, [])
        n = len(slots)
        day_klass = "b-day"
        if d.weekday() >= 5:
            day_klass += " b-day--end"
        inner = f"<span>{_esc(label)}</span><b>{d.day}</b><i>{n if n else '—'}</i>"
        if not n:
            sched_bits.append(f'<span class="{day_klass} b-day--off">{inner}</span>')
            continue
        nojs_share = None
        if pick_id is not None and any(int(s["id"]) == pick_id for s in slots):
            page_url = base_path + place_query(session_id=pick_id, invite=invite)
            nojs_share = share_payload(view, page_url=page_url, invite=invite)
        tickets = "".join(
            _b_ticket(
                s,
                vt_session_id=pick_id,
                base_path=base_path,
                invite=invite,
                focused=(pick_id == int(s["id"])),
                common_price=common,
                nojs_share=nojs_share if pick_id == int(s["id"]) else None,
                dark=dark,
                soon=soon_html(s, now=now) if isinstance(now, datetime) and soon_id == int(s["id"]) else "",
            )
            for s in slots
        )
        frag = f"{frag_prefix}-{d.isoformat()}"
        if d == default_day:
            day_klass += " b-day--current"
        sched_bits.append(f'<a class="{day_klass}" id="{frag}" href="#{frag}">{inner}</a>')
        sched_bits.append(f'<div class="b-daypane"><div class="b-tickets">{tickets}</div></div>')
    return f'<nav class="b-sched" aria-label="День">{"".join(sched_bits)}</nav>'


def _place_visit(view: Mapping[str, Any]) -> dict[str, Any]:
    """Модель блоков карточки v2 (arena_visit_info). Тренеры — из view: школа катка встаёт к ним."""
    from src.application.arena_visit_info import visit_view
    from src.application.place_visit_blocks import price_floors

    card = view["card"]
    slots = [s for d in view.get("days") or [] for s in d.get("sessions") or []]
    rental = price_floors(slots).get("rental")
    rental_price = ""
    if rental:
        text = format_price_minor(rental[0], str(card.get("currency_code") or "BYN"))
        rental_price = f"от {text}" if rental[1] else text
    return visit_view(
        card, has_trainers=bool(view.get("trainers")), rental_price=rental_price, has_slots=bool(slots)
    )


def _b_buy_pill(view: Mapping[str, Any], links: Mapping[str, Any], vv: Mapping[str, Any]) -> str:
    """Кнопка онлайн-кассы в шапке блока «На льду».

    Касса «только в день сеанса», а сегодня сеансов нет — кнопка сначала открывает шторку:
    билет на другой день онлайн не купить, зато можно поставить напоминание в Telegram.
    """
    from src.application.catalog_icons import icon_svg

    pair = links.get("tickets")
    mode = (vv.get("tickets") or {}).get("mode")
    if not pair or mode not in ("online", "same_day"):
        return ""
    href, blank = pair
    attrs = ' rel="noopener nofollow" target="_blank"' if blank else ' rel="nofollow"'
    label = "Билеты онлайн"
    today_slots = [
        s for d in view.get("days") or [] if _parse_iso_date(d.get("local_date")) == view.get("today")
        for s in d.get("sessions") or []
    ]
    if mode != "same_day" or today_slots:
        return f'<a class="b-buypill" href="{_esc(href)}"{attrs}>{label}{icon_svg("external")}</a>'
    card = view["card"]
    name = format_public_name(str(card.get("name") or ""))
    nxt = view.get("next_slot")
    when = f" Ближайший сеанс — {_esc(slot_when(nxt, today=view['today']))}." if nxt is not None else ""
    bell = links.get("bell")
    remind = (
        f'<a class="b-sheet__main" href="{_esc(bell)}">{icon_svg("bell")}Напомнить в Telegram</a>' if bell else ""
    )
    return (
        f'<a class="b-buypill" href="{_esc(href)}"{attrs} data-sameday-open>{label}{icon_svg("external")}</a>'
        '<dialog class="b-sheet" id="sameDaySheet" aria-labelledby="sameDayTitle">'
        '<div class="b-sheet__in" tabindex="-1" autofocus>'
        '<button type="button" class="b-sheet__x" data-sheet-close aria-label="Закрыть">'
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button>'
        '<h2 class="b-sheet__title" id="sameDayTitle">Онлайн-билет появится в день сеанса</h2>'
        f'<p class="b-sheet__text">{_esc(name)} продаёт онлайн только на сегодняшние сеансы. '
        f"Заранее билет можно купить в кассе.{when}</p>"
        f"{remind}"
        f'<a class="b-sheet__alt" href="{_esc(href)}"{attrs}>Всё равно открыть сайт кассы</a>'
        "</div></dialog>"
        "<script>(function(){var d=document.getElementById('sameDaySheet');"
        "var a=document.querySelector('[data-sameday-open]');if(!d||!a||!d.showModal)return;"
        "a.addEventListener('click',function(e){e.preventDefault();d.showModal();});"
        "d.addEventListener('click',function(e){if(e.target===d||e.target.closest('[data-sheet-close]'))d.close();});"
        "})();</script>"
    )


def _b_schedule_parts(
    view: Mapping[str, Any],
    *,
    base_path: str,
    invite: bool,
    links: Mapping[str, Any],
    vv: Mapping[str, Any] | None = None,
) -> tuple[str, str, str] | None:
    """(заголовок, тело, правая часть шапки) блока массового катания — или None."""
    from src.application.place_visit_blocks import prices_html, ticket_line_html

    card = view["card"]
    if not _skating(card):
        return None
    vv = vv if vv is not None else _place_visit(view)
    title = t("kind.public_skate")
    mode = normalize_schedule_mode(card.get("schedule_mode"))
    days = list(view.get("days") or [])
    line = ticket_line_html(vv)
    if mode == SCHEDULE_MODE_SEASON_CLOSED:
        reopen = _parse_iso_date(card.get("schedule_reopen_date"))
        text = season_closed_user_line(reopen_date=reopen, note=card.get("schedule_mode_note"))
        return title, f'<p class="b-text">{_esc(text)}</p>', ""
    if card.get("in_season") is False:
        return None
    if not days:
        empty = _b_schedule_when_empty(card, links, title=title)
        return (title, line + empty, "") if empty or line else None

    by_date = _sessions_by_date(days)
    if not by_date:
        # Дни пришли, но все без сеансов — та же пустая карточка (TASK-330).
        if not _schedule_waits(card):
            return None
        return title, line + _b_schedule_when_empty(card, links, title=title), ""
    all_slots = [s for slots in by_date.values() for s in slots]
    _aside_price, common = _b_price_floor(all_slots)
    strip = _b_day_strip(view, by_date, frag_prefix="d", base_path=base_path, invite=invite, common=common)
    currency = str(all_slots[0].get("currency_code") or card.get("currency_code") or "BYN")
    prices = prices_html(all_slots, vv, currency=currency)
    foot: list[str] = []
    zovi = zovi_entry_path(view)
    if zovi:
        foot.append(f'<a class="b-link" href="{_esc(zovi)}">{_esc(t("share.card"))}</a>')
    links_row = f'<div class="b-links">{"".join(foot)}</div>' if foot else ""
    body = f"{prices}{line}<div data-glide-session-list-root>{strip}{links_row}</div>"
    return title, body, _b_buy_pill(view, links, vv)


def _b_schedule(
    view: Mapping[str, Any],
    *,
    base_path: str,
    invite: bool,
    links: Mapping[str, Any],
    vv: Mapping[str, Any] | None = None,
) -> str:
    from src.application.style_b import section

    parts = _b_schedule_parts(view, base_path=base_path, invite=invite, links=links, vv=vv)
    if parts is None:
        return ""
    title, body, aside = parts
    return section(title, body, aside_html=aside, klass="b-sec--place", sec_id="schedule")


def _b_ohm_parts(view: Mapping[str, Any], *, base_path: str, invite: bool) -> tuple[str, str] | None:
    """(тело, подпись в шапке) ОХМ: те же полоса дней и билеты, только тёмные.

    Сеанс ОХМ выбирается тапом и уходит в «Позвать», как в Mini App (``arenaOhmDayTabs``).
    """
    by_date = _sessions_by_date([d for d in (view.get("ohm_days") or []) if d.get("sessions")])
    if not by_date:
        return None
    slots = [s for d in sorted(by_date) for s in by_date[d]]
    first = slots[0]
    aside_bits: list[str] = []
    aside_price, price = _b_price_floor(slots)
    if aside_price:
        aside_bits.append(aside_price)
    start, end = format_clock(str(first.get("starts_at_local") or "")), format_clock(str(first.get("ends_at_local") or ""))
    try:
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
        minutes = (eh * 60 + em) - (sh * 60 + sm)
        if minutes > 0:
            aside_bits.append(f"{minutes} мин")
    except ValueError:
        pass
    strip = _b_day_strip(view, by_date, frag_prefix="o", base_path=base_path, invite=invite, common=price, dark=True)
    notes: list[str] = []
    for slot in slots:
        for key in ("age_note", "capacity_note", "price_note"):
            note = _sentence(str(slot.get(key) or ""))
            if note and note not in notes:
                notes.append(note)
    notes_html = f'<p class="b-note">{_esc(" ".join(notes))}</p>' if notes else ""
    return f"{strip}{notes_html}", " · ".join(aside_bits)


def _b_ohm(view: Mapping[str, Any], *, base_path: str, invite: bool) -> str:
    from src.application.style_b import section

    parts = _b_ohm_parts(view, base_path=base_path, invite=invite)
    if parts is None:
        return ""
    body, aside_text = parts
    aside = f'<span class="b-aside">{_esc(aside_text)}</span>' if aside_text else ""
    return section(t("kind.hockey_practice"), body, aside_html=aside, klass="b-sec--place", sec_id="ohm")


def _b_ice(
    view: Mapping[str, Any], *, base_path: str, invite: bool, links: Mapping[str, Any], vv: Mapping[str, Any]
) -> str:
    """Блок «На льду»: массовое катание и ОХМ — вкладками одного блока, а не двумя расписаниями.

    Вкладки без JS: радио-кнопки и :has(). Обе панели в разметке — поисковик видит и ОХМ.
    """
    from src.application.style_b import section

    skate = _b_schedule_parts(view, base_path=base_path, invite=invite, links=links, vv=vv)
    ohm = _b_ohm_parts(view, base_path=base_path, invite=invite)
    if skate is None and ohm is None:
        return ""
    if ohm is None:
        title, body, aside = skate  # type: ignore[misc]
        return section(title, body, aside_html=aside, klass="b-sec--place", sec_id="schedule")
    ohm_body, ohm_aside = ohm
    ohm_label = t("kind.hockey_practice")
    if skate is None:
        aside = f'<span class="b-aside">{_esc(ohm_aside)}</span>' if ohm_aside else ""
        return section(ohm_label, ohm_body, aside_html=aside, klass="b-sec--place", sec_id="ohm")
    _title, skate_body, buy = skate
    ohm_head = f'<p class="b-pane__aside">{_esc(ohm_aside)}</p>' if ohm_aside else ""
    body = (
        '<div class="b-icetabs">'
        '<input type="radio" name="icetab" id="icetab-skate" class="b-icetabs__r" checked>'
        '<input type="radio" name="icetab" id="icetab-ohm" class="b-icetabs__r">'
        '<div class="b-seg" role="tablist">'
        f'<label for="icetab-skate" class="b-seg__i b-seg__i--skate">{_esc(t("kind.public_skate"))}</label>'
        f'<label for="icetab-ohm" class="b-seg__i b-seg__i--ohm">{_esc(ohm_label)}</label></div>'
        f'<div class="b-pane b-pane--skate">{skate_body}</div>'
        f'<div class="b-pane b-pane--ohm" id="ohm">{ohm_head}{ohm_body}</div>'
        "</div>"
    )
    return section("На льду", body, aside_html=buy, klass="b-sec--place", sec_id="schedule")


def _b_hours_rows(card: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Строки часов для таблицы «Как добраться»: «Открыто · каждый день 7:00–23:00», «Касса · 11:00–21:00»."""
    hours = card.get("opening_hours")
    if not isinstance(hours, Mapping):
        return []
    season_closed = _out_of_season(card)
    rows: list[tuple[str, str]] = []
    for key, label in (("complex", "Комплекс"), ("kassa", "Касса")):
        block = hours.get(key)
        if isinstance(block, Mapping) and block.get("open") and block.get("close"):
            rows.append((label, f"{format_clock(str(block['open']))}–{format_clock(str(block['close']))}"))
    groups = hours_groups(hours) if has_known_hours(hours) else []
    if len(groups) == 1 and groups[0][0] == "Ежедневно" and groups[0][1] is not None:
        pair = groups[0][1]
        rows.append(("Открыто", f"каждый день {format_clock(pair[0])}–{format_clock(pair[1])}"))
    else:
        for label, pair in groups:
            value = f"{format_clock(pair[0])}–{format_clock(pair[1])}" if pair is not None else "выходной"
            rows.append((label.lower(), value))
    if season_closed:
        # Сезон закрыт: это часы на время сезона, а не «можно приехать на этой неделе».
        rows = [("В сезоне" if key == "Открыто" else key, value) for key, value in rows]
    return rows


def _b_contacts(card: Mapping[str, Any], links: Mapping[str, Any]) -> str:
    """Адрес, часы и контакты внизу страницы: кнопки уже на обложке, здесь — справка и NAP для поиска."""
    html = _b_arrive(card, links, buttons=False, title="Адрес и контакты")
    address = format_place_address(str(card.get("address") or ""), city=_city(card))
    if not html and not address:
        return ""
    row = (
        f'<div class="b-info__row"><span class="b-info__key">Адрес</span>'
        f'<span class="b-info__val">{_esc(address)}</span></div>'
        if address
        else ""
    )
    if not html:
        from src.application.style_b import section

        return section("Адрес и контакты", f'<div class="b-info">{row}</div>', klass="b-sec--place", sec_id="contacts")
    return html.replace('<div class="b-info">', f'<div class="b-info">{row}', 1)


def _b_arrive(
    card: Mapping[str, Any], links: Mapping[str, Any], *, buttons: bool = True, title: str = ""
) -> str:
    from src.application.catalog_icons import icon_svg
    from src.application.style_b import section

    show_buttons = buttons
    buttons: list[str] = []
    if links.get("tel"):
        buttons.append(
            f'<a class="b-btn" href="{_esc(links["tel"])}" data-catalog-phone-beacon="{_esc(links.get("tel_beacon"))}">'
            f"{icon_svg('phone')}{_esc(t('cta.call'))}</a>"
        )
    if links.get("route"):
        href, blank = links["route"]
        attrs = ' rel="noopener nofollow" target="_blank"' if blank else ' rel="nofollow"'
        buttons.append(f'<a class="b-btn" href="{_esc(href)}"{attrs}>{icon_svg("route")}{_esc(t("cta.route"))}</a>')
    rows: list[str] = [
        f'<div class="b-info__row"><span class="b-info__key">{_esc(key)}</span>'
        f'<span class="b-info__val">{_esc(value)}</span></div>'
        for key, value in _b_hours_rows(card)
    ]
    phone = str(card.get("phone") or "").strip()
    if links.get("tel") and phone:
        rows.append(
            f'<a class="b-info__row" href="{_esc(links["tel"])}" data-catalog-phone-beacon="{_esc(links.get("tel_beacon"))}">'
            f'<span class="b-info__key">Телефон</span><span class="b-info__val">'
            f"{_esc(format_phone_display(phone.split(';')[0]))}</span></a>"
        )
    site = safe_external_url(card.get("website_url"))
    if site:
        rows.append(
            f'<a class="b-info__row" href="{_esc(site)}" rel="noopener nofollow" target="_blank">'
            f'<span class="b-info__key">Сайт</span><span class="b-info__val">{_esc(_display_host(site))}</span></a>'
        )
    instagram = str((card.get("social_urls") or {}).get("instagram") or "").strip()
    if instagram.lower().startswith("https://"):
        handle = instagram.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
        rows.append(
            f'<a class="b-info__row" href="{_esc(instagram)}" rel="noopener nofollow" target="_blank">'
            f'<span class="b-info__key">Instagram</span><span class="b-info__val">@{_esc(handle)}</span></a>'
        )
    body = ""
    if buttons and show_buttons:
        body += f'<div class="b-btns">{"".join(buttons)}</div>'
    if rows:
        body += f'<div class="b-info">{"".join(rows)}</div>'
    sec_id = "contacts" if title else ""
    return section(title or t("hub.directions"), body, klass="b-sec--place", sec_id=sec_id)


def _b_trainers(view: Mapping[str, Any], *, base_url: str, school_html: str = "") -> str:
    """Тренеры на этом месте (TASK-265), как в Mini App: тап — карточка тренера в Telegram.

    Нет тренеров — нет блока: вход для тренера тогда стоит в «Ещё на катке».
    """
    from src.application.place_links import public_telegram_cta_url, trainer_start_param
    from src.application.style_b import section, trainer_rows_html

    trainers = list(view.get("trainers") or [])
    if not trainers:
        return ""
    card = view["card"]
    coach = _b_coach_entry(card, first=False) if _skating(card) else ""
    arena_id = int(card["id"])
    city_id = int(card.get("city_id") or 0) or None

    def href_for(trainer: Mapping[str, Any]) -> str | None:
        return public_telegram_cta_url(
            base_url,
            start_param=trainer_start_param(int(trainer["id"]), arena_id),
            surface="place_page",
            city_id=city_id,
            arena_id=arena_id,
        )

    return section(
        t("place.trainers"),
        trainer_rows_html(trainers, href_for=href_for, cta=t("cta.go")) + school_html + coach,
        klass="b-sec--place",
        sec_id="trainers",
    )


def _b_coach_entry(card: Mapping[str, Any], *, first: bool) -> str:
    """Вход для тренера последней строкой раздела «Тренеры» — сразу на лендинг этого катка.

    Ссылка ``/trainers/{город}/{каток}`` (без slug — ``/trainers``); тап считается как
    ``coach_open`` (coach-sheet.js). Внутри Mini App не видна (tg-out).
    """
    from src.application.style_b import COACH_SHEET_SCRIPT_VERSION
    from src.application.trainer_landing_page import trainer_rink_path

    arena_id = int(card["id"])
    slug = str(card.get("slug") or "")
    href = trainer_rink_path(city_name=_city(card), slug=slug) if slug and _city(card) else "/trainers"
    city_id = int(card.get("city_id") or 0) or None
    beacon = f"/api/public/catalog/contact-click?surface=place_page&arena_id={arena_id}"
    if city_id:
        beacon += f"&city_id={city_id}"
    title = t("coach.entry_first_title") if first else t("coach.entry_title")
    sub = t("coach.entry_first_sub") if first else t("coach.entry_sub")
    return (
        f'<a class="b-coach tg-out" href="{_esc(href)}" data-coach-open data-beacon="{_esc(beacon)}">'
        f'<span class="b-coach__ic" aria-hidden="true">+</span>'
        f'<span class="b-coach__t"><b>{_esc(title)}</b><span>{_esc(sub)}</span></span>'
        f'<span class="b-coach__go">{_esc(t("coach.entry_go"))}&nbsp;›</span></a>'
        f'<script defer src="/static/share/coach-sheet.js?v={_esc(COACH_SHEET_SCRIPT_VERSION)}"></script>'
    )


def _b_onsite(card: Mapping[str, Any], *, cta_url: str | None, trainers_listed: bool = False) -> str:
    from src.application.catalog_icons import icon_svg
    from src.application.style_b import section

    amenities = card.get("amenities") or {}
    body = ""
    if card.get("venue_type") == "shop":
        chips = [
            f'<span class="b-chip">{icon_svg(icon)}{_esc(title)}</span>'
            for key, icon, title, _sub in _SHOP_SERVICES
            if amenities.get(key) is True
        ]
        chips += [
            f'<span class="b-chip">{_esc(label)}</span>' for key, label in _SHOP_DISCIPLINES if amenities.get(key) is True
        ]
        if chips:
            body += f'<div class="b-chips">{"".join(chips)}</div>'
        return section("Что здесь можно сделать", body, klass="b-sec--place")
    food = _food_partner(card)
    chips = [
        _b_amenity_chip(icon_svg(icon), label, food if key == "cafe" else None)
        for key, icon, label in _B_AMENITIES
        if amenities.get(key) is True
    ]
    if chips:
        body += f'<div class="b-chips">{"".join(chips)}</div>'
    n = 0 if trainers_listed else int(card.get("trainer_count") or 0)
    if n > 0:
        word = plural_ru(n, "тренер", "тренера", "тренеров")
        verb = "работает" if n == 1 else "работают"
        go = f'<span class="b-card__go">{_esc(t("cta.enroll"))}</span>' if cta_url else ""
        tag = "a" if cta_url else "div"
        href = f' href="{_esc(cta_url)}"' if cta_url else ""
        body += (
            f'<{tag} class="b-card"{href}><span><b>Здесь {verb} {n} {word}</b>'
            f"<span>индивидуальные и групповые занятия</span></span>{go}</{tag}>"
        )
    return section(t("place.on_site"), body, klass="b-sec--place")


def _food_partner(card: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for partner in card.get("partners") or []:
        if isinstance(partner, Mapping) and partner.get("kind") in ("food", "coffee"):
            return partner
    return None


def _b_amenity_chip(icon_html: str, label: str, partner: Mapping[str, Any] | None) -> str:
    """Чип «Кафе» при партнёре-кафе ведёт к блоку «После катка» и несёт его предложение."""
    if partner is None:
        return f'<span class="b-chip">{icon_html}{_esc(label)}</span>'
    mark = f'<span class="gp-chip-mark">{_esc(partner.get("offer"))}</span>'
    return f'<a class="b-chip" href="#partners">{icon_html}{_esc(label)}{mark}</a>'


_PARTNER_CHEVRON = (
    '<svg class="gp-row__chev" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M9 6l6 6-6 6"/></svg>'
)


def _b_partners(card: Mapping[str, Any]) -> str:
    """«После катка»: партнёры рядом — строка открывает шторку partner-sheet.js.

    Без JS строка ведёт на карту партнёра. Сразу после чипов «На месте»: лёд и тренеры выше.
    """
    from src.application.style_b import section

    partners = [p for p in card.get("partners") or [] if isinstance(p, Mapping)]
    if not partners:
        return ""
    rows: list[str] = []
    for p in partners:
        photo = (p.get("photos") or [None])[0] or p.get("logo")
        media = (
            f'<img class="gp-row__media" src="{_esc(photo)}" alt="" width="80" height="80" loading="lazy" decoding="async" />'
            if photo
            else '<span class="gp-row__media"></span>'
        )
        line = " · ".join(x for x in (str(p.get("line") or ""), str(p.get("where") or "")) if x)
        href = p.get("maps_url") or "#partners"
        rows.append(
            f'<a class="gp-row" href="{_esc(href)}" data-partner="{_esc(p.get("slug"))}">{media}'
            f'<span class="gp-row__body"><span class="gp-row__name">{_esc(p.get("name"))}</span>'
            f'<span class="gp-row__line">{_esc(line)}</span>'
            f'<span class="gp-row__offer">{_esc(p.get("offer"))} с&nbsp;Glide</span></span>{_PARTNER_CHEVRON}</a>'
        )
    aside = '<span class="gp-kicker">Партнёры Glide</span>'
    body = f'<div class="gp-list">{"".join(rows)}</div>'
    boot = {
        "partners": partners,
        "arenaId": card.get("id"),
        "cityId": card.get("city_id"),
        "placeName": format_public_name(str(card.get("name") or "")),
    }
    wv = _webapp_bundle_version()
    assets = (
        f'<script type="application/json" id="gp-data">{json_for_script(boot)}</script>'
        f'<link rel="stylesheet" href="/static/webapp/partner-sheet.css?v={_esc(wv)}" />'
        f'<script defer src="/static/webapp/partner-sheet.js?v={_esc(wv)}"></script>'
        "<script>document.addEventListener('DOMContentLoaded',function(){"
        "var d=JSON.parse(document.getElementById('gp-data').textContent);"
        "if(window.GlidePartners)GlidePartners.bind(document.getElementById('partners'),d.partners,"
        "{surface:'place_page',arenaId:d.arenaId,cityId:d.cityId,placeName:d.placeName});});</script>"
    )
    return section("После катка", body, aside_html=aside, klass="b-sec--place", sec_id="partners") + assets


def _b_rental(card: Mapping[str, Any]) -> str:
    from src.application.style_b import section

    hours = card.get("opening_hours") if isinstance(card.get("opening_hours"), Mapping) else {}
    catalog = hours.get("rental_catalog")
    if not isinstance(catalog, list):
        return ""
    rows: list[str] = []
    for row in catalog:
        if not isinstance(row, Mapping):
            continue
        label = str(row.get("label") or "").strip()
        price = str(row.get("price") or "").strip()
        if not label or not price:
            continue
        per = str(row.get("per") or "").strip()
        value = f"{price}/{per}" if per else price
        rows.append(
            f'<div class="b-info__row"><span class="b-info__key">{_esc(label)}</span>'
            f'<span class="b-info__val">{_esc(value)}</span></div>'
        )
    if not rows:
        return ""
    note = str(hours.get("rental_note") or "").strip()
    note_html = f'<p class="b-note">{_esc(_sentence(note))}</p>' if note else ""
    body = f'<div class="b-info">{"".join(rows)}</div>{note_html}'
    return section(_rental_section_title(card, hours), body, klass="b-sec--place")


def _b_about(card: Mapping[str, Any]) -> str:
    text = str(card.get("short_description") or "").strip()
    if not text:
        return ""
    # Справочный текст с led.by — не для сниппета: Google любит его больше meta description.
    return f'<section class="b-sec b-sec--place" data-nosnippet><p class="b-text">{_esc(text)}</p></section>'


def _b_plan(view: Mapping[str, Any], *, invite: bool) -> str:
    """Тёмный билет «Выбранный сеанс» над расписанием.

    По ссылке ``?s=`` сервер заполняет его сам. Без ``?s=`` кладётся скрытая заготовка:
    place-share.js показывает и заполняет её по тапу на время — без JS её не видно.
    """
    card = view["card"]
    focus = view.get("focus")
    if focus is None:
        if view.get("focus_missing"):
            nxt = view.get("next_slot")
            tail = f" Ближайший — {_esc(slot_when(nxt, today=view['today']))}." if nxt is not None else ""
            return (
                '<section class="b-sec" id="plan"><div class="b-plan b-plan--gone">'
                f"<b>Сеанса из ссылки уже нет в расписании.</b><span>{tail.strip()}</span></div></section>"
            )
        if not _skating(card) or not (view.get("days") or view.get("ohm_days")):
            return ""
    from src.application.session_load import LOAD_PLAN_LINES, load_meter_html

    kicker = "Тебя зовут кататься" if invite else "Выбранный сеанс"
    day_text = time_text = kind_text = soon = note = ""
    price_parts: list[tuple[str, str]] = []
    level = focus.get("typical_load_level") if focus is not None else None
    seats_line = plan_status_seats(focus.get("capacity_note")) if focus is not None else ""
    if focus is not None:
        d = _parse_iso_date(focus.get("local_date"))
        day_text = day_heading(d, today=view["today"]) if d else ""
        start = format_clock(str(focus.get("starts_at_local") or ""))
        end = format_clock(str(focus.get("ends_at_local") or ""))
        soon = starts_in_label(focus, now=view["now"])
        kind_text = session_kind_label(focus)
        price_parts, note = slot_plan_prices(focus)
        time_text = f"{start}–{end}" if end else start
    place_name = format_public_name(str(card.get("name") or ""))
    address = format_place_address(str(card.get("address") or ""), city=_city(card))
    where = " · ".join(x for x in (place_name, address) if x)

    def span(cls: str, text: str) -> str:
        hidden = "" if text else " hidden"
        return f'<span class="b-plan__{cls}"{hidden}>{_esc(text)}</span>'

    cells = "".join(f"<div><dt>{_esc(label)}</dt><dd>{_esc(value)}</dd></div>" for label, value in price_parts)
    prices = f'<dl class="b-plan__prices"{"" if cells else " hidden"}>{cells}</dl>'
    note_html = f'<p class="b-plan__note"{"" if note else " hidden"}>{_esc(note)}</p>'
    load_on = bool(seats_line or level in LOAD_PLAN_LINES)
    load = (
        f'<span class="b-plan__load"{"" if load_on else " hidden"}>'
        f'{"" if seats_line else load_meter_html(level)}'
        f'<span>{_esc(seats_line or LOAD_PLAN_LINES.get(level, ""))}</span></span>'
    )
    status_on = bool(soon or load_on)
    status = f'<p class="b-plan__status"{"" if status_on else " hidden"}>{span("soon", soon)}{load}</p>'
    company = _company_link(view)
    foot_bits = (f'<span class="b-plan__where">{_esc(where)}</span>' if where else "") + company
    foot = f'<footer class="b-plan__foot">{foot_bits}</footer>' if foot_bits else ""
    section_hidden = " hidden" if focus is None else ""
    return (
        f'<section class="b-sec" id="plan"{section_hidden}><div class="b-plan">'
        f'<header class="b-plan__head"><span class="b-plan__kicker">{_esc(kicker)}</span>'
        + span("day", day_text)
        + span("time", time_text)
        + "</header><div class=\"b-plan__mid\">"
        + span("kind", kind_text)
        + prices
        + note_html
        + status
        + "</div>"
        + foot
        + "</div></section>"
    )


def _company_link(view: Mapping[str, Any]) -> str:
    """Кнопка сбора компании только если город включён флагом. Иначе разметки нет."""
    from src.application.ice_company.flag import city_enabled
    from src.application.place_links import public_telegram_cta_url
    from src.shared.config import Settings

    card = view.get("card")
    focus = view.get("focus")
    if not isinstance(card, Mapping) or not isinstance(focus, Mapping) or focus.get("id") is None:
        return ""
    city_id = int(card.get("city_id") or 0)
    if not city_enabled(city_id):
        return ""
    session_id = int(focus["id"])
    url = public_telegram_cta_url(
        Settings().webapp_base_url or "",
        start_param=f"company_{session_id}",
        surface="place_page",
        city_id=city_id,
        arena_id=int(card.get("id") or 0) or None,
        session_id=session_id,
    )
    if not url:
        return ""
    return f'<a class="b-plan__company" href="{_esc(url)}">Собрать компанию</a>'


def render_place_body_b(
    view: Mapping[str, Any],
    *,
    base_path: str,
    base_url: str,
    invite: bool,
    cta_url: str | None,
    share: Mapping[str, str],
    story_image_url: str | None,
) -> str:
    from src.application.public_web_cta import phone_beacon_script, place_action_links

    card = view["card"]
    city_id = int(card.get("city_id") or 0) or None
    links = place_action_links(card, base_url=base_url, surface="place_page", city_id=city_id)
    if card.get("venue_type") == "shop":
        parts = [
            _b_hero(card, status_html=_b_status(view)),
            _b_about(card),
            _b_arrive(card, links),
            _b_onsite(card, cta_url=cta_url),
            _b_partners(card),
        ]
        body = "".join(parts)
        return body + phone_beacon_script(body)
    from src.application.place_links import public_telegram_cta_url, watch_start_param
    from src.application.place_visit_blocks import (
        facts_html,
        more_html,
        school_in_trainers_html,
        services_html,
    )

    if card.get("id") is not None:
        bell = public_telegram_cta_url(
            base_url, start_param=f"arena_{int(card['id'])}", surface="place_page",
            city_id=city_id, arena_id=int(card["id"]),
        )
        if bell:
            links["bell"] = bell
        # TASK-330: колокольчик пустой карточки ставит бот по /start watch_<id>.
        watch = public_telegram_cta_url(
            base_url, start_param=watch_start_param(int(card["id"])), surface="place_page",
            city_id=city_id, arena_id=int(card["id"]),
        )
        if watch:
            links["watch"] = watch
    vv = _place_visit(view)
    food = _food_partner(card)
    trainers_listed = bool(view.get("trainers"))
    coach_in_more = _b_coach_entry(card, first=True) if _skating(card) and not trainers_listed else ""
    hours = card.get("opening_hours") if isinstance(card.get("opening_hours"), Mapping) else {}
    # Порядок блоков — arena_visit_info.PLACE_BLOCKS: cover, ice, facts, services, trainers, partners, more.
    parts = [
        _b_hero(card, status_html=_b_status(view), chips_html=_b_hero_chips(card, links)),
        _b_plan(view, invite=invite),
        _b_ice(view, base_path=base_path, invite=invite, links=links, vv=vv),
        facts_html(vv, cafe_offer=str(food.get("offer") or "") if food else ""),
        services_html(vv, title=_rental_section_title(card, hours) if hours.get("rental_title") else "Прокат и услуги"),
        _b_trainers(view, base_url=base_url, school_html=school_in_trainers_html(vv.get("school"))),
        _b_partners(card),
        more_html(vv, coach_html=coach_in_more, tel_href=str(links.get("tel") or "")),
        _b_about(card),
        _b_contacts(card, links),
    ]
    body = "".join(parts)
    return body + phone_beacon_script(body)
