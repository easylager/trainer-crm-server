"""Три страницы города стиля B. Вариант — по числу катков и schedule_mode, не по имени.

«Неделя» и «Лёд рядом» — по одному запросу. Нет строки — нет блока.
"""

from __future__ import annotations

import html as html_lib
from datetime import date, datetime, timedelta
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_icons import icon_svg, rink_motif_svg
from src.application.ice_city_day import DEFAULT_TIMEZONE, plural_ru
from src.application.photo_cdn import public_photo_url
from src.application.place_links import place_path, place_start_param, public_telegram_cta_url
from src.application.week_grid import collapse_even_grid
from src.shared.copy_ru import t
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params
from src.shared.phone_guard import is_valid_public_phone, tel_href
from src.shared.public_display import format_clock, format_phone_display, format_public_name

VARIANT_MANY = "many"
VARIANT_ONE = "one"
VARIANT_PHONE = "phone"

_WEEK_SQL = text(
    f"""
    /* task246-week */
    SELECT s.local_date, s.starts_at_local, s.ends_at_local,
           s.price_adult_minor, s.price_child_minor, s.price_rental_minor, s.currency_code
    FROM ice_sessions s
    JOIN arenas a ON a.id = s.arena_id
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    WHERE s.arena_id = :arena_id
      AND {PUBLIC_ARENA_VISIBLE_SQL}
      AND s.status = 'active'
      AND s.kind IN ('public_skate', 'open_ice')
      AND s.local_date >= :dfrom AND s.local_date < :dto
      AND (s.valid_until IS NULL OR s.valid_until >= :now)
    ORDER BY s.local_date, s.starts_at_local, s.id
    """
)

_NEARBY_SQL = text(
    f"""
    /* task246-nearby */
    WITH points AS (
        SELECT c.id AS city_id, c.name,
               AVG(a.latitude) AS lat,
               AVG(a.longitude) AS lon,
               COUNT(DISTINCT a.id)::int AS rink_count
        FROM cities c
        JOIN arenas a ON a.city_id = c.id
        LEFT JOIN arena_profiles p ON p.arena_id = a.id
        WHERE c.id <> :city_id
          AND a.latitude IS NOT NULL AND a.longitude IS NOT NULL
          AND COALESCE(a.venue_type, 'ice') IN ('ice', 'outdoor')
          AND {PUBLIC_ARENA_VISIBLE_SQL}
        GROUP BY c.id, c.name
    ),
    nxt AS (
        SELECT DISTINCT ON (a.city_id)
               a.city_id, s.local_date, s.starts_at_local
        FROM ice_sessions s
        JOIN arenas a ON a.id = s.arena_id
        LEFT JOIN arena_profiles p ON p.arena_id = a.id
        JOIN cities c ON c.id = a.city_id
        WHERE {PUBLIC_ARENA_VISIBLE_SQL}
          AND s.status = 'active'
          AND s.kind IN ('public_skate', 'open_ice')
          AND s.starts_at_utc >= :now AND s.starts_at_utc < :win_to
          AND (s.valid_until IS NULL OR s.valid_until >= :now)
        ORDER BY a.city_id, s.starts_at_utc, s.id
    )
    SELECT points.city_id, points.name, points.rink_count,
           nxt.local_date, nxt.starts_at_local,
           (6371 * acos(LEAST(1.0, GREATEST(-1.0,
              cos(radians(:olat)) * cos(radians(points.lat))
              * cos(radians(points.lon) - radians(:olon))
              + sin(radians(:olat)) * sin(radians(points.lat))
           )))) AS distance_km
    FROM points
    JOIN nxt ON nxt.city_id = points.city_id
    ORDER BY distance_km, points.city_id
    LIMIT 3
    """
)


def choose_city_variant(places: list[Mapping[str, Any]]) -> str:
    """Много катков, один каток с расписанием или город, где катание только по телефону."""
    rinks = [p for p in places if str(p.get("venue_type") or "ice") in ("ice", "outdoor")]
    if not rinks:
        return VARIANT_MANY
    modes = {str(p.get("schedule_mode") or "auto") for p in rinks}
    if modes == {"phone"}:
        return VARIANT_PHONE
    if len(rinks) == 1:
        return VARIANT_ONE
    return VARIANT_MANY


def _esc(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _clock(value: Any) -> str:
    return format_clock(str(value or ""))


def _money(minor: Any, currency: str) -> str:
    if minor is None:
        return ""
    major = int(minor) / 100
    if major == int(major):
        body = str(int(major))
    else:
        body = f"{major:.2f}".replace(".", ",")
    return f"{body} {currency or 'BYN'}"


def _origin(places: list[Mapping[str, Any]]) -> tuple[float, float] | None:
    lats = [float(p["latitude"]) for p in places if p.get("latitude") is not None and p.get("longitude") is not None]
    lons = [float(p["longitude"]) for p in places if p.get("latitude") is not None and p.get("longitude") is not None]
    if not lats:
        return None
    return sum(lats) / len(lats), sum(lons) / len(lons)


def _photo(place: Mapping[str, Any]) -> tuple[str | None, bool]:
    key = str(place.get("photo_key") or "").strip()
    url = public_photo_url(key) if key else None
    return url, bool(place.get("display_tone"))


def _hero(title: str, sub: str, *, photo: str | None, toned: bool, back: str = "") -> str:
    if photo:
        klass = "g-photo g-photo--toned" if toned else "g-photo"
        media = (
            f'<img class="{klass}" src="{_esc(photo)}" alt="" width="1600" height="900" '
            'fetchpriority="high" decoding="async" />'
        )
    else:
        media = f'<div class="g-motif-wrap">{rink_motif_svg()}</div>'
    sub_html = f'<p class="g-hero__sub">{sub}</p>' if sub else ""
    return (
        f'<header class="g-hero{" g-hero--photo" if photo else " g-hero--motif"}">'
        f"{media}{back}"
        f'<div class="g-hero__copy"><h1 class="g-hero__title">{_esc(title)}</h1>{sub_html}</div>'
        "</header>"
    )


def price_sentence(rows: list[Mapping[str, Any]], *, has_rental: bool, has_sharpening: bool) -> str:
    """Одна фраза из цен, которые есть. Нет взрослого билета — пусто."""
    adult = next((r.get("price_adult_minor") for r in rows if r.get("price_adult_minor") is not None), None)
    if adult is None:
        return ""
    currency = str(next((r.get("currency_code") for r in rows if r.get("currency_code")), "BYN"))
    child = next((r.get("price_child_minor") for r in rows if r.get("price_child_minor") is not None), None)
    text = f"Взрослый билет — {_money(adult, currency)}"
    if child is not None:
        text += f", детский — {_money(child, currency)}"
    extras: list[str] = []
    rental_price = any(r.get("price_rental_minor") is not None for r in rows)
    if has_rental or rental_price:
        extras.append("прокат")
    if has_sharpening:
        extras.append("заточка")
    if extras:
        text += ". Есть " + " и ".join(extras)
    return text


def _week_rows(rows: list[Mapping[str, Any]], *, today: date) -> list[dict[str, Any]]:
    by_day: dict[date, list[str]] = {}
    for row in rows:
        day = _as_date(row.get("local_date"))
        clock = _clock(row.get("starts_at_local"))
        if day is None or not clock:
            continue
        by_day.setdefault(day, []).append(clock)
    out: list[dict[str, Any]] = []
    for day in sorted(by_day):
        times = by_day[day]
        out.append(
            {
                "date": day,
                "weekend": day.weekday() >= 5,
                "label": "сегодня" if day == today else "завтра" if day == today + timedelta(days=1) else _weekday(day),
                "times": times,
                "collapsed": collapse_even_grid(times),
            }
        )
    return out


def _weekday(day: date) -> str:
    return ("пн", "вт", "ср", "чт", "пт", "сб", "вс")[day.weekday()]


def _km(distance: float) -> str:
    if distance < 1:
        return "меньше километра"
    return f"{round(distance)} км"


async def load_week(
    session: AsyncSession,
    *,
    arena_id: int,
    today: date,
    now: datetime,
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                _WEEK_SQL,
                {
                    "arena_id": arena_id,
                    "dfrom": today,
                    "dto": today + timedelta(days=7),
                    "now": now,
                    **public_scope_params(),
                },
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def load_nearby(
    session: AsyncSession,
    *,
    city_id: int,
    origin: tuple[float, float],
    today: date,
    now: datetime,
) -> list[dict[str, Any]]:
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    start = datetime(today.year, today.month, today.day, tzinfo=tz)
    rows = (
        (
            await session.execute(
                _NEARBY_SQL,
                {
                    "city_id": city_id,
                    "olat": origin[0],
                    "olon": origin[1],
                    "win_to": start + timedelta(days=2),
                    "now": now,
                    **public_scope_params(),
                },
            )
        )
        .mappings()
        .all()
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        day = _as_date(row.get("local_date"))
        if day == today:
            when = "сегодня"
        elif day == today + timedelta(days=1):
            when = "завтра"
        else:
            continue
        out.append(
            {
                "name": str(row["name"]),
                "rink_count": int(row["rink_count"] or 0),
                "when": when,
                "time": _clock(row.get("starts_at_local")),
                "distance": _km(float(row["distance_km"] or 0)),
            }
        )
    return out


def _nearby_html(items: list[Mapping[str, Any]], *, title: str) -> str:
    if not items:
        return ""
    cards = []
    for item in items:
        n = int(item.get("rink_count") or 0)
        word = plural_ru(n, "каток", "катка", "катков")
        line = f"{format_public_name(str(item.get('name') or ''))} — {n} {word} · {item.get('when')} в {item.get('time')}"
        cards.append(
            '<article class="g-near">'
            f'<b>{_esc(line)}</b>'
            f'<span>{_esc(item.get("distance") or "")}</span>'
            "</article>"
        )
    return f'<section class="g-sec"><h2>{_esc(title)}</h2>{"".join(cards)}</section>'


def _today_html(rows: list[Mapping[str, Any]], *, today: date, now: datetime) -> str:
    today_rows = [r for r in rows if _as_date(r.get("local_date")) == today]
    if not today_rows:
        return ""
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    local_now = now.astimezone(tz)
    cards = []
    marked = False
    for row in today_rows:
        clock = _clock(row.get("starts_at_local"))
        soon = ""
        klass = "g-ticket"
        minutes = _minutes_of(row.get("starts_at_local"))
        if minutes is not None and not marked:
            now_m = local_now.hour * 60 + local_now.minute
            if minutes >= now_m:
                marked = True
                klass += " g-ticket--next"
                delta = minutes - now_m
                if delta < 60:
                    soon = f"через {delta} мин"
                elif delta:
                    soon = f"через {delta // 60} ч"
        end = _clock(row.get("ends_at_local"))
        end_html = f'<span>до { _esc(end) }</span>' if end else ""
        soon_html = f'<span class="g-ticket__soon">{_esc(soon)}</span>' if soon else ""
        cards.append(f'<article class="{klass}"><b>{_esc(clock)}</b>{end_html}{soon_html}</article>')
    return f'<section class="g-sec"><h2>{_esc(t("hub.today"))}</h2><div class="g-tickets">{"".join(cards)}</div></section>'


def _minutes_of(value: Any) -> int | None:
    clock = _clock(value)
    if ":" not in clock:
        return None
    hour, minute = clock.split(":", 1)
    if not hour.isdigit() or not minute.isdigit():
        return None
    return int(hour) * 60 + int(minute)


def _week_html(rows: list[Mapping[str, Any]], *, today: date) -> str:
    days = _week_rows(rows, today=today)
    if not days:
        return ""
    lines = []
    for day in days:
        klass = "g-week__day g-week__day--end" if day["weekend"] else "g-week__day"
        body = day["collapsed"] or " · ".join(day["times"])
        lines.append(f'<p class="{klass}"><b>{_esc(day["label"])}</b><span>{_esc(body)}</span></p>')
    return f'<section class="g-sec"><h2>{_esc(t("hub.week"))}</h2>{"".join(lines)}</section>'


def _directions(place: Mapping[str, Any]) -> str:
    lat, lon = place.get("latitude"), place.get("longitude")
    if lat is None or lon is None:
        return ""
    href = f"https://yandex.ru/maps/?pt={float(lon)},{float(lat)}&z=16&l=map"
    return (
        f'<section class="g-sec"><h2>{_esc(t("hub.directions"))}</h2>'
        f'<a class="g-btn" href="{_esc(href)}">{icon_svg("route")}{_esc(t("cta.route"))}</a>'
        "</section>"
    )


def render_one_city(view: Mapping[str, Any]) -> str:
    places = list(view.get("places") or [])
    rink = next(p for p in places if str(p.get("venue_type") or "ice") in ("ice", "outdoor"))
    city = format_public_name(str(view["city"]["name"]))
    name = format_public_name(str(rink.get("name") or ""))
    rows = list(view.get("week_rows") or [])
    n = len(rows)
    word = plural_ru(n, "сеанс", "сеанса", "сеансов")
    href = place_path(city_name=str(view["city"]["name"]), slug=str(rink.get("slug") or "")) if rink.get("slug") else ""
    linked = f'<a href="{_esc(href)}">{_esc(name)}</a>' if href else _esc(name)
    sub = f"{linked} · {n} {word} на этой неделе" if n else linked
    photo, toned = _photo(rink)
    amenities = rink.get("amenities") if isinstance(rink.get("amenities"), Mapping) else {}
    sentence = price_sentence(
        rows,
        has_rental=bool(amenities.get("skate_rental")),
        has_sharpening=bool(amenities.get("skate_sharpening")),
    )
    price_html = f'<p class="g-price">{_esc(sentence)}</p>' if sentence else ""
    return "".join(
        [
            _hero(t("hub.on_ice", city=city), sub, photo=photo, toned=toned),
            _today_html(rows, today=view["today"], now=view["now"]),
            price_html,
            _week_html(rows, today=view["today"]),
            _directions(rink),
            _nearby_html(list(view.get("nearby") or []), title=t("hub.nearby")),
        ]
    )


def render_phone_city(view: Mapping[str, Any], *, base_url: str) -> str:
    city = view["city"]
    city_name = format_public_name(str(city["name"]))
    rinks = [p for p in list(view.get("places") or []) if str(p.get("venue_type") or "ice") in ("ice", "outdoor")]
    blocks: list[str] = [_hero(t("hub.on_ice", city=city_name), "", photo=None, toned=False)]
    for rink in rinks:
        name = format_public_name(str(rink.get("name") or ""))
        phone = str(rink.get("phone") or "").strip()
        if phone and is_valid_public_phone(phone):
            buttons = (
                f'<a class="g-btn g-btn--phone" href="tel:{_esc(tel_href(phone))}">'
                f'{icon_svg("phone")}{_esc(format_phone_display(phone))}</a>'
            )
            follow = _follow_html(rink, city_id=int(city["id"]), base_url=base_url)
            blocks.append(
                '<section class="g-sec">'
                f'<h2>{_esc(t("hub.when_title"))}</h2>'
                f'<p>{_esc(t("hub.phone_when", name=name))}</p>'
                f"{buttons}{follow}</section>"
            )
        way = _directions(rink)
        if way:
            blocks.append(way)
    blocks.append(_nearby_html(list(view.get("nearby") or []), title=t("hub.nearby_scheduled")))
    return "".join(blocks)


def _follow_html(rink: Mapping[str, Any], *, city_id: int, base_url: str) -> str:
    arena_id = rink.get("id")
    if arena_id is None:
        return ""
    href = public_telegram_cta_url(
        base_url,
        start_param=place_start_param(int(arena_id)),
        surface="place_page",
        city_id=city_id,
        arena_id=int(arena_id),
    )
    if not href:
        return ""
    return f'<a class="g-btn g-btn--ghost" href="{_esc(href)}">{icon_svg("bell")}{_esc(t("cta.follow_rink"))}</a>'

