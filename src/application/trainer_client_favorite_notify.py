"""
Trainer push when a catalog client bookmarks them (client_trainer_edges.is_saved true).

One-shot per transition to saved — not repeated if the heart is toggled off and on again
(the next save after unsave will notify again; first duplicate save does not).
"""
from __future__ import annotations

import html
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import get_trainer_telegram_id
from src.application.subscription_tier_use_cases import trainer_has_analytics_access
from src.bot import messages as msg
from src.shared.config import Settings

logger = logging.getLogger(__name__)


async def _catalog_client_display_label(session: AsyncSession, catalog_telegram_id: int) -> str:
    r = await session.execute(
        text(
            """
            SELECT first_name, last_name, telegram_username
            FROM clients
            WHERE telegram_id = :tid
            LIMIT 1
            """
        ),
        {"tid": catalog_telegram_id},
    )
    row = r.mappings().first()
    if not row:
        return "Клиент"
    fn = (row.get("first_name") or "").strip()
    ln = (row.get("last_name") or "").strip()
    name = f"{fn} {ln}".strip()
    if name:
        return name
    un = (row.get("telegram_username") or "").strip().lstrip("@")
    if un:
        return f"@{un}"
    return "Клиент"


async def notify_trainer_new_catalog_favorite(
    *,
    session: AsyncSession,
    trainer_id: int,
    client_catalog_telegram_id: int,
) -> None:
    """Best-effort Telegram message to trainer bot; swallows send errors after logging."""
    settings = Settings()
    if not settings.telegram_bot_token_trainer:
        return
    trainer_tid = await get_trainer_telegram_id(session, trainer_id)
    if not trainer_tid:
        return

    raw_label = await _catalog_client_display_label(session, client_catalog_telegram_id)
    safe_label = html.escape(raw_label)
    body = msg.TRAINER_CLIENT_FAVORITE_ADDED_HTML.format(client_label=safe_label)

    reply_markup: InlineKeyboardMarkup | None = None
    if await trainer_has_analytics_access(session, trainer_id):
        base = (settings.webapp_base_url or "").rstrip("/")
        if base.lower().startswith("https://"):
            stats_url = f"{base}/webapp/trainer-stats"
            reply_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.TRAINER_BUTTON_FAVORITE_STATS_WEBAPP,
                            web_app=WebAppInfo(url=stats_url),
                        ),
                    ],
                ]
            )

    bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await bot.send_message(
            chat_id=int(trainer_tid),
            text=body,
            reply_markup=reply_markup,
        )
    except Exception:
        logger.exception(
            "Failed to send catalog-favorite notification trainer_id=%s client_tid=%s",
            trainer_id,
            client_catalog_telegram_id,
        )
    finally:
        await bot.session.close()
