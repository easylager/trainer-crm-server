"""
Push a moderation card to admins the moment a trainer creates an arena (TASK-046).

Before this, ``/pending_arenas`` was pull-only — nothing told an admin a new arena was
waiting, so it could sit unconfirmed (and invisible to clients) indefinitely. Mirrors
``admin_moderation_notify.notify_admins_trainer_queued_for_moderation``: same card shape
as the pull path (``format_admin_arena_pending_caption``), failures logged, never raised.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import messages as msg
from src.bot.admin_arena_card import format_admin_arena_pending_caption
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings

logger = logging.getLogger(__name__)

# Must match ADMIN_ARENA_APPROVE_PREFIX / ADMIN_ARENA_REJECT_PREFIX in admin_handlers.
ADMIN_ARENA_APPROVE_PREFIX = "admin:arena:approve:"
ADMIN_ARENA_REJECT_PREFIX = "admin:arena:reject:"


def _arena_keyboard(arena_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=msg.ADMIN_BUTTON_APPROVE,
                    callback_data=f"{ADMIN_ARENA_APPROVE_PREFIX}{arena_id}",
                ),
                InlineKeyboardButton(
                    text=msg.ADMIN_BUTTON_REJECT,
                    callback_data=f"{ADMIN_ARENA_REJECT_PREFIX}{arena_id}",
                ),
            ]
        ]
    )


async def notify_admins_new_trainer_arena(arena_id: int) -> None:
    """Deliver one HTML card per admin right after ``create_trainer_arena`` commits."""
    from src.application.admin_arena_moderation import get_arena_pending_row

    settings = Settings()
    token = settings.telegram_bot_token_admin
    admin_ids = list(dict.fromkeys(settings.admin_telegram_ids or []))
    if not token or not admin_ids:
        return
    async with async_session_factory() as session:
        arena = await get_arena_pending_row(session, arena_id)
    if not arena:
        logger.warning("arena admin notify: arena %s missing", arena_id)
        return
    caption = msg.ADMIN_NOTIFY_NEW_ARENA_PREFIX + format_admin_arena_pending_caption(arena)
    kb = _arena_keyboard(arena_id)
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        for chat_id in admin_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=caption, reply_markup=kb)
            except Exception:  # noqa: BLE001
                logger.exception("arena admin notify failed chat_id=%s arena_id=%s", chat_id, arena_id)
    finally:
        await bot.session.close()
