"""Подписка на колокольчик из бота: ``/start watch_<arena_id>`` (TASK-328 AC7).

Путь для сайта: там нет Mini App initData, поэтому кнопка ведёт в клиентский бот, и
подписку оформляет бот от имени того, кто нажал Start. Модуль без aiogram — ответ
проверяется тестом.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_public_use_cases import get_public_arena_card
from src.application.client_ice_watch_use_cases import subscribe_ice_watch
from src.application.client_session_use_cases import get_or_create_session
from src.application.client_use_cases import get_or_create_client
from src.application.ice_watch_message import OPEN_SCHEDULE_BUTTON, compose_watch_subscribed_reply
from src.application.place_links import parse_watch_start_param
from src.infrastructure.db.models import ICE_WATCH_KIND_SESSIONS

# Как у кнопки в Mini App: подписка на любые новые сеансы катка.
WATCH_START_FILTER = {"when": "any", "day": None, "intent": "skate"}


def parse_watch_start(payload: str | None) -> int | None:
    # Один разбор с сайтом и учётом клика (place_links): ссылку строит сайт, читает бот.
    return parse_watch_start_param(payload)


async def subscribe_from_bot_start(
    session: AsyncSession,
    *,
    telegram_id: int,
    arena_id: int,
    webapp_base_url: str,
    telegram_username: str | None = None,
) -> dict[str, Any] | None:
    """Создать или переоткрыть ``sessions``-подписку; ``None`` — катка нет в каталоге.

    Ответ: ``{"text", "button_text", "url"}``; ``url`` — ``None``, если Mini App
    недоступен (не HTTPS), тогда ответ без кнопки.
    """
    card = await get_public_arena_card(session, str(int(arena_id)))
    if card is None or not card.get("has_skating"):
        return None
    client_id = await get_or_create_client(session, telegram_id, telegram_username=telegram_username)
    await session.commit()
    await get_or_create_session(telegram_id, session)
    await subscribe_ice_watch(
        session,
        client_id=int(client_id),
        telegram_id=int(telegram_id),
        arena_id=int(card["id"]),
        watch_kind=ICE_WATCH_KIND_SESSIONS,
        filter_json=dict(WATCH_START_FILTER),
        city_id=card.get("city_id"),
    )
    name = str(card.get("name") or "")
    base = (webapp_base_url or "").strip().rstrip("/")
    url = f"{base}/webapp/arena?arena_id={int(card['id'])}" if base.lower().startswith("https://") else None
    return {
        "text": compose_watch_subscribed_reply(name),
        "button_text": OPEN_SCHEDULE_BUTTON,
        "url": url,
    }
