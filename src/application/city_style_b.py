"""Три страницы города стиля B. Вариант — по числу катков и schedule_mode, не по имени.

«Неделя» и «Лёд рядом» — по одному запросу. Нет строки — нет блока.
"""

from __future__ import annotations

import html as html_lib
import json
from datetime import date, datetime, timedelta
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_city_day import DEFAULT_TIMEZONE
from src.application.style_b import b_photo_url
from src.application.week_grid import collapse_even_grid
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params
from src.shared.public_display import format_clock

VARIANT_MANY = "many"
VARIANT_ONE = "one"
VARIANT_PHONE = "phone"

_WEEK_SQL = text(
    f"""
    /* task246-week */
    SELECT s.id, s.local_date, s.starts_at_local, s.ends_at_local,
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
    , ph AS (
        SELECT DISTINCT ON (a.city_id) a.city_id, m.variants AS photo_variants, m.display_tone
        FROM arenas a
        LEFT JOIN arena_profiles p ON p.arena_id = a.id
        JOIN cities c ON c.id = a.city_id
        JOIN media m ON m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
        WHERE {PUBLIC_ARENA_VISIBLE_SQL}
          AND COALESCE(a.venue_type, 'ice') IN ('ice', 'outdoor')
        ORDER BY a.city_id, m.sort_order, m.id
    )
    SELECT points.city_id, points.name, points.rink_count,
           nxt.local_date, nxt.starts_at_local, ph.photo_variants, ph.display_tone,
           (6371 * acos(LEAST(1.0, GREATEST(-1.0,
              cos(radians(:olat)) * cos(radians(points.lat))
              * cos(radians(points.lon) - radians(:olon))
              + sin(radians(:olat)) * sin(radians(points.lat))
           )))) AS distance_km
    FROM points
    JOIN nxt ON nxt.city_id = points.city_id
    LEFT JOIN ph ON ph.city_id = points.city_id
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


def city_origin(places: list[Mapping[str, Any]]) -> tuple[float, float] | None:
    lats = [float(p["latitude"]) for p in places if p.get("latitude") is not None and p.get("longitude") is not None]
    lons = [float(p["longitude"]) for p in places if p.get("latitude") is not None and p.get("longitude") is not None]
    if not lats:
        return None
    return sum(lats) / len(lats), sum(lons) / len(lons)


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


def week_days(rows: list[Mapping[str, Any]], *, today: date) -> list[dict[str, Any]]:
    by_day: dict[date, list[dict[str, Any]]] = {}
    for row in rows:
        day = _as_date(row.get("local_date"))
        clock = _clock(row.get("starts_at_local"))
        if day is None or not clock:
            continue
        sid = row.get("id")
        by_day.setdefault(day, []).append(
            {"time": clock, "id": int(sid) if sid is not None else None},
        )
    out: list[dict[str, Any]] = []
    for day in sorted(by_day):
        sessions = sorted(by_day[day], key=lambda item: item["time"])
        times = [item["time"] for item in sessions]
        out.append(
            {
                "date": day,
                "weekend": day.weekday() >= 5,
                "label": "сегодня" if day == today else "завтра" if day == today + timedelta(days=1) else _weekday(day),
                "times": times,
                "sessions": sessions,
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
        variants = row.get("photo_variants")
        if isinstance(variants, str):
            variants = json.loads(variants)
        variants = variants if isinstance(variants, Mapping) else {}
        out.append(
            {
                "name": str(row["name"]),
                "photo_url": b_photo_url(variants.get("card")),
                "display_tone": bool(row.get("display_tone")),
                "rink_count": int(row["rink_count"] or 0),
                "when": when,
                "time": _clock(row.get("starts_at_local")),
                "distance": _km(float(row["distance_km"] or 0)),
            }
        )
    return out


