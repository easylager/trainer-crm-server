"""Публичная главная каталога Glide — ``/`` (TASK-191-A, TASK-210-A)."""

from __future__ import annotations

import html as html_lib
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_city_day import (
    ICE_CITY_DAY_FROM_SQL,
    ICE_CITY_DAY_SESSION_WHERE_SQL,
    DEFAULT_TIMEZONE,
    city_slug,
    human_date,
    plural_ru,
)
from src.application.ice_session_use_cases import STATUS_ACTIVE
from src.application.ice_time_windows import home_picker_dates, resolve_home_window
from src.application.place_links import (
    catalog_start_param,
    join_public_origin,
    place_path,
    public_telegram_cta_url,
)
from src.application.schedule_staleness import LEVEL_VERY_STALE, load_arena_freshness, staleness_level
from src.shared.catalog_visibility import CATALOG_LISTED_SQL
from src.shared.copy_ru import t
from src.shared.glide_city_cookie import normalize_glide_city_slug
from src.shared.html_template import fill_placeholders, html_lang_for_country, json_for_script
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, ice_discovery_countries, public_scope_params
from src.shared.schedule_basis import (
    SCHEDULE_BASIS_LIVE,
    SCHEDULE_BASIS_PHOTO,
    SCHEDULE_BASIS_PROJECTED,
    normalize_schedule_basis,
)
from src.shared.specialist_roles import specialist_role_display

_log = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "catalog-home.html"

# (русское имя, область, запасные широта/долгота). Ключ справочника — city_slug(имя),
# не ручная транслитерация: у city_slug «ц» → c, «й» → y, поэтому «Бобруйск» = bobruysk.
_BY_CITY_ROWS: tuple[tuple[str, str, float, float], ...] = (
    ("Минск", "Минская область", 53.9023, 27.5619),
    ("Борисов", "Минская область", 54.2279, 28.5050),
    ("Жодино", "Минская область", 54.0942605, 28.3262757),
    ("Молодечно", "Минская область", 54.3011204, 26.8650159),
    ("Озерный", "Минская область", 53.8330, 27.9830),
    ("Раубичи", "Минская область", 54.0628, 27.7354),
    ("Силичи", "Минская область", 54.1565, 27.8349),
    ("Слуцк", "Минская область", 53.0274, 27.5499),
    ("Солигорск", "Минская область", 52.7909489, 27.5366473),
    ("Брест", "Брестская область", 52.0926764, 23.7384897),
    ("Барановичи", "Брестская область", 53.1493182, 26.0014462),
    ("Береза", "Брестская область", 52.5299, 24.98099),
    ("Ивацевичи", "Брестская область", 52.7211098, 25.3303487),
    ("Кобрин", "Брестская область", 52.2136574, 24.3641108),
    ("Лунинец", "Брестская область", 52.2600712, 26.7899673),
    ("Пинск", "Брестская область", 52.1221795, 26.1277244),
    ("Пружаны", "Брестская область", 52.5663378, 24.4743121),
    ("Витебск", "Витебская область", 55.1692254, 30.2266233),
    ("Новополоцк", "Витебская область", 55.5069684, 28.7024495),
    ("Орша", "Витебская область", 54.5217761, 30.4381153),
    ("Полоцк", "Витебская область", 55.4870, 28.7858),
    ("Гомель", "Гомельская область", 52.4604315, 31.0219016),
    ("Жлобин", "Гомельская область", 52.902213, 30.0582516),
    ("Мозырь", "Гомельская область", 52.0490, 29.2456),
    ("Речица", "Гомельская область", 52.3614, 30.3947),
    ("Светлогорск", "Гомельская область", 52.6311832, 29.718548),
    ("Гродно", "Гродненская область", 53.6690, 23.8290),
    ("Лида", "Гродненская область", 53.8954462, 25.3237632),
    ("Островец", "Гродненская область", 54.6101379, 25.9612152),
    ("Могилёв", "Могилёвская область", 53.88464, 30.32903),
    ("Бобруйск", "Могилёвская область", 53.1423013, 29.2469144),
    ("Горки", "Могилёвская область", 54.2747969, 30.9993037),
    ("Шклов", "Могилёвская область", 54.2044194, 30.3049466),
)
_BY_REGIONS: dict[str, str] = {city_slug(name): region for name, region, _lat, _lon in _BY_CITY_ROWS}
_BY_CITY_COORDS: dict[str, tuple[float, float]] = {
    city_slug(name): (lat, lon) for name, _region, lat, lon in _BY_CITY_ROWS
}
_OTHER_REGION = "Прочие"

_OBLAST_CENTER_SLUGS = frozenset({"minsk", "brest", "vitebsk", "gomel", "grodno", "mogilev"})
_MIN_PLACES_FOR_UPCOMING_BLOCK = 5
_USER_UPCOMING_LIMIT = 3
_MAP_VIEWBOX = (600, 520)
_BY_LON_MIN, _BY_LON_MAX = 23.0, 32.7
_BY_LAT_MIN, _BY_LAT_MAX = 51.2, 56.2
_MAP_COUNTRY_PATH = (
    "M37,226 L82,222 L148,201 L166,147 L212,121 L224,90 L271,74 L307,45 L376,59 L423,63 "
    "L464,85 L464,128 L512,156 L489,212 L547,236 L572,288 L512,297 L541,324 L506,367 "
    "L518,394 L464,404 L447,440 L418,449 L371,457 L336,447 L283,439 L248,422 L189,422 "
    "L130,413 L82,413 L37,439 L43,394 L14,377 L55,341 L55,297 L31,270 Z"
)

# Одна строка на арену: места считаем в Python, сеансы — тем же предикатом, что «лёд сегодня».
# Окно (:starts_at…:ends_at) и горизонт блока «Ближайшие» (:horizon_end) режутся здесь,
# very_stale отбрасывается после load_arena_freshness — как count_sessions_on_local_calendar_day_by_city.
_CITY_STATS_SQL = text(
    f"""
    SELECT c.id,
           c.name,
           c.country,
           c.sort_order,
           a.id AS arena_id,
           COALESCE(a.venue_type, 'ice') AS venue_type,
           a.latitude,
           a.longitude,
           MAX(p.slug) AS place_slug,
           COUNT(DISTINCT s.id) FILTER (
             WHERE s.starts_at_utc >= :starts_at
               AND s.starts_at_utc < :ends_at
           ) AS window_sessions,
           COUNT(DISTINCT s.id) AS horizon_sessions
    FROM cities c
    JOIN arenas a ON a.city_id = c.id
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    LEFT JOIN ice_sessions s ON s.arena_id = a.id
      AND s.starts_at_utc < :horizon_end
      {ICE_CITY_DAY_SESSION_WHERE_SQL}
    WHERE c.id = ANY(:city_ids)
      AND {PUBLIC_ARENA_VISIBLE_SQL}
    GROUP BY c.id, c.name, c.country, c.sort_order, a.id, a.venue_type, a.latitude, a.longitude
    """
)

_HOCKEY_FUTURE_SQL = text(
    f"""
    SELECT EXISTS (
        SELECT 1
        {ICE_CITY_DAY_FROM_SQL}
        WHERE c.country = ANY(:ice_countries)
          AND {PUBLIC_ARENA_VISIBLE_SQL}
          AND s.kind = 'hockey_practice'
          AND s.status = :st
          AND s.starts_at_utc > :now
    ) AS has_hockey
    """
)

_HOME_TRAINERS_SQL = text(
    f"""
    SELECT t.id,
           TRIM(
             COALESCE(p.first_name, '')
             || CASE WHEN p.last_name IS NOT NULL AND p.last_name <> '' THEN ' ' || p.last_name ELSE '' END
           ) AS full_name,
           p.specialist_role,
           a.name AS arena_name,
           ap.slug AS arena_slug,
           c.name AS city_name
    FROM trainers t
    LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
    JOIN cities c ON c.id = :city_id
    LEFT JOIN LATERAL (
        SELECT ta.arena_id
        FROM trainer_arenas ta
        WHERE ta.trainer_id = t.id AND ta.is_public = true
        ORDER BY ta.arena_id
        LIMIT 1
    ) pick ON true
    LEFT JOIN arenas a ON a.id = pick.arena_id
    LEFT JOIN arena_profiles ap ON ap.arena_id = a.id
    WHERE EXISTS (
        SELECT 1 FROM trainer_cities tc WHERE tc.trainer_id = t.id AND tc.city_id = :city_id
    )
      AND {CATALOG_LISTED_SQL}
    ORDER BY t.id
    LIMIT 3
    """
)

_COUNTRY_SECTION_ORDER = ("BY", "RU")
_COUNTRY_SECTION_LABEL = {"BY": "Беларусь", "RU": "Россия"}
_MINSK_SLUG = "minsk"
_UPCOMING_HORIZON_DAYS = 7
_MINUTES_UNTIL_LIMIT = 120


def _is_minsk_city(city: Mapping[str, Any]) -> bool:
    return str(city.get("slug") or "") == _MINSK_SLUG or str(city.get("name") or "").strip() == "Минск"


def _city_rank_key(city: Mapping[str, Any]) -> tuple[Any, ...]:
    """Минск первым в секции страны, далее по активности (сеансы сегодня, места, имя)."""
    return (
        0 if _is_minsk_city(city) else 1,
        -int(city.get("session_count") or 0),
        -int(city.get("place_count") or 0),
        str(city.get("name") or ""),
    )


def group_catalog_cities_by_country(cities: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for city in cities:
        code = str(city.get("country") or "BY").strip().upper() or "BY"
        buckets.setdefault(code, []).append(city)
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    for code in _COUNTRY_SECTION_ORDER:
        if code in buckets:
            groups.append((code, sorted(buckets.pop(code), key=_city_rank_key)))
    for code in sorted(buckets):
        groups.append((code, sorted(buckets[code], key=_city_rank_key)))
    return groups


_USER_UPCOMING_SQL = text(
    f"""
WITH city_clock AS (
    SELECT DISTINCT ON (a.city_id)
           a.city_id,
           COALESCE(p.timezone, '{DEFAULT_TIMEZONE}') AS tz
    FROM arenas a
    JOIN cities c ON c.id = a.city_id
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    WHERE a.city_id = :user_city_id
    ORDER BY a.city_id, a.id
)
SELECT c.name AS city_name,
       a.name AS arena_name,
       p.slug AS arena_slug,
       s.id AS session_id,
       s.starts_at_local,
       s.ends_at_local,
       s.local_date,
       s.schedule_basis,
       s.starts_at_utc,
       s.price_adult_minor,
       s.price_rental_minor,
       s.currency_code,
       cc.tz AS city_timezone
{ICE_CITY_DAY_FROM_SQL}
JOIN city_clock cc ON cc.city_id = a.city_id
WHERE a.city_id = :user_city_id
  AND s.starts_at_utc >= :starts_at
  AND s.starts_at_utc < :ends_at
  AND NOT (a.id = ANY(:very_stale_ids))
  {ICE_CITY_DAY_SESSION_WHERE_SQL}
ORDER BY s.starts_at_utc, s.id
LIMIT :lim
"""
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _esc(value: Any) -> str:
    return html_lib.escape(str(value or ""), quote=True)


def _local_today(tz_name: str, now: datetime) -> date:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo(DEFAULT_TIMEZONE)
    return now.astimezone(tz).date()


_WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_MONTHS_SHORT = (
    "янв",
    "фев",
    "мар",
    "апр",
    "май",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
)


def _session_day_label(row: Mapping[str, Any], *, now: datetime) -> str:
    tz_name = str(row.get("city_timezone") or DEFAULT_TIMEZONE)
    local_date = row.get("local_date")
    if not isinstance(local_date, date):
        return ""
    today = _local_today(tz_name, now)
    relative = human_date(local_date, today=today)
    if relative in ("сегодня", "завтра"):
        return relative
    wd = _WEEKDAYS_SHORT[local_date.weekday()]
    return f"{wd}, {local_date.day} {_MONTHS_SHORT[local_date.month - 1]}"


def _map_project(lat: float, lon: float) -> tuple[float, float]:
    w, h = _MAP_VIEWBOX
    pad_x, pad_y = 20.0, 20.0
    x = pad_x + (lon - _BY_LON_MIN) / (_BY_LON_MAX - _BY_LON_MIN) * (w - 2 * pad_x)
    y = pad_y + (_BY_LAT_MAX - lat) / (_BY_LAT_MAX - _BY_LAT_MIN) * (h - 2 * pad_y)
    return x, y


def _map_dot_radius(place_count: int) -> float:
    return float(min(10, max(5, place_count)))


def _build_day_picker(now: datetime) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for d in home_picker_dates(now):
        wd = _WEEKDAYS_SHORT[d.weekday()]
        label = f"{wd}, {d.day} {_MONTHS_SHORT[d.month - 1]}"
        items.append({"date": d.isoformat(), "label": label, "href": f"/?when=day&d={d.isoformat()}"})
    return items


def _minsk_date(now: datetime) -> date:
    return now.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _minutes_until(basis: str, starts: Any, now: datetime) -> int | None:
    """Минуты до старта. Только живой сеанс и строго меньше двух часов; projected — всегда None."""
    if basis != SCHEDULE_BASIS_LIVE:
        return None
    if not isinstance(starts, datetime):
        return None
    minutes = int((_aware_utc(starts) - _aware_utc(now)).total_seconds() // 60)
    if minutes <= 0 or minutes >= _MINUTES_UNTIL_LIMIT:
        return None
    return minutes


def _price_with_rental(row: Mapping[str, Any]) -> str | None:
    adult = row.get("price_adult_minor")
    rental = row.get("price_rental_minor")
    if adult is None or rental is None:
        return None
    total = int(adult) + int(rental)
    major = total / 100.0
    total_text = str(int(major)) if major == int(major) else f"{major:.2f}"
    currency = str(row.get("currency_code") or "BYN")
    return t("price.with_rental", total=total_text, currency=currency)


def _basis_fields(basis: str) -> tuple[str, str | None]:
    if basis == SCHEDULE_BASIS_PROJECTED:
        return t("basis.projected"), t("basis.projected_long")
    if basis == SCHEDULE_BASIS_LIVE:
        return t("basis.live"), None
    if basis == SCHEDULE_BASIS_PHOTO:
        return t("basis.photo"), None
    return "", None


def _session_card(row: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    basis = normalize_schedule_basis(None if row.get("schedule_basis") is None else str(row.get("schedule_basis")))
    label, long = _basis_fields(basis)
    card = dict(row)
    card["schedule_basis"] = basis
    card["minutes_until"] = _minutes_until(basis, row.get("starts_at_utc"), now)
    card["price_with_rental"] = _price_with_rental(row)
    card["basis_label"] = label
    card["basis_long"] = long
    return card


def _trainer_card_href(city_id: int) -> str:
    """До TASK-206 страницы тренера нет: тот же open-telegram, что у кнопки каталога."""
    href = public_telegram_cta_url(
        "",
        start_param=catalog_start_param(int(city_id), intent="coach"),
        surface="catalog_home",
        city_id=int(city_id),
    )
    return href or ""


def _period_when_phrase(when_key: str) -> str:
    return {
        "today": t("home.when_phrase.today"),
        "tomorrow": t("home.when_phrase.tomorrow"),
        "weekend": t("home.when_phrase.weekend"),
        "day": t("home.when_phrase.day"),
    }.get(when_key, t("home.when_phrase.today"))


def _resolve_user_city(
    catalog_cities: list[dict[str, Any]],
    *,
    user_city_slug: str | None,
    public_slug_set: set[str],
) -> dict[str, Any] | None:
    slug = normalize_glide_city_slug(user_city_slug or "")
    if slug and slug in public_slug_set:
        for city in catalog_cities:
            if str(city.get("slug")) == slug:
                return city
    for city in catalog_cities:
        if str(city.get("slug")) == _MINSK_SLUG:
            return city
    for city in catalog_cities:
        if str(city.get("country") or "").upper() == "BY":
            return city
    return catalog_cities[0] if catalog_cities else None


def _user_city_button_href(city: Mapping[str, Any]) -> str:
    slug = str(city["slug"])
    sole = str(city.get("sole_place_slug") or "").strip()
    if int(city.get("place_count") or 0) == 1 and sole:
        return place_path(city_name=str(city["name"]), slug=sole)
    return f"/c/{slug}"


def _upcoming_block_title(city_name: str, when_key: str) -> str:
    if when_key == "weekend":
        return t("home.upcoming.weekend", city=city_name)
    return t("home.upcoming.city", city=city_name)


def _upcoming_more_href(
    city: Mapping[str, Any],
    when_key: str,
    *,
    selected_day: date | None,
    today: date,
) -> str | None:
    """«Все →». ``w`` — как ``selection_page.clean_when``. Для дня есть только страница «сегодня»."""
    slug = str(city["slug"])
    if when_key == "weekend":
        return f"/c/{slug}?w=weekend"
    if when_key == "tomorrow":
        return f"/c/{slug}?w=tomorrow"
    if when_key == "today":
        return f"/c/{slug}?w=today"
    if when_key == "day" and selected_day == today:
        return f"/ice/{slug}/today"
    return None


def build_city_layout(catalog_cities: list[dict[str, Any]]) -> dict[str, Any]:
    by_cities = [c for c in catalog_cities if str(c.get("country") or "").upper() == "BY"]
    ru_cities = [c for c in catalog_cities if str(c.get("country") or "").upper() == "RU"]
    minsk = next((c for c in by_cities if str(c.get("slug")) == _MINSK_SLUG), None)
    oblast_centers = [
        c for c in by_cities if str(c.get("slug")) in _OBLAST_CENTER_SLUGS and str(c.get("slug")) != _MINSK_SLUG
    ]
    oblast_centers.sort(key=lambda c: (-int(c.get("session_count") or 0), str(c.get("name") or "")))
    used_slugs = {str(c.get("slug")) for c in ([minsk] if minsk else []) + oblast_centers}
    region_buckets: dict[str, list[dict[str, Any]]] = {}
    for city in by_cities:
        slug = str(city.get("slug") or "")
        if slug in used_slugs:
            continue
        region = _BY_REGIONS.get(slug)
        if not region:
            region = _OTHER_REGION
            _log.warning(
                "BY city %s (%s) has no oblast in the home directory; grouped as %s",
                city.get("name"),
                slug,
                _OTHER_REGION,
            )
        region_buckets.setdefault(region, []).append(city)
    for _region, group in region_buckets.items():
        group.sort(key=lambda c: (-int(c.get("session_count") or 0), str(c.get("name") or "")))
    regions = [
        {"name": name, "cities": group, "count": len(group)}
        for name, group in sorted(region_buckets.items(), key=lambda x: x[0])
    ]
    return {
        "minsk": minsk,
        "oblast_centers": oblast_centers,
        "regions": regions,
        "ru_cities": sorted(ru_cities, key=lambda c: str(c.get("name") or "")),
    }


def build_map_points(catalog_cities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for city in catalog_cities:
        if str(city.get("country") or "").upper() != "BY":
            continue
        lat, lon = city.get("avg_lat"), city.get("avg_lon")
        if lat is None or lon is None:
            continue
        slug = str(city["slug"])
        points.append(
            {
                "slug": slug,
                "name": str(city["name"]),
                "x": _map_project(float(lat), float(lon))[0],
                "y": _map_project(float(lat), float(lon))[1],
                "r": _map_dot_radius(int(city.get("place_count") or 0)),
                "is_oblast_center": slug in _OBLAST_CENTER_SLUGS,
                "is_minsk": slug == _MINSK_SLUG,
                "session_count": int(city.get("session_count") or 0),
            }
        )
    return points


def render_map_svg(points: list[Mapping[str, Any]]) -> str:
    parts = [
        '<svg class="home-map" viewBox="0 0 600 520" role="img" aria-label="',
        _esc(t("home.map.aria")),
        '">',
        f'<path d="{_MAP_COUNTRY_PATH}" fill="#eaf3f3" stroke="#b9d3d2" stroke-width="2" stroke-linejoin="round"/>',
    ]
    minsk = next((p for p in points if p.get("is_minsk")), None)
    if minsk:
        parts.append(
            f'<circle cx="{minsk["x"]:.1f}" cy="{minsk["y"]:.1f}" r="{float(minsk["r"]) + 24:.1f}" '
            f'fill="#0f8f8a" fill-opacity="0.18" stroke="#0f8f8a" stroke-width="2"/>'
        )
    parts.append('<g fill="#0f8f8a">')
    for pt in points:
        title = (
            f"{pt['name']} — {pt['session_count']} {plural_ru(int(pt['session_count']), 'сеанс', 'сеанса', 'сеансов')}"
        )
        parts.append(
            f'<a href="/c/{_esc(pt["slug"])}"><title>{_esc(title)}</title>'
            f'<circle cx="{float(pt["x"]):.1f}" cy="{float(pt["y"]):.1f}" r="{float(pt["r"]):.1f}"/></a>'
        )
    parts.append("</g>")
    parts.append('<g font-size="14" font-weight="600" fill="#0d1b26">')
    for pt in points:
        if not pt.get("is_oblast_center"):
            continue
        parts.append(
            f'<text x="{float(pt["x"]):.1f}" y="{float(pt["y"]) - float(pt["r"]) - 6:.1f}">{_esc(pt["name"])}</text>'
        )
    parts.append("</g></svg>")
    return "".join(parts)


def _fold_arena_rows(rows: list[Mapping[str, Any]], *, very_stale: set[int]) -> list[dict[str, Any]]:
    buckets: dict[int, dict[str, Any]] = {}
    order: list[int] = []
    for row in rows:
        cid = int(row["id"])
        if cid not in buckets:
            order.append(cid)
            buckets[cid] = {
                "id": cid,
                "name": str(row["name"]),
                "country": str(row["country"] or ""),
                "slug": city_slug(str(row["name"])),
                "place_count": 0,
                "ice_place_count": 0,
                "shop_count": 0,
                "session_count": 0,
                "arenas_with_sessions": 0,
                "horizon_arenas_with_sessions": 0,
                "_lat_sum": 0.0,
                "_lon_sum": 0.0,
                "_lat_n": 0,
                "_slugs": [],
            }
        city = buckets[cid]
        city["place_count"] += 1
        venue = str(row.get("venue_type") or "ice")
        if venue in ("ice", "outdoor"):
            city["ice_place_count"] += 1
        if venue == "shop":
            city["shop_count"] += 1
        lat, lon = row.get("latitude"), row.get("longitude")
        if lat is not None and lon is not None:
            city["_lat_sum"] += float(lat)
            city["_lon_sum"] += float(lon)
            city["_lat_n"] += 1
        place_slug = str(row.get("place_slug") or "").strip()
        if place_slug:
            city["_slugs"].append(place_slug)
        aid = int(row["arena_id"])
        stale = aid in very_stale
        window_n = 0 if stale else int(row.get("window_sessions") or 0)
        horizon_n = 0 if stale else int(row.get("horizon_sessions") or 0)
        city["session_count"] += window_n
        if window_n > 0:
            city["arenas_with_sessions"] += 1
        if horizon_n > 0:
            city["horizon_arenas_with_sessions"] += 1
    cities: list[dict[str, Any]] = []
    for cid in order:
        city = buckets[cid]
        if city["_lat_n"]:
            city["avg_lat"] = city["_lat_sum"] / city["_lat_n"]
            city["avg_lon"] = city["_lon_sum"] / city["_lat_n"]
        else:
            fallback = _BY_CITY_COORDS.get(str(city["slug"]))
            if fallback:
                city["avg_lat"], city["avg_lon"] = fallback
            else:
                city["avg_lat"] = None
                city["avg_lon"] = None
        city["sole_place_slug"] = city["_slugs"][0] if city["place_count"] == 1 and city["_slugs"] else None
        for key in ("_lat_sum", "_lon_sum", "_lat_n", "_slugs"):
            del city[key]
        cities.append(city)
    return cities


def _selected_home_day(when_key: str, window_date: str | None, *, show_day_picker: bool, today: date) -> date | None:
    """Календарный день для ``when=day``. Пикер без даты — None. Неверный ``d`` — сегодня."""
    if when_key != "day" or show_day_picker:
        return None
    if window_date:
        return date.fromisoformat(window_date)
    return today


async def load_catalog_home_view(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    when: str | None = None,
    day_date: str | None = None,
    user_city_slug: str | None = None,
) -> dict[str, Any]:
    """
    TASK-210-A: загрузка данных главной с выбором периода.

    :param when: 'today'|'tomorrow'|'weekend'|'day' или None (умный дефолт)
    :param day_date: 'YYYY-MM-DD' для when='day'
    :param user_city_slug: slug города из cookie glide_city
    """
    from src.application.ice_city_day import _public_cities

    now = _aware_utc(now or _utc_now())
    when_key, window, show_day_picker = resolve_home_window(when, day_date, now)
    period_start, period_end = window.starts_at, window.ends_at
    today = _minsk_date(now)
    selected_day = _selected_home_day(when_key, window.local_date, show_day_picker=show_day_picker, today=today)
    horizon_end = now + timedelta(days=_UPCOMING_HORIZON_DAYS)

    cities = await _public_cities(session)
    empty: dict[str, Any] = {
        "cities": [],
        "city_groups": [],
        "city_layout": {"minsk": None, "oblast_centers": [], "regions": [], "ru_cities": []},
        "sessions": [],
        "sessions_title": "",
        "show_upcoming_block": False,
        "show_day_picker": show_day_picker,
        "day_picker": _build_day_picker(now) if show_day_picker else [],
        "country": "BY",
        "now": now,
        "when_key": when_key,
        "period_start": period_start,
        "period_end": period_end,
        "selected_date": selected_day.isoformat() if selected_day else None,
        "user_city": None,
        "user_city_id": None,
        "user_city_slug": _MINSK_SLUG,
        "map_points": [],
        "map_svg": "",
        "chips": {
            "hockey": False,
            "rollerski": False,
            "first_time_href": "/first-time",
            "hockey_href": None,
        },
        "trainers": [],
        "shop_count": 0,
    }
    if not cities:
        return empty

    city_ids = [int(c["id"]) for c in cities]
    stats_rows = (
        (
            await session.execute(
                _CITY_STATS_SQL,
                {
                    "city_ids": city_ids,
                    "starts_at": period_start,
                    "ends_at": period_end,
                    "horizon_end": horizon_end,
                    "now": now,
                    "st": STATUS_ACTIVE,
                    **public_scope_params(),
                },
            )
        )
        .mappings()
        .all()
    )

    session_arena_ids = [
        int(row["arena_id"])
        for row in stats_rows
        if int(row.get("window_sessions") or 0) > 0 or int(row.get("horizon_sessions") or 0) > 0
    ]
    fresh = await load_arena_freshness(session, session_arena_ids, now=now) if session_arena_ids else {}
    very_stale = {aid for aid, item in fresh.items() if staleness_level(item) == LEVEL_VERY_STALE}
    catalog_cities = _fold_arena_rows(list(stats_rows), very_stale=very_stale)

    city_groups = group_catalog_cities_by_country(catalog_cities)
    catalog_cities = [city for _, group in city_groups for city in group]
    public_slug_set = {str(c["slug"]) for c in catalog_cities}
    user_city = _resolve_user_city(catalog_cities, user_city_slug=user_city_slug, public_slug_set=public_slug_set)
    user_city_id = int(user_city["id"]) if user_city else None
    show_upcoming_block = bool(
        user_city and int(user_city.get("horizon_arenas_with_sessions") or 0) >= _MIN_PLACES_FOR_UPCOMING_BLOCK
    )

    sessions: list[dict[str, Any]] = []
    if show_upcoming_block and user_city_id is not None:
        upcoming = (
            (
                await session.execute(
                    _USER_UPCOMING_SQL,
                    {
                        "user_city_id": user_city_id,
                        "starts_at": period_start,
                        "ends_at": period_end,
                        "now": now,
                        "st": STATUS_ACTIVE,
                        "lim": _USER_UPCOMING_LIMIT,
                        "very_stale_ids": sorted(very_stale) or [-1],
                        **public_scope_params(),
                    },
                )
            )
            .mappings()
            .all()
        )
        sessions = [_session_card(row, now=now) for row in upcoming]

    hockey_row = (
        (
            await session.execute(
                _HOCKEY_FUTURE_SQL,
                {
                    "now": now,
                    "st": STATUS_ACTIVE,
                    "ice_countries": list(ice_discovery_countries()),
                    **public_scope_params(),
                },
            )
        )
        .mappings()
        .first()
    )
    has_hockey = bool(hockey_row and hockey_row.get("has_hockey"))

    trainers: list[dict[str, Any]] = []
    shop_count = 0
    if user_city_id is not None:
        shop_count = int(user_city.get("shop_count") or 0) if user_city else 0
        trainer_rows = (await session.execute(_HOME_TRAINERS_SQL, {"city_id": user_city_id})).mappings().all()
        for row in trainer_rows:
            role = specialist_role_display(str(row.get("specialist_role") or ""))
            arena_name = str(row.get("arena_name") or "").strip()
            trainers.append(
                {
                    "id": int(row["id"]),
                    "name": str(row.get("full_name") or "").strip() or "Тренер",
                    "specialization": role,
                    "arena_name": arena_name,
                    "href": _trainer_card_href(user_city_id),
                }
            )

    sessions_title = (
        _upcoming_block_title(str(user_city["name"]), when_key) if user_city and show_upcoming_block else ""
    )
    countries = {str(c.get("country") or "") for c in catalog_cities}
    country = "BY" if "BY" in countries else (next(iter(countries), "BY") if countries else "BY")
    map_points = build_map_points(catalog_cities)

    user_city_vm = None
    if user_city:
        user_city_vm = {
            "id": int(user_city["id"]),
            "name": str(user_city["name"]),
            "slug": str(user_city["slug"]),
            "session_count": int(user_city.get("session_count") or 0),
            "place_count": int(user_city.get("place_count") or 0),
            "ice_place_count": int(user_city.get("ice_place_count") or 0),
            "arenas_with_sessions": int(user_city.get("arenas_with_sessions") or 0),
            "horizon_arenas_with_sessions": int(user_city.get("horizon_arenas_with_sessions") or 0),
            "href": _user_city_button_href(user_city),
            "when_phrase": _period_when_phrase(when_key),
            "show_upcoming_block": show_upcoming_block,
            "upcoming_more_href": _upcoming_more_href(user_city, when_key, selected_day=selected_day, today=today),
        }

    return {
        **empty,
        "cities": catalog_cities,
        "city_groups": city_groups,
        "city_layout": build_city_layout(catalog_cities),
        "sessions": sessions,
        "sessions_title": sessions_title,
        "show_upcoming_block": show_upcoming_block,
        "show_day_picker": show_day_picker,
        "day_picker": _build_day_picker(now) if show_day_picker else [],
        "country": country,
        "when_key": when_key,
        "selected_date": selected_day.isoformat() if selected_day else None,
        "user_city": user_city_vm,
        "user_city_id": user_city_id,
        "user_city_slug": str(user_city["slug"]) if user_city else _MINSK_SLUG,
        "map_points": map_points,
        "map_svg": render_map_svg(map_points),
        "chips": {
            "hockey": has_hockey,
            "rollerski": False,
            "first_time_href": "/first-time",
            # /c/ не понимает kind=ohm — чип скрыт, пока фильтр не появится (Q-001 / спека).
            "hockey_href": None,
        },
        "trainers": trainers,
        "shop_count": shop_count,
    }


def _city_row(city: Mapping[str, Any], *, when_key: str) -> str:
    name = str(city["name"])
    slug = str(city["slug"])
    places = int(city["place_count"] or 0)
    sessions = int(city["session_count"] or 0)
    p_word = plural_ru(places, "место", "места", "мест")
    if sessions:
        s_word = plural_ru(sessions, "сеанс", "сеанса", "сеансов")
        phrase = _period_when_phrase(when_key)
        stats = f"{places} {p_word} · {sessions} {s_word} {phrase}"
    else:
        stats = f"{places} {p_word}"
    links = f'<a href="/c/{_esc(slug)}">{_esc(t("home.all_places"))}</a>'
    if sessions > 0 and when_key == "today":
        links += f' · <a href="/ice/{_esc(slug)}/today">{_esc(t("home.ice_today"))}</a>'
    return (
        '<li class="city">'
        f'<h2 class="city__name"><a href="/c/{_esc(slug)}">{_esc(name)}</a></h2>'
        f'<p class="city__stats">{_esc(stats)}</p>'
        f'<p class="city__links">{links}</p>'
        "</li>"
    )


def _day_picker_html(items: list[Mapping[str, Any]]) -> str:
    if not items:
        return ""
    links = "".join(
        f'<li><a href="{html_lib.escape(str(it.get("href") or ""), quote=True)}">{_esc(it.get("label"))}</a></li>'
        for it in items
    )
    return f'<nav class="day-picker"><ul>{links}</ul></nav>'


def _chips_html(chips: Mapping[str, Any]) -> str:
    parts = [f'<a class="chip chip--active" href="/">{_esc(t("chip.ice"))}</a>']
    parts.append(
        f'<a class="chip" href="{_esc(chips.get("first_time_href") or "/first-time")}">{_esc(t("chip.first_time"))}</a>'
    )
    return '<div class="chips">' + "".join(parts) + "</div>"


def _user_city_button_html(user_city: Mapping[str, Any] | None) -> str:
    if not user_city:
        return ""
    sessions = int(user_city.get("session_count") or 0)
    title = t(
        "home.city_button.title",
        city=str(user_city.get("name") or ""),
        sessions=sessions,
        sessions_word=plural_ru(sessions, "сеанс", "сеанса", "сеансов"),
        when_phrase=str(user_city.get("when_phrase") or ""),
    )
    return (
        f'<a class="city-button" id="cities" href="{_esc(user_city.get("href"))}">'
        f'<span class="city-button__caption">{_esc(t("home.city_button.caption"))}</span>'
        f'<span class="city-button__title">{_esc(title)}</span></a>'
    )


def _cities_html(city_groups: list[tuple[str, list[Mapping[str, Any]]]], *, when_key: str) -> str:
    if not city_groups:
        return f'<p class="muted">{_esc(t("home.cities_empty"))}</p>'
    parts: list[str] = []
    for code, group in city_groups:
        label = _COUNTRY_SECTION_LABEL.get(code, code)
        parts.append(
            '<section class="country-group">'
            f'<h3 class="country-group__title">{_esc(label)}</h3>'
            '<ul class="cities">' + "".join(_city_row(c, when_key=when_key) for c in group) + "</ul></section>"
        )
    return "".join(parts)


def _session_row(row: Mapping[str, Any], *, now: datetime) -> str:
    """Строка сеанса. «через N мин» берётся из view-model и у projected всегда пусто."""
    city_name = str(row["city_name"])
    slug = str(row.get("arena_slug") or "").strip()
    arena_name = str(row["arena_name"])
    starts = str(row.get("starts_at_local") or "").strip()
    ends = str(row.get("ends_at_local") or "").strip()
    time_text = f"{starts}–{ends}" if starts and ends else (starts or ends or "—")
    day_label = _session_day_label(row, now=now)
    basis = str(row.get("schedule_basis") or SCHEDULE_BASIS_LIVE)
    is_projected = basis == SCHEDULE_BASIS_PROJECTED

    if slug:
        href = place_path(city_name=city_name, slug=slug)
        if row.get("session_id"):
            href += f"?s={int(row['session_id'])}"
        name_html = f'<a href="{_esc(href)}">{_esc(arena_name)}</a>'
    else:
        name_html = _esc(arena_name)

    day_html = f'<span class="session__day">{_esc(day_label)}</span>' if day_label else ""
    soon_html = ""
    if row.get("minutes_until") is not None and not is_projected:
        soon_html = f'<span class="session__soon">{_esc(t("home.minutes_until", n=int(row["minutes_until"])))}</span>'
    session_class = "session session--projected" if is_projected else "session"
    extras: list[str] = []
    if row.get("basis_label"):
        extras.append(f'<span class="session__basis">{_esc(row.get("basis_label"))}</span>')
    if row.get("basis_long"):
        extras.append(f'<span class="session__basis-long">{_esc(row.get("basis_long"))}</span>')
    if row.get("price_with_rental"):
        extras.append(f'<span class="session__price">{_esc(row.get("price_with_rental"))}</span>')

    return (
        f'<li class="{session_class}">'
        f'{day_html}<span class="session__time">{_esc(time_text)}</span>'
        f"{soon_html}"
        f'<span class="session__place">{name_html}</span>'
        f'<span class="session__city">{_esc(city_name)}</span>'
        f"{''.join(extras)}"
        "</li>"
    )


def _json_ld(view: Mapping[str, Any], *, canonical_url: str) -> str:
    elements = []
    for n, city in enumerate(view.get("cities") or []):
        slug = str(city["slug"])
        elements.append(
            {
                "@type": "ListItem",
                "position": n + 1,
                "name": city.get("name"),
                "url": join_public_origin(canonical_url, f"/c/{slug}"),
            }
        )
    graph = [
        {
            "@type": "WebSite",
            "name": "Glide",
            "url": canonical_url,
            "description": "Катки, расписание массовых катаний и лёд сегодня",
        },
        {
            "@type": "ItemList",
            "name": "Города каталога Glide",
            "itemListElement": elements,
        },
    ]
    return json_for_script({"@context": "https://schema.org", "@graph": graph})


def _format_date_string(now: datetime) -> str:
    """Дата-строка по Минску: 'Пятница, 9 октября'."""
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    local = now.astimezone(tz)
    weekdays = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
    months_gen = (
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
    weekday = weekdays[local.weekday()]
    return f"{weekday.capitalize()}, {local.day} {months_gen[local.month - 1]}"


def _counter_text(session_count: int, city_count: int, when_key: str) -> str:
    when_text = {
        "today": t("home.counter.when.today"),
        "tomorrow": t("home.counter.when.tomorrow"),
        "weekend": t("home.counter.when.weekend"),
        "day": t("home.counter.when.day"),
    }.get(when_key, t("home.counter.when.today"))
    return t(
        "home.counter",
        when=when_text,
        sessions=session_count,
        sessions_word=plural_ru(session_count, "сеанс", "сеанса", "сеансов"),
        cities=city_count,
        cities_word=plural_ru(city_count, "городе", "городах", "городах"),
    )


def render_catalog_home_page(
    view: Mapping[str, Any],
    *,
    canonical_url: str,
    og_image_url: str,
    cta_url: str | None,
    trainers_url: str,
    robots: str = "index, follow",
) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    cities = list(view.get("cities") or [])
    raw_groups = view.get("city_groups")
    if isinstance(raw_groups, list) and raw_groups:
        city_groups = [(str(a), list(b)) for a, b in raw_groups]
    else:
        city_groups = group_catalog_cities_by_country(cities)
    sessions = list(view.get("sessions") or [])
    now = view.get("now") if isinstance(view.get("now"), datetime) else _utc_now()
    country = str(view.get("country") or "BY")
    sessions_title = str(view.get("sessions_title") or t("when.today"))
    lang, og_locale = html_lang_for_country(country)

    when_key = str(view.get("when_key") or "today")

    # TASK-210: нейтральный заголовок (PDEC-019)
    page_h1 = "Где покататься"
    title = "Где покататься в Беларуси — катки и расписание массовых катаний | Glide"
    description = (
        "Где покататься: города с катками, расписание массовых катаний и ссылки на все места в каталоге Glide."
    )
    cities_html = _cities_html(city_groups, when_key=when_key)
    show_upcoming = bool(view.get("show_upcoming_block"))
    user_city = view.get("user_city") if isinstance(view.get("user_city"), Mapping) else None
    more_href = str(user_city.get("upcoming_more_href") or "") if user_city else ""
    more_html = (
        f'<p class="sessions__more"><a href="{_esc(more_href)}">{_esc(t("home.all_link"))}</a></p>'
        if show_upcoming and more_href
        else ""
    )
    if show_upcoming and sessions:
        sessions_html = (
            '<ul class="sessions">' + "".join(_session_row(s, now=now) for s in sessions) + "</ul>" + more_html
        )
    elif show_upcoming:
        sessions_html = f'<p class="muted">{_esc(t("home.sessions_empty"))}</p>' + more_html
    else:
        sessions_html = ""
        sessions_title = ""

    # Дата-строка
    date_string = _format_date_string(now)

    # Счётчик сеансов (только BY)
    by_cities = [c for c in cities if c.get("country") == "BY"]
    total_sessions = sum(int(c.get("session_count") or 0) for c in by_cities)
    cities_with_sessions = len([c for c in by_cities if int(c.get("session_count") or 0) > 0])
    counter_text = _counter_text(total_sessions, cities_with_sessions, when_key)

    chips = view.get("chips") if isinstance(view.get("chips"), Mapping) else {}
    day_picker = view.get("day_picker") if isinstance(view.get("day_picker"), list) else []
    map_svg = str(view.get("map_svg") or "")

    values = {
        "__LANG__": lang,
        "__OG_LOCALE__": og_locale,
        "__OG_TITLE__": _esc(title),
        "__OG_DESCRIPTION__": _esc(description),
        "__CANONICAL__": _esc(canonical_url),
        "__OG_IMAGE__": _esc(og_image_url),
        "__ROBOTS__": _esc(robots),
        "__JSONLD__": _json_ld(view, canonical_url=canonical_url),
        "__CITIES__": cities_html,
        "__MAP_SVG__": map_svg,
        "__DAY_PICKER__": _day_picker_html(day_picker),
        "__CITY_BUTTON__": _user_city_button_html(user_city),
        "__CHIPS__": _chips_html(chips),
        "__SESSIONS_TITLE__": _esc(sessions_title),
        "__SESSIONS__": sessions_html,
        "__TRAINERS_URL__": _esc(trainers_url),
        "__PAGE_H1__": _esc(page_h1),
        "__DATE_STRING__": _esc(date_string),
        "__COUNTER_TEXT__": _esc(counter_text),
        "__WHEN_TODAY__": _esc(t("when.today")),
        "__WHEN_TOMORROW__": _esc(t("when.tomorrow")),
        "__WHEN_WEEKEND__": _esc(t("when.weekend")),
        "__WHEN_DAY__": _esc(t("when.day")),
    }
    html = fill_placeholders(template, values)
    if cta_url:
        html = html.replace("__CTA_URL__", _esc(cta_url))
    else:
        start = html.find('<a class="cta cta--secondary"')
        end = html.find("</a>", start)
        if start != -1 and end != -1:
            html = html[:start] + html[end + 4 :]
    return html


def catalog_home_og_image_url(base_url: str) -> str:
    path = "/logos/02-horizontal-full/glide-horizontal-teal-icon-black-text-on-white.png"
    base = (base_url or "").strip().rstrip("/")
    if base.lower().startswith("https://"):
        return f"{base}{path}"
    return path


def parse_city_session_count_from_home(html: str, city_name: str) -> int | None:
    """Тестовый хелпер: «N сеансов сегодня» в карточке города."""
    block = re.search(
        rf'<h2 class="city__name"><a href="[^"]+">{re.escape(city_name)}</a></h2>\s*'
        r'<p class="city__stats">([^<]+)</p>',
        html,
    )
    if not block:
        return None
    stats = block.group(1)
    match = re.search(r"(\d+)\s+сеанс", stats)
    return int(match.group(1)) if match else 0
