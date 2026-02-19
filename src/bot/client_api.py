"""Client bot API client: fetch active trainers and photos (no auth)."""
import logging
from typing import Any

import aiohttp

from src.shared.config import Settings

logger = logging.getLogger(__name__)


async def fetch_active_trainers(limit: int = 50) -> list[dict[str, Any]]:
    """Load active trainers with profile, photos, service_ids from public API."""
    base = Settings().api_base_url.rstrip("/")
    url = f"{base}/api/public/trainers?limit={limit}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning("Catalog API returned %s: %s", resp.status, await resp.text())
                    return []
                data = await resp.json()
                return data.get("items") or []
    except Exception as e:
        logger.exception("Failed to fetch catalog: %s", e)
        return []


def build_photo_url(file_key: str) -> str | None:
    """Build full photo URL (PHOTO_BASE_URL or API_BASE_URL + /api/public/photos)."""
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
