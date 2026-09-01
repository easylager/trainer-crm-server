"""Trainer one-time «поделитесь ссылкой» tip, sent right after the first booking milestone."""

from __future__ import annotations

import html

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.application.trainer_client_invite_tracking import record_trainer_client_invite_link_first_copy
from src.application.trainer_invite_links import build_trainer_universal_invite_link
from src.bot import messages as msg
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings


async def send_trainer_share_catalog_tip_to_chat(
    *,
    bot: Bot,
    chat_id: int,
    trainer_id: int,
) -> None:
    """
    Second message after the first booking: the trainer's own invite link — always a link.

    Onboarding v2 asks for neither city nor prices, so the old city-scoped deep link
    (``client_{city}_{service}_{trainer}``) could not be built for most trainers, and this
    message — which fires exactly once per trainer (``share_catalog_tip_sent_at``) — degraded
    into «укажите город и услугу». The single growth push of the funnel was spent on a chore,
    at the one moment the trainer is most willing to invite someone.

    The universal ``welcome_ref_{trainer_id}`` link (the same one behind the hub paperclip)
    needs nothing but the client bot username, so there is no profile state in which we have
    nothing to send.
    """
    settings = Settings()
    link, err = build_trainer_universal_invite_link(
        client_bot_username=settings.client_bot_username,
        trainer_id=trainer_id,
    )
    if err == "missing_username":
        await bot.send_message(
            chat_id=chat_id,
            text=msg.TRAINER_SHARE_CATALOG_TIP_NO_CLIENT_BOT,
            parse_mode=ParseMode.HTML,
        )
        return
    if not link:
        return  # invalid_trainer_id — nothing honest to say, and the caller has no fallback
    tip = msg.TRAINER_SHARE_CATALOG_TIP_DEEP_ONLY_HTML.format(deep_link=html.escape(link))
    # Кнопка копирования ссылки в Telegram (встроенная функция)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text='📋 Скопировать ссылку', copy_text=link)]]
    )
    await bot.send_message(chat_id=chat_id, text=tip, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    async with async_session_factory() as session:
        await record_trainer_client_invite_link_first_copy(session, trainer_id)
