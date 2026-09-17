"""
Re-apply the client bot's hub menu button on every inbound message/callback.

Telegram silently drops a chat's MenuButtonWebApp back to a non-functional state after
Mini App use and gives the bot no notification when this happens (same behavior the
trainer bot already defends against — see trainer_menu_sync_middleware.py). Since every
client always gets the same hub button (no linked/unlinked distinction like the trainer
bot), this only needs to throttle repeated identical re-applies, not track a signature.
"""
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.bot.client_menu_commands import sync_client_hub_menu_button

logger = logging.getLogger(__name__)


class ClientMenuSyncMiddleware(BaseMiddleware):
    """Re-apply the hub menu button per-chat; throttle so busy chats don't hammer the API."""

    _last_time: dict[int, float] = {}
    THROTTLE_SEC = 60.0

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat_id: int | None = None
        bot = None

        if isinstance(event, Message) and event.chat and event.chat.type == "private":
            chat_id = event.chat.id
            bot = event.bot
        elif (
            isinstance(event, CallbackQuery)
            and event.message
            and event.message.chat
            and event.message.chat.type == "private"
        ):
            chat_id = event.message.chat.id
            bot = event.bot

        if chat_id is None or bot is None:
            return await handler(event, data)

        now = time.monotonic()
        if (now - self._last_time.get(chat_id, 0.0)) < self.THROTTLE_SEC:
            return await handler(event, data)

        try:
            await sync_client_hub_menu_button(bot, chat_id)
        except Exception:
            logger.exception("client_menu_sync: Telegram menu API failed chat_id=%s", chat_id)
            return await handler(event, data)
        self._last_time[chat_id] = now
        return await handler(event, data)
