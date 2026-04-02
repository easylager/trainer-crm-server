"""
Keep Telegram menu in sync with trainer status and subscription tier.

- Active trainers get full menu based on subscription tier (CRM features, stats).
- Non-active trainers (pending_profile, deactivated, etc.) get minimal menu (guide, profile, subscription).

Throttles repeated set_my_commands when nothing changed; always syncs when signature changes
(e.g. subscription removed in admin, or status demoted) so the 60s throttle does not block urgent updates.
"""
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.application.trainer_access_state import TrainerAccessState, get_trainer_access_state
from src.application.trainer_link import get_trainer_id_by_telegram_id
from src.bot.trainer_menu_commands import (
    reset_trainer_menu_to_minimal,
    sync_trainer_menu_commands,
    trainer_menu_signature,
)
from src.infrastructure.db import async_session_factory


class TrainerMenuSyncMiddleware(BaseMiddleware):
    """Refresh menu when status or subscription tier changes; throttle only identical consecutive states."""

    _last_sig: dict[int, str] = {}
    _last_time: dict[int, float] = {}
    THROTTLE_SEC = 60.0

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat_id: int | None = None
        uid: int | None = None
        bot = None

        if isinstance(event, Message) and event.chat and event.chat.type == "private" and event.from_user:
            chat_id = event.chat.id
            uid = event.from_user.id
            bot = event.bot
        elif (
            isinstance(event, CallbackQuery)
            and event.from_user
            and event.message
            and event.message.chat
            and event.message.chat.type == "private"
        ):
            chat_id = event.message.chat.id
            uid = event.from_user.id
            bot = event.bot

        if chat_id is None or uid is None or bot is None:
            return await handler(event, data)

        now = time.monotonic()
        async with async_session_factory() as session:
            state, _ = await get_trainer_access_state(session, uid)
            tid = await get_trainer_id_by_telegram_id(session, uid)
            if not tid:
                return await handler(event, data)
            # Signature includes state so menu resets when trainer loses active status
            if state == TrainerAccessState.ACTIVE:
                tier_sig = await trainer_menu_signature(session, tid)
                sig = f"active|{tier_sig}"
            else:
                sig = f"minimal|{state.value}"

        prev_sig = self._last_sig.get(uid)
        signature_changed = prev_sig != sig
        if not signature_changed and (now - self._last_time.get(uid, 0.0)) < self.THROTTLE_SEC:
            return await handler(event, data)

        async with async_session_factory() as session:
            if state == TrainerAccessState.ACTIVE:
                await sync_trainer_menu_commands(bot, chat_id, tid, session)
            else:
                await reset_trainer_menu_to_minimal(bot, chat_id)
        self._last_sig[uid] = sig
        self._last_time[uid] = now
        return await handler(event, data)
