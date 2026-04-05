"""
Public HTTPS origin for Telegram MenuButtonWebApp and Mini App URLs.

Telegram requires HTTPS for Web App menu buttons. Prefer WEBAPP_BASE_URL; if it is still HTTP
(e.g. localhost default), fall back to API_BASE_URL so prod setups that only set API_BASE_URL work.
"""
from __future__ import annotations

from src.shared.config import Settings


def mini_app_https_base(settings: Settings) -> tuple[str | None, str]:
    """Returns (base_url_without_trailing_slash_or_none, reason_for_logs)."""
    web = (settings.webapp_base_url or "").strip().rstrip("/")
    api = (settings.api_base_url or "").strip().rstrip("/")
    if web.lower().startswith("https://"):
        return web, "WEBAPP_BASE_URL"
    if api.lower().startswith("https://"):
        return api, "API_BASE_URL (WEBAPP_BASE_URL not HTTPS)"
    return None, "no HTTPS base"
