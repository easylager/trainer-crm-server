"""
Platform-agnostic identity for Mini App opens.

Route handlers today still speak «telegram id» because the DB and bots are Telegram-first.
When adding another host (e.g. another messenger), extend MiniAppPlatform and add fields
only if a single int is not enough — keep user_id as the primary key for our app where possible.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MiniAppPlatform(str, Enum):
    """Host that embedded the WebView."""

    TELEGRAM = "telegram"
    MAX = "max"  # VK Mini Apps launch params (HMAC sign) — used in MAX messenger and VK clients.


@dataclass(frozen=True)
class MiniAppPrincipal:
    """
    Authenticated Mini App user for one request.

    ``user_id`` is the numeric id from that host (Telegram user id, or ``vk_user_id`` when platform is MAX).

    Client catalog persistence still uses a synthetic ``telegram_id`` surrogate for MAX users
    (see ``client_catalog_telegram_key``); trainers use ``trainers.vk_user_id`` when linked.
    """

    platform: MiniAppPlatform
    user_id: int
