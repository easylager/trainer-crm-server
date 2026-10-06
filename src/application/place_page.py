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
    list_public_arena_sessions,
)
from src.application.client_share_message import share_body_for_native_share_dialog
from src.application.ice_city_day import format_price_minor, plural_ru
from src.shared.schedule_basis import basis_hint_ru, public_basis_css_class
from src.application.arena_profile import (
    WEEKDAY_SHORT_RU,
    format_intervals_ru,
    has_known_hours,
    hours_for_weekday,
    hours_groups,
    intervals_for_weekday,
    opening_hours_schema_org,
)
from src.application.place_links import place_query
from src.application.schedule_staleness import (
    LEVEL_FRESH,
    LEVEL_VERY_STALE,
    load_arena_freshness,
    stale_note,
    staleness_level,
    very_stale_note,
)
from src.shared.html_template import fill_placeholders, json_for_script, safe_external_url
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
) -> dict[str, Any] | None:
    """Карточка места + неделя расписания + выбранный сеанс. ``None`` — места нет в каталоге."""
    card = await get_public_arena_card(session, arena_ref)
    if card is None:
        return None
    now = now or datetime.now(timezone.utc)
    tz = ZoneInfo(str(card.get("timezone") or "Europe/Minsk"))
    today = now.astimezone(tz).date()

    lookup_days: list[dict[str, Any]] = []
    level = LEVEL_FRESH
    schedule_note = ""
    if _skating(card):
        feed = await list_public_arena_sessions(
            session,
            str(card["id"]),
            date_from=today,
            date_to=today + timedelta(days=FOCUS_LOOKUP_DAYS - 1),
        )
        lookup_days = list((feed or {}).get("days") or [])
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
    return {
        "card": card,
        "days": days,
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
    пересылает объявление. Поэтому без восклицаний и без «лучший каток города».
    """
    card = view["card"]
    today: date = view["today"]
    name = str(card.get("name") or "")
    slot = view.get("focus") or view.get("next_slot")
    lines: list[str] = []
    if invite:
        lines.append("Погнали кататься? ⛸" if _skating(card) else "Сходим сюда?")
    else:
        if _skating(card):
            lines.append(f"{name} — массовое катание")
        else:
            lines.append(f"{name} — {str(card.get('venue_noun') or '').lower()}".rstrip(" —"))
    if slot is not None and _skating(card):
        when = slot_when(slot, today=today, absolute=True)
        price = slot_price(slot)
        line = f"{when}" + (f" · {price}" if price else "")
        if invite:
            line = f"{when} — {name}" + (f", {price}" if price else "")
        lines.append(line)
    elif invite:
        lines.append(name)
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


def _schedule_html(view: Mapping[str, Any], *, base_path: str, invite: bool) -> str:
    card = view["card"]
    if not _skating(card) or card.get("in_season") is False:
        return ""
    days = view.get("days") or []
    focus = view.get("focus")
    focus_id = int(focus["id"]) if focus is not None else None
    note = str(view.get("schedule_note") or "").strip()
    if view.get("schedule_level") == LEVEL_VERY_STALE:
        # TASK-180: расписание > 72 ч не подтверждалось — вместо сеансов просьба уточнить.
        phone = str(card.get("phone") or "").strip()
        tel = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
        links = []
        if phone and tel:
            links.append(f'<a href="tel:{_esc(tel)}">{_esc(phone)}</a>')
        tickets = safe_external_url(card.get("tickets_url")) or safe_external_url(card.get("website_url"))
        if tickets:
            links.append(f'<a href="{_esc(tickets)}" rel="nofollow noopener" target="_blank">Сайт катка</a>')
        return (
            '<section class="sec" id="schedule"><h2 class="sec__title">Массовое катание</h2>'
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
            '<section class="sec"><h2 class="sec__title">Массовое катание</h2>'
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
        tel = f' <a href="tel:{_esc(phone)}">Позвонить</a>' if phone else ""
        basis_note = f'<p class="schedule-basis">{_esc(non_live[0])}.{tel}</p>'
    parts = ['<section class="sec" id="schedule"><h2 class="sec__title">Массовое катание</h2>']
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


def _focus_html(view: Mapping[str, Any], *, invite: bool) -> str:
    card = view["card"]
    focus = view.get("focus")
    if focus is None:
        if view.get("focus_missing"):
            nxt = view.get("next_slot")
            tail = f" Ближайший — {_esc(slot_when(nxt, today=view['today']))}." if nxt is not None else ""
            return (
                '<section class="plan plan--gone" id="plan">'
                f'<p class="plan__kicker">Этот сеанс уже прошёл</p><p class="plan__note">Расписание ниже — актуальное.{tail}</p>'
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
    label = str(focus.get("session_label") or "").strip()
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


def _hours_html(card: Mapping[str, Any]) -> str:
    hours = card.get("opening_hours")
    if not has_known_hours(hours):
        return ""
    rows = "".join(
        f'<p class="row"><span>{_esc(WEEKDAY_SHORT_RU[d])}</span>'
        f'<b>{_esc(format_intervals_ru(intervals_for_weekday(hours, d)) if intervals_for_weekday(hours, d) else "выходной")}</b></p>'
        for d in range(7)
    )
    return f'<section class="sec"><h2 class="sec__title">Когда можно приехать</h2>{rows}</section>'


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
        price_text = f"{price}/{per}" if per else price
        items.append(
            f'<p class="row"><span>{_esc(label)}</span><b>{_esc(price_text)}</b>'
            + (f'<span class="row__note">{_esc(note)}</span>' if note else "")
            + "</p>"
        )
    if not items:
        return ""
    return '<section class="sec"><h2 class="sec__title">Прокат инвентаря</h2>' + "".join(items) + "</section>"


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
    if phone:
        tel = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
        rows.append(f'<p class="row"><span>Телефон</span><b><a href="tel:{_esc(tel)}">{_esc(phone)}</a></b></p>')
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


def _share_html(share: Mapping[str, str], *, venue_type: str = "ice") -> str:
    url = share["share_url"]
    body = share["share_body"]
    full = f"{body}\n{url}" if body else url
    tg = f"https://t.me/share/url?url={quote(url, safe='')}&text={quote(body, safe='')}"
    wa = f"https://wa.me/?text={quote(full, safe='')}"
    viber = f"viber://forward?text={quote(full, safe='')}"
    vk = f"https://vk.com/share.php?url={quote(url, safe='')}"
    return (
        '<section class="share" aria-label="Поделиться">'
        f'<p class="share__title">{"Позвать друзей" if venue_type == "ice" else "Поделиться"}</p>'
        '<div class="share__row">'
        f'<a class="share__btn share__btn--tg" href="{_esc(tg)}" rel="noopener" target="_blank">Telegram</a>'
        f'<a class="share__btn" href="{_esc(viber)}">Viber</a>'
        f'<a class="share__btn" href="{_esc(wa)}" rel="noopener" target="_blank">WhatsApp</a>'
        f'<a class="share__btn" href="{_esc(vk)}" rel="noopener" target="_blank">VK</a>'
        f'<button class="share__btn" type="button" data-copy="{_esc(full)}">Скопировать</button>'
        "</div></section>"
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
                "name": f"Массовое катание — {card.get('name')}",
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
    cta = f'<a class="cta" href="{_esc(cta_url)}">Открыть в Telegram</a>' if cta_url else ""
    maps = _maps_url(card)
    route = (
        f'<a class="cta cta--ghost" href="{_esc(maps)}" rel="noopener" target="_blank">Как добраться</a>'
        if maps
        else ""
    )
    # Telegram — в закреплённой кнопке снизу (dock), сверху только маршрут: две одинаковые
    # кнопки на одном экране выглядят как сбой, а не как настойчивость.
    del cta
    actions = f'<div class="actions actions--one">{route}</div>' if route else ""
    # Главная кнопка всегда под пальцем: страницу читают с телефона, листая до конца.
    sticky = f'<div class="dock"><a class="cta" href="{_esc(cta_url)}">Открыть в Telegram</a></div>' if cta_url else ""
    body = "".join(
        [
            hero,
            _focus_html(view, invite=invite),
            about,
            actions,
            _schedule_html(view, base_path=base_path, invite=invite),
            _services_html(card),
            _hours_html(card),
            _rental_catalog_html(card),
            _amenities_html(card),
            _trainers_html(card, cta_url=cta_url),
            _contacts_html(card),
            _share_html(share, venue_type=vt),
            sticky,
        ]
    )
    city = _city(card)
    city_link = f'<a href="{_esc(city_page_url)}">Весь лёд: {_esc(city)} сегодня</a>' if city_page_url and city else ""
    # Ссылка с ?s= / ?i= — та же страница; в индекс идёт только каноническая.
    robots = "noindex, follow" if (view.get("focus") is not None or invite) else "index, follow"

    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "__OG_TITLE__": _esc(title),
        "__OG_DESCRIPTION__": _esc(og_description(view)),
        "__CANONICAL__": _esc(canonical_url),
        "__OG_URL__": _esc(share["share_url"]),
        "__OG_IMAGE__": _esc(og_image_url),
        "__STORY_IMAGE__": _esc(story_image_url),
        "__ROBOTS__": robots,
        "__JSONLD__": _json_ld(view, canonical_url=canonical_url, image_url=og_image_url),
        "__CITY__": _esc(city or "Беларусь"),
        "__CITY_LINK__": city_link,
        "__TRUST__": _trust_html(view),
        "__BODY__": body,
    }
    return fill_placeholders(html, replacements)
