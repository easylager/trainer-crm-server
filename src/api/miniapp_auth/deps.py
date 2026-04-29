"""
FastAPI dependencies for Mini App authentication.

Telegram: initData in ``?init_data=`` or ``X-Telegram-Init-Data``.
MAX / VK Mini Apps: launch query string in the same ``init_data`` query param or ``X-VK-Launch-Params``,
with ``X-Mini-App-Platform: max``.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Form, Header, HTTPException, Query

from src.api.miniapp_auth.telegram import verify_telegram_init_data_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.api.miniapp_auth.vk_launch_params import verify_vk_miniapp_launch_principal
from src.shared.config import Settings
from src.shared.telegram_webapp import InitDataAuthError


def _normalized_miniapp_platform(x_mini_app_platform: str | None) -> str:
    return (x_mini_app_platform or "").strip().lower() or MiniAppPlatform.TELEGRAM.value


def reject_unsupported_miniapp_platform_normalized(platform: str) -> None:
    if platform in ("", MiniAppPlatform.TELEGRAM.value, MiniAppPlatform.MAX.value):
        return
    raise HTTPException(
        status_code=501,
        detail=f"Mini App platform {platform!r} is not supported yet",
    )


def reject_unsupported_miniapp_platform(x_mini_app_platform: str | None) -> None:
    """Reject unknown hosts."""
    reject_unsupported_miniapp_platform_normalized(_normalized_miniapp_platform(x_mini_app_platform))


@dataclass(frozen=True)
class MiniappCredentialIn:
    """Raw credential string + normalized platform key (``telegram`` | ``max``)."""

    raw: str
    platform: str


def require_miniapp_credential_in(
    x_mini_app_platform: str | None = Header(None, alias="X-Mini-App-Platform"),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    x_vk_launch: str | None = Header(None, alias="X-VK-Launch-Params"),
) -> MiniappCredentialIn:
    """Parse credential from query/header; platform selects which transport fields are read."""
    platform = _normalized_miniapp_platform(x_mini_app_platform)
    reject_unsupported_miniapp_platform_normalized(platform)
    if platform == MiniAppPlatform.MAX.value:
        raw = (init_data or x_vk_launch or "").strip()
    else:
        raw = (init_data or x_telegram_init_data or "").strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    return MiniappCredentialIn(raw=raw, platform=platform)


def require_miniapp_credential_in_multipart(
    x_mini_app_platform: str | None = Header(None, alias="X-Mini-App-Platform"),
    init_data: str | None = Form(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    x_vk_launch: str | None = Header(None, alias="X-VK-Launch-Params"),
) -> MiniappCredentialIn:
    """Multipart uploads: same as :func:`require_miniapp_credential_in` but ``init_data`` from form."""
    platform = _normalized_miniapp_platform(x_mini_app_platform)
    reject_unsupported_miniapp_platform_normalized(platform)
    if platform == MiniAppPlatform.MAX.value:
        raw = (init_data or x_vk_launch or "").strip()
    else:
        raw = (init_data or x_telegram_init_data or "").strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    return MiniappCredentialIn(raw=raw, platform=platform)


def _principal_from_credential_trainer(cred: MiniappCredentialIn) -> MiniAppPrincipal:
    if cred.platform == MiniAppPlatform.MAX.value:
        secret = Settings().vk_mini_app_protected_key
        if not (secret or "").strip():
            raise HTTPException(status_code=503, detail="VK Mini App not configured")
        try:
            return verify_vk_miniapp_launch_principal(cred.raw, secret)
        except InitDataAuthError:
            raise HTTPException(status_code=401, detail="Invalid or expired launch params") from None
    token = Settings().telegram_bot_token_trainer
    if not token:
        raise HTTPException(status_code=503, detail="Trainer Mini App not configured")
    try:
        return verify_telegram_init_data_principal(cred.raw, token)
    except InitDataAuthError:
        raise HTTPException(status_code=401, detail="Invalid or expired init data") from None


def get_client_miniapp_principal(
    cred: MiniappCredentialIn = Depends(require_miniapp_credential_in),
) -> MiniAppPrincipal:
    """Client Mini App: Telegram initData or VK launch params + client-facing secrets."""
    if cred.platform == MiniAppPlatform.MAX.value:
        secret = Settings().vk_mini_app_protected_key
        if not (secret or "").strip():
            raise HTTPException(status_code=503, detail="VK Mini App not configured")
        try:
            return verify_vk_miniapp_launch_principal(cred.raw, secret)
        except InitDataAuthError:
            raise HTTPException(status_code=401, detail="Invalid or expired launch params") from None
    token = Settings().telegram_bot_token_client
    if not token:
        raise HTTPException(status_code=503, detail="Client Mini App not configured")
    try:
        return verify_telegram_init_data_principal(cred.raw, token)
    except InitDataAuthError:
        raise HTTPException(status_code=401, detail="Invalid or expired init data") from None


def get_trainer_miniapp_principal(
    cred: MiniappCredentialIn = Depends(require_miniapp_credential_in),
) -> MiniAppPrincipal:
    """Trainer Mini App: validate with trainer bot token or VK protected key."""
    return _principal_from_credential_trainer(cred)


def get_trainer_miniapp_principal_multipart(
    cred: MiniappCredentialIn = Depends(require_miniapp_credential_in_multipart),
) -> MiniAppPrincipal:
    """Trainer Mini App auth for ``multipart/form-data`` (photo / document upload)."""
    return _principal_from_credential_trainer(cred)


def get_admin_miniapp_principal(
    cred: MiniappCredentialIn = Depends(require_miniapp_credential_in),
) -> MiniAppPrincipal:
    """Admin Web App: Telegram initData + allow-list ``admin_telegram_ids``."""
    if cred.platform == MiniAppPlatform.MAX.value:
        raise HTTPException(
            status_code=501,
            detail="Admin Mini App from MAX/VK is not supported — use Telegram.",
        )
    token = Settings().telegram_bot_token_admin
    if not token:
        raise HTTPException(status_code=503, detail="Admin Web App not configured")
    try:
        principal = verify_telegram_init_data_principal(cred.raw, token)
    except InitDataAuthError:
        raise HTTPException(status_code=401, detail="Invalid or expired init data") from None
    allowed = Settings().admin_telegram_ids or []
    if principal.user_id not in allowed:
        raise HTTPException(status_code=403, detail="Not an admin")
    return principal
