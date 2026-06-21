"""
Blocks trainer bot work only for states that cannot use CRM yet (e.g. incomplete profile, deactivated).

NOT_LINKED (telegram not bound to a trainer row): only /start with welcome-link payload is allowed;
everything else gets TRAINER_ONLY_VIA_SITE — no slash menu, no hub, no CRM callbacks.

Allows full bot workflows when linked trainer is ACTIVE, BOOKING_READY (TTV minimal), or
PENDING_MODERATION (full anketa submitted — catalog still outside chat). Same allowlist as before
for early onboarding: /start, /guide, /profile, /myprofile, /cancel, support, profwiz:*,
booking_add_note:* / booking_invite_client:* (handlers enforce booking ownership).
"""
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatAction
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.application.trainer_access_state import (
    TrainerAccessState,
    get_trainer_access_state,
    trainer_may_use_bot_workflows,
)
from src.bot import messages as msg
from src.bot import trainer_benchmark_config as bench_cfg
from src.bot.trainer_bot_state import trainer_booking_note_awaiting, trainer_support_awaiting
from src.bot.trainer_gate_text import trainer_gate_message
from src.infrastructure.db import async_session_factory

bench_log = logging.getLogger("trainer_bot.bench")

_START_LINK_PREFIX = "link_"
_START_REF_PREFIX = "ref_"


def _command_root(text: str | None) -> str | None:
    if not text or not text.strip():
        return None
    t = text.split()[0]
    if "@" in t:
        t = t.split("@", 1)[0]
    return t


def _is_allowed_command(text: str | None) -> bool:
    root = _command_root(text)
    return root in ("/start", "/home", "/guide", "/profile", "/myprofile", "/cancel")


def _is_welcome_link_start(text: str | None) -> bool:
    """True when /start carries a welcome or referral payload that must reach the handler."""
    if not text or not text.strip():
        return False
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return False
    payload = parts[1].strip()
    if payload.startswith(_START_LINK_PREFIX):
        return True
    if payload.startswith(_START_REF_PREFIX):
        return True
    return False


# Keep in sync with trainer_handlers callback_data values (exact match or prefix).
_ALLOWED_CALLBACK_EXACT: tuple[str, ...] = (
    "guide",
    "trainer:support",
    "trainer:faq",
    "trainer:invite",
)
# Booking-scoped CRM (notes, invite link) must work in pending_profile before full anketa / catalog — handlers verify ownership.
_BOOKING_CRM_CALLBACK_PREFIXES: tuple[str, ...] = (
    "booking_add_note:",
    "booking_invite_client:",
)


def _normalized_callback_data(data: str | None) -> str:
    """Telegram usually sends clean ASCII; strip defensively for inline keyboards from API."""
    if data is None:
        return ""
    return str(data).strip()


def _callback_allowed(data: str | None) -> bool:
    data = _normalized_callback_data(data)
    if not data:
        return False
    if data in _ALLOWED_CALLBACK_EXACT:
        return True
    low = data.lower()
    # Case-insensitive: inline data is always lowercase from our builders, belts-and-suspenders for API/proxy quirks.
    if low.startswith("profwiz:"):
        return True
    if any(low.startswith(p) for p in _BOOKING_CRM_CALLBACK_PREFIXES):
        return True
    return False


class TrainerGateMiddleware(BaseMiddleware):
    """Pass through linked trainers who may use CRM bot flows, or allowlisted onboarding/help commands."""

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

        t0 = time.perf_counter()
        async with async_session_factory() as session:
            state, trainer = await get_trainer_access_state(session, uid)
        if bench_cfg.log_inner_phases():
            bench_log.info(
                "BENCH trainer_gate kind=message user_id=%s gate_db_ms=%.1f",
                uid,
                (time.perf_counter() - t0) * 1000,
            )

        # Unlinked telegram: only welcome-link /start may proceed; block hub, slash commands, free text.
        if state == TrainerAccessState.NOT_LINKED:
            if _is_welcome_link_start(event.text):
                return await handler(event, data)
            if event.chat:
                await event.bot.send_chat_action(chat_id=event.chat.id, action=ChatAction.TYPING)
            await event.answer(msg.TRAINER_ONLY_VIA_SITE)
            return None

        if uid and uid in trainer_support_awaiting:
            return await handler(event, data)
        if uid and uid in trainer_booking_note_awaiting:
            return await handler(event, data)
        if _is_allowed_command(event.text):
            return await handler(event, data)
        if trainer_may_use_bot_workflows(state):
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

        t0 = time.perf_counter()
        async with async_session_factory() as session:
            state, trainer = await get_trainer_access_state(session, uid)
        if bench_cfg.log_inner_phases():
            bench_log.info(
                "BENCH trainer_gate kind=callback user_id=%s gate_db_ms=%.1f",
                uid,
                (time.perf_counter() - t0) * 1000,
            )

        if state == TrainerAccessState.NOT_LINKED:
            await event.answer(msg.TRAINER_ONLY_VIA_SITE, show_alert=True)
            if event.message:
                await event.bot.send_chat_action(chat_id=event.message.chat.id, action=ChatAction.TYPING)
                await event.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return None

        if _callback_allowed(getattr(event, "data", None)):
            return await handler(event, data)
        if trainer_may_use_bot_workflows(state):
            return await handler(event, data)
        await event.answer(msg.TRAINER_GATE_CALLBACK_BLOCKED, show_alert=True)
        if event.message:
            await event.bot.send_chat_action(chat_id=event.message.chat.id, action=ChatAction.TYPING)
            await event.message.answer(trainer_gate_message(state, trainer))
        return None
