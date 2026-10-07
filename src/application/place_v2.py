"""Страница места v2 (TASK-211): статус, дни, цена с прокатом, ОХМ, режимы.

Подписи — только ``copy_ru``. Цвета в шаблоне — только ``var(--g-*)``.
Часы комплекса не считаются здесь: готовый HTML ``_hours_html`` встраивается
в блок «Что есть на месте» (его тело параллельно меняет TASK-208).
"""

from __future__ import annotations

import html as html_lib
from datetime import date, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any, Mapping
from urllib.parse import urlencode

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_city_day import city_slug, format_price_minor, plural_ru
from src.application.place_links import place_query
from src.shared.arena_schedule_mode import SCHEDULE_MODE_PHONE, SCHEDULE_MODE_SEASON_CLOSED, normalize_schedule_mode
from src.shared.copy_ru import t
from src.shared.html_template import safe_external_url
from src.shared.schedule_basis import SCHEDULE_BASIS_PROJECTED, normalize_schedule_basis

_WD = ("when.mon", "when.tue", "when.wed", "when.thu", "when.fri", "when.sat", "when.sun")
_DOSSIER = ("unknown", "conflicts", "склеивать")
_AMENITY_KEYS = (
    ("skate_sharpening", "amenity.sharpening"),
    ("parking", "amenity.parking"),
    ("locker_rooms", "amenity.lockers"),
    ("cafe", "amenity.cafe"),
    ("accessibility", "amenity.access"),
)

_ICON_BACK = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M15 6l-6 6 6 6"/></svg>'
)
_ICON_PHONE = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/></svg>'
)
_ICON_PIN = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 21s-7-6.5-7-12a7 7 0 0 1 14 0c0 5.5-7 12-7 12z"/><circle cx="12" cy="9" r="2.5"/></svg>'
)
_ICON_SHARE = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 15V3M7 8l5-5 5 5"/><path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/></svg>'
)
_ICON_BELL = (
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10 21a2 2 0 0 0 4 0"/></svg>'
)
_ICON_INVITE = (
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="9" cy="8" r="3.5"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M19 8v6M16 11h6"/></svg>'
)


def _esc(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def public_text(value: Any) -> str:
    """Публичная строка. Служебные пометки досье («unknown», «Conflicts») не показываем."""
    text = str(value or "").strip()
    if not text:
        return ""
    low = text.lower()
    if any(marker in low for marker in _DOSSIER):
        return ""
    return text


def scrub_card(card: Mapping[str, Any]) -> dict[str, Any]:
    clean = dict(card)
    for key in ("district", "address", "short_description", "schedule_mode_note", "phone"):
        if key in clean:
            clean[key] = public_text(clean.get(key)) or None
    hours = clean.get("opening_hours")
    if isinstance(hours, Mapping) and "note" in hours:
        hours = dict(hours)
        hours["note"] = public_text(hours.get("note")) or None
        clean["opening_hours"] = hours
    return clean


def _parse_iso_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _parse_iso_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else None
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _hhmm(slot: Mapping[str, Any], key: str) -> str:
    return str(slot.get(key) or "")[:5]


def _is_projected(slot: Mapping[str, Any]) -> bool:
    return normalize_schedule_basis(str(slot.get("schedule_basis") or "")) == SCHEDULE_BASIS_PROJECTED


def _major(minor: int) -> str:
    major = int(minor) / 100.0
    if major == int(major):
        return str(int(major))
    return f"{major:.2f}"


def session_price_view(slot: Mapping[str, Any]) -> tuple[str, str]:
    """``(основная цена, вторая строка)``. «С прокатом» = adult + rental, иначе второй части нет."""
    currency = str(slot.get("currency_code") or "BYN")
    adult = slot.get("price_adult_minor")
    if adult is None:
        adult = slot.get("price_minor")
    bits: list[str] = []
    if adult is not None:
        bits.append(format_price_minor(int(adult), currency))
    child = slot.get("price_child_minor")
    if child is not None:
        bits.append(t("session.child", price=_major(int(child))))
    primary = " · ".join(bits)
    secondary: list[str] = []
    label = public_text(slot.get("session_label"))
    if label:
        secondary.append(label)
    rental = slot.get("price_rental_minor")
    if adult is not None and rental is not None:
        secondary.append(
            t("price.with_rental", total=_major(int(adult) + int(rental)), currency=currency)
        )
    return primary, " · ".join(secondary)


def skate_status(slots: list[Mapping[str, Any]], *, now: datetime, today: date) -> tuple[str, str]:
    """Четыре ветки плашки. ``projected`` не даёт «Сейчас идёт»."""
    live: list[tuple[datetime, Mapping[str, Any]]] = []
    today_future: list[tuple[datetime, Mapping[str, Any]]] = []
    later: list[tuple[datetime, date, Mapping[str, Any]]] = []
    for slot in slots:
        start = _parse_iso_dt(slot.get("starts_at_utc"))
        end = _parse_iso_dt(slot.get("ends_at_utc"))
        if start is None or end is None:
            continue
        day = _parse_iso_date(slot.get("local_date"))
        if start <= now < end and not _is_projected(slot):
            live.append((end, slot))
        elif start > now and day == today:
            today_future.append((start, slot))
        elif start > now and day is not None and day > today:
            later.append((start, day, slot))
    if live:
        end, _slot = min(live, key=lambda item: item[0])
        minutes = max(1, int((end - now).total_seconds() // 60))
        return "now", t("status.now", n=minutes)
    if today_future:
        _start, slot = min(today_future, key=lambda item: item[0])
        return "today", t("status.today", time=_hhmm(slot, "starts_at_local"))
    if later:
        _start, day, slot = min(later, key=lambda item: item[0])
        when = t("when.tomorrow").lower() if day == today + timedelta(days=1) else t(_WD[day.weekday()]).lower()
        return "later", t("status.later", when=when, time=_hhmm(slot, "starts_at_local"))
    return "none", t("status.none")


def choose_schedule_day(
    slots_by_day: Mapping[str, list[Any]], *, today: date, requested: date | None
) -> date:
    """Первый день недели, где есть сеансы. ``?d=`` внутри этих семи дней побеждает."""
    week = [today + timedelta(days=i) for i in range(7)]
    if requested in week:
        return requested
    for day in week:
        if slots_by_day.get(day.isoformat()):
            return day
    return today


def day_tab_label(day: date, *, today: date, count: int) -> str:
    if day == today:
        name = t("when.today")
    elif day == today + timedelta(days=1):
        name = t("when.tomorrow")
    else:
        name = t(_WD[day.weekday()])
    return f"{name} · {count}"


def _ago_short(moment: datetime | None, *, now: datetime) -> str:
    if moment is None:
        return ""
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 60:
        return t("ago.just")
    minutes = seconds // 60
    if minutes < 60:
        return t("ago.minutes", n=minutes)
    hours = minutes // 60
    if hours < 48:
        return t("ago.hours", n=hours)
    return ""


def follow_start_url(arena_id: int) -> str | None:
    """Deep link бота ``t.me/<client>?start=follow_{id}``. Не ``startapp``."""
    from src.application.trainer_invite_links import normalize_client_bot_username
    from src.shared.config import Settings

    bot = normalize_client_bot_username(Settings().client_bot_username)
    if not bot or int(arena_id) <= 0:
        return None
    return f"https://t.me/{bot}?start=follow_{int(arena_id)}"


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlmb = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlmb / 2) ** 2
    return 2 * radius * asin(sqrt(a))


async def load_nearby_skating_city(
    session: AsyncSession,
    *,
    city_id: int,
    latitude: float,
    longitude: float,
    today: date,
    now: datetime,
) -> dict[str, Any] | None:
    """Ближайший другой город, где в ближайшие 7 дней есть массовое катание.

    Одна выборка: средние координаты катков города, число катков с сеансами,
    число сеансов сегодня. Расстояние — между точкой этого места и средней
    точкой города.
    """
    from src.application.ice_session_use_cases import STATUS_ACTIVE
    from src.shared.arena_schedule_mode import arena_schedule_mode_sql
    from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params

    horizon = today + timedelta(days=6)
    rows = (
        await session.execute(
            text(
                f"""
                SELECT c.id, c.name,
                       AVG(a.latitude) AS lat,
                       AVG(a.longitude) AS lon,
                       COUNT(DISTINCT a.id) FILTER (WHERE s.id IS NOT NULL)::int AS rinks,
                       COUNT(s.id) FILTER (WHERE s.local_date = :today)::int AS today_sessions
                FROM arenas a
                JOIN cities c ON c.id = a.city_id
                JOIN arena_profiles p ON p.arena_id = a.id
                LEFT JOIN ice_sessions s
                  ON s.arena_id = a.id
                 AND s.status = :st
                 AND s.kind IN ('public_skate', 'open_ice')
                 AND s.starts_at_utc > :now
                 AND (s.valid_until IS NULL OR s.valid_until >= :now)
                 AND s.local_date >= :today
                 AND s.local_date <= :horizon
                WHERE {PUBLIC_ARENA_VISIBLE_SQL}
                  AND {arena_schedule_mode_sql()} <> 'season_closed'
                  AND a.latitude IS NOT NULL
                  AND a.longitude IS NOT NULL
                  AND c.id <> :city_id
                GROUP BY c.id, c.name
                HAVING COUNT(s.id) > 0
                """
            ),
            {
                "st": STATUS_ACTIVE,
                "now": now,
                "today": today,
                "horizon": horizon,
                "city_id": int(city_id),
                **public_scope_params(),
            },
        )
    ).mappings().all()
    best: dict[str, Any] | None = None
    best_km = 10**9
    for row in rows:
        if row["lat"] is None or row["lon"] is None:
            continue
        dist = _km(float(latitude), float(longitude), float(row["lat"]), float(row["lon"]))
        if dist < best_km:
            best_km = dist
            best = {
                "city_id": int(row["id"]),
                "name": str(row["name"]),
                "rinks": int(row["rinks"] or 0),
                "today_sessions": int(row["today_sessions"] or 0),
                "km": max(1, int(round(dist))),
            }
    return best


def _tel(phone: str) -> str | None:
    raw = str(phone or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    return f"tel:{digits}" if raw and digits else None


def _report_href() -> str | None:
    from src.shared.config import Settings

    return safe_external_url(Settings().subscription_support_url)


def _direction_href(card: Mapping[str, Any], base_url: str) -> str | None:
    if card.get("latitude") is None or card.get("longitude") is None or card.get("id") is None:
        return None
    from src.application.public_web_cta import CONTACT_ACTION_DIRECTION, public_outbound_url

    city_id = int(card["city_id"]) if card.get("city_id") else None
    arena_id = int(card["id"])
    url = public_outbound_url(
        base_url,
        action=CONTACT_ACTION_DIRECTION,
        surface="place_page",
        city_id=city_id,
        arena_id=arena_id,
    )
    if url:
        return url
    params: dict[str, str] = {"action": "direction", "surface": "place_page", "arena_id": str(arena_id)}
    if city_id:
        params["city_id"] = str(city_id)
    return "/api/public/catalog/outbound?" + urlencode(params)


def _phone_beacon(card: Mapping[str, Any]) -> str:
    from src.application.public_web_cta import CONTACT_ACTION_PHONE, contact_click_beacon_url

    return contact_click_beacon_url(
        action=CONTACT_ACTION_PHONE,
        surface="place_page",
        city_id=int(card["city_id"]) if card.get("city_id") else None,
        arena_id=int(card["id"]) if card.get("id") else None,
    )


def _slots_by_day(days: list[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for day in days:
        key = str(day.get("local_date") or "")[:10]
        if key:
            out[key] = list(day.get("sessions") or [])
    return out


def _flat(days: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [slot for day in days for slot in (day.get("sessions") or [])]


def _chrome(card: Mapping[str, Any], *, closed: bool) -> str:
    from src.shared.venue_types import has_public_skating

    city = str(card.get("city_name") or "").strip()
    skating = bool(card["has_skating"]) if "has_skating" in card else has_public_skating(card.get("venue_type"))
    if city and not closed and skating:
        title = t("place.city_rinks", city=city)
    else:
        title = city
    back = f"/c/{city_slug(city)}" if city else "/"
    aria = t("place.back", city=city) if city else t("place.back", city="")
    return (
        '<header class="chrome" data-glide-chrome="place">'
        f'<a class="chrome__back" href="{_esc(back)}" aria-label="{_esc(aria)}">{_ICON_BACK}</a>'
        f'<span class="chrome__city">{_esc(title)}</span>'
        '<a class="chrome__brand" href="/">Glide</a>'
        "</header>"
    )


def _photo(card: Mapping[str, Any], *, show_empty: bool) -> str:
    from src.application.place_page import _hero_photo_url

    url = _hero_photo_url(card)
    if url:
        return (
            f'<div class="photo" data-empty="{_esc(t("place.no_photo"))}">'
            f'<img src="{_esc(url)}" alt="{_esc(card.get("name"))}" width="780" height="190" /></div>'
        )
    if not show_empty:
        return ""
    return f'<div class="photo photo--empty">{_esc(t("place.no_photo"))}</div>'


def _address_line(card: Mapping[str, Any]) -> str:
    parts = [public_text(card.get("address")), public_text(card.get("district"))]
    return " · ".join(part for part in parts if part)


def _status_html(kind: str, text: str, *, phone: bool) -> str:
    hint = ""
    if kind == "none" and phone:
        hint = f'<span class="status__hint">{_esc(t("status.call"))}</span>'
    css = "status status--warn" if kind == "closed" else "status"
    return (
        f'<div class="{css}">'
        + ("" if kind == "closed" else '<span class="status__dot"></span>')
        + f"<span><b>{_esc(text)}</b>{hint}</span></div>"
    )


def _action_button(href: str, icon: str, label: str, *, extra: str = "") -> str:
    return (
        f'<a class="act" href="{_esc(href)}"{extra}>'
        f'<span class="act__icon">{icon}</span>{_esc(label)}</a>'
    )


def _actions(card: Mapping[str, Any], *, base_url: str, share_url: str, share_text: str) -> tuple[str, bool]:
    buttons: list[str] = []
    phone = _tel(str(card.get("phone") or ""))
    beacon = False
    if phone:
        buttons.append(
            _action_button(
                phone,
                _ICON_PHONE,
                t("cta.call"),
                extra=f' data-catalog-phone-beacon="{_esc(_phone_beacon(card))}"',
            )
        )
        beacon = True
    direction = _direction_href(card, base_url)
    if direction:
        buttons.append(_action_button(direction, _ICON_PIN, t("cta.route")))
    buttons.append(
        f'<a class="act" href="{_esc(share_url)}" data-glide-share="{_esc(share_url)}" '
        f'data-glide-share-text="{_esc(share_text)}">'
        f'<span class="act__icon">{_ICON_SHARE}</span>{_esc(t("cta.share"))}</a>'
    )
    style = f' style="grid-template-columns: repeat({len(buttons)}, minmax(0, 1fr))"'
    return f'<div class="acts"{style}>{"".join(buttons)}</div>', beacon


def _follow_button(arena_id: int, *, closed: bool) -> str:
    """Кнопка подписки. Состояние «уже следите» — только после GET, его здесь нет."""
    url = follow_start_url(arena_id)
    if not url:
        return ""
    if closed:
        label = t("cta.follow_closed")
        css = "follow follow--open"
    else:
        label = t("cta.follow")
        css = "follow"
    return (
        f'<a class="{css}" href="{_esc(url)}" data-arena-follow="{int(arena_id)}">'
        f"{_ICON_BELL}{_esc(label)}</a>"
    )


def _schedule_caption(slots: list[Mapping[str, Any]], card: Mapping[str, Any], *, now: datetime) -> str:
    if slots and all(_is_projected(slot) for slot in slots):
        return t("basis.projected_grid")
    observed = None
    for slot in slots:
        if _is_projected(slot):
            continue
        moment = _parse_iso_dt(slot.get("observed_at"))
        if moment is not None and (observed is None or moment > observed):
            observed = moment
    if observed is None:
        fresh = card.get("freshness") or {}
        observed = _parse_iso_dt(fresh.get("schedule_observed_at"))
    ago = _ago_short(observed, now=now)
    if not ago:
        return t("basis.live")
    return t("basis.live_ago", ago=ago)


def _session_row(slot: Mapping[str, Any], *, base_path: str) -> str:
    start = _hhmm(slot, "starts_at_local")
    end = _hhmm(slot, "ends_at_local")
    primary, secondary = session_price_view(slot)
    projected = _is_projected(slot)
    css = "sess sess--projected" if projected else "sess"
    until = f'<span class="sess__until">{_esc(t("session.until", time=end))}</span>' if end else ""
    basis = f'<span class="sess__basis">{_esc(t("basis.projected"))}</span>' if projected else ""
    price = f'<span class="sess__price">{_esc(primary)}</span>' if primary else ""
    sub = f'<span class="sess__sub">{_esc(secondary)}</span>' if secondary else ""
    href = base_path + place_query(session_id=int(slot["id"]), invite=True)
    aria = t("session.invite_aria", time=start)
    return (
        f'<div class="{css}">'
        f'<span class="sess__when"><span class="sess__time">{_esc(start)}</span>{until}</span>'
        f'<span class="sess__meta">{price}{basis}{sub}</span>'
        f'<a class="sess__invite" href="{_esc(href)}" aria-label="{_esc(aria)}" rel="nofollow">'
        f"{_ICON_INVITE}</a></div>"
    )


def _schedule_html(
    view: Mapping[str, Any],
    *,
    base_path: str,
    requested: date | None,
) -> str:
    card = view["card"]
    days = list(view.get("days") or [])
    by_day = _slots_by_day(days)
    today: date = view["today"]
    now: datetime = view["now"]
    selected = choose_schedule_day(by_day, today=today, requested=requested)
    week_slots = _flat(days)
    caption = _schedule_caption(by_day.get(selected.isoformat()) or week_slots, card, now=now)
    tabs: list[str] = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        slots = by_day.get(day.isoformat()) or []
        label = day_tab_label(day, today=today, count=len(slots))
        href = f"{base_path}?d={day.isoformat()}"
        current = ' aria-current="page"' if day == selected else ""
        css = "daytab daytab--on" if day == selected else "daytab"
        tabs.append(f'<a class="{css}" href="{_esc(href)}"{current}>{_esc(label)}</a>')
    rows = "".join(_session_row(slot, base_path=base_path) for slot in (by_day.get(selected.isoformat()) or []))
    note = public_text(view.get("schedule_note"))
    stale = f'<p class="sched__stale">{_esc(note)}</p>' if note else ""
    hint = f'<p class="hint">{_esc(t("session.invite_hint"))}</p>' if rows else ""
    return (
        '<section class="block" id="schedule">'
        '<div class="block__head">'
        f'<h2>{_esc(t("kind.public_skate"))}</h2>'
        f'<span class="block__aside">{_esc(caption)}</span></div>'
        f'{stale}<div class="daytabs" role="tablist">{"".join(tabs)}</div>'
        f'<div class="sess-list">{rows}</div>{hint}</section>'
    )


def _ohm_html(sessions: list[Mapping[str, Any]], *, now: datetime) -> str:
    upcoming = []
    for slot in sessions:
        end = _parse_iso_dt(slot.get("ends_at_utc"))
        if end is not None and end > now:
            upcoming.append(slot)
    if not upcoming:
        return ""
    first = upcoming[0]
    currency = str(first.get("currency_code") or "BYN")
    adult = first.get("price_adult_minor")
    price = format_price_minor(int(adult), currency) if adult is not None else ""
    start = _parse_iso_dt(first.get("starts_at_utc"))
    end = _parse_iso_dt(first.get("ends_at_utc"))
    minutes = int((end - start).total_seconds() // 60) if start and end else None
    right = ""
    if price and minutes:
        right = f"{price} / {minutes} мин"
    elif price:
        right = price
    elif minutes:
        right = f"{minutes} мин"
    grouped: dict[int, list[str]] = {}
    labels: list[str] = []
    for slot in upcoming:
        day = _parse_iso_date(slot.get("local_date"))
        if day is None:
            continue
        grouped.setdefault(day.weekday(), []).append(_hhmm(slot, "starts_at_local"))
        label = public_text(slot.get("session_label"))
        if label and label not in labels:
            labels.append(label)
    parts = []
    for weekday in sorted(grouped):
        times = ", ".join(grouped[weekday])
        parts.append(f"{t(_WD[weekday])} {times}")
    line = " · ".join(parts)
    if len(labels) == 1:
        line = f"{line} — {labels[0]}" if line else labels[0]
    conditions = []
    for key in ("age_note", "capacity_note"):
        note = public_text(first.get(key))
        if note and note not in conditions:
            conditions.append(note)
    cond = f'<p class="ohm__note">{_esc(" ".join(conditions))}</p>' if conditions else ""
    aside = f'<span class="block__aside">{_esc(right)}</span>' if right else ""
    return (
        '<section class="ohm">'
        '<div class="block__head">'
        f'<h2>{_esc(t("kind.hockey_practice"))}</h2>{aside}</div>'
        + (f'<p class="ohm__when">{_esc(line)}</p>' if line else "")
        + cond
        + "</section>"
    )


def _rental_cells(card: Mapping[str, Any]) -> list[str]:
    hours = card.get("opening_hours") if isinstance(card.get("opening_hours"), Mapping) else {}
    catalog = hours.get("rental_catalog") if isinstance(hours, Mapping) else None
    cells: list[str] = []
    if isinstance(catalog, list):
        for row in catalog:
            if not isinstance(row, Mapping):
                continue
            label = public_text(row.get("label"))
            price = public_text(row.get("price"))
            if not label or not price:
                continue
            per = public_text(row.get("per"))
            text = f"{label} · {price}/{per}" if per else f"{label} · {price}"
            cells.append(f"<li>{_esc(text)}</li>")
    amenities = card.get("amenities") or {}
    if not cells and isinstance(amenities, Mapping) and amenities.get("skate_rental") is True:
        cells.append(f"<li>{_esc(t('amenity.rental'))}</li>")
    return cells


def _on_site_html(card: Mapping[str, Any], *, hours_html: str) -> str:
    amenities = card.get("amenities") if isinstance(card.get("amenities"), Mapping) else {}
    cells = _rental_cells(card)
    for key, copy_key in _AMENITY_KEYS:
        if amenities.get(key) is True:
            cells.append(f"<li>{_esc(t(copy_key))}</li>")
    hours = hours_html if hours_html and not any(marker in hours_html.lower() for marker in _DOSSIER) else ""
    if not cells and not hours:
        return ""
    grid = f'<ul class="amenity">{"".join(cells)}</ul>' if cells else ""
    return (
        '<section class="block">'
        f'<h2>{_esc(t("section.on_site"))}</h2>{grid}'
        f'<div class="amenity-hours">{hours}</div></section>'
    )


def _phone_card(card: Mapping[str, Any]) -> str:
    phone = _tel(str(card.get("phone") or ""))
    title = f'<h2>{_esc(t("mode.phone"))}</h2>'
    if phone:
        beacon = _phone_beacon(card)
        call = (
            f'<a class="call" href="{_esc(phone)}" data-catalog-phone-beacon="{_esc(beacon)}">'
            f'{_esc(t("cta.call"))}</a>'
            f'<p class="hint">{_esc(t("phone.ask"))}</p>'
        )
        return f'<section class="mode-card">{title}{call}</section>'
    report = _report_href() or "#report"
    return (
        '<section class="mode-card">'
        f"{title}<p>{_esc(t('phone.missing'))}</p>"
        f'<a href="{_esc(report)}">{_esc(t("cta.report_short"))}</a></section>'
    )


def _closed_blocks(view: Mapping[str, Any]) -> str:
    card = view["card"]
    reopen = _parse_iso_date(card.get("schedule_reopen_date"))
    lines = [f'<b>{_esc(t("mode.closed_title"))}</b>']
    if reopen is not None:
        lines.append(_esc(t("mode.reopen", date=reopen.strftime("%d.%m.%Y"))))
    note = public_text(card.get("schedule_mode_note"))
    if note:
        lines.append(_esc(note))
    banner = f'<div class="status status--warn status--stack">{"".join(f"<span>{line}</span>" for line in lines)}</div>'
    follow = _follow_button(int(card["id"]), closed=True) if card.get("id") is not None else ""
    follow_card = (
        '<section class="open-card">'
        f'<h2>{_esc(t("closed.follow_title"))}</h2>'
        f'<p>{_esc(t("closed.follow_text"))}</p>{follow}</section>'
    )
    nearby = view.get("nearby")
    nearby_html = ""
    if isinstance(nearby, Mapping) and nearby.get("name"):
        n = int(nearby.get("rinks") or 0)
        m = int(nearby.get("today_sessions") or 0)
        rinks = f"{n} {plural_ru(n, 'каток', 'катка', 'катков')}"
        sessions = f"{m} {plural_ru(m, 'сеанс', 'сеанса', 'сеансов')} сегодня"
        meta = t("nearby.line", sessions=sessions, km=int(nearby.get("km") or 0))
        href = f"/c/{city_slug(str(nearby['name']))}"
        nearby_html = (
            '<section class="block">'
            f'<h2>{_esc(t("nearby.title"))}</h2>'
            f'<a class="nearby" href="{_esc(href)}">'
            f'<span><b>{_esc(str(nearby["name"]))} · {_esc(rinks)}</b>'
            f'<span class="nearby__meta">{_esc(meta)}</span></span>'
            '<span class="nearby__go" aria-hidden="true">→</span></a></section>'
        )
    phone = _tel(str(card.get("phone") or ""))
    call = ""
    if phone:
        beacon = _phone_beacon(card)
        call = (
            f'<a class="call call--block" href="{_esc(phone)}" data-catalog-phone-beacon="{_esc(beacon)}">'
            f'<b>{_esc(t("closed.call"))}</b>'
            f'<span>{_esc(t("phone.ask_open"))}</span></a>'
        )
    return banner + follow_card + nearby_html + call


def _footer(view: Mapping[str, Any], *, canonical_url: str, closed: bool) -> str:
    slots = _flat(list(view.get("days") or []))
    report_key = "cta.report_open" if closed else "cta.report"
    href = _report_href() or "#report"
    bits = [f'<a id="report" href="{_esc(href)}">{_esc(t(report_key))}</a>']
    if canonical_url:
        bits.append(f"<span>{_esc(canonical_url)}</span>")
    if not closed and slots:
        if all(_is_projected(slot) for slot in slots):
            bits.insert(0, f"<span>{_esc(t('footer.projected'))}</span>")
        else:
            bits.insert(0, f"<span>{_esc(t('footer.schedule'))}</span>")
    return f'<footer class="foot">{"".join(bits)}</footer>'


def _trainers_block(trainers_html: str) -> str:
    if not trainers_html:
        return ""
    return trainers_html.replace(
        '<h2 class="sec__title">Тренеры</h2>',
        f'<h2>{_esc(t("section.trainers"))}</h2>',
        1,
    )


def build_place_body(
    view: Mapping[str, Any],
    *,
    base_path: str,
    canonical_url: str,
    base_url: str,
    share_url: str,
    share_text: str,
    day: str | None,
    hours_html: str,
    services_html: str,
    trainers_html: str,
    contacts_html: str,
    focus_html: str,
    trust_html: str,
) -> tuple[str, bool]:
    """HTML страницы и нужен ли скрипт учёта звонка."""
    from src.shared.venue_types import has_public_skating

    card = view["card"]
    skating = bool(card["has_skating"]) if "has_skating" in card else has_public_skating(card.get("venue_type"))
    mode = normalize_schedule_mode(card.get("schedule_mode")) if skating else "auto"
    closed = skating and mode == SCHEDULE_MODE_SEASON_CLOSED
    phone_mode = skating and mode == SCHEDULE_MODE_PHONE
    out_of_season = skating and card.get("in_season") is False and not closed and not phone_mode
    requested = _parse_iso_date(day)
    today: date = view["today"]
    now: datetime = view["now"]
    slots = _flat(list(view.get("days") or []))
    kind, text = ("closed", t("mode.closed_title")) if closed else ("", "")
    if skating and not closed and not phone_mode and not out_of_season:
        kind, text = skate_status(slots, now=now, today=today)
    elif out_of_season:
        from src.application.place_page import status_badge

        badge = status_badge(view)
        kind, text = (badge[0], badge[1]) if badge else ("", "")
    elif phone_mode:
        kind, text = "phone", t("mode.phone")

    phone = bool(_tel(str(card.get("phone") or "")))
    status = _status_html(kind, text, phone=phone) if text and not closed else ""
    actions, beacon = ("", False)
    if not closed:
        actions, beacon = _actions(card, base_url=base_url, share_url=share_url, share_text=share_text)
    follow = ""
    if not closed and not phone_mode and card.get("id") is not None and skating:
        follow = _follow_button(int(card["id"]), closed=False)
        if follow:
            follow += f'<p class="follow-hint">{_esc(t("follow.hint"))}</p>'
    about = public_text(card.get("short_description"))
    about_html = f'<p class="about">{_esc(about)}</p>' if about else ""
    where = _address_line(card)

    if closed:
        main = _closed_blocks(view)
    elif phone_mode:
        main = _phone_card(card)
    elif out_of_season or view.get("schedule_level") == "very_stale":
        main = _very_stale_or_empty(view)
    elif skating:
        main = _schedule_html(view, base_path=base_path, requested=requested)
        main += _ohm_html(list(view.get("ohm_sessions") or []), now=now)
    else:
        main = ""

    side = "".join(
        [
            services_html,
            _on_site_html(card, hours_html=hours_html),
            _trainers_block(trainers_html),
            contacts_html,
        ]
    )
    intro_status = "" if closed else status
    body = "".join(
        [
            _chrome(card, closed=closed),
            _photo(card, show_empty=not closed),
            '<section class="intro">',
            f'<h1>{_esc(card.get("name"))}</h1>',
            (f'<p class="where">{_esc(where)}</p>' if where else ""),
            intro_status,
            actions,
            follow,
            "</section>",
            focus_html,
            about_html,
            '<div class="place-grid"><div class="place-main">',
            main,
            '</div><aside class="place-side">',
            side,
            "</aside></div>",
            trust_html,
            _footer(view, canonical_url=canonical_url, closed=closed),
        ]
    )
    if "data-catalog-phone-beacon" in body:
        beacon = True
    return body, beacon


def _very_stale_or_empty(view: Mapping[str, Any]) -> str:
    from src.application.schedule_staleness import LEVEL_VERY_STALE

    card = view["card"]
    note = public_text(view.get("schedule_note"))
    if view.get("schedule_level") != LEVEL_VERY_STALE:
        if note:
            return f'<p class="sched__stale">{_esc(note)}</p>'
        return ""
    phone = _tel(str(card.get("phone") or ""))
    link = ""
    if phone:
        shown = public_text(card.get("phone"))
        link = f'<p class="sched__stale"><a href="{_esc(phone)}">{_esc(shown or t("cta.call"))}</a></p>'
    return (
        '<section class="block" id="schedule">'
        f'<h2>{_esc(t("kind.public_skate"))}</h2>'
        f'<p class="sched__stale">{_esc(note)}</p>{link}</section>'
    )
