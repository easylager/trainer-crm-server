"""Публичная главная каталога Glide — ``/`` (TASK-191-A, TASK-210-A)."""

from __future__ import annotations

import html as html_lib
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_city_day import (
    ICE_CITY_DAY_FROM_SQL,
    DEFAULT_TIMEZONE,
    city_slug,
    human_date,
    plural_ru,
)
from src.application.ice_session_use_cases import STATUS_ACTIVE
from src.application.place_links import join_public_origin, place_path
from src.shared.catalog_visibility import CATALOG_LISTED_SQL
from src.shared.copy_ru import t
from src.shared.glide_city_cookie import normalize_glide_city_slug
from src.shared.html_template import fill_placeholders, html_lang_for_country, json_for_script
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, ice_discovery_countries, public_scope_params
from src.shared.specialist_roles import specialist_role_display

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "catalog-home.html"
_NATIONWIDE_SESSIONS = 3  # TASK-210: до 3 ближайших сеансов

# TASK-210: справочник «город → область» для всех публичных BY-городов (29+).
_BY_REGIONS: dict[str, str] = {
    "minsk": "Минская область",
    "brest": "Брестская область",
    "gomel": "Гомельская область",
    "grodno": "Гродненская область",
    "mogilev": "Могилёвская область",
    "vitebsk": "Витебская область",
    "baranovichi": "Брестская область",
    "bereza": "Брестская область",
    "bobruisk": "Могилёвская область",
    "borisov": "Минская область",
    "gorki": "Могилёвская область",
    "zhodino": "Минская область",
    "ivatsevichi": "Брестская область",
    "kobrin": "Брестская область",
    "lida": "Гродненская область",
    "luninets": "Брестская область",
    "molodechno": "Минская область",
    "mozyr": "Гомельская область",
    "novopolock": "Витебская область",
    "orsha": "Витебская область",
    "ostrovets": "Гродненская область",
    "pinsk": "Брестская область",
    "polotsk": "Витебская область",
    "pruzhany": "Брестская область",
    "raubichi": "Минская область",
    "rechitsa": "Гомельская область",
    "shklov": "Могилёвская область",
    "silichi": "Минская область",
    "slutsk": "Минская область",
    "soligorsk": "Минская область",
    "svetlogorsk": "Гомельская область",
}

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

_CITY_STATS_SQL = text(
    f"""
    SELECT c.id,
           c.name,
           c.country,
           c.sort_order,
           COUNT(DISTINCT a.id) AS place_count,
           COUNT(DISTINCT a.id) FILTER (
             WHERE COALESCE(a.venue_type, 'ice') IN ('ice', 'outdoor')
           ) AS ice_place_count,
           COUNT(DISTINCT a.id) FILTER (WHERE a.venue_type = 'shop') AS shop_count,
           AVG(a.latitude) FILTER (
             WHERE a.latitude IS NOT NULL AND a.longitude IS NOT NULL
           ) AS avg_lat,
           AVG(a.longitude) FILTER (
             WHERE a.latitude IS NOT NULL AND a.longitude IS NOT NULL
           ) AS avg_lon,
           COUNT(DISTINCT s.id) AS session_count,
           COUNT(DISTINCT a.id) FILTER (WHERE s.id IS NOT NULL) AS arenas_with_sessions,
           CASE WHEN COUNT(DISTINCT a.id) = 1 THEN MAX(p.slug) ELSE NULL END AS sole_place_slug
    FROM cities c
    JOIN arenas a ON a.city_id = c.id
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    LEFT JOIN ice_sessions s ON s.arena_id = a.id
      AND s.status = :st
      AND s.kind IN ('public_skate', 'open_ice')
      AND s.starts_at_utc >= :starts_at
      AND s.starts_at_utc < :ends_at
      AND (s.valid_until IS NULL OR s.valid_until >= :starts_at)
    WHERE c.id = ANY(:city_ids)
      AND {PUBLIC_ARENA_VISIBLE_SQL}
    GROUP BY c.id, c.name, c.country, c.sort_order
    HAVING COUNT(DISTINCT a.id) > 0
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


# TASK-210: выбор периода времени
def _default_when_key(now: datetime) -> str:
    """Умный дефолт: Пн-Пт до 15:00 — 'today'; Пт с 15:00, Сб, Вс — 'weekend'."""
    tz = ZoneInfo(DEFAULT_TIMEZONE)  # Europe/Minsk
    local = now.astimezone(tz)
    weekday = local.weekday()  # 0 = Пн, 4 = Пт, 5 = Сб, 6 = Вс

    # Пт с 15:00 до конца дня — weekend
    if weekday == 4 and local.time() >= time(15, 0):
        return "weekend"
    # Сб весь день — weekend
    if weekday == 5:
        return "weekend"
    # Вс до 18:00 — weekend; после 18:00 — следующие выходные
    if weekday == 6:
        if local.time() < time(18, 0):
            return "weekend"
        else:
            return "weekend"  # следующие выходные, но всё равно ключ weekend
    # Остальное — today
    return "today"


def _parse_when(when: str | None, now: datetime) -> tuple[str, datetime, datetime]:
    """Возвращает (key, starts_at, ends_at) для фильтрации сеансов."""
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    local = now.astimezone(tz)
    today = local.date()

    key = (when or "").strip().lower()
    if key == "day":
        tz = ZoneInfo(DEFAULT_TIMEZONE)
        today = local.date()
        starts_at = now
        ends_at = datetime.combine(today + timedelta(days=1), time(0, 0), tzinfo=tz).astimezone(timezone.utc)
        return "day", starts_at, ends_at
    if not key or key not in ("today", "tomorrow", "weekend"):
        key = _default_when_key(now)

    # Сегодня: с now до конца дня
    if key == "today":
        starts_at = now
        ends_at = datetime.combine(today + timedelta(days=1), time(0, 0), tzinfo=tz).astimezone(timezone.utc)
        return "today", starts_at, ends_at

    # Завтра: завтра весь день
    if key == "tomorrow":
        tomorrow = today + timedelta(days=1)
        starts_at = datetime.combine(tomorrow, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
        ends_at = datetime.combine(tomorrow + timedelta(days=1), time(0, 0), tzinfo=tz).astimezone(timezone.utc)
        return "tomorrow", starts_at, ends_at

    # В выходные: Сб 00:00 - Пн 00:00 (или с текущего момента, если сейчас выходные)
    if key == "weekend":
        # Если сейчас Сб или Вс, начинаем с текущего момента
        if today.weekday() in (5, 6):  # Сб или Вс
            saturday = today - timedelta(days=today.weekday() - 5)
        else:
            # Ближайшая суббота
            saturday = today + timedelta(days=(5 - today.weekday()) % 7)
            if saturday == today and local.time() >= time(18, 0) and today.weekday() == 6:
                # Вс после 18:00 — следующие выходные
                saturday = today + timedelta(days=6)

        monday = saturday + timedelta(days=2)
        starts_at = max(now, datetime.combine(saturday, time(0, 0), tzinfo=tz).astimezone(timezone.utc))
        ends_at = datetime.combine(monday, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
        return "weekend", starts_at, ends_at

def _parse_day_date(d: str | None, now: datetime) -> date | None:
    """Парсит ?d=YYYY-MM-DD, возвращает дату или None."""
    if not d:
        return None
    try:
        parsed = date.fromisoformat(d.strip())
        tz = ZoneInfo(DEFAULT_TIMEZONE)
        today = now.astimezone(tz).date()
        # Проверяем, что дата в допустимом диапазоне (сегодня ... +7 дней)
        if today <= parsed <= today + timedelta(days=7):
            return parsed
    except (ValueError, AttributeError):
        pass
    return None


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


def catalog_home_headline(countries: set[str]) -> tuple[str, str]:
    """``(h1, document title)`` — не обещаем «только Беларусь», если в списке есть RU."""
    codes = {c.strip().upper() for c in countries if c}
    if codes == {"BY"} or (not codes):
        h1 = "Катки Беларуси"
        title = "Катки Беларуси — расписание и города | Glide"
    elif codes <= {"BY", "RU"} and "RU" in codes:
        h1 = "Катки — расписание по городам"
        title = "Катки Беларуси и России — расписание и города | Glide"
    else:
        h1 = "Катки — расписание по городам"
        title = "Катки — расписание и города | Glide"
    return h1, title


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
       cc.tz AS city_timezone
{ICE_CITY_DAY_FROM_SQL}
JOIN city_clock cc ON cc.city_id = a.city_id
WHERE a.city_id = :user_city_id
  AND {PUBLIC_ARENA_VISIBLE_SQL}
  AND s.status = :st
  AND s.kind IN ('public_skate', 'open_ice')
  AND s.starts_at_utc >= :starts_at
  AND s.starts_at_utc < :ends_at
  AND (s.valid_until IS NULL OR s.valid_until >= :starts_at)
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


def _sessions_block_title(sessions: list[Mapping[str, Any]], *, now: datetime) -> str:
    if not sessions:
        return "Лёд сегодня"
    all_today = True
    for row in sessions:
        tz_name = str(row.get("city_timezone") or DEFAULT_TIMEZONE)
        local_date = row.get("local_date")
        if not isinstance(local_date, date):
            continue
        if local_date != _local_today(tz_name, now):
            all_today = False
            break
    return "Лёд сегодня" if all_today else "Ближайший лёд"


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
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    today = now.astimezone(tz).date()
    items: list[dict[str, str]] = []
    for offset in range(7):
        d = today + timedelta(days=offset)
        wd = _WEEKDAYS_SHORT[d.weekday()]
        label = f"{wd}, {d.day} {_MONTHS_SHORT[d.month - 1]}"
        items.append({"date": d.isoformat(), "label": label, "href": f"/?when=day&d={d.isoformat()}"})
    return items


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


def _upcoming_more_href(city: Mapping[str, Any], when_key: str) -> str:
    slug = str(city["slug"])
    if when_key == "weekend":
        return f"/c/{slug}?when=weekend"
    if when_key in ("today", "tomorrow"):
        return f"/ice/{slug}/today"
    return f"/c/{slug}?when={when_key}"


def build_city_layout(catalog_cities: list[dict[str, Any]]) -> dict[str, Any]:
    by_cities = [c for c in catalog_cities if str(c.get("country") or "").upper() == "BY"]
    ru_cities = [c for c in catalog_cities if str(c.get("country") or "").upper() == "RU"]
    minsk = next((c for c in by_cities if str(c.get("slug")) == _MINSK_SLUG), None)
    oblast_centers = [
        c
        for c in by_cities
        if str(c.get("slug")) in _OBLAST_CENTER_SLUGS and str(c.get("slug")) != _MINSK_SLUG
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
            continue
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
        title = f'{pt["name"]} — {pt["session_count"]} {plural_ru(int(pt["session_count"]), "сеанс", "сеанса", "сеансов")}'
        parts.append(
            f'<a href="/c/{_esc(pt["slug"])}"><title>{_esc(title)}</title>'
            f'<circle cx="{float(pt["x"]):.1f}" cy="{float(pt["y"]):.1f}" r="{float(pt["r"]):.1f}"/></a>'
        )
    parts.append("</g>")
    parts.append('<g font-size="14" font-weight="600" fill="#0d1b26">')
    for pt in points:
        if not pt.get("is_oblast_center"):
            continue
        parts.append(f'<text x="{float(pt["x"]):.1f}" y="{float(pt["y"]) - float(pt["r"]) - 6:.1f}">{_esc(pt["name"])}</text>')
    parts.append("</g></svg>")
    return "".join(parts)


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

    now = now or _utc_now()
    when_key, period_start, period_end = _parse_when(when, now)
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    show_day_picker = False
    if when_key == "day":
        parsed_day = _parse_day_date(day_date, now)
        raw_day = (day_date or "").strip()
        if not raw_day:
            show_day_picker = True
        target_date = parsed_day or now.astimezone(tz).date()
        period_start = datetime.combine(target_date, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
        period_end = datetime.combine(target_date + timedelta(days=1), time(0, 0), tzinfo=tz).astimezone(timezone.utc)

    cities = await _public_cities(session)
    empty: dict[str, Any] = {
        "cities": [],
        "city_groups": [],
        "city_layout": {"minsk": None, "oblast_centers": [], "regions": [], "ru_cities": []},
        "sessions": [],
        "sessions_title": t("home.upcoming.city", city=""),
        "show_upcoming_block": False,
        "show_day_picker": show_day_picker,
        "day_picker": _build_day_picker(now) if show_day_picker else [],
        "country": "BY",
        "now": now,
        "when_key": when_key,
        "period_start": period_start,
        "period_end": period_end,
        "user_city": None,
        "map_points": [],
        "map_svg": "",
        "chips": {"hockey": False, "rollerski": False, "first_time_href": "/first-time"},
        "trainers": [],
        "shop_count": 0,
    }
    if not cities:
        return empty

    city_ids = [int(c["id"]) for c in cities]
    stats_rows = (
        await session.execute(
            _CITY_STATS_SQL,
            {
                "city_ids": city_ids,
                "starts_at": period_start,
                "ends_at": period_end,
                "st": STATUS_ACTIVE,
                **public_scope_params(),
            },
        )
    ).mappings().all()

    catalog_cities: list[dict[str, Any]] = []
    for row in stats_rows:
        catalog_cities.append(
            {
                "id": int(row["id"]),
                "name": str(row["name"]),
                "country": str(row["country"] or ""),
                "slug": city_slug(str(row["name"])),
                "place_count": int(row["place_count"] or 0),
                "ice_place_count": int(row["ice_place_count"] or 0),
                "shop_count": int(row["shop_count"] or 0),
                "session_count": int(row["session_count"] or 0),
                "arenas_with_sessions": int(row["arenas_with_sessions"] or 0),
                "avg_lat": row.get("avg_lat"),
                "avg_lon": row.get("avg_lon"),
                "sole_place_slug": row.get("sole_place_slug"),
            }
        )

    city_groups = group_catalog_cities_by_country(catalog_cities)
    catalog_cities = [city for _, group in city_groups for city in group]
    public_slug_set = {str(c["slug"]) for c in catalog_cities}
    user_city = _resolve_user_city(catalog_cities, user_city_slug=user_city_slug, public_slug_set=public_slug_set)
    user_city_id = int(user_city["id"]) if user_city else None
    show_upcoming_block = bool(
        user_city and int(user_city.get("arenas_with_sessions") or 0) >= _MIN_PLACES_FOR_UPCOMING_BLOCK
    )

    sessions: list[dict[str, Any]] = []
    if show_upcoming_block and user_city_id is not None:
        upcoming = (
            await session.execute(
                _USER_UPCOMING_SQL,
                {
                    "user_city_id": user_city_id,
                    "starts_at": period_start,
                    "ends_at": period_end,
                    "st": STATUS_ACTIVE,
                    "lim": _USER_UPCOMING_LIMIT,
                    **public_scope_params(),
                },
            )
        ).mappings().all()
        sessions = [dict(r) for r in upcoming]

    hockey_row = (
        await session.execute(
            _HOCKEY_FUTURE_SQL,
            {"now": now, "st": STATUS_ACTIVE, "ice_countries": list(ice_discovery_countries()), **public_scope_params()},
        )
    ).mappings().first()
    has_hockey = bool(hockey_row and hockey_row.get("has_hockey"))

    trainers: list[dict[str, Any]] = []
    shop_count = 0
    if user_city_id is not None:
        shop_count = int(user_city.get("shop_count") or 0) if user_city else 0
        trainer_rows = (
            await session.execute(_HOME_TRAINERS_SQL, {"city_id": user_city_id})
        ).mappings().all()
        for row in trainer_rows:
            role = specialist_role_display(str(row.get("specialist_role") or ""))
            arena_slug = str(row.get("arena_slug") or "").strip()
            arena_name = str(row.get("arena_name") or "").strip()
            trainers.append(
                {
                    "id": int(row["id"]),
                    "name": str(row.get("full_name") or "").strip() or "Тренер",
                    "specialization": role,
                    "arena_name": arena_name,
                    "href": f"/t/{city_slug(str(row.get('city_name') or ''))}/{int(row['id'])}"
                    if arena_slug
                    else f"/trainers",
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
            "href": _user_city_button_href(user_city),
            "when_phrase": _period_when_phrase(when_key),
            "show_upcoming_block": show_upcoming_block,
            "upcoming_more_href": _upcoming_more_href(user_city, when_key),
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
        "user_city": user_city_vm,
        "user_city_id": user_city_id,
        "user_city_slug": str(user_city["slug"]) if user_city else _MINSK_SLUG,
        "map_points": map_points,
        "map_svg": render_map_svg(map_points),
        "chips": {
            "hockey": has_hockey,
            "rollerski": False,
            "first_time_href": "/first-time",
            "hockey_href": f"/c/{user_city_vm['slug']}?kind=ohm" if user_city_vm and has_hockey else None,
        },
        "trainers": trainers,
        "shop_count": shop_count,
    }


def _city_row(city: Mapping[str, Any]) -> str:
    name = str(city["name"])
    slug = str(city["slug"])
    places = int(city["place_count"] or 0)
    sessions = int(city["session_count"] or 0)
    p_word = plural_ru(places, "место", "места", "мест")
    if sessions:
        s_word = plural_ru(sessions, "сеанс", "сеанса", "сеансов")
        stats = f"{places} {p_word} · {sessions} {s_word} сегодня"
    else:
        stats = f"{places} {p_word}"
    links = f'<a href="/c/{_esc(slug)}">Все места</a>'
    if sessions > 0:
        links += f' · <a href="/ice/{_esc(slug)}/today">Лёд сегодня</a>'
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
        f'<li><a href="{html_lib.escape(str(it.get("href") or ""), quote=True)}">'
        f'{_esc(it.get("label"))}</a></li>'
        for it in items
    )
    return f'<nav class="day-picker"><ul>{links}</ul></nav>'


def _chips_html(chips: Mapping[str, Any], *, user_city_slug: str) -> str:
    parts = [f'<a class="chip chip--active" href="/">{_esc(t("chip.ice"))}</a>']
    if chips.get("hockey") and chips.get("hockey_href"):
        parts.append(f'<a class="chip" href="{_esc(chips["hockey_href"])}">{_esc(t("chip.hockey"))}</a>')
    parts.append(
        f'<a class="chip" href="{_esc(chips.get("first_time_href") or "/first-time")}">'
        f'{_esc(t("chip.first_time"))}</a>'
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


def _cities_html(city_groups: list[tuple[str, list[Mapping[str, Any]]]]) -> str:
    if not city_groups:
        return '<p class="muted">Пока нет опубликованных городов.</p>'
    parts: list[str] = []
    for code, group in city_groups:
        label = _COUNTRY_SECTION_LABEL.get(code, code)
        parts.append(
            '<section class="country-group">'
            f'<h3 class="country-group__title">{_esc(label)}</h3>'
            '<ul class="cities">' + "".join(_city_row(c) for c in group) + "</ul></section>"
        )
    return "".join(parts)


def _session_row(row: Mapping[str, Any], *, now: datetime) -> str:
    """Рендеринг строки сеанса. TASK-210: projected сеансы — пунктир и метка 'обычно'."""
    city_name = str(row["city_name"])
    slug = str(row.get("arena_slug") or "").strip()
    arena_name = str(row["arena_name"])
    starts = str(row.get("starts_at_local") or "").strip()
    ends = str(row.get("ends_at_local") or "").strip()
    time_text = f"{starts}–{ends}" if starts and ends else (starts or ends or "—")
    day_label = _session_day_label(row, now=now)

    # TASK-210: projected сеансы с меткой
    schedule_basis = str(row.get("schedule_basis") or "live")
    is_projected = schedule_basis == "projected"

    if slug:
        href = place_path(city_name=city_name, slug=slug)
        if row.get("session_id"):
            href += f"?s={int(row['session_id'])}"
        name_html = f'<a href="{_esc(href)}">{_esc(arena_name)}</a>'
    else:
        name_html = _esc(arena_name)

    day_html = f'<span class="session__day">{_esc(day_label)}</span>' if day_label else ""

    # TASK-210: для projected — пунктир и метка
    session_class = "session"
    if is_projected:
        session_class += " session--projected"

    basis_note = ""
    if is_projected:
        basis_note = f' <span class="session__basis">{_esc(t("basis.projected"))}</span>'

    return (
        f'<li class="{session_class}">'
        f'{day_html}<span class="session__time">{_esc(time_text)}</span>'
        f'<span class="session__place">{name_html}</span>'
        f'<span class="session__city">{_esc(city_name)}</span>'
        f"{basis_note}"
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


def _when_label(key: str) -> str:
    """Подпись для переключателя времени."""
    labels = {
        "today": t("when.today"),
        "tomorrow": t("when.tomorrow"),
        "weekend": t("when.weekend"),
        "day": t("when.day"),
    }
    return labels.get(key, t("when.today"))


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

    country_codes = {str(c.get("country") or "BY").upper() for c in cities}
    # TASK-210: нейтральный заголовок (PDEC-019)
    page_h1 = "Где покататься"
    title = "Где покататься в Беларуси — катки и расписание массовых катаний | Glide"
    description = (
        "Где покататься: города с катками, расписание массовых катаний и ссылки на все места в каталоге Glide."
    )
    cities_html = _cities_html(city_groups)
    show_upcoming = bool(view.get("show_upcoming_block"))
    if show_upcoming and sessions:
        sessions_html = '<ul class="sessions">' + "".join(_session_row(s, now=now) for s in sessions) + "</ul>"
    elif show_upcoming:
        sessions_html = '<p class="muted">Ближайших сеансов пока нет — загляните в расписание по городу.</p>'
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

    user_city = view.get("user_city") if isinstance(view.get("user_city"), Mapping) else None
    chips = view.get("chips") if isinstance(view.get("chips"), Mapping) else {}
    day_picker = view.get("day_picker") if isinstance(view.get("day_picker"), list) else []
    map_svg = str(view.get("map_svg") or "")
    user_city_slug = str(view.get("user_city_slug") or _MINSK_SLUG)

    values = {
        "__LANG__": lang,
        "__OG_LOCALE__": og_locale,
        "__OG_TITLE__": _esc(title),
        "__OG_DESCRIPTION__": _esc(description),
        "__CANONICAL__": _esc(canonical_url),
        "__OG_IMAGE__": _esc(og_image_url),
        "__ROBOTS__": "index, follow",
        "__JSONLD__": _json_ld(view, canonical_url=canonical_url),
        "__CITIES__": cities_html,
        "__MAP_SVG__": map_svg,
        "__DAY_PICKER__": _day_picker_html(day_picker),
        "__CITY_BUTTON__": _user_city_button_html(user_city),
        "__CHIPS__": _chips_html(chips, user_city_slug=user_city_slug),
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
