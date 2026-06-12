"""
Keep Telegram menu in sync with trainer link status.

Linked trainers get only the «Обзор» Web App button (no slash command menu).
Unlinked chats get an empty commands menu without hub access.

Throttles repeated API calls when nothing changed.
"""
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.application.trainer_link import get_trainer_id_by_telegram_id
from src.bot import trainer_benchmark_config as bench_cfg
from src.bot.trainer_menu_commands import (
    reset_trainer_menu_for_unlinked,
    sync_trainer_linked_chat_menu,
)
from src.infrastructure.db import async_session_factory

bench_log = logging.getLogger("trainer_bot.bench")


class TrainerMenuSyncMiddleware(BaseMiddleware):
    """Refresh chat menu when link status changes; throttle only identical consecutive states."""

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
        t_read = time.perf_counter()
        async with async_session_factory() as session:
            tid = await get_trainer_id_by_telegram_id(session, uid)
        read_ms = (time.perf_counter() - t_read) * 1000

        sig = "linked" if tid else "unlinked"
        prev_sig = self._last_sig.get(uid)
        signature_changed = prev_sig != sig
        throttled = not signature_changed and (now - self._last_time.get(uid, 0.0)) < self.THROTTLE_SEC
        if throttled:
            if bench_cfg.log_inner_phases():
                bench_log.info(
                    "BENCH trainer_menu_sync user_id=%s read_ms=%.1f menu_sync_ms=0 throttled=1",
                    uid,
                    read_ms,
                )
            return await handler(event, data)

        t_sync = time.perf_counter()
        if tid:
            await sync_trainer_linked_chat_menu(bot, chat_id)
        else:
            await reset_trainer_menu_for_unlinked(bot, chat_id)
        menu_sync_ms = (time.perf_counter() - t_sync) * 1000
        if bench_cfg.log_inner_phases():
            bench_log.info(
                "BENCH trainer_menu_sync user_id=%s read_ms=%.1f menu_sync_ms=%.1f throttled=0 sig_changed=%s",
                uid,
                read_ms,
                menu_sync_ms,
                int(signature_changed),
            )
        self._last_sig[uid] = sig
        self._last_time[uid] = now
        return await handler(event, data)
