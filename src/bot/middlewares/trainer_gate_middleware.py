"""
Blocks trainer bot work features until profile is complete and trainer is active (moderation approved).
Allows: /start, /guide, /profile, /myprofile, /cancel, support flow, guide/support/faq callbacks, profwiz:* (legacy inline buttons → Mini App stub).
Other callbacks (e.g. trainer:invite) require ACTIVE — same as non-allowlisted commands.
"""
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatAction
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.application.trainer_access_state import TrainerAccessState, get_trainer_access_state
from src.bot import messages as msg
from src.bot import trainer_benchmark_config as bench_cfg
from src.bot.trainer_bot_state import trainer_support_awaiting
from src.bot.trainer_gate_text import trainer_gate_message
from src.infrastructure.db import async_session_factory

bench_log = logging.getLogger("trainer_bot.bench")


def _command_root(text: str | None) -> str | None:
    if not text or not text.strip():
        return None
    t = text.split()[0]
    if "@" in t:
        t = t.split("@", 1)[0]
    return t


def _is_allowed_command(text: str | None) -> bool:
    root = _command_root(text)
    return root in ("/start", "/guide", "/profile", "/myprofile", "/cancel")


# Keep in sync with trainer_handlers callback_data values.
_ALLOWED_CALLBACK_PREFIXES: tuple[str, ...] = (
    "guide",
    "trainer:support",
    "trainer:faq",
)


def _callback_allowed(data: str | None) -> bool:
    if not data:
        return False
    if data in _ALLOWED_CALLBACK_PREFIXES:
        return True
    if data.startswith("profwiz:"):
        return True
    return False


class TrainerGateMiddleware(BaseMiddleware):
    """Pass through only ACTIVE trainers (or allowlisted onboarding/help commands)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            return await self._handle_message(handler, event, data)
        if isinstance(event, CallbackQuery):
            return await self._handle_callback(handler, event, data)
        return await handler(event, data)

    async def _handle_message(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        uid = event.from_user.id if event.from_user else 0
        if uid and uid in trainer_support_awaiting:
            return await handler(event, data)
        if _is_allowed_command(event.text):
            return await handler(event, data)

        t0 = time.perf_counter()
        async with async_session_factory() as session:
            state, trainer = await get_trainer_access_state(session, uid)
        if bench_cfg.log_inner_phases():
            bench_log.info(
                "BENCH trainer_gate kind=message user_id=%s gate_db_ms=%.1f",
                uid,
                (time.perf_counter() - t0) * 1000,
            )
        if state == TrainerAccessState.ACTIVE:
            return await handler(event, data)
        await event.answer(trainer_gate_message(state, trainer))
        return None

    async def _handle_callback(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        uid = event.from_user.id if event.from_user else 0
        if _callback_allowed(event.data):
            return await handler(event, data)

        t0 = time.perf_counter()
        async with async_session_factory() as session:
            state, trainer = await get_trainer_access_state(session, uid)
        if bench_cfg.log_inner_phases():
            bench_log.info(
                "BENCH trainer_gate kind=callback user_id=%s gate_db_ms=%.1f",
                uid,
                (time.perf_counter() - t0) * 1000,
            )
        if state == TrainerAccessState.ACTIVE:
            return await handler(event, data)
        await event.answer(msg.TRAINER_GATE_CALLBACK_BLOCKED, show_alert=True)
        if event.message:
            await event.bot.send_chat_action(chat_id=event.message.chat.id, action=ChatAction.TYPING)
            await event.message.answer(trainer_gate_message(state, trainer))
        return None
