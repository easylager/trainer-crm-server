"""Исходящие вызовы Bot API через лимитер процесса. 429 ждёт retry_after."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

from src.application.ice_company.lifecycle import BotBlocked, ChatMigrated, RateLimited, button_rows
from src.application.ice_company.limiter import OutboundLimiter
from src.shared.config import Settings

logger = logging.getLogger(__name__)


def _markup(buttons: list[dict[str, str]]) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    rows = []
    for group in button_rows(buttons):
        row = []
        for button in group:
            if button.get("url"):
                row.append(InlineKeyboardButton(text=button["text"], url=button["url"]))
            elif button.get("data"):
                row.append(InlineKeyboardButton(text=button["text"], callback_data=button["data"]))
        if row:
            rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


class AiogramSender:
    def __init__(self, bot: Bot, settings: Settings | None = None) -> None:
        cfg = settings or Settings()
        self.bot = bot
        self.limiter = OutboundLimiter(
            global_per_sec=cfg.ice_company_outbound_global_per_sec,
            chat_per_sec=cfg.ice_company_outbound_chat_per_sec,
            group_per_min=cfg.ice_company_outbound_group_per_min,
        )

    async def dm(self, chat_id: int, text: str, buttons: list[dict[str, str]]) -> int:
        await self.limiter.acquire(chat_id, is_group=chat_id < 0)
        try:
            msg = await self.bot.send_message(chat_id, text, reply_markup=_markup(buttons))
        except TelegramRetryAfter as exc:
            self.limiter.note_retry_after()
            raise RateLimited(float(exc.retry_after)) from exc
        except TelegramForbiddenError as exc:
            raise BotBlocked() from exc
        except TelegramBadRequest as exc:
            migrated = getattr(exc, "migrate_to_chat_id", None)
            if migrated:
                raise ChatMigrated(int(migrated)) from exc
            logger.info("ice_company dm failed: %s", type(exc).__name__)
            return 0
        return int(msg.message_id)

    async def edit(self, ref: dict[str, Any], text: str, buttons: list[dict[str, str]]) -> None:
        chat_id = ref.get("chat_id")
        is_group = bool(ref.get("is_group")) or (isinstance(chat_id, int) and chat_id < 0)
        await self.limiter.acquire(int(chat_id) if chat_id is not None else None, is_group=is_group)
        markup = _markup(buttons)
        photo = ref.get("photo_url")
        if photo and ref.get("inline_message_id"):
            try:
                await self.bot.edit_message_media(
                    media=InputMediaPhoto(media=str(photo), caption=text),
                    inline_message_id=str(ref["inline_message_id"]),
                    reply_markup=markup,
                )
                return
            except TelegramRetryAfter as exc:
                self.limiter.note_retry_after()
                raise RateLimited(float(exc.retry_after)) from exc
            except TelegramBadRequest as exc:
                if "not modified" in str(exc).lower():
                    return
                logger.info("ice_company media edit skipped: %s", type(exc).__name__)
        try:
            if ref.get("inline_message_id"):
                await self.bot.edit_message_text(
                    text,
                    inline_message_id=str(ref["inline_message_id"]),
                    reply_markup=markup,
                )
            else:
                await self.bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=ref.get("message_id"),
                    reply_markup=markup,
                )
        except TelegramRetryAfter as exc:
            self.limiter.note_retry_after()
            raise RateLimited(float(exc.retry_after)) from exc
        except TelegramBadRequest as exc:
            migrated = getattr(exc, "migrate_to_chat_id", None)
            if migrated:
                raise ChatMigrated(int(migrated)) from exc
            if "not modified" in str(exc).lower():
                return
            logger.info("ice_company edit failed: %s", type(exc).__name__)
