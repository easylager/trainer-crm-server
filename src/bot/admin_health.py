"""
Admin bot: fetch API /health for /version (aiohttp, short timeout).
"""

from __future__ import annotations

import asyncio
import html
import logging
from typing import Any

import aiohttp

from src.bot import messages as msg
from src.bot.main_mini_app_check import CheckResult, check_main_mini_app, format_health_line
from src.shared.config import Settings

logger = logging.getLogger(__name__)

HEALTH_TIMEOUT_SEC = 5.0

#: Последний результат проверки Main Mini App. ``/version`` вызывает ``fetch_api_health()`` и
#: ``format_admin_version_message()`` по очереди, а обработчик знает только эти два вызова.
_last_main_mini_app: CheckResult | None = None


async def refresh_main_mini_app_check(settings: Settings | None = None) -> CheckResult:
    """``getMe`` клиентского бота → ``has_main_web_app`` (TASK-223 / P1-5). Не бросает."""
    global _last_main_mini_app
    s = settings or Settings()
    _last_main_mini_app = await check_main_mini_app(s.telegram_bot_token_client, expected=s.client_bot_main_mini_app)
    return _last_main_mini_app


async def fetch_api_health() -> dict[str, Any] | str:
    """
    GET {api_base_url}/health (заодно обновляет проверку Main Mini App для строки в /version).
    Returns parsed JSON dict on 200, or a short Russian-safe error string (no stack traces).
    """
    _, health = await asyncio.gather(refresh_main_mini_app_check(), _fetch_api_health_body())
    return health


async def _fetch_api_health_body() -> dict[str, Any] | str:
    base = Settings().api_base_url.rstrip("/")
    url = f"{base}/health"
    timeout = aiohttp.ClientTimeout(total=HEALTH_TIMEOUT_SEC)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                try:
                    data = await resp.json()
                except Exception:
                    data = None
                if resp.status == 200 and isinstance(data, dict):
                    return data
                if isinstance(data, dict) and (data.get("db") or data.get("code") or data.get("status")):
                    return data
                if resp.status != 200:
                    return f"HTTP {resp.status}"
                return data if isinstance(data, dict) else {}
    except TimeoutError:
        return "таймаут"
    except aiohttp.ClientError as e:
        return str(e)[:120]
    except Exception as e:
        logger.warning("fetch_api_health failed: %s", e)
        return str(e)[:120]


def format_admin_version_message(
    settings: Settings,
    health: dict[str, Any] | str,
    main_mini_app: CheckResult | None = None,
) -> str:
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
    parts.append(html.escape(format_health_line(main_mini_app or _last_main_mini_app)))
    parts.append(msg.ADMIN_VERSION_NOTIFICATION_SERVICE)
    return "\n".join(parts)
