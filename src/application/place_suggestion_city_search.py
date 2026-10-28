"""
City picker for a place suggestion (PDEC-028): our public cities first, then Nominatim.

A person may suggest a place in a city we don't have yet, so the picker falls back to the
geocoder. Nominatim's usage policy allows at most one request per second and asks for
caching, so: an in-process 1-hour cache and a 1 req/s throttle — over the limit the
geocoder part is simply empty, never an error. Its failures are swallowed the same way.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_arena_create_use_cases import NOMINATIM_SEARCH, nominatim_user_agent
from src.shared.ice_discovery_scope import public_city_scope_sql, public_scope_params

logger = logging.getLogger(__name__)

OUR_LIMIT = 5
TOTAL_LIMIT = 6
MIN_GEOCODE_QUERY_LEN = 2
CACHE_TTL_SEC = 3600.0
MIN_INTERVAL_SEC = 1.0
GEOCODE_TIMEOUT_SEC = 4.0

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_last_request_at: float = 0.0

Geocode = Callable[[str], Awaitable[list[dict[str, Any]]]]


def _like_prefix(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _parse_nominatim(data: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in data or []:
        addr = item.get("address") or {}
        name = addr.get("city") or addr.get("town") or addr.get("village")
        country = (addr.get("country_code") or "").upper()
        if not name or len(country) != 2:
            continue
        key = (name.lower(), country)
        if key in seen:
            continue
        seen.add(key)
        try:
            lat, lon = float(item["lat"]), float(item["lon"])
        except (KeyError, TypeError, ValueError):
            lat = lon = None
        out.append({
            "city_id": None,
            "name": name,
            "region": addr.get("state") or None,
            "country": country,
            "lat": lat,
            "lon": lon,
            "is_new": True,
        })
    return out


async def nominatim_cities(q: str) -> list[dict[str, Any]]:
    """Cities matching ``q`` from Nominatim. Never raises; throttled and cached per process."""
    global _last_request_at
    key = (q or "").strip().lower()
    if not key:
        return []
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL_SEC:
        return hit[1]
    if now - _last_request_at < MIN_INTERVAL_SEC:
        return []
    _last_request_at = now
    try:
        async with httpx.AsyncClient(timeout=GEOCODE_TIMEOUT_SEC) as client:
            r = await client.get(
                NOMINATIM_SEARCH,
                params={
                    "q": q.strip(),
                    "format": "jsonv2",
                    "limit": "6",
                    "addressdetails": "1",
                    "featureType": "city",
                    "accept-language": "ru",
                },
                headers={"User-Agent": nominatim_user_agent("CitySearch")},
            )
            r.raise_for_status()
            result = _parse_nominatim(r.json())
    except Exception:  # noqa: BLE001
        logger.info("place suggestion city search: nominatim failed q=%r", q, exc_info=True)
        return []
    _cache[key] = (now, result)
    return result


async def search_cities(session: AsyncSession, q: str, *, geocode: Geocode = nominatim_cities) -> list[dict[str, Any]]:
    query = " ".join((q or "").split())[:120]
    if not query:
        return []
    r = await session.execute(
        text(
            f"""
            SELECT c.id, c.name, c.region, c.country, c.latitude, c.longitude
            FROM cities c
            WHERE {public_city_scope_sql("c")}
              AND c.name ILIKE :q ESCAPE '\\'
            ORDER BY c.sort_order, c.name
            LIMIT {OUR_LIMIT}
            """
        ),
        {"q": _like_prefix(query), **public_scope_params()},
    )
    ours = [
        {
            "city_id": int(row[0]),
            "name": row[1],
            "region": row[2],
            "country": row[3],
            "lat": row[4],
            "lon": row[5],
            "is_new": False,
        }
        for row in r.fetchall()
    ]
    if len(query) < MIN_GEOCODE_QUERY_LEN or len(ours) >= TOTAL_LIMIT:
        return ours
    try:
        found = await geocode(query)
    except Exception:  # noqa: BLE001
        logger.info("place suggestion city search: geocoder failed q=%r", query, exc_info=True)
        found = []
    known = {(i["name"].strip().lower(), (i["country"] or "").upper()) for i in ours}
    extra = [g for g in found if (str(g.get("name") or "").strip().lower(), (g.get("country") or "").upper()) not in known]
    return (ours + extra)[:TOTAL_LIMIT]
