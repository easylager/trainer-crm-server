"""
Notify admins about trainer events: first login, profile ready for moderation, first booking.
Failures are logged, never raised to callers.
"""
from __future__ import annotations

import html
import logging
import os
from datetime import date, datetime, time

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.shared.config import Settings

logger = logging.getLogger(__name__)


def _trainer_display_name(trainer: dict) -> str:
    """first_name/last_name live under trainer['profile'], not top-level (see TrainerRepository.get_by_id)."""
    profile = trainer.get("profile") or {}
    first_name = (profile.get("first_name") or "").strip()
    last_name = (profile.get("last_name") or "").strip()
    full_name = f"{first_name} {last_name}".strip()
    return full_name or "Без имени"


async def _send_to_admins(text: str, *, event: str, trainer_id: int) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        # pytest sets this for the duration of every test; never spam real admins from a test run.
        logger.debug("Skipping %s notification under pytest (trainer_id=%s)", event, trainer_id)
        return

    settings = Settings()
    if not settings.telegram_bot_token_admin or not settings.admin_telegram_ids:
        logger.warning("Admin bot not configured, skipping %s notification (trainer_id=%s)", event, trainer_id)
        return

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
                "failed to notify admin about %s, trainer_id=%s chat_id=%s", event, trainer_id, chat_id
            )


async def notify_admins_trainer_first_login(trainer_id: int, trainer: dict) -> None:
    """Notify admins when a new trainer logs in for the first time."""
    full_name = html.escape(_trainer_display_name(trainer))
    username = (trainer.get("telegram_username") or "").strip()
    username_str = f"@{html.escape(username)}" if username else "без username"
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    text = (
        f"🆕 <b>Новый тренер в боте</b>\n\n"
        f"👤 {full_name}\n"
        f"📱 {username_str}\n"
        f"🆔 Trainer ID: {trainer_id}\n"
        f"⏰ {now}"
    )
    await _send_to_admins(text, event="trainer first login", trainer_id=trainer_id)


async def notify_admins_trainer_intro_completed(trainer_id: int, trainer: dict) -> None:
    """Notify admins when a trainer fills in the intro block (name, phone, city)."""
    full_name = html.escape(_trainer_display_name(trainer))
    username = (trainer.get("telegram_username") or "").strip()
    username_str = f"@{html.escape(username)}" if username else "без username"
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    text = (
        f"✅ <b>Тренер заполнил блок «Знакомство»</b>\n\n"
        f"👤 {full_name}\n"
        f"📱 {username_str}\n"
        f"🆔 Trainer ID: {trainer_id}\n"
        f"⏰ {now}"
    )
    await _send_to_admins(text, event="trainer intro block filled", trainer_id=trainer_id)


async def notify_admins_trainer_first_booking(trainer_id: int, trainer: dict, booking: dict) -> None:
    """Notify admins when a trainer makes their first real booking."""
    full_name = html.escape(_trainer_display_name(trainer))
    username = (trainer.get("telegram_username") or "").strip()
    username_str = f"@{html.escape(username)}" if username else "без username"
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    client_name = html.escape(str(booking.get("client_name") or "Не указано"))

    slot_date = booking.get("slot_date")
    start_time = booking.get("start_time")
    date_str = slot_date.strftime("%d.%m.%Y") if isinstance(slot_date, date) else None
    time_str = start_time.strftime("%H:%M") if isinstance(start_time, time) else None

    text = (
        f"🎉 <b>Первая запись тренера</b>\n\n"
        f"👤 {full_name}\n"
        f"📱 {username_str}\n"
        f"🆔 Trainer ID: {trainer_id}\n"
        f"👨‍💼 Клиент: {client_name}\n"
    )
    if date_str:
        text += f"📅 Дата занятия: {date_str}" + (f" · {time_str}" if time_str else "") + "\n"
    text += f"⏰ {now}"

    await _send_to_admins(text, event="trainer first booking", trainer_id=trainer_id)
