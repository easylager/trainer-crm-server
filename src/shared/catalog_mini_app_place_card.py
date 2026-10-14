"""Mini App rollout: server-rendered /p/… place card for selected Telegram accounts."""

from __future__ import annotations

from src.shared.config import get_settings


def mini_app_server_place_card_enabled(telegram_id: int) -> bool:
    """True when this Telegram user should open /p/… inside the client Mini App."""
    ids = get_settings().catalog_mini_app_server_place_card_telegram_ids
    if not ids:
        return False
    return int(telegram_id) in ids
