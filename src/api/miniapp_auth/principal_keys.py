"""
Map :class:`MiniAppPrincipal` to legacy DB keys (``client_sessions.telegram_id``, ``clients.telegram_id``, edges).

Telegram: native user id. MAX/VK: synthetic negative key so we avoid a breaking PK migration on ``client_sessions``.
"""
from __future__ import annotations

from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal

# VK user ids are positive; Telegram ids are positive — keep synthetic keys in a disjoint negative range.
VK_CLIENT_SESSION_TELEGRAM_SURROGATE_BASE = 10**12


# Trainer support / legacy columns: disjoint negative space from client catalog surrogate.
TRAINER_MINIAPP_LEGACY_TELEGRAM_BASE = 2 * 10**12


def client_catalog_telegram_key(principal: MiniAppPrincipal) -> int:
    """
    Integer used wherever the client catalog stack still expects ``telegram_id`` (session, edges, lookups).

    For MAX, this is a stable surrogate; ``clients.vk_user_id`` stores the real VK id when present.
    """
    if principal.platform == MiniAppPlatform.TELEGRAM:
        return int(principal.user_id)
    if principal.platform == MiniAppPlatform.MAX:
        return -(VK_CLIENT_SESSION_TELEGRAM_SURROGATE_BASE + int(principal.user_id))
    raise NotImplementedError(principal.platform)


def trainer_legacy_telegram_id_for_storage(principal: MiniAppPrincipal) -> int:
    """
    Integer for tables that only have ``*_telegram_id`` (e.g. support) when the host is MAX.

    Telegram users keep their real id; VK trainers get a negative surrogate disjoint from client keys.
    """
    if principal.platform == MiniAppPlatform.TELEGRAM:
        return int(principal.user_id)
    if principal.platform == MiniAppPlatform.MAX:
        return -(TRAINER_MINIAPP_LEGACY_TELEGRAM_BASE + int(principal.user_id))
    raise NotImplementedError(principal.platform)

