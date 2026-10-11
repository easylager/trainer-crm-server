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
from src.application.arena_profile import (
    WEEKDAY_SHORT_RU,
    format_intervals_ru,
    has_known_hours,
    hours_for_weekday,
    hours_groups,
    intervals_for_weekday,
    opening_hours_schema_org,
)
from src.application.place_links import join_public_origin, place_query
from src.shared.arena_schedule_mode import (
    PHONE_LINE,
    SCHEDULE_MODE_PHONE,
    SCHEDULE_MODE_SEASON_CLOSED,
    normalize_schedule_mode,
    season_closed_user_line,
)
from src.application.schedule_staleness import (
    LEVEL_FRESH,
    LEVEL_VERY_STALE,
    load_arena_freshness,
    stale_note,
    staleness_level,
    very_stale_note,
)
from src.shared.copy_ru import t
from src.shared.html_template import fill_placeholders, html_lang_for_country, json_for_script, safe_external_url
from src.shared.phone_guard import is_valid_public_phone, tel_href
from src.shared.schedule_basis import basis_hint_ru, public_basis_css_class
from src.shared.venue_types import has_public_skating

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "place.html"

#: Сколько дней расписания показывает страница. Неделя — горизонт «планирую выходные».
SCHEDULE_DAYS = 7
#: Сколько дней ищем выбранный сеанс (?s=). Шит «Поделиться» предлагает сеансы из ленты
#: карточки (две недели) — сеанс через 10 дней не должен выглядеть «уже прошедшим».
FOCUS_LOOKUP_DAYS = 14
#: Сколько слотов дня показывать до «ещё N».
_SLOTS_PER_DAY = 12

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
    ("retail", "🛒", "Розница", "Коньки, защита, форма"),
    ("skate_sharpening", "🔧", "Заточка", "Лезвия под ваш стиль катания"),
    ("skate_molding", "🔥", "Формовка", "Ботинок по форме стопы"),
    ("blade_profiling", "📐", "Профилирование", "Профиль лезвия под игрока"),
    ("foot_scan", "🦶", "3D-скан стопы", "Точный подбор размера"),
    ("skate_rental", "🔁", "Прокат", "Коньки на время"),
    ("repair", "🛠️", "Ремонт", "Коньки, клюшки, форма"),
)
_SHOP_DISCIPLINES: tuple[tuple[str, str], ...] = (
    ("discipline_hockey", "🏒 Хоккей"),
    ("discipline_figure", "⛸ Фигурное"),
    ("discipline_roller", "🛼 Ролики"),
)
_AMENITY_CHIPS: tuple[tuple[str, str], ...] = (
    ("skate_rental", "⛸ Прокат коньков"),
    ("skate_sharpening", "🔧 Заточка на месте"),
    ("locker_rooms", "🚪 Раздевалки"),
    ("cafe", "☕ Кафе"),
    ("parking", "🅿️ Парковка"),
    ("accessibility", "♿ Доступная среда"),
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


def starts_in_label(slot: Mapping[str, Any], *, now: datetime) -> str:
    """«Начнётся через 40 минут» — только если до начала меньше трёх часов."""
    starts = _parse_iso_dt(slot.get("starts_at_utc"))
    if starts is None:
        return ""
    minutes = int((starts - now).total_seconds() // 60)
    if minutes <= 0 or minutes > 180:
        return ""
    if minutes < 60:
        return f"Начнётся через {minutes} {plural_ru(minutes, 'минуту', 'минуты', 'минут')}"
    hours, rest = divmod(minutes, 60)
    if rest < 10:
        return f"Начнётся через {hours} {plural_ru(hours, 'час', 'часа', 'часов')}"
    return f"Начнётся через {hours} ч {rest} мин"


def ago_label(moment: datetime | None, *, now: datetime) -> str:
    """«обновлено 3 часа назад» без ложной точности."""
    if moment is None:
        return ""
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 3600:
        return "обновлено меньше часа назад"
    hours = seconds // 3600
    if hours < 24:
        return f"обновлено {hours} {plural_ru(hours, 'час', 'часа', 'часов')} назад"
    days = hours // 24
    if days == 1:
        return "обновлено вчера"
    return f"обновлено {days} {plural_ru(days, 'день', 'дня', 'дней')} назад"


def _hhmm_in_interval(hhmm: str, open_: str, close: str) -> bool:
    if close > open_:
        return open_ <= hhmm < close
    return hhmm >= open_ or hhmm < close


def open_now_label(card: Mapping[str, Any], *, now: datetime) -> str:
    """«Открыто до 22:00» / «Закроется в 19:00» / «Сегодня выходной»."""
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
            return f"Открыто до {close}"
    for open_, _close in intervals:
        if hhmm < open_:
            return f"Откроется в {open_}"
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
    level = LEVEL_FRESH
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
        # TASK-180: свежесть на момент ``now`` (тот же расчёт, что в API).
        fresh = (await load_arena_freshness(session, [int(card["id"])], now=now)).get(int(card["id"]))
        level = staleness_level(fresh)
        if level == LEVEL_VERY_STALE:
            # > 72 ч без удачного прогона: сеансы не выдаём за расписание вовсе.
            lookup_days = []
            schedule_note = very_stale_note(
                fresh,
                now=now,
                has_phone=bool(str(card.get("phone") or "").strip()),
                has_site=bool(str(card.get("tickets_url") or card.get("website_url") or "").strip()),
            )
        elif lookup_days:
            schedule_note = stale_note(fresh, now=now)

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
        # Расписание не подтверждено (> 72 ч) — не говорим «сеанс прошёл», говорим про расписание.
        focus_missing = focus is None and level != LEVEL_VERY_STALE

    all_slots = [s for d in days for s in d.get("sessions") or []]
    next_slot = all_slots[0] if all_slots else None
    ohm_days: list[dict[str, Any]] = []
    if _skating(card) and level != LEVEL_VERY_STALE:
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
            focus_missing = focus is None and level != LEVEL_VERY_STALE
    return {
        "card": card,
        "days": days,
        "ohm_days": ohm_days,
        "focus": focus,
        "focus_missing": focus_missing,
        "next_slot": next_slot,
        "session_count": len(all_slots),
        "schedule_level": level,
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
        if mode == SCHEDULE_MODE_PHONE:
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
        nxt = view.get("next_slot")
        if nxt is not None:
            if _parse_iso_date(nxt.get("local_date")) == today:
                return "live", "Сегодня есть лёд"
            return "soon", f"Ближайший лёд: {slot_when(nxt, today=today)}"
    label = open_now_label(card, now=now)
    if label:
        return ("open" if label.startswith("Открыто") else "shut"), label
    return None


def _skating(card: Mapping[str, Any]) -> bool:
    return has_public_skating(card.get("venue_type"))


def _city(card: Mapping[str, Any]) -> str:
    return str(card.get("city_name") or "").strip()


def _where(card: Mapping[str, Any]) -> str:
    parts = [str(card.get("district") or "").strip(), str(card.get("address") or "").strip()]
    return " · ".join(p for p in parts if p)


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
    if custom:
        return custom
    key = _SESSION_KIND_COPY_KEYS.get(str(slot.get("kind") or "").strip())
    return t(key) if key else ""


def invite_share_hook(view: Mapping[str, Any]) -> str:
    """Короткий текст приглашения — без даты и цены (они на og/story-картинке)."""
    if _skating(view["card"]):
        return "Погнали кататься?"
    return "Сходим сюда?"


def page_title(view: Mapping[str, Any], *, invite: bool = False) -> str:
    card = view["card"]
    name = str(card.get("name") or "")
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
        return f"{name}, {city} — расписание массового катания" if city else name
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


def _slot_chip(slot: Mapping[str, Any], *, focused: bool, base_path: str, invite: bool) -> str:
    hhmm = str(slot.get("starts_at_local") or "")[:5]
    price = slot_price(slot)
    href = base_path + place_query(session_id=int(slot["id"]), invite=invite)
    basis_cls = public_basis_css_class(str(slot.get("schedule_basis") or "live"))
    cls = "slot slot--focus" if focused else "slot"
    if basis_cls:
        cls += f" {basis_cls}"
    price_html = f'<span class="slot__price">{_esc(price)}</span>' if price else ""
    hint = basis_hint_ru(str(slot.get("schedule_basis") or "live"))
    title_attr = f' title="{_esc(hint)}"' if hint else ""
    # Слот — ссылка на ту же страницу с ?s=: выбрал сеанс — и делишься уже им.
    return (
        f'<a class="{cls}" href="{_esc(href)}#plan" rel="nofollow"{title_attr}>'
        f'<span class="slot__time">{_esc(hhmm)}</span>{price_html}</a>'
    )


def _schedule_mode_call_html(card: Mapping[str, Any]) -> str:
    phone = str(card.get("phone") or "").strip()
    if phone and is_valid_public_phone(phone):
        return f'<p class="sched__mode"><a href="tel:{_esc(tel_href(phone))}">{t("cta.call")}</a></p>'
    return ""


def _schedule_html(view: Mapping[str, Any], *, base_path: str, invite: bool) -> str:
    card = view["card"]
    if not _skating(card):
        return ""
    mode = normalize_schedule_mode(card.get("schedule_mode"))
    if mode == SCHEDULE_MODE_PHONE:
        return (
            f'<section class="sec" id="schedule"><h2 class="sec__title">{t("kind.public_skate")}</h2>'
            f'<p class="sched__mode">{_esc(PHONE_LINE)}</p>'
            + _schedule_mode_call_html(card)
            + "</section>"
        )
    if mode == SCHEDULE_MODE_SEASON_CLOSED:
        reopen = _parse_iso_date(card.get("schedule_reopen_date"))
        line = season_closed_user_line(reopen_date=reopen, note=card.get("schedule_mode_note"))
        return (
            f'<section class="sec" id="schedule"><h2 class="sec__title">{t("kind.public_skate")}</h2>'
            f'<p class="sched__mode">{_esc(line)}</p></section>'
        )
    if card.get("in_season") is False:
        return ""
    days = view.get("days") or []
    focus = view.get("focus")
    focus_id = int(focus["id"]) if focus is not None else None
    note = str(view.get("schedule_note") or "").strip()
    if view.get("schedule_level") == LEVEL_VERY_STALE:
        # TASK-180: расписание > 72 ч не подтверждалось — вместо сеансов просьба уточнить.
        phone = str(card.get("phone") or "").strip()
        links = []
        if phone and is_valid_public_phone(phone):
            links.append(f'<a href="tel:{_esc(tel_href(phone))}">{_esc(phone)}</a>')
        tickets = safe_external_url(card.get("tickets_url")) or safe_external_url(card.get("website_url"))
        if tickets:
            links.append(f'<a href="{_esc(tickets)}" rel="nofollow noopener" target="_blank">Сайт катка</a>')
        return (
            f'<section class="sec" id="schedule"><h2 class="sec__title">{t("kind.public_skate")}</h2>'
            f'<p class="sched__stale">{_esc(note)}</p>'
            + (f'<p class="sched__stale">{" · ".join(links)}</p>' if links else "")
            + "</section>"
        )
    if not days:
        phone = str(card.get("phone") or "").strip()
        hint = (
            "Расписание этого катка мы пока не получаем автоматически — позвоните, там подскажут."
            if phone
            else "Расписание этого катка мы пока не получаем автоматически."
        )
        return (
            f'<section class="sec"><h2 class="sec__title">{t("kind.public_skate")}</h2>'
            f'<p class="muted">{_esc(hint)}</p></section>'
        )
    phone = str(card.get("phone") or "").strip()
    non_live = [
        basis_hint_ru(str(s.get("schedule_basis") or "live"))
        for day in days
        for s in (day.get("sessions") or [])
    ]
    non_live = [h for h in non_live if h]
    basis_note = ""
    if non_live:
        if phone and is_valid_public_phone(phone):
            tel_link = f' <a href="tel:{_esc(tel_href(phone))}">{t("cta.call")}</a>'
        else:
            tel_link = ""
        basis_note = f'<p class="schedule-basis">{_esc(non_live[0])}.{tel_link}</p>'
    parts = [f'<section class="sec" id="schedule"><h2 class="sec__title">{t("kind.public_skate")}</h2>']
    if note:
        # TASK-180: > 6 ч без удачного прогона — сеансы показываем, но честно.
        parts.append(f'<p class="sched__stale">{_esc(note)}</p>')
    if basis_note:
        parts.append(basis_note)
    for day in days:
        d = _parse_iso_date(day.get("local_date"))
        if d is None:
            continue
        slots = list(day.get("sessions") or [])
        chips = "".join(
            _slot_chip(s, focused=(focus_id == int(s["id"])), base_path=base_path, invite=invite)
            for s in slots[:_SLOTS_PER_DAY]
        )
        more = len(slots) - _SLOTS_PER_DAY
        more_html = f'<span class="slot slot--more">ещё {more}</span>' if more > 0 else ""
        parts.append(
            '<div class="day">'
            f'<p class="day__label">{_esc(day_heading(d, today=view["today"]))}</p>'
            f'<div class="slots">{chips}{more_html}</div></div>'
        )
    parts.append('<p class="hint">Нажмите на время, чтобы поделиться именно этим сеансом.</p></section>')
    return "".join(parts)


def _ohm_html(view: Mapping[str, Any], *, base_path: str, invite: bool) -> str:
    days = view.get("ohm_days") or []
    slots = [s for day in days for s in (day.get("sessions") or [])]
    if not slots:
        return ""
    focus = view.get("focus")
    focus_id = int(focus["id"]) if focus is not None else None
    notes: list[str] = []
    for slot in slots:
        for key in ("age_note", "capacity_note"):
            note = str(slot.get(key) or "").strip()
            if note and note not in notes:
                notes.append(note)
    parts = [f'<section class="sec" id="ohm"><h2 class="sec__title">{t("kind.hockey_practice")}</h2>']
    for day in days:
        d = _parse_iso_date(day.get("local_date"))
        if d is None:
            continue
        day_slots = list(day.get("sessions") or [])
        if not day_slots:
            continue
        chips = "".join(
            _slot_chip(s, focused=(focus_id == int(s["id"])), base_path=base_path, invite=invite)
            for s in day_slots[:_SLOTS_PER_DAY]
        )
        parts.append(
            '<div class="day">'
            f'<p class="day__label">{_esc(day_heading(d, today=view["today"]))}</p>'
            f'<div class="slots">{chips}</div></div>'
        )
    if notes:
        parts.append(f'<p class="hint">{_esc(" ".join(notes))}</p>')
    parts.append("</section>")
    return "".join(parts)


def _focus_html(view: Mapping[str, Any], *, invite: bool) -> str:
    card = view["card"]
    focus = view.get("focus")
    if focus is None:
        if view.get("focus_missing"):
            nxt = view.get("next_slot")
            tail = f" Ближайший — {_esc(slot_when(nxt, today=view['today']))}." if nxt is not None else ""
            return (
                '<section class="plan plan--gone" id="plan">'
                f'<p class="plan__kicker">Сеанса из ссылки уже нет в расписании</p>'
                f'<p class="plan__note">Расписание ниже — актуальное.{tail}</p>'
                "</section>"
            )
        return ""
    soon = starts_in_label(focus, now=view["now"])
    kicker = "Тебя зовут кататься" if invite else "Выбранный сеанс"
    prices = "".join(f"<li>{_esc(line)}</li>" for line in slot_price_lines(focus))
    end = str(focus.get("ends_at_local") or "")[:5]
    start = str(focus.get("starts_at_local") or "")[:5]
    time_text = f"{start}–{end}" if start and end else start
    d = _parse_iso_date(focus.get("local_date"))
    day_text = day_heading(d, today=view["today"]) if d else ""
    label = session_kind_label(focus)
    return (
        '<section class="plan" id="plan">'
        f'<p class="plan__kicker">{_esc(kicker)}</p>'
        f'<p class="plan__day">{_esc(day_text)}</p>'
        f'<p class="plan__time">{_esc(time_text)}</p>'
        + (f'<p class="plan__label">{_esc(label)}</p>' if label else "")
        + (f'<p class="plan__soon">{_esc(soon)}</p>' if soon else "")
        + (f'<ul class="plan__prices">{prices}</ul>' if prices else "")
        + f'<p class="plan__where">{_esc(card.get("name"))}'
        + (f" · {_esc(_where(card))}" if _where(card) else "")
        + "</p></section>"
    )


def _services_html(card: Mapping[str, Any]) -> str:
    if card.get("venue_type") != "shop":
        return ""
    amenities = card.get("amenities") or {}
    tiles = [
        f'<div class="tile"><span class="tile__icon">{icon}</span>'
        f'<p class="tile__title">{_esc(title)}</p><p class="tile__sub">{_esc(sub)}</p></div>'
        for key, icon, title, sub in _SHOP_SERVICES
        if amenities.get(key) is True
    ]
    disciplines = [
        f'<span class="chip">{_esc(label)}</span>' for key, label in _SHOP_DISCIPLINES if amenities.get(key) is True
    ]
    if not tiles and not disciplines:
        return ""
    for_whom = (
        f'<p class="for-whom">Специализация</p><div class="chips">{"".join(disciplines)}</div>' if disciplines else ""
    )
    return (
        '<section class="sec"><h2 class="sec__title">Что здесь можно сделать</h2>'
        + (f'<div class="tiles">{"".join(tiles)}</div>' if tiles else "")
        + for_whom
        + "</section>"
    )


def _amenities_html(card: Mapping[str, Any]) -> str:
    if card.get("venue_type") == "shop":
        return ""
    amenities = card.get("amenities") or {}
    chips = [f'<span class="chip">{_esc(label)}</span>' for key, label in _AMENITY_CHIPS if amenities.get(key) is True]
    if not chips:
        return ""
    return (
        '<section class="sec"><h2 class="sec__title">Удобства</h2>'
        f'<div class="chips">{"".join(chips)}</div></section>'
    )


def _fixed_hours_row(label: str, block: Any) -> str:
    if not isinstance(block, Mapping):
        return ""
    open_ = str(block.get("open") or "").strip()
    close = str(block.get("close") or "").strip()
    if not open_ or not close:
        return ""
    return f'<p class="row"><span>{_esc(label)}</span><b>{_esc(f"{open_}–{close}")}</b></p>'


def _hours_html(card: Mapping[str, Any]) -> str:
    hours = card.get("opening_hours")
    if not isinstance(hours, Mapping):
        return ""
    season_closed = _out_of_season(card)
    rows = _fixed_hours_row("Комплекс", hours.get("complex")) + _fixed_hours_row("Касса", hours.get("kassa"))
    if has_known_hours(hours):
        rows += _hours_rows(hours, season_closed=season_closed)
    if not rows:
        return ""
    if season_closed:
        return (
            '<section class="sec"><h2 class="sec__title">Часы в сезоне</h2>'
            '<p class="muted">Сейчас приехать нельзя. '
            "Ниже — часы на время, когда площадка открыта.</p>"
            f"{rows}</section>"
        )
    return f'<section class="sec"><h2 class="sec__title">Когда можно приехать</h2>{rows}</section>'


def _out_of_season(card: Mapping[str, Any]) -> bool:
    """Зимняя площадка вне сезона (``in_season``) или явный режим «сезон закрыт»."""
    if normalize_schedule_mode(card.get("schedule_mode")) == SCHEDULE_MODE_SEASON_CLOSED:
        return True
    return card.get("in_season") is False


def _hours_rows(hours: Mapping[str, Any], *, season_closed: bool) -> str:
    """Закрытый сезон — «ежедневно», не расписание этой недели."""
    if season_closed:
        groups = hours_groups(hours)
        if groups and all(pair for _, pair in groups):
            return "".join(
                f'<p class="row"><span>{_esc(label)}</span>'
                f"<b>{_esc(pair[0])}–{_esc(pair[1])}</b></p>"
                for label, pair in groups
                if pair is not None
            )
    return "".join(
        f'<p class="row"><span>{_esc(WEEKDAY_SHORT_RU[d])}</span>'
        f'<b>{_esc(format_intervals_ru(intervals_for_weekday(hours, d)) if intervals_for_weekday(hours, d) else "выходной")}</b></p>'
        for d in range(7)
    )


def _rental_section_title(card: Mapping[str, Any], hours: Mapping[str, Any]) -> str:
    """Minikatok продаёт услуги площадки. Остальной прайс — прокат, пока не сказано иначе."""
    explicit = str(hours.get("rental_title") or "").strip()
    if explicit:
        return explicit
    blob = f"{card.get('name') or ''} {card.get('website_url') or ''}".casefold()
    if "minikatok" in blob:
        return "Услуги"
    return "Прокат инвентаря"


def _rental_catalog_html(card: Mapping[str, Any]) -> str:
    hours = card.get("opening_hours") if isinstance(card.get("opening_hours"), Mapping) else {}
    catalog = hours.get("rental_catalog")
    if not isinstance(catalog, list) or not catalog:
        return ""
    items = []
    for row in catalog:
        if not isinstance(row, Mapping):
            continue
        label = str(row.get("label") or "").strip()
        price = str(row.get("price") or "").strip()
        if not label or not price:
            continue
        per = str(row.get("per") or "").strip()
        note = str(row.get("note") or "").strip()
        per_html = f'<span class="offer__per">/{_esc(per)}</span>' if per else ""
        note_html = f'<p class="offer__note">{_esc(note)}</p>' if note else ""
        items.append(
            '<div class="offer">'
            f'<div class="offer__top"><span class="offer__name">{_esc(label)}</span>'
            f'<b class="offer__price">{_esc(price)}{per_html}</b></div>'
            f"{note_html}</div>"
        )
    if not items:
        return ""
    title = _rental_section_title(card, hours)
    note = str(hours.get("rental_note") or "").strip()
    note_html = f'<p class="muted">{_esc(note)}</p>' if note else ""
    return f'<section class="sec"><h2 class="sec__title">{_esc(title)}</h2>' + "".join(items) + note_html + "</section>"


def _trainers_html(card: Mapping[str, Any], *, cta_url: str | None) -> str:
    n = int(card.get("trainer_count") or 0)
    if n <= 0 or card.get("venue_type") == "shop":
        return ""
    word = plural_ru(n, "тренер", "тренера", "тренеров")
    verb = "работает" if n == 1 else "работают"
    link = f' <a href="{_esc(cta_url)}">Записаться в Telegram</a>' if cta_url else ""
    return (
        '<section class="sec"><h2 class="sec__title">Тренеры</h2>'
        f"<p>Здесь {verb} {n} {word} — индивидуальные и групповые занятия.{link}</p></section>"
    )


def _hero_photo_url(card: Mapping[str, Any]) -> str | None:
    """Первое опубликованное фото места — во всю ширину шапки. Нет фото — шапка без него."""
    hero = card.get("hero")
    variants = hero.get("variants") if isinstance(hero, Mapping) else None
    if not isinstance(variants, Mapping):
        return None
    url = str(variants.get("card") or variants.get("thumb") or variants.get("hero") or "").strip()
    return url if url.lower().startswith(("https://", "http://", "/")) else None


def _maps_url(card: Mapping[str, Any]) -> str | None:
    lat, lon = card.get("latitude"), card.get("longitude")
    if lat is not None and lon is not None:
        return f"https://yandex.ru/maps/?pt={float(lon)},{float(lat)}&z=16&l=map"
    query = " ".join(x for x in (_city(card), str(card.get("address") or "")) if x).strip()
    return f"https://yandex.ru/maps/?text={quote(query)}" if query else None


def _display_host(url: str) -> str:
    """«https://xn--j1aaid0h.xn--90ais/» → «конёк.бел»: адрес показываем так, как его набирают."""
    host = url.split("://", 1)[-1].rstrip("/")
    try:
        return host.encode("ascii").decode("idna") if "xn--" in host else host
    except UnicodeError:
        return host


def _contacts_html(card: Mapping[str, Any]) -> str:
    rows: list[str] = []
    address = str(card.get("address") or "").strip()
    maps = _maps_url(card)
    if address:
        addr_html = (
            f'<a href="{_esc(maps)}" rel="noopener" target="_blank">{_esc(address)}</a>' if maps else _esc(address)
        )
        rows.append(f'<p class="row"><span>Адрес</span><b>{addr_html}</b></p>')
    phone = str(card.get("phone") or "").strip()
    if phone and is_valid_public_phone(phone):
        rows.append(f'<p class="row"><span>Телефон</span><b><a href="tel:{_esc(tel_href(phone))}">{_esc(phone)}</a></b></p>')
    site = safe_external_url(card.get("website_url"))
    if site:
        label = str(card.get("venue_site_label") or "Сайт")
        rows.append(
            f'<p class="row"><span>{_esc(label)}</span><b><a href="{_esc(site)}" rel="noopener nofollow" target="_blank">'
            f"{_esc(_display_host(site))}</a></b></p>"
        )
    instagram = str((card.get("social_urls") or {}).get("instagram") or "").strip()
    if instagram.lower().startswith("https://"):
        handle = instagram.rstrip("/").rsplit("/", 1)[-1]
        rows.append(
            f'<p class="row"><span>Instagram</span><b><a href="{_esc(instagram)}" rel="noopener nofollow" '
            f'target="_blank">@{_esc(handle)}</a></b></p>'
        )
    tickets = safe_external_url(card.get("tickets_url"))
    if tickets:
        rows.append(
            f'<p class="row"><span>Билеты</span><b><a href="{_esc(tickets)}" rel="noopener nofollow" target="_blank">Купить онлайн</a></b></p>'
        )
    if not rows:
        return ""
    return '<section class="sec"><h2 class="sec__title">Контакты</h2>' + "".join(rows) + "</section>"


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
) -> str:
    """Ряд «Поделиться». Подборка в Telegram — только url (превью из og), без text=."""
    url = share["share_url"]
    body = share["share_body"]
    full = f"{body}\n{url}" if body else url
    tg = f"https://t.me/share/url?url={quote(url, safe='')}"
    if not telegram_link_only and body:
        tg += f"&text={quote(body, safe='')}"
    wa = f"https://wa.me/?text={quote(full, safe='')}"
    viber = f"viber://forward?text={quote(full, safe='')}"
    vk = f"https://vk.com/share.php?url={quote(url, safe='')}"
    story = ""
    if story_image_url:
        story = (
            f'<a class="share__story" href="{_esc(story_image_url)}" download="glide-story.png">'
            "Сохранить картинку в галерею</a>"
        )
    return (
        f'<section class="share" aria-label="{t("cta.share")}">'
        f'<p class="share__title">{"Позвать друзей" if venue_type == "ice" else t("cta.share")}</p>'
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
        + story
        + "</section>"
    )


def _trust_html(view: Mapping[str, Any]) -> str:
    """Откуда данные и насколько они свежие (DEC-014). Без этого «8 BYN» — просто цифра."""
    card = view["card"]
    now: datetime = view["now"]
    fresh = card.get("freshness") or {}
    lines: list[str] = []
    observed = _parse_iso_dt(fresh.get("schedule_observed_at"))
    if _skating(card) and observed is not None:
        source = str(fresh.get("source_label") or "сайта катка")
        if source.startswith("сайт "):
            source = "сайта " + source[5:]
        lines.append(f"Расписание с {source}, {ago_label(observed, now=now)}.")
    verified = _parse_iso_dt(fresh.get("verified_at"))
    edited = _parse_iso_dt(fresh.get("profile_updated_at"))
    if verified is not None:
        lines.append(
            f"Карточку проверила команда Glide {verified.day} {_MONTHS_GEN[verified.month - 1]} {verified.year}."
        )
    if edited is not None and (verified is None or edited > verified):
        # Q-012: у места без расписания с сайта единственный честный сигнал свежести —
        # последняя правка карточки командой.
        lines.append(f"Данные карточки {ago_label(edited, now=now).replace('обновлено', 'обновлены', 1)}.")
    if not lines:
        lines.append("Карточку собрала команда Glide по открытым данным.")
    if card.get("venue_type") == "outdoor":
        lines.append("Открытый лёд зависит от погоды — уточняйте перед выездом.")
    if _skating(card) and view.get("session_count"):
        lines.append("Время и цену конкретного сеанса лучше уточнить на месте.")
    return "".join(f"<p>{_esc(line)}</p>" for line in lines)


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
    for day in view.get("days") or []:
        for slot in day.get("sessions") or []:
            event: dict[str, Any] = {
                "@type": "Event",
                "name": f"{t('kind.public_skate')} — {card.get('name')}",
                "startDate": slot.get("starts_at_utc"),
                "endDate": slot.get("ends_at_utc"),
                "eventStatus": "https://schema.org/EventScheduled",
                "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
                "location": {"@type": "Place", "name": card.get("name"), "address": place["address"]},
            }
            adult = slot.get("price_adult_minor")
            if adult is not None:
                event["offers"] = {
                    "@type": "Offer",
                    "price": f"{int(adult) / 100:.2f}",
                    "priceCurrency": slot.get("currency_code") or "BYN",
                    "url": canonical_url + place_query(session_id=int(slot["id"])),
                }
            events.append(event)
            if len(events) >= 10:
                break
        if len(events) >= 10:
            break
    if events:
        place["event"] = events
    # </script> или <!-- внутри JSON закрыли бы тег раньше времени — экранируем < > &.
    return json_for_script(place)


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
    badge = status_badge(view)
    vt = str(card.get("venue_type") or "ice")
    icon = {"ice": "❄️", "gym": "🏋️", "choreo": "🩰", "pool": "🏊", "outdoor": "🌳", "shop": "🧰"}.get(vt, "📍")
    badge_html = (
        f'<p class="badge badge--{_esc(badge[0])}"><span class="badge__dot"></span>{_esc(badge[1])}</p>'
        if badge
        else ""
    )
    where = _where(card)
    photo = _hero_photo_url(card)
    photo_html = (
        f'<img class="hero__photo" src="{_esc(photo)}" alt="{_esc(card.get("name"))}" loading="eager" decoding="async" />'
        if photo
        else ""
    )
    hero = (
        f'<header class="hero hero--{_esc(vt)}{" hero--photo" if photo else ""}">'
        + photo_html
        + f'<p class="hero__type">{icon} {_esc(card.get("venue_noun") or "")}</p>'
        f'<h1 class="hero__title">{_esc(card.get("name"))}</h1>'
        + (f'<p class="hero__where">{_esc(where)}</p>' if where else "")
        + badge_html
        + "</header>"
    )
    description_text = str(card.get("short_description") or "").strip()
    about = f'<p class="about">{_esc(description_text)}</p>' if description_text else ""
    from src.application.public_web_cta import render_place_primary_actions

    base_url = join_public_origin(canonical_url, "/").rstrip("/") if canonical_url else ""
    actions = render_place_primary_actions(
        card,
        base_url=base_url,
        surface="place_page",
        city_id=int(card.get("city_id") or 0) or None,
        city_name=_city(card) or "",
        telegram_url=cta_url,
    )
    body = "".join(
        [
            hero,
            _focus_html(view, invite=invite),
            about,
            actions,
            _schedule_html(view, base_path=base_path, invite=invite),
            _ohm_html(view, base_path=base_path, invite=invite),
            _services_html(card),
            _hours_html(card),
            _rental_catalog_html(card),
            _amenities_html(card),
            _trainers_html(card, cta_url=cta_url),
            _contacts_html(card),
            _share_html(share, venue_type=vt, story_image_url=story_image_url),
        ]
    )
    city = _city(card)
    city_link = f'<a href="{_esc(city_page_url)}">Весь лёд: {_esc(city)} сегодня</a>' if city_page_url and city else ""
    # Ссылка с ?s= / ?i= — та же страница; в индекс идёт только каноническая.
    robots = (
        "noindex, follow"
        if (view.get("focus") is not None or invite or bool(share_src))
        else "index, follow"
    )

    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    lang, og_locale = html_lang_for_country(country if country is not None else card.get("country"))
    replacements = {
        "__OG_TITLE__": _esc(title),
        "__OG_DESCRIPTION__": _esc(og_description(view)),
        "__CANONICAL__": _esc(canonical_url),
        "__OG_URL__": _esc(share["share_url"]),
        "__OG_IMAGE__": _esc(og_image_url),
        "__LANG__": lang,
        "__OG_LOCALE__": og_locale,
        "__ROBOTS__": robots,
        "__HEAD_EXTRA__": "",
        "__JSONLD__": _json_ld(view, canonical_url=canonical_url, image_url=og_image_url),
        "__CITY__": _esc(city or "Беларусь"),
        "__CITY_LINK__": city_link,
        "__TRUST__": _trust_html(view),
        "__BODY__": body,
    }
    return fill_placeholders(html, replacements)
