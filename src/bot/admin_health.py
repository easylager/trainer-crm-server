"""
Admin bot: fetch API /health for /version (aiohttp, short timeout).
"""
from __future__ import annotations

import html
import logging
from typing import Any

import aiohttp

from src.bot import messages as msg
from src.shared.config import Settings

logger = logging.getLogger(__name__)

HEALTH_TIMEOUT_SEC = 5.0


async def fetch_api_health() -> dict[str, Any] | str:
    """
    GET {api_base_url}/health.
    Returns parsed JSON dict on 200, or a short Russian-safe error string (no stack traces).
    """
    base = Settings().api_base_url.rstrip("/")
    url = f"{base}/health"
    timeout = aiohttp.ClientTimeout(total=HEALTH_TIMEOUT_SEC)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return f"HTTP {resp.status}"
                data = await resp.json()
                return data if isinstance(data, dict) else {}
    except TimeoutError:
        return "таймаут"
    except aiohttp.ClientError as e:
        return str(e)[:120]
    except Exception as e:
        logger.warning("fetch_api_health failed: %s", e)
        return str(e)[:120]


def format_admin_version_message(settings: Settings, health: dict[str, Any] | str) -> str:
    """HTML body for /version (caller sends with parse_mode HTML)."""
    deploy = settings.app_deploy_version or settings.sentry_release or "не задано"
    env_s = settings.sentry_environment or "—"
    parts = [
        msg.ADMIN_VERSION_TITLE,
        msg.ADMIN_VERSION_DEPLOY.format(deploy=html.escape(str(deploy))),
        msg.ADMIN_VERSION_SENTRY_ENV.format(env=html.escape(str(env_s))),
    ]
    if isinstance(health, dict):
        parts.append(
            msg.ADMIN_VERSION_API_HEALTH.format(
                status=html.escape(str(health.get("status", "?"))),
                db=html.escape(str(health.get("db", "?"))),
                s3=html.escape(str(health.get("s3", "?"))),
            )
        )
    else:
        parts.append(msg.ADMIN_VERSION_API_ERROR.format(error=html.escape(str(health))))
    parts.append(msg.ADMIN_VERSION_NOTIFICATION_SERVICE)
    return "\n".join(parts)
