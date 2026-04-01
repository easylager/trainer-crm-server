"""Client bot API client: fetch active trainers and photos (no auth)."""
import logging
from typing import Any

import aiohttp

from src.shared.config import Settings

logger = logging.getLogger(__name__)


async def _get_json(path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """GET public API path; returns items list or []."""
    base = Settings().api_base_url.rstrip("/")
    url = f"{base}{path}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params or {}) as resp:
                if resp.status != 200:
                    logger.warning("API %s returned %s: %s", path, resp.status, await resp.text())
                    return []
                data = await resp.json()
                return data.get("items") or []
    except Exception as e:
        logger.exception("Failed to fetch %s: %s", path, e)
        return []


async def fetch_cities() -> list[dict[str, Any]]:
    """Load cities for city picker."""
    return await _get_json("/api/public/cities")


async def fetch_services() -> list[dict[str, Any]]:
    """Load services for service picker."""
    return await _get_json("/api/public/services")


async def fetch_arenas(city_id: int) -> list[dict[str, Any]]:
    """Load arenas in a city."""
    return await _get_json("/api/public/arenas", {"city_id": city_id})


async def fetch_active_trainers(
    limit: int = 10,
    offset: int = 0,
    city_id: int | None = None,
    service_id: int | None = None,
    arena_id: int | None = None,
    order_by: str = "rating",
) -> tuple[list[dict[str, Any]], int]:
    """Load active trainers; paginated. Returns (items, total)."""
    base = Settings().api_base_url.rstrip("/")
    url = f"{base}/api/public/trainers"
    params: dict[str, Any] = {"limit": limit, "offset": offset, "order_by": order_by}
    if city_id is not None:
        params["city_id"] = city_id
    if service_id is not None:
        params["service_id"] = service_id
    if arena_id is not None:
        params["arena_id"] = arena_id
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning("API trainers returned %s: %s", resp.status, await resp.text())
                    return [], 0
                data = await resp.json()
                items = data.get("items") or []
                total = data.get("total", len(items))
                return items, total
    except Exception as e:
        logger.exception("Failed to fetch trainers: %s", e)
        return [], 0


def build_photo_url(file_key: str) -> str | None:
    """Build full photo URL (PHOTO_BASE_URL or API_BASE_URL + /api/public/photos)."""
    if not file_key:
        return None
    s = Settings()
    base = s.photo_base_url or (s.api_base_url.rstrip("/") + "/api/public/photos")
    return f"{base.rstrip('/')}/{file_key}"


async def fetch_photo_bytes(photo_url: str) -> bytes | None:
    """Download photo bytes from URL so bot can send as file (localhost-friendly)."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()
    except Exception as e:
        logger.warning("Failed to fetch photo %s: %s", photo_url, e)
        return None


async def resolve_trainer_photo_bytes(file_key: str | None) -> bytes | None:
    """
    Bytes for Telegram send_photo: read from S3/local (same as GET /api/public/photos/{key}),
    then HTTP fallback. Admin bot often runs in a separate process where api_base_url is not
    reachable — direct storage read fixes missing photos on moderation cards.
    """
    if not file_key or not str(file_key).strip():
        return None
    key = str(file_key).strip()
    from src.infrastructure import s3

    result = s3.get_photo(key)
    if result:
        return result[0]
    url = build_photo_url(key)
    if url:
        return await fetch_photo_bytes(url)
    return None
