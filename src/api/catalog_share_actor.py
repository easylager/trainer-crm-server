"""Stable catalog actor for public routes.

Mini App: ``telegram_actor_hash`` of the client key. Without a principal:
``public_actor_hash`` of IP and User-Agent. The hash is ``None`` when the actor
secret is unset (fail closed). Catalog share and ice invites must write the same value.
"""

from __future__ import annotations

from fastapi import Request

from src.api.middleware.http_limits import client_ip_from_request
from src.api.miniapp_auth.principal_keys import client_catalog_telegram_key
from src.api.miniapp_auth.types import MiniAppPrincipal
from src.application.catalog_consumer_events import public_actor_hash, telegram_actor_hash


def catalog_share_actor(principal: MiniAppPrincipal | None, request: Request) -> tuple[int | None, str | None]:
    """Актёр шаринга каталога — тот же стабильный HMAC, что у входов и просмотров.

    Mini App: ``telegram_actor_hash`` от ключа клиента. Без principal — ``public_actor_hash``
    по IP и User-Agent. ``None`` у хэша, если секрет актёра не задан (fail closed).
    """
    if principal is not None:
        telegram_id = client_catalog_telegram_key(principal)
        return telegram_id, telegram_actor_hash(telegram_id)
    return None, public_actor_hash(
        client_ip=client_ip_from_request(request),
        user_agent=request.headers.get("user-agent"),
    )
