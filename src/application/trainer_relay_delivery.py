"""Send relay messages through Telegram bots (trainer↔client, two-bot setup)."""

from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.bot import messages as msg
from src.shared.config import Settings


async def send_client_relay_from_trainer(
    *,
    client_telegram_id: int,
    trainer_display_name: str,
    body_text: str,
    session_id: int,
) -> None:
    """Private chat → **client bot** DM."""
    settings = Settings()
    client_bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        text_html = msg.format_client_relay_from_trainer_html(
            trainer_name=trainer_display_name,
            body_text=body_text,
        )
        kb = msg.build_client_relay_keyboard(session_id)
        await client_bot.send_message(
            chat_id=int(client_telegram_id),
            text=text_html,
            reply_markup=kb,
        )
    finally:
        await client_bot.session.close()


async def send_trainer_relay_from_client(
    *,
    trainer_telegram_id: int,
    client_display_name: str,
    body_text: str,
    session_id: int,
) -> None:
    """Private chat → **trainer bot** DM with reply/close chrome."""
    settings = Settings()
    trainer_bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        text_html = msg.format_trainer_relay_from_client_html(
            client_name=client_display_name,
            body_text=body_text,
        )
        kb = msg.build_trainer_relay_keyboard(session_id)
        await trainer_bot.send_message(
            chat_id=int(trainer_telegram_id),
            text=text_html,
            reply_markup=kb,
        )
    finally:
        await trainer_bot.session.close()


async def send_trainer_plain_notification(*, telegram_chat_id: int, html_text: str) -> None:
    """Trainer bot message without keyboards (hints after close)."""
    settings = Settings()
    trainer_bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await trainer_bot.send_message(chat_id=int(telegram_chat_id), text=html_text)
    finally:
        await trainer_bot.session.close()


async def send_client_plain_notification(*, telegram_chat_id: int, html_text: str) -> None:
    """Client bot DM without keyboards."""
    settings = Settings()
    client_bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await client_bot.send_message(chat_id=int(telegram_chat_id), text=html_text)
    finally:
        await client_bot.session.close()
