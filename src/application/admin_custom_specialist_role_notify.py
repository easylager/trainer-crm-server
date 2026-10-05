"""
Сказать админам, что тренер вписал роль, которой нет в подсказках онбординга.

Своя услуга — отдельная строка в ``services`` и уведомление при создании.
Своя роль — только текст в анкете: без пинга админ не видит повторяющиеся
формулировки, которые стоит добавить в ``SUGGESTED_ROLES``.
"""
from __future__ import annotations

import html
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import text

from src.infrastructure.db import async_session_factory
from src.shared.config import Settings

logger = logging.getLogger(__name__)


async def notify_admins_new_custom_specialist_role(
    *, role: str, trainer_id: int
) -> None:
    settings = Settings()
    token = settings.telegram_bot_token_admin
    admin_ids = list(dict.fromkeys(settings.admin_telegram_ids or []))
    if not token or not admin_ids:
        return

    async with async_session_factory() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT p.first_name, p.last_name, t.telegram_username
                    FROM trainers t
                    LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
                    WHERE t.id = :tid
                    """
                ),
                {"tid": trainer_id},
            )
        ).fetchone()

    trainer_name = ""
    username = ""
    if row is not None:
        trainer_name = " ".join(p for p in [row[0], row[1]] if p).strip()
        username = (row[2] or "").strip()
    who = html.escape(trainer_name) if trainer_name else f"id={trainer_id}"
    if username:
        who += f" (@{html.escape(username)})"

    caption = (
        "🆕 <b>Своя роль «Кто я»</b>\n"
        f"Формулировка: {html.escape(role)}\n"
        f"Тренер: {who}\n\n"
        "Роль уже на карточке автора. Если формулировка удачная — добавьте её "
        "в подсказки онбординга (<code>SUGGESTED_ROLES</code>)."
    )

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        for chat_id in admin_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=caption)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "custom specialist role admin notify failed chat_id=%s trainer_id=%s",
                    chat_id,
                    trainer_id,
                )
    finally:
        await bot.session.close()
