"""Одно правило раздела «Заточка».

Место входит, если одновременно:
1. оно публично видно (``PUBLIC_ARENA_VISIBLE_SQL``);
2. оно не закрыто на сезон (``_is_closed_season_row``: месяцы сезона, не ``schedule_mode``);
3. ``skate_sharpening`` или ``blade_profiling`` равны true.

Тип места не важен. Прокат, ремонт и формовка сами по себе место в раздел не кладут.
Python-предикат и ``SHARPENING_SECTION_SQL`` обязаны давать один ответ на одних строках.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from src.application.arena_profile import is_in_season
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, arena_publicly_visible_row

#: Ключи, которые делают место «Заточкой». Порядок фиксирован: его сравнивают с фильтром.
SHARPENING_AMENITY_KEYS: tuple[str, ...] = ("skate_sharpening", "blade_profiling")

#: Имя bind-параметра месяца (1–12, Europe/Minsk) для ``SHARPENING_SECTION_SQL``.
SHARPENING_MONTH_PARAM = "sharpening_month"


def _amenity_is_true_sql(key: str) -> str:
    if key not in SHARPENING_AMENITY_KEYS:
        raise ValueError(f"not a sharpening amenity: {key}")
    return f"(p.amenities ->> '{key}') = 'true'"


SHARPENING_AMENITY_SQL = "(" + " OR ".join(_amenity_is_true_sql(key) for key in SHARPENING_AMENITY_KEYS) + ")"

# Зеркало is_in_season / _is_closed_season_row: нет границ — сезон круглый год.
# Диапазон через Новый год (ноябрь–март) открыт, когда месяц >= старта или месяц <= конца.
_SEASON_OPEN_SQL = f"""(
    p.season_start_month IS NULL
    OR p.season_end_month IS NULL
    OR (
        p.season_start_month <= p.season_end_month
        AND CAST(:{SHARPENING_MONTH_PARAM} AS int) BETWEEN p.season_start_month AND p.season_end_month
    )
    OR (
        p.season_start_month > p.season_end_month
        AND (
            CAST(:{SHARPENING_MONTH_PARAM} AS int) >= p.season_start_month
            OR CAST(:{SHARPENING_MONTH_PARAM} AS int) <= p.season_end_month
        )
    )
)"""

#: Полный предикат. Запрос соединяет ``arenas a``, ``arena_profiles p``, ``cities c``
#: и биндит ``public_scope_params()`` плюс ``:sharpening_month``.
SHARPENING_SECTION_SQL = f"{PUBLIC_ARENA_VISIBLE_SQL} AND {_SEASON_OPEN_SQL} AND {SHARPENING_AMENITY_SQL}"


def is_sharpening_section_keys(keys: tuple[str, ...] | list[str] | None) -> bool:
    """``?svc=service`` и ``?svc=sharpening`` — один и тот же раздел."""
    return tuple(str(key) for key in (keys or ()) if key) == SHARPENING_AMENITY_KEYS


def amenity_on(value: Any) -> bool:
    """JSONB true и строка ``true`` — одно и то же, как ``(amenities ->> k) = 'true'``."""
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def _amenities(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("amenities")
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _visibility_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Колонки ``PUBLIC_ARENA_VISIBLE_SQL`` под ``arena_publicly_visible_row``."""
    has_photo = row.get("has_photo")
    if has_photo is None and "has_media" in row:
        has_photo = row.get("has_media")
    status = row.get("profile_status") if "profile_status" in row else row.get("status")
    return {
        "is_active": row.get("is_active"),
        "is_confirmed": row.get("is_confirmed"),
        "city_is_active": row.get("city_is_active", True),
        "country": row.get("city_country") or row.get("country"),
        "profile_status": status,
        "created_by_trainer_id": row.get("created_by_trainer_id"),
        "has_photo": bool(has_photo),
    }


def row_closed_for_season(row: Mapping[str, Any], *, month: int) -> bool:
    """Python-зеркало ``_is_closed_season_row``: нет месяцев — не закрыто."""
    start = row.get("season_start_month")
    end = row.get("season_end_month")
    if start is None or end is None:
        return False
    return not is_in_season(start, end, int(month))


def row_in_sharpening_section(row: Mapping[str, Any], *, month: int) -> bool:
    """Место раздела «Заточка». Зеркало ``SHARPENING_SECTION_SQL``."""
    if not arena_publicly_visible_row(_visibility_row(row)):
        return False
    if row_closed_for_season(row, month=month):
        return False
    amenities = _amenities(row)
    return any(amenity_on(amenities.get(key)) for key in SHARPENING_AMENITY_KEYS)
