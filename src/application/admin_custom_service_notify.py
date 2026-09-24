"""
Сказать админам, что тренер вписал услугу, которой у нас не было.

Без этого своя услуга живёт вслепую: клиент её на карточке видит, а мы — нет,
и «поднять» удачную формулировку в общий список каталога (``is_public=true``)
некому. Зеркалит ``admin_arena_notify``: тот же тихий режим — упавшее
уведомление не роняет запрос тренера, он уже работает.

Кнопок модерации намеренно нет. Услуга уже работает у автора, и решение
«годится ли она всем» не срочное — делается руками в админке, когда таких
формулировок накопится достаточно, чтобы увидеть повторы.
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


async def notify_admins_new_custom_service(
    *, service_id: int, name: str, trainer_id: int
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
        f"🆕 <b>Своя услуга #{service_id}</b>\n"
        f"Название: {html.escape(name)}\n"
        f"Добавил: {who}\n\n"
        "Видна только на карточке автора. Чтобы пустить её в общий фильтр каталога — "
        f"<code>UPDATE services SET is_public = true WHERE id = {service_id};</code>"
    )

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        for chat_id in admin_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=caption)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "custom service admin notify failed chat_id=%s service_id=%s",
                    chat_id,
                    service_id,
                )
    finally:
        await bot.session.close()
