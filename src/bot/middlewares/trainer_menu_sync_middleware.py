"""
After active trainer passes the gate, keep Telegram menu in sync with subscription tier (throttled).
"""
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from src.application.trainer_access_state import TrainerAccessState, get_trainer_access_state
from src.application.trainer_link import get_trainer_id_by_telegram_id
from src.bot.trainer_menu_commands import sync_trainer_menu_commands
from src.infrastructure.db import async_session_factory


class TrainerMenuSyncMiddleware(BaseMiddleware):
    """Refresh menu commands (stats vs no stats) when tier may have changed; avoid hammering Telegram API."""

    _last_sync: dict[int, float] = {}
    THROTTLE_SEC = 60.0

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.chat and event.chat.type == "private" and event.from_user:
            uid = event.from_user.id
            now = time.monotonic()
            last = self._last_sync.get(uid, 0.0)
            if now - last >= self.THROTTLE_SEC:
                async with async_session_factory() as session:
                    state, _ = await get_trainer_access_state(session, uid)
                    if state != TrainerAccessState.ACTIVE:
                        return await handler(event, data)
                    tid = await get_trainer_id_by_telegram_id(session, uid)
                    if not tid:
                        return await handler(event, data)
                    await sync_trainer_menu_commands(event.bot, event.chat.id, tid, session)
                self._last_sync[uid] = now
        return await handler(event, data)
