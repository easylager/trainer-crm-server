"""Send catalog-listed invite push (support + client invite link copy button)."""

from __future__ import annotations

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from src.application.trainer_invite_links import build_trainer_universal_invite_link
from src.bot import messages as msg
from src.bot.trainer_guide_keyboard import TRAINER_SUPPORT_CALLBACK
from src.shared.config import Settings


def catalog_listed_invite_push_keyboard(copy_link: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="💬 Написать в поддержку",
                callback_data=TRAINER_SUPPORT_CALLBACK,
            )
        ],
    ]
    if copy_link:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔗 Ссылка для клиентов",
                    copy_text=CopyTextButton(text=copy_link),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_trainer_catalog_listed_invite_push(
    bot: Bot,
    *,
    chat_id: int,
    trainer_id: int,
) -> str | None:
    """
    Send HTML body + keyboard. Returns None on success, or an error token
    (``missing_username``) when the link cannot be built.
    """
    settings = Settings()
    link, err = build_trainer_universal_invite_link(
        client_bot_username=settings.client_bot_username,
        trainer_id=int(trainer_id),
    )
    if err:
        return err
    await bot.send_message(
        chat_id=chat_id,
        text=msg.TRAINER_CATALOG_LISTED_INVITE_PUSH_HTML,
        parse_mode=ParseMode.HTML,
        reply_markup=catalog_listed_invite_push_keyboard(link),
    )
    return None
