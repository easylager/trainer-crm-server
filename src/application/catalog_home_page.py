"""Публичная главная каталога Glide — ``/`` (TASK-191-A, TASK-210-A)."""

from __future__ import annotations

import html as html_lib
import json
import logging
import math
import re
from datetime import date, datetime, time, timedelta, timezone
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
from src.application.ice_time_windows import (
    home_picker_dates,
    resolve_day_window,
    resolve_home_window,
    resolve_window,
)
from src.application.place_links import (
    catalog_start_param,
    join_public_origin,
    place_path,
    public_telegram_cta_url,
)
from src.shared.arena_schedule_mode import arena_schedule_mode_sql
from src.shared.catalog_sharpening import SHARPENING_MONTH_PARAM, SHARPENING_SECTION_SQL
from src.shared.catalog_visibility import CATALOG_LISTED_SQL
from src.shared.copy_ru import t
from src.shared.glide_city_cookie import normalize_glide_city_slug
from src.shared.public_display import format_clock, format_public_name
from src.shared.html_template import fill_placeholders, html_lang_for_country, json_for_script
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params
from src.shared.schedule_basis import SCHEDULE_BASIS_LIVE, normalize_schedule_basis

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
_MAP_VIEWBOX = (600, 520)
_MAP_PAD = 20.0
# Рамка карты в градусах; граница страны и точки городов проецируются одной функцией.
_BY_LON_MIN, _BY_LON_MAX = 23.0, 32.9
_BY_LAT_MIN, _BY_LAT_MAX = 51.1, 56.3
# Равнопромежуточная проекция с поправкой на широту (cos средней широты): на 53–54° N
# градус долготы почти вдвое короче градуса широты, иначе страна растянута по горизонтали.
_MAP_LON_K = math.cos(math.radians((_BY_LAT_MIN + _BY_LAT_MAX) / 2))
_MAP_SCALE = min(
    (_MAP_VIEWBOX[0] - 2 * _MAP_PAD) / ((_BY_LON_MAX - _BY_LON_MIN) * _MAP_LON_K),
    (_MAP_VIEWBOX[1] - 2 * _MAP_PAD) / (_BY_LAT_MAX - _BY_LAT_MIN),
)
_MAP_OX = (_MAP_VIEWBOX[0] - (_BY_LON_MAX - _BY_LON_MIN) * _MAP_LON_K * _MAP_SCALE) / 2
_MAP_OY = (_MAP_VIEWBOX[1] - (_BY_LAT_MAX - _BY_LAT_MIN) * _MAP_SCALE) / 2


def _map_project(lat: float, lon: float) -> tuple[float, float]:
    x = _MAP_OX + (lon - _BY_LON_MIN) * _MAP_LON_K * _MAP_SCALE
    y = _MAP_OY + (_BY_LAT_MAX - lat) * _MAP_SCALE
    return x, y


# Граница Беларуси: Natural Earth 1:10m (public domain), внешнее кольцо, упрощено
# Дугласом–Пекером до 0.025° (190 вершин) и спроецировано _map_project. Точки городов
# из _BY_CITY_ROWS проверены на попадание внутрь контура (tests/api/test_task224_home_map.py).
_MAP_BOUNDARY_LONLAT: tuple[tuple[float, float], ...] = (
    (23.606, 51.517), (23.532, 51.659), (23.560, 51.755), (23.629, 51.810), (23.595, 51.843),
    (23.676, 51.994), (23.637, 52.084), (23.512, 52.124), (23.488, 52.182), (23.190, 52.241),
    (23.166, 52.289), (23.392, 52.510), (23.869, 52.670), (23.922, 52.743), (23.911, 53.005),
    (23.859, 53.068), (23.894, 53.152), (23.801, 53.242), (23.591, 53.611), (23.486, 53.939),
    (23.627, 53.898), (24.170, 53.959), (24.257, 53.894), (24.378, 53.887), (24.667, 53.994),
    (24.806, 53.975), (24.782, 54.093), (24.822, 54.135), (25.072, 54.132), (25.157, 54.176),
    (25.206, 54.257), (25.370, 54.248), (25.459, 54.299), (25.554, 54.231), (25.502, 54.222),
    (25.516, 54.145), (25.763, 54.156), (25.789, 54.236), (25.696, 54.321), (25.529, 54.321),
    (25.613, 54.422), (25.631, 54.508), (25.740, 54.569), (25.721, 54.767), (25.778, 54.805),
    (25.783, 54.870), (25.870, 54.939), (26.139, 54.969), (26.264, 55.140), (26.601, 55.121),
    (26.657, 55.215), (26.801, 55.273), (26.450, 55.327), (26.543, 55.460), (26.532, 55.516),
    (26.596, 55.568), (26.616, 55.688), (26.823, 55.706), (26.981, 55.827), (27.593, 55.794),
    (27.645, 55.923), (27.927, 56.109), (28.111, 56.157), (28.311, 56.043), (28.390, 56.089),
    (28.611, 56.088), (28.732, 55.947), (28.831, 55.938), (29.031, 56.024), (29.396, 55.948),
    (29.444, 55.907), (29.384, 55.880), (29.344, 55.787), (29.481, 55.681), (29.948, 55.848),
    (30.106, 55.822), (30.200, 55.858), (30.469, 55.794), (30.481, 55.754), (30.587, 55.718),
    (30.596, 55.665), (30.694, 55.652), (30.742, 55.594), (30.848, 55.611), (30.913, 55.572),
    (30.919, 55.492), (30.881, 55.451), (30.918, 55.388), (30.794, 55.286), (30.960, 55.163),
    (31.006, 55.023), (30.913, 55.025), (30.936, 54.973), (30.815, 54.928), (30.826, 54.877),
    (30.763, 54.802), (31.168, 54.622), (31.065, 54.492), (31.168, 54.467), (31.285, 54.347),
    (31.325, 54.229), (31.823, 54.053), (31.838, 53.962), (31.745, 53.795), (32.106, 53.807),
    (32.462, 53.707), (32.488, 53.670), (32.399, 53.635), (32.411, 53.582), (32.577, 53.486),
    (32.701, 53.462), (32.717, 53.335), (32.455, 53.300), (32.479, 53.275), (32.424, 53.204),
    (32.117, 53.081), (31.796, 53.112), (31.756, 53.187), (31.614, 53.210), (31.379, 53.182),
    (31.364, 53.089), (31.247, 53.014), (31.561, 52.787), (31.570, 52.725), (31.481, 52.682),
    (31.629, 52.548), (31.551, 52.512), (31.608, 52.372), (31.567, 52.311), (31.699, 52.251),
    (31.682, 52.202), (31.763, 52.150), (31.764, 52.101), (31.383, 52.117), (31.229, 52.038),
    (31.096, 52.080), (30.919, 52.059), (30.941, 51.994), (30.742, 51.898), (30.515, 51.604),
    (30.523, 51.563), (30.584, 51.542), (30.563, 51.522), (30.618, 51.467), (30.588, 51.427),
    (30.646, 51.367), (30.551, 51.237), (30.355, 51.305), (30.320, 51.402), (30.149, 51.484),
    (29.829, 51.430), (29.638, 51.491), (29.466, 51.385), (29.320, 51.366), (29.228, 51.456),
    (29.227, 51.519), (29.160, 51.603), (29.063, 51.631), (28.981, 51.569), (28.800, 51.533),
    (28.729, 51.401), (28.637, 51.450), (28.604, 51.554), (28.461, 51.572), (28.334, 51.528),
    (28.210, 51.652), (28.071, 51.558), (27.831, 51.613), (27.793, 51.517), (27.714, 51.464),
    (27.664, 51.493), (27.693, 51.589), (27.477, 51.624), (27.267, 51.587), (27.277, 51.651),
    (27.189, 51.664), (27.151, 51.757), (26.855, 51.749), (26.666, 51.801), (26.446, 51.806),
    (26.408, 51.851), (25.768, 51.929), (25.138, 51.949), (24.722, 51.882), (24.391, 51.880),
    (24.244, 51.718), (23.981, 51.586), (23.750, 51.644), (23.629, 51.629), (23.594, 51.605),
)
_MAP_COUNTRY_PATH = (
    "M" + " L".join(f"{_map_project(lat, lon)[0]:.1f},{_map_project(lat, lon)[1]:.1f}" for lon, lat in _MAP_BOUNDARY_LONLAT) + " Z"
)
# Куда ставить подпись областного центра, чтобы она не легла на соседние точки.
_MAP_LABEL_SIDE: dict[str, str] = {
    "minsk": "above",
    "grodno": "above",
    "vitebsk": "above",
    "brest": "below",
    "gomel": "below",
    "mogilev": "right",
}
# Зона нажатия ≥ 44px на экране: svg шириной ~360px при viewBox 600 → масштаб 0.6,
# радиус 37 единиц даёт ~44px диаметра. Малые города — 28 (их точки стоят плотнее).
_MAP_TAP_RADIUS_MAJOR = 37.0
_MAP_TAP_RADIUS_MINOR = 28.0

# Одна строка на арену: места считаем в Python, сеансы — тем же предикатом, что «лёд сегодня».
# Окно (:starts_at…:ends_at) и горизонт блока «Ближайшие» (:horizon_end) режутся здесь.
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
           COUNT(DISTINCT s.id) AS horizon_sessions,
           (
               SELECT m.variants
               FROM media m
               WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
               ORDER BY m.sort_order, m.id
               LIMIT 1
           ) AS photo_variants,
           (
               SELECT m.width
               FROM media m
               WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
               ORDER BY m.sort_order, m.id
               LIMIT 1
           ) AS photo_width,
           (
               SELECT COALESCE(m.display_tone, false)
               FROM media m
               WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
               ORDER BY m.sort_order, m.id
               LIMIT 1
           ) AS display_tone
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

# TASK-224: факты для плитки города и строки «ваш город» — одним запросом на все города.
# Ближайший сеанс МК и ближайший ОХМ (в горизонте недели).
_CITY_NEXT_SQL = text(
    f"""
SELECT DISTINCT ON (a.city_id, (s.kind = 'hockey_practice'))
       a.city_id,
       (s.kind = 'hockey_practice') AS is_ohm,
       a.name AS arena_name,
       s.local_date,
       s.starts_at_local,
       s.starts_at_utc,
       COALESCE(p.timezone, '{DEFAULT_TIMEZONE}') AS tz
{ICE_CITY_DAY_FROM_SQL}
WHERE a.city_id = ANY(:city_ids)
  AND {PUBLIC_ARENA_VISIBLE_SQL}
  AND {arena_schedule_mode_sql()} <> 'season_closed'
  AND s.status = :st
  AND s.kind IN ('public_skate', 'open_ice', 'hockey_practice')
  AND s.starts_at_utc > :now
  AND (s.kind = 'hockey_practice' OR s.starts_at_utc < :horizon_end)
  AND (s.valid_until IS NULL OR s.valid_until >= :now)
ORDER BY a.city_id, (s.kind = 'hockey_practice'), s.starts_at_utc, s.id
"""
)

# Что вообще есть в городе: раздел «Заточка», тренеры в каталоге. Будущий ОХМ — из _CITY_NEXT_SQL.
_CITY_FLAGS_SQL = text(
    f"""
SELECT c.id,
       EXISTS (
         SELECT 1 FROM arenas a
         LEFT JOIN arena_profiles p ON p.arena_id = a.id
         WHERE a.city_id = c.id AND {SHARPENING_SECTION_SQL}
       ) AS has_sharpening,
       EXISTS (
         SELECT 1 FROM trainer_cities tc
         JOIN trainers t ON t.id = tc.trainer_id
         WHERE tc.city_id = c.id AND {CATALOG_LISTED_SQL}
       ) AS has_trainers
FROM cities c
WHERE c.id = ANY(:city_ids)
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


def _map_dot_radius(place_count: int) -> float:
    return float(min(10, max(5, place_count)))


def map_point_inside_country(x: float, y: float) -> bool:
    """Точка (в координатах viewBox) внутри контура страны — проверка данных карты в тестах."""
    poly = [_map_project(lat, lon) for lon, lat in _MAP_BOUNDARY_LONLAT]
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


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
    """Источник сеанса в публичный текст не попадает. Поле в данных остаётся."""
    del basis
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
        return f"/c/{slug}?t=ice&w=today"
    return None


def _city_list_when(when: str | None, when_key: str, *, selected_day: date | None, today: date) -> str | None:
    """Окно, которое плитка города несёт в список. Только явно выбранное: без ``when``
    главная показывает умный дефолт, и плитка по-прежнему ведёт на страницу города.

    Выбрал «Завтра» — плитка «24 сеанса завтра» открывает именно эти сеансы, а не
    город с другим окном. Произвольную дату список не понимает — тогда без окна.
    """
    if not (when or "").strip():
        return None
    if when_key in ("today", "tomorrow", "weekend"):
        return when_key
    if when_key == "day" and selected_day == today:
        return "today"
    if when_key == "day" and selected_day == today + timedelta(days=1):
        return "tomorrow"
    return None


def _city_href(city: Mapping[str, Any], *, when: str | None, default: str) -> str:
    if when and int(city.get("session_count") or 0) > 0:
        return f"/c/{city['slug']}?t=ice&w={when}"
    return default


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


def home_map_legend_labels(when_key: str) -> tuple[str, str]:
    """Подписи легенды карты главной — в такт фильтру «Сегодня / Завтра / Выходные»."""
    key = when_key if when_key in ("today", "tomorrow", "weekend") else "today"
    return t(f"home.map.legend_on.{key}"), t(f"home.map.legend_off.{key}")


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
                "has_ohm": bool(city.get("has_ohm")),
                "place_count": int(city.get("place_count") or 0),
            }
        )
    return points


def _map_label_pos(pt: Mapping[str, Any]) -> tuple[float, float, str]:
    x, y, r = float(pt["x"]), float(pt["y"]), float(pt["r"])
    side = _MAP_LABEL_SIDE.get(str(pt.get("slug") or ""), "above")
    ring = 24.0 if pt.get("is_minsk") else (8.0 if pt.get("has_ohm") else 0.0)
    if side == "below":
        return x, y + r + ring + 20.0, "middle"
    if side == "right":
        return x + r + ring + 8.0, y + 6.0, "start"
    return x, y - r - ring - 8.0, "middle"


def render_map_svg(points: list[Mapping[str, Any]]) -> str:
    """Карта страны: точка = город (ссылка на /c/{slug}), кольцо = есть ОХМ, подпись у областных центров.

    У каждой точки прозрачный круг-зона нажатия (см. _MAP_TAP_RADIUS_*): сами точки малы,
    а карта должна работать пальцем. Областные центры рисуются последними, их зона шире
    и накрывает соседей (Раубичи в 18 единицах от Минска при радиусе 37). Какой город
    откроется, решает скрипт страницы: ближайший центр внутри своей зоны, не верхняя ссылка.
    ``<title>`` нет — иначе браузер показывает название верхней ссылки, то есть Минск.
    """
    parts = [
        '<svg class="home-map" viewBox="0 0 600 520" role="img" aria-label="',
        _esc(t("home.map.aria")),
        '">',
        f'<path d="{_MAP_COUNTRY_PATH}" fill="#12232f" stroke="var(--g-dark-line)" stroke-width="2" stroke-linejoin="round"/>',
    ]
    minsk = next((p for p in points if p.get("is_minsk")), None)
    if minsk:
        parts.append(
            f'<circle cx="{float(minsk["x"]):.1f}" cy="{float(minsk["y"]):.1f}" r="{float(minsk["r"]) + 24:.1f}" '
            f'fill="var(--g-accent)" fill-opacity="0.14"/>'
        )
    ordered = sorted(points, key=lambda p: (bool(p.get("is_oblast_center")), bool(p.get("is_minsk"))))
    parts.append('<g class="home-map__cities">')
    for pt in ordered:
        x, y, r = float(pt["x"]), float(pt["y"]), float(pt["r"])
        tap = _MAP_TAP_RADIUS_MAJOR if pt.get("is_oblast_center") else _MAP_TAP_RADIUS_MINOR
        ring = (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 8:.1f}" fill="none" stroke="var(--g-accent)" '
            'stroke-width="2" stroke-dasharray="3 4"/>'
            if pt.get("has_ohm")
            else ""
        )
        parts.append(
            f'<a href="/c/{_esc(pt["slug"])}" class="home-map__city" aria-label="{_esc(pt["name"])}">'
            f'<circle class="home-map__tap" cx="{x:.1f}" cy="{y:.1f}" r="{tap:.1f}" fill="transparent"/>'
            f'<g class="home-map__vis">'
            f"{ring}"
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{"var(--g-accent)" if int(pt.get("session_count") or 0) else "#4a6273"}"/>'
            f"</g></a>"
        )
    parts.append("</g>")
    parts.append('<g font-size="20" font-weight="600" fill="var(--g-on-photo)" pointer-events="none">')
    for pt in ordered:
        if not pt.get("is_oblast_center"):
            continue
        lx, ly, anchor = _map_label_pos(pt)
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}">{_esc(pt["name"])}</text>')
    parts.append("</g></svg>")
    return "".join(parts)


def _fold_arena_rows(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
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
                "photo_key": "",
                "photo_variants": {},
                "display_tone": False,
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
        window_n = int(row.get("window_sessions") or 0)
        horizon_n = int(row.get("horizon_sessions") or 0)
        city["session_count"] += window_n
        if window_n > 0:
            city["arenas_with_sessions"] += 1
        if horizon_n > 0:
            city["horizon_arenas_with_sessions"] += 1
        raw_variants = row.get("photo_variants")
        if isinstance(raw_variants, str):
            raw_variants = json.loads(raw_variants)
        variants = raw_variants if isinstance(raw_variants, Mapping) else {}
        photo_key = str(variants.get("card") or "").strip()
        # Фото города — только каток: магазин на плитке города («Спортмастер» у Бобруйска) путает.
        if photo_key and str(row.get("venue_type") or "ice") in ("ice", "outdoor"):
            # Фото города — самое крупное фото крытого катка; уличный каток и магазин — запасные.
            rank = (str(row.get("venue_type") or "ice") == "ice", int(row.get("photo_width") or 0))
            if not city["photo_key"] or rank > city.get("_photo_rank", (False, -1)):
                city["photo_key"] = photo_key
                city["photo_hero_key"] = str(variants.get("hero") or photo_key)
                city["photo_variants"] = dict(variants)
                city["display_tone"] = bool(row.get("display_tone"))
                city["_photo_rank"] = rank
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


def _next_fact(row: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    """Ближайший сеанс города: ЧЧ:ММ, день по-человечески («завтра», «сб»), дата."""
    local_date = row.get("local_date")
    if isinstance(local_date, datetime):
        local_date = local_date.date()
    tz_name = str(row.get("tz") or DEFAULT_TIMEZONE)
    today = _local_today(tz_name, now)
    hhmm = format_clock(str(row.get("starts_at_local") or ""))
    day_label = ""
    is_today = False
    is_weekend = False
    if isinstance(local_date, date):
        is_today = local_date == today
        is_weekend = local_date.weekday() in (5, 6)
        relative = human_date(local_date, today=today)
        day_label = relative if relative in ("сегодня", "завтра") else _WEEKDAYS_SHORT[local_date.weekday()]
    return {
        "local_date": local_date.isoformat() if isinstance(local_date, date) else None,
        "hhmm": hhmm,
        "arena_name": str(row.get("arena_name") or ""),
        "day_label": day_label,
        "is_today": is_today,
        "is_weekend": is_weekend,
    }


async def _attach_city_facts(
    session: AsyncSession,
    cities: list[dict[str, Any]],
    *,
    now: datetime,
    horizon_end: datetime,
) -> None:
    """Дописывает в каждый город ``next_skate``, ``next_ohm``, ``has_ohm``, ``has_sharpening``, ``has_trainers``.

    Два запроса на все города сразу — бюджет SQL главной не зависит от числа городов.
    """
    for city in cities:
        city.setdefault("next_skate", None)
        city.setdefault("next_ohm", None)
        city.setdefault("has_ohm", False)
        city.setdefault("has_sharpening", False)
        city.setdefault("has_trainers", False)
    if not cities:
        return
    by_id = {int(c["id"]): c for c in cities}
    city_ids = list(by_id)
    next_rows = (
        (
            await session.execute(
                _CITY_NEXT_SQL,
                {
                    "city_ids": city_ids,
                    "now": now,
                    "horizon_end": horizon_end,
                    "st": STATUS_ACTIVE,
                    **public_scope_params(),
                },
            )
        )
        .mappings()
        .all()
    )
    for row in next_rows:
        city = by_id.get(int(row["city_id"]))
        if city is None:
            continue
        fact = _next_fact(row, now=now)
        if row.get("is_ohm"):
            city["next_ohm"] = fact
            city["has_ohm"] = True
        else:
            city["next_skate"] = fact
    flag_rows = (
        (
            await session.execute(
                _CITY_FLAGS_SQL,
                {
                    "city_ids": city_ids,
                    SHARPENING_MONTH_PARAM: now.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).month,
                    **public_scope_params(),
                },
            )
        ).mappings().all()
    )
    for row in flag_rows:
        city = by_id.get(int(row["id"]))
        if city is None:
            continue
        city["has_sharpening"] = bool(row.get("has_sharpening"))
        city["has_trainers"] = bool(row.get("has_trainers"))


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
        "selected_date": selected_day.isoformat() if selected_day else None,
        "user_city": None,
        "user_city_id": None,
        "user_city_slug": _MINSK_SLUG,
        "map_points": [],
        "map_svg": "",
        "chips": {
            "hockey": False,
            "rollerski": False,
            "first_time_href": None,
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

    catalog_cities = _fold_arena_rows(list(stats_rows))

    city_groups = group_catalog_cities_by_country(catalog_cities)
    catalog_cities = [city for _, group in city_groups for city in group]
    await _attach_city_facts(
        session,
        catalog_cities,
        now=now,
        horizon_end=horizon_end,
    )
    public_slug_set = {str(c["slug"]) for c in catalog_cities}
    user_city = _resolve_user_city(catalog_cities, user_city_slug=user_city_slug, public_slug_set=public_slug_set)
    user_city_id = int(user_city["id"]) if user_city else None
    # TASK-224: главная — только города. Блок «Ближайшие», тренеры и чипы переехали
    # на страницу города (/c/{slug}); здесь остаются факты для плитки.
    show_upcoming_block = False
    sessions: list[dict[str, Any]] = []
    trainers: list[dict[str, Any]] = []
    sessions_title = ""
    shop_count = int(user_city.get("shop_count") or 0) if user_city else 0

    has_hockey = any(bool(c.get("has_ohm")) for c in catalog_cities)
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
            "shop_count": int(user_city.get("shop_count") or 0),
            "next_skate": user_city.get("next_skate"),
            "next_ohm": user_city.get("next_ohm"),
            "has_ohm": bool(user_city.get("has_ohm")),
            "has_sharpening": bool(user_city.get("has_sharpening")),
            "has_trainers": bool(user_city.get("has_trainers")),
        }

    from src.application.selection_page import selection_path

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
        "city_when": _city_list_when(when, when_key, selected_day=selected_day, today=today),
        "selected_date": selected_day.isoformat() if selected_day else None,
        "user_city": user_city_vm,
        "user_city_id": user_city_id,
        "user_city_slug": str(user_city["slug"]) if user_city else _MINSK_SLUG,
        "map_points": map_points,
        "map_svg": render_map_svg(map_points),
        "chips": {
            "hockey": has_hockey,
            "rollerski": False,
            # /first-time появится в TASK-215. До тех пор чип не рисуем.
            "first_time_href": None,
            "hockey_href": (
                selection_path(city_name=str(user_city["name"]), venue=None, when=None, kind="ohm")
                if has_hockey and user_city
                else None
            ),
        },
        "trainers": trainers,
        "shop_count": shop_count,
    }


# ---------------------------------------------------------------------------
# Рендер главной (TASK-224): «ваш город» → карта → плитки городов → остальные по областям.
# Никаких фильтров и переключателей времени: главная выбирает город, город отвечает на
# потребность (design/prototypes/2026-10-09-city-router-home.html, экран 0).
# ---------------------------------------------------------------------------

_MAX_CITY_TILES = 10


def _rink_count_text(city: Mapping[str, Any]) -> str:
    rinks = int(city.get("ice_place_count") or 0)
    if rinks:
        return f"{rinks} {plural_ru(rinks, 'каток', 'катка', 'катков')}"
    places = int(city.get("place_count") or 0)
    return f"{places} {plural_ru(places, 'место', 'места', 'мест')}"


def _next_phrase(fact: Mapping[str, Any] | None) -> str:
    """«завтра 12:00» / «сб 13:00» / «сегодня 18:00» — без тегов, экранируется снаружи."""
    if not fact:
        return ""
    day = str(fact.get("day_label") or "").strip()
    hhmm = str(fact.get("hhmm") or "").strip()
    return " ".join(x for x in (day, hhmm) if x)


def _tile_rank(city: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -int(city.get("session_count") or 0),
        -int(city.get("horizon_arenas_with_sessions") or 0),
        0 if str(city.get("slug")) in _OBLAST_CENTER_SLUGS else 1,
        -int(city.get("place_count") or 0),
        str(city.get("name") or ""),
    )


def split_home_tiles(
    cities: list[Mapping[str, Any]], *, user_city_slug: str | None
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Какие города идут плитками, какие — в «ещё N городов по областям».

    Плитка — областной центр или город с сеансом на неделе; «ваш город» уже стоит
    карточкой сверху и плиткой не дублируется. Остальные — ссылками в раскрывашке.
    """
    by_cities = [c for c in cities if str(c.get("country") or "").upper() == "BY"]
    wanted = user_city_slug or ""
    tiles: list[Mapping[str, Any]] = []
    rest: list[Mapping[str, Any]] = []
    for city in sorted(by_cities, key=_tile_rank):
        slug = str(city.get("slug") or "")
        is_user = bool(wanted) and slug == wanted
        is_live = int(city.get("horizon_arenas_with_sessions") or 0) > 0 or int(city.get("session_count") or 0) > 0
        if is_user or ((slug in _OBLAST_CENTER_SLUGS or is_live) and len(tiles) < _MAX_CITY_TILES):
            tiles.append(city)
        else:
            rest.append(city)
    if wanted:
        tiles.sort(key=lambda c: 0 if str(c.get("slug") or "") == wanted else 1)
    if len(tiles) > _MAX_CITY_TILES:
        rest = tiles[_MAX_CITY_TILES:] + rest
        tiles = tiles[:_MAX_CITY_TILES]
    return tiles, rest


def _json_ld(view: Mapping[str, Any], *, canonical_url: str) -> str:
    elements = []
    for n, city in enumerate(view.get("cities") or []):
        slug = str(city["slug"])
        elements.append(
            {
                "@type": "ListItem",
                "position": n + 1,
                "name": city.get("name"),
                # У главной в каноническом адресе нет маркера /c/ — join_public_origin
                # вернул бы корневой путь, а разметка ждёт полный адрес.
                "url": f"{canonical_url.rstrip('/')}/c/{slug}",
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


def _counter_when_text(when_key: str, now: datetime) -> str:
    """В воскресенье до 18:00 окно «выходные» — это остаток сегодня, не суббота+воскресенье."""
    when_text = {
        "today": t("home.counter.when.today"),
        "tomorrow": t("home.counter.when.tomorrow"),
        "weekend": t("home.counter.when.weekend"),
        "day": t("home.counter.when.day"),
    }.get(when_key, t("home.counter.when.today"))
    if when_key == "weekend":
        local = now.astimezone(ZoneInfo(DEFAULT_TIMEZONE))
        if local.weekday() == 6 and local.time() < time(18, 0):
            return t("home.counter.when.today")
    return when_text


def _counter_text(
    session_count: int,
    city_count: int,
    when_key: str,
    *,
    now: datetime,
    city_name: str | None = None,
) -> str:
    when_text = _counter_when_text(when_key, now)
    sessions_word = plural_ru(session_count, "сеанс", "сеанса", "сеансов")
    if city_count == 1 and city_name:
        label = when_text[:1].lower() + when_text[1:]
        return f"{city_name} — {label} {session_count} {sessions_word}"
    return t(
        "home.counter",
        when=when_text,
        sessions=session_count,
        sessions_word=sessions_word,
        cities=city_count,
        cities_word=plural_ru(city_count, "городе", "городах", "городах"),
    )


def _today_done_text(cities: list[Mapping[str, Any]]) -> str:
    """«0 сеансов в 0 городах» — правда, но бесполезная: говорим, что сегодня льда нет,
    и где он завтра. Счётчик считает оставшиеся сеансы — «нет» верно и днём, и вечером."""
    tomorrow = [
        c
        for c in cities
        if isinstance(c.get("next_skate"), Mapping) and c["next_skate"].get("day_label") == "завтра"
    ]
    if not tomorrow:
        return t("home.counter.today_done_bare")
    return t(
        "home.counter.today_done",
        cities=len(tomorrow),
        cities_word=plural_ru(len(tomorrow), "городе", "городах", "городах"),
    )


def _b_home_city_card(user_city: Mapping[str, Any] | None, *, city_when: str | None = None) -> str:
    """Тёмная карточка «Ваш город»: сколько сеансов и ближайший, ниже — «Другой город»."""
    from src.application.catalog_icons import icon_svg

    if not user_city:
        return ""
    bits: list[str] = []
    sessions = int(user_city.get("session_count") or 0)
    nxt = user_city.get("next_skate") if isinstance(user_city.get("next_skate"), Mapping) else None
    if sessions:
        bits.append(f"{sessions}\u00a0{plural_ru(sessions, 'сеанс', 'сеанса', 'сеансов')}")
    if nxt and nxt.get("hhmm"):
        place = format_public_name(str(nxt.get("arena_name") or ""))
        when = f"в\u00a0{nxt['hhmm']}" if nxt.get("is_today") else _next_phrase(nxt)
        bits.append(f"ближайший {when}" + (f", {place}" if place else ""))
    ohm = user_city.get("next_ohm") if isinstance(user_city.get("next_ohm"), Mapping) else None
    if ohm and ohm.get("hhmm"):
        if ohm.get("is_today"):
            bits.append("ОХМ сегодня")
        elif ohm.get("is_weekend"):
            bits.append("ОХМ в выходные")
        else:
            bits.append(f"ОХМ {ohm.get('day_label') or ''}".strip())
    line = " · ".join(bits)
    href = user_city.get("href") or "/c/" + str(user_city.get("slug") or "")
    if href == f"/c/{user_city.get('slug')}":
        href = _city_href(user_city, when=city_when, default=href)
    line_html = f'<span class="b-city__line">{_esc(line)}</span>' if line else ""
    return (
        f'<a class="b-city" href="{_esc(href)}"><span class="b-city__body">'
        f'<span class="b-city__kicker">Ваш город</span>'
        f'<span class="b-city__name">{_esc(format_public_name(str(user_city.get("name") or "")))}</span>'
        f"{line_html}</span>{icon_svg('arrow')}</a>"
        f'<a class="b-link" href="#cities">{_esc(t("home.other_city"))}</a>'
    )


def _b_when_nav(view: Mapping[str, Any]) -> str:
    when_key = str(view.get("when_key") or "today")
    items = (
        ("today", t("when.today"), "/?when=today"),
        ("tomorrow", t("when.tomorrow"), "/?when=tomorrow"),
        ("weekend", t("when.weekend"), "/?when=weekend"),
        ("day", t("when.day"), "/?when=day"),
    )
    links = "".join(
        f'<a href="{href}"' + (' aria-current="true"' if key == when_key else "") + f">{_esc(label)}</a>"
        for key, label, href in items
    )
    nav = f'<nav class="b-when vt-when-strip" aria-label="Когда">{links}</nav>'
    if view.get("show_day_picker"):
        days = "".join(
            f'<a class="b-day" href="{_esc(item["href"])}"><span>{_esc(item["label"])}</span></a>'
            for item in view.get("day_picker") or []
        )
        nav += f'<nav class="b-days" aria-label="День">{days}</nav>'
    return nav


def _b_city_tile(city: Mapping[str, Any], *, when_key: str, city_when: str | None = None) -> str:
    from src.application.style_b import b_photo_url, tile_html

    name = format_public_name(str(city["name"]))
    sessions = int(city.get("session_count") or 0)
    if sessions:
        word = plural_ru(sessions, "сеанс", "сеанса", "сеансов")
        when = _period_when_phrase(when_key)
        head = f"{sessions}\u00a0{word}" + (f" {when}" if when and when_key != "today" else "")
        line = f"{head} · {_rink_count_text(city)}"
    elif city.get("next_skate"):
        line = f"ближайший {_next_phrase(city.get('next_skate'))}"
    else:
        line = _rink_count_text(city)
    if city.get("has_ohm"):
        line += " · ОХМ"
    variants = city.get("photo_variants")
    return tile_html(
        href=_city_href(city, when=city_when, default=f"/c/{city['slug']}"),
        name=name,
        line=line,
        photo_url=b_photo_url(city.get("photo_key")),
        photo_alt=name,
        toned=bool(city.get("display_tone")),
        photo_variants=variants if isinstance(variants, Mapping) else None,
    )


def _b_more_cities(rest: list[Mapping[str, Any]]) -> str:
    from src.application.catalog_icons import icon_svg

    if not rest:
        return ""
    buckets: dict[str, list[Mapping[str, Any]]] = {}
    for city in rest:
        region = _BY_REGIONS.get(str(city.get("slug") or ""), _OTHER_REGION)
        buckets.setdefault(region, []).append(city)
    lines: list[str] = []
    for region in sorted(buckets):
        names = ", ".join(
            f'<a href="/c/{_esc(c["slug"])}">{_esc(format_public_name(str(c["name"])))}</a>'
            for c in sorted(buckets[region], key=lambda c: str(c.get("name") or ""))
        )
        lines.append(f"<p><b>{_esc(region.replace(' область', ''))}:</b> {names}</p>")
    n = len(rest)
    summary = f"Ещё {n}\u00a0{plural_ru(n, 'город', 'города', 'городов')} по областям"
    return (
        f'<details class="b-details"><summary>{_esc(summary)}{icon_svg("down")}</summary>'
        f'<div class="b-details__body">{"".join(lines)}</div></details>'
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
    """Главная в стиле B (доска «B · Главная»).

    Герой с фото катка «вашего города», выбор времени, карточка «Ваш город», тёмная карта,
    сетка городов с фото и раскрывашка «ещё N городов по областям».
    """
    from src.application.public_web_cta import public_page_view_beacon_script
    from src.application.style_b import COMPONENTS_VERSION, STYLE_VERSION, TOKENS_VERSION, b_photo_url, brand_link, hero_html

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    cities = list(view.get("cities") or [])
    now = view.get("now") if isinstance(view.get("now"), datetime) else _utc_now()
    country = str(view.get("country") or "BY")
    lang, og_locale = html_lang_for_country(country)
    when_key = str(view.get("when_key") or "today")

    title = "Где покататься в Беларуси — катки и расписание массовых катаний | Glide"
    # Без счётчиков сеансов: поисковик держит описание неделями. Города — в порядке
    # главной (Минск первым, дальше по активности).
    by_names = [format_public_name(str(c.get("name") or "")) for c in cities if c.get("country") == "BY"]
    description = "Расписание массовых катаний на катках Беларуси: где покататься сегодня, завтра и в выходные."
    if by_names:
        rest = len(by_names) - 4
        listed = ", ".join(by_names[:4])
        if rest > 0:
            listed += f" и ещё {rest}\u00a0{plural_ru(rest, 'город', 'города', 'городов')}"
        description += f" {listed} — цены и адреса."
    user_city = view.get("user_city") if isinstance(view.get("user_city"), Mapping) else None
    user_slug = str(user_city.get("slug") or "") if user_city else None

    by_cities = [c for c in cities if c.get("country") == "BY"]
    with_sessions = [c for c in by_cities if int(c.get("session_count") or 0) > 0]
    total_sessions = sum(int(c.get("session_count") or 0) for c in with_sessions)
    sole_name = str(with_sessions[0].get("name") or "") if len(with_sessions) == 1 else None
    counter_text = _counter_text(total_sessions, len(with_sessions), when_key, now=now, city_name=sole_name)
    if when_key == "today" and not total_sessions:
        counter_text = _today_done_text(by_cities)
    counter_text = re.sub(r"(\d) ", "\\1\u00a0", counter_text)

    hero_city = user_city
    if not (hero_city and hero_city.get("photo_hero_key")):
        hero_city = next((c for c in by_cities if c.get("photo_hero_key")), None)
    hero_variants = hero_city.get("photo_variants") if hero_city else None
    if not isinstance(hero_variants, Mapping):
        hero_variants = None
    photo = b_photo_url(hero_city.get("photo_hero_key")) if hero_city else None
    hero = hero_html(
        title="Где покататься",
        title_break="покататься",
        kicker=_format_date_string(now).lower(),
        sub_html=_esc(counter_text),
        sub_class="counter",
        photo_url=photo,
        photo_alt=f"Каток, {format_public_name(str(hero_city.get('name') or ''))}" if hero_city else "",
        toned=bool(hero_city.get("display_tone")) if hero_city else False,
        # Тренеры — вторая аудитория: вход на их лендинг наверху, справа от марки (не только в подвале).
        bar_html=brand_link() + f'<a class="b-pill b-pill--end" href="{_esc(trainers_url)}">Для тренеров</a>',
        variant="tall",
        photo_variants=hero_variants,
    )

    tiles, rest = split_home_tiles(cities, user_city_slug=user_slug)
    if not cities:
        cities_html = f'<section class="b-sec"><p class="b-text">{_esc(t("home.cities_empty"))}</p></section>'
    else:
        city_when = view.get("city_when")
        grid = "".join(_b_city_tile(c, when_key=when_key, city_when=city_when) for c in tiles)
        head = {
            "today": "Сегодня в городах",
            "tomorrow": "Завтра в городах",
            "weekend": "В выходные в городах",
        }.get(when_key, "Города")
        cities_html = (
            f'<section class="b-sec" id="cities"><div class="b-sec__head"><h2 class="b-h2">{head}</h2></div>'
            f'<div class="b-grid2">{grid}</div>{_b_more_cities(rest)}</section>'
        )

    map_svg = str(view.get("map_svg") or "")
    map_html = ""
    if map_svg:
        legend_on, legend_off = home_map_legend_labels(when_key)
        map_html = (
            '<section class="b-sec"><div class="b-sec__head"><h2 class="b-h2">Лёд по всей Беларуси</h2></div>'
            f'<figure class="b-map">{map_svg}<figcaption class="b-map__legend">'
            f'<span><i></i>{_esc(legend_on)}</span>'
            f'<span class="off"><i></i>{_esc(legend_off)}</span></figcaption></figure></section>'
        )
    # TASK-278: «Открыть в Telegram» — плашкой внизу экрана, а не секцией в конце страницы.
    from src.application.style_b import (
        b_press_script_html,
        public_fonts_head_html,
        telegram_dock_html,
        telegram_dock_script_html,
    )

    cta = telegram_dock_html(cta_url, hint=t("tg.map_all"))
    values = {
        "__LANG__": lang,
        "__OG_LOCALE__": og_locale,
        "__OG_TITLE__": _esc(title),
        "__OG_DESCRIPTION__": _esc(description),
        "__CANONICAL__": _esc(canonical_url),
        "__OG_IMAGE__": _esc(og_image_url),
        "__ROBOTS__": _esc(robots),
        "__JSONLD__": _json_ld(view, canonical_url=canonical_url),
        "__PUBLIC_FONTS_HEAD__": public_fonts_head_html(),
        "__TOKENS_V__": TOKENS_VERSION,
        "__STYLE_V__": STYLE_VERSION,
        "__COMPONENTS_V__": COMPONENTS_VERSION,
        "__HERO__": hero,
        "__WHEN__": _b_when_nav(view),
        "__HERO_CITY__": _b_home_city_card(user_city, city_when=view.get("city_when")),
        "__MAP__": map_html,
        "__CITIES__": cities_html,
        "__CTA__": cta,
        "__B_PRESS_SCRIPT__": b_press_script_html(),
        "__TG_DOCK_SCRIPT__": telegram_dock_script_html(),
        "__FOOTER__": _esc(t("home.footer")),
        "__ELSEWHERE__": _b_elsewhere(cities),
        "__TRAINERS_URL__": _esc(trainers_url),
        "__PAGE_VIEW_BEACON__": public_page_view_beacon_script(surface="catalog_home"),
    }
    return fill_placeholders(template, values)


def _b_elsewhere(cities: list[Mapping[str, Any]]) -> str:
    ru = [c for c in cities if str(c.get("country") or "").upper() == "RU"]
    if not ru:
        return ""
    links = "".join(
        f'<a href="/c/{_esc(c["slug"])}">{_esc(format_public_name(str(c["name"])))}</a>'
        for c in sorted(ru, key=lambda c: str(c.get("name")))
    )
    return f'<span class="elsewhere">{links}</span>'


def catalog_home_og_image_url(base_url: str) -> str:
    path = "/logos/02-horizontal-full/glide-horizontal-teal-icon-black-text-on-white.png"
    base = (base_url or "").strip().rstrip("/")
    if base.lower().startswith("https://"):
        return f"{base}{path}"
    return path


def parse_city_session_count_from_home(html: str, city_name: str) -> int | None:
    """Тестовый хелпер: «N сеансов» в плитке города; город в раскрывашке — 0; нет на странице — None."""
    plain = html.replace("\u00a0", " ")
    for match in re.finditer(
        r'<a class="b-tile" href="[^"]+">.*?<span class="b-tile__name">([^<]+)</span>'
        r'<span class="b-tile__line">([^<]*)</span>',
        plain,
        re.S,
    ):
        if html_lib.unescape(match.group(1)) == city_name:
            found = re.search(r"(\d+)\s+сеанс", match.group(2))
            return int(found.group(1)) if found else 0
    hero = re.search(
        r'<a class="b-city" href="[^"]+">.*?<span class="b-city__name">([^<]+)</span>(.*?)</a>', plain, re.S
    )
    if hero and html_lib.unescape(hero.group(1)) == city_name:
        found = re.search(r"(\d+)\s+сеанс", re.sub(r"<[^>]+>", "", hero.group(2)))
        return int(found.group(1)) if found else 0
    more = re.search(r'<details class="b-details">(.*?)</details>', plain, re.S)
    if more and f">{html_lib.escape(city_name, quote=True)}</a>" in more.group(1):
        return 0
    return None
