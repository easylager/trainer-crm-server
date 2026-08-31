"""
Notify admins about trainer events: first login, profile ready for moderation, first booking.
Failures are logged, never raised to callers.
"""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.infrastructure.db import async_session_factory
from src.shared.config import Settings

logger = logging.getLogger(__name__)


async def notify_admins_trainer_first_login(trainer_id: int, trainer: dict) -> None:
    """Notify admins when a new trainer logs in for the first time."""
    settings = Settings()
    if not settings.telegram_bot_token_admin or not settings.admin_telegram_ids:
        logger.warning("Admin bot not configured, skipping first login notification")
        return

    first_name = trainer.get("first_name", "")
    last_name = trainer.get("last_name", "") or ""
    username = trainer.get("telegram_username", "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    full_name = f"{first_name} {last_name}".strip() or "Unknown"
    username_str = f"@{username}" if username else "No username"

    text = (
        f"🆕 <b>Новый тренер в боте</b>\n\n"
        f"👤 {full_name}\n"
        f"📱 {username_str}\n"
        f"🆔 Trainer ID: {trainer_id}\n"
        f"⏰ {now}"
    )

    bot = Bot(
        token=settings.telegram_bot_token_admin,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    admin_ids = list(dict.fromkeys(settings.admin_telegram_ids or []))
    for chat_id in admin_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception(
                "failed to notify admin about trainer first login, trainer_id=%s chat_id=%s",
                trainer_id,
                chat_id,
            )


async def notify_admins_trainer_profile_ready_for_moderation(trainer_id: int, trainer: dict) -> None:
    """Notify admins when a trainer profile is ready for moderation."""
    settings = Settings()
    if not settings.telegram_bot_token_admin or not settings.admin_telegram_ids:
        logger.warning("Admin bot not configured, skipping profile ready notification")
        return

    first_name = trainer.get("first_name", "")
    last_name = trainer.get("last_name", "") or ""
    username = trainer.get("telegram_username", "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    full_name = f"{first_name} {last_name}".strip() or "Unknown"
    username_str = f"@{username}" if username else "No username"

    text = (
        f"✅ <b>Профиль готов к модерации</b>\n\n"
        f"👤 {full_name}\n"
        f"📱 {username_str}\n"
        f"🆔 Trainer ID: {trainer_id}\n"
        f"⏰ {now}\n\n"
        f"<i>Блок «Знакомство» заполнен</i>"
    )

    bot = Bot(
        token=settings.telegram_bot_token_admin,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    admin_ids = list(dict.fromkeys(settings.admin_telegram_ids or []))
    for chat_id in admin_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception(
                "failed to notify admin about profile ready for moderation, trainer_id=%s chat_id=%s",
                trainer_id,
                chat_id,
            )


async def notify_admins_trainer_first_booking(
    trainer_id: int, trainer: dict, booking: dict
) -> None:
    """Notify admins when a trainer makes their first booking."""
    settings = Settings()
    if not settings.telegram_bot_token_admin or not settings.admin_telegram_ids:
        logger.warning("Admin bot not configured, skipping first booking notification")
        return

    first_name = trainer.get("first_name", "")
    last_name = trainer.get("last_name", "") or ""
    username = trainer.get("telegram_username", "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    full_name = f"{first_name} {last_name}".strip() or "Unknown"
    username_str = f"@{username}" if username else "No username"

    # Extract booking info if available
    client_name = booking.get("client_name", "Unknown")
    booking_date = booking.get("start_at", "")
    if booking_date and hasattr(booking_date, "strftime"):
        booking_date = booking_date.strftime("%Y-%m-%d %H:%M")

    text = (
        f"🎉 <b>Первая запись тренера</b>\n\n"
        f"👤 {full_name}\n"
        f"📱 {username_str}\n"
        f"🆔 Trainer ID: {trainer_id}\n"
        f"👨‍💼 Клиент: {client_name}\n"
    )

    if booking_date:
        text += f"📅 Дата: {booking_date}\n"

    text += f"⏰ {now}"

    bot = Bot(
        token=settings.telegram_bot_token_admin,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    admin_ids = list(dict.fromkeys(settings.admin_telegram_ids or []))
    for chat_id in admin_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception(
                "failed to notify admin about trainer first booking, trainer_id=%s chat_id=%s",
                trainer_id,
                chat_id,
            )
