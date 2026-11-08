"""Карточка нового отзыва админам с кнопками «Подтвердить» / «Отклонить» (по образцу ``place_suggestion_notify``).

Шлёт через админ-бота; сбои только в лог — отзыв клиента из-за уведомления не должен пропасть.
"""
from __future__ import annotations

import html
import logging
from typing import Any, Mapping

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.application.review_moderation_use_cases import load_review_for_moderation
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings
from src.shared.review_moderation import REVIEW_APPROVE, REVIEW_MOD_PREFIX, REVIEW_REJECT

logger = logging.getLogger(__name__)

_TEXT_MAX = 3000


def format_review_card(review: Mapping[str, Any]) -> str:
    """«Новый отзыв · Тренер · ★5 · Клиент» + текст (HTML-safe, длинный обрезан под лимит Telegram)."""
    body = str(review.get("review_text") or "").strip()
    if len(body) > _TEXT_MAX:
        body = body[:_TEXT_MAX].rstrip() + "…"
    stars = "★" * int(review["rating"]) + "☆" * (5 - int(review["rating"]))
    return (
        f"<b>Отзыв на проверку</b> №{int(review['id'])}\n"
        f"Тренер: {html.escape(str(review['trainer_name']))}\n"
        f"Ученик: {html.escape(str(review['client_name']))} · {stars}\n\n"
        f"«{html.escape(body)}»"
    )


def review_keyboard(rating_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"{REVIEW_MOD_PREFIX}{REVIEW_APPROVE}:{int(rating_id)}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"{REVIEW_MOD_PREFIX}{REVIEW_REJECT}:{int(rating_id)}"),
            ]
        ]
    )


async def send_review_cards(rating_ids: list[int]) -> None:
    """Одна карточка на отзыв каждому админу; нет токена или админов — тихо ничего."""
    settings = Settings()
    token = settings.telegram_bot_token_admin
    admin_ids = list(dict.fromkeys(settings.admin_telegram_ids or []))
    if not token or not admin_ids or not rating_ids:
        return
    cards: list[tuple[int, str]] = []
    async with async_session_factory() as session:
        for rid in rating_ids:
            review = await load_review_for_moderation(session, rid)
            if review and review["status"] == "pending" and review["review_text"]:
                cards.append((rid, format_review_card(review)))
    if not cards:
        return
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        for rid, caption in cards:
            for chat_id in admin_ids:
                try:
                    await bot.send_message(chat_id=chat_id, text=caption, reply_markup=review_keyboard(rid))
                except Exception:  # noqa: BLE001
                    logger.exception("review moderation notify failed chat_id=%s rating_id=%s", chat_id, rid)
    finally:
        await bot.session.close()


async def notify_admins_new_review(client_telegram_id: int, trainer_id: int) -> None:
    """После того как клиент прислал текст отзыва: найти строку оценки и отправить карточку."""
    from sqlalchemy import text

    async with async_session_factory() as session:
        rid = (
            await session.execute(
                text(
                    "SELECT id FROM trainer_ratings WHERE trainer_id = :t AND client_telegram_id = :c "
                    "AND review_status = 'pending'"
                ),
                {"t": int(trainer_id), "c": int(client_telegram_id)},
            )
        ).scalar()
    if rid is not None:
        await send_review_cards([int(rid)])
