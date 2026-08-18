"""
When Postgres is down, answer the user instead of failing silently or crashing polling.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from src.bot import messages as msg
from src.shared.config import Settings
from src.shared.outage import is_db_unavailable

logger = logging.getLogger(__name__)

_NOTICE_COOLDOWN_SEC = 45.0


def _user_id_from_event(event: TelegramObject) -> int | None:
    if isinstance(event, Update):
        if event.message and event.message.from_user:
            return event.message.from_user.id
        if event.callback_query and event.callback_query.from_user:
            return event.callback_query.from_user.id
        if event.edited_message and event.edited_message.from_user:
            return event.edited_message.from_user.id
        return None
    if isinstance(event, Message) and event.from_user:
        return event.from_user.id
    if isinstance(event, CallbackQuery) and event.from_user:
        return event.from_user.id
    from_user = getattr(event, "from_user", None)
    uid = getattr(from_user, "id", None) if from_user is not None else None
    return int(uid) if uid is not None else None


async def _notify_unavailable(event: TelegramObject, bot: Any, text: str) -> None:
    try:
        if isinstance(event, Update):
            if event.callback_query:
                await event.callback_query.answer(text, show_alert=True)
                return
            if event.message:
                await event.message.answer(text)
                return
            return
        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
            return
        if isinstance(event, Message):
            await event.answer(text)
            return
        if bot is not None and hasattr(bot, "send_message"):
            uid = _user_id_from_event(event)
            if uid:
                await bot.send_message(uid, text)
    except Exception:
        logger.warning("failed to send service-unavailable notice", exc_info=True)


class ServiceUnavailableMiddleware(BaseMiddleware):
    """Catch DB outages (and planned MAINTENANCE_MODE) so users see a human message."""

    def __init__(self) -> None:
        self._last_notice_at: dict[int, float] = {}

    def _should_notify(self, user_id: int | None) -> bool:
        if user_id is None:
            return True
        now = time.monotonic()
        last = self._last_notice_at.get(user_id, 0.0)
        if now - last < _NOTICE_COOLDOWN_SEC:
            return False
        self._last_notice_at[user_id] = now
        return True

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if Settings().maintenance_mode:
            uid = _user_id_from_event(event)
            if self._should_notify(uid):
                await _notify_unavailable(event, data.get("bot"), msg.SERVICE_UNAVAILABLE_USER)
            return None
        try:
            return await handler(event, data)
        except Exception as exc:
            if not is_db_unavailable(exc):
                raise
            logger.warning("bot request failed: database unavailable: %s", exc)
            uid = _user_id_from_event(event)
            if self._should_notify(uid):
                await _notify_unavailable(event, data.get("bot"), msg.SERVICE_UNAVAILABLE_USER)
            return None
