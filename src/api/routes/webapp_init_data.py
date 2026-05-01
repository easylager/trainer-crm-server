"""
HTTP-facing helpers: raw init_data string → numeric user id for legacy callers.

Step 1 of multi-platform prep:
- Verification and platform-specific parsing live in ``src.api.miniapp_auth`` (Telegram first).
- This module keeps the historical names (trainer_telegram_id, …) and maps auth errors to HTTP,
  so hundreds of route handlers do not need renames yet.

Next steps (roadmap):
- FastAPI Depends(get_client_principal) that picks verifier by X-Mini-App-Platform or URL prefix.
- Optional JWT / signed cookie for non-Telegram hosts while keeping the same JSON API.
"""
from __future__ import annotations

from fastapi import HTTPException

from src.api.miniapp_auth import verify_telegram_init_data_principal
from src.api.miniapp_auth.deps import miniapp_credential_http_exception
from src.shared.config import Settings
from src.shared.telegram_webapp import InitDataAuthError


def get_telegram_id_from_init_data(init_data: str, *, bot_token: str) -> int:
    """
    Legacy name: returns Telegram user id after verifying Telegram Web App initData.
    Internally uses MiniAppPrincipal (platform=TELEGRAM); return value is principal.user_id.
    """
    try:
        principal = verify_telegram_init_data_principal(init_data, bot_token)
        return principal.user_id
    except InitDataAuthError:
        raise miniapp_credential_http_exception() from None


def trainer_telegram_id(init_data: str) -> int:
    return get_telegram_id_from_init_data(init_data, bot_token=Settings().telegram_bot_token_trainer)


def client_telegram_id(init_data: str) -> int:
    return get_telegram_id_from_init_data(init_data, bot_token=Settings().telegram_bot_token_client)


def strip_client_name_field(value: str | None) -> str | None:
    if value is None:
        return None
    t = (value or "").strip()[:64]
    return t or None


def admin_telegram_id(init_data: str) -> int:
    """Validate init_data with admin bot token; require telegram_id in admin_telegram_ids."""
    token = Settings().telegram_bot_token_admin
    if not token:
        raise HTTPException(status_code=503, detail="Admin Web App not configured")
    tid = get_telegram_id_from_init_data(init_data, bot_token=token)
    admin_ids = Settings().admin_telegram_ids or []
    if tid not in admin_ids:
        raise HTTPException(status_code=403, detail="Not an admin")
    return tid
