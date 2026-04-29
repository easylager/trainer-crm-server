"""
Telegram Web App: validate initData and produce a MiniAppPrincipal.

Validation rules live in src.shared.telegram_webapp (HMAC, auth_date). This module only maps
success to our cross-platform shape so other hosts can mirror the same API surface later.
"""
from __future__ import annotations

from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.shared.telegram_webapp import InitDataAuthError, require_telegram_user_id


def verify_telegram_init_data_principal(init_data: str, bot_token: str) -> MiniAppPrincipal:
    """
    Verify initData for the given bot token and return a principal.

    Raises:
        InitDataAuthError: invalid HMAC, stale auth_date, or missing user (caller maps to HTTP).
    """
    uid = require_telegram_user_id(init_data, bot_token)
    return MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=int(uid))
