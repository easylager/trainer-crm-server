"""
Rate limit middleware: one limiter per bot process, applied to every Update (message/callback).
If over limit, respond with a short message and skip handler.
"""
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject, Update

from src.bot import messages as msg
from src.shared.rate_limit import RateLimiter


def _user_id_from_update(update: Update) -> int | None:
    """Extract user id from message or callback_query; None if not from user."""
    if update.message and update.message.from_user:
        return update.message.from_user.id
    if update.callback_query and update.callback_query.from_user:
        return update.callback_query.from_user.id
    if update.edited_message and update.edited_message.from_user:
        return update.edited_message.from_user.id
    return None


async def _notify_throttled(bot: Bot, update: Update, text: str) -> None:
    """Send rate-limit message: reply in chat for message, answer callback for callback_query."""
    if update.message:
        await update.message.answer(text)
    elif update.callback_query:
        await update.callback_query.answer(text, show_alert=True)


class RateLimitMiddleware(BaseMiddleware):
    """Sliding-window rate limit per user; on exceed: notify and do not call handler."""

    def __init__(
        self,
        limiter: RateLimiter,
        bot: Bot,
        throttle_message: str = msg.RATE_LIMIT_MESSAGE,
    ) -> None:
        self._limiter = limiter
        self._bot = bot
        self._throttle_message = throttle_message

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        user_id = _user_id_from_update(event)
        if user_id is None:
            return await handler(event, data)
        if not self._limiter.check_and_consume(user_id):
            await _notify_throttled(self._bot, event, self._throttle_message)
            return
        return await handler(event, data)
