"""Клавиатура сообщений «следить за катком». Подписи — из макета design-v2/Share.html."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from src.application.arena_follows import FollowButton


def follow_reply_markup(buttons: tuple[FollowButton, ...] | list[FollowButton]) -> InlineKeyboardMarkup | None:
    built: list[InlineKeyboardButton] = []
    for button in buttons:
        url = (button.web_app_url or "").strip()
        if url.lower().startswith("https://"):
            built.append(InlineKeyboardButton(text=button.text, web_app=WebAppInfo(url=url)))
        elif button.callback_data:
            built.append(InlineKeyboardButton(text=button.text, callback_data=button.callback_data))
    if not built:
        return None
    if len(built) <= 2:
        return InlineKeyboardMarkup(inline_keyboard=[built])
    return InlineKeyboardMarkup(inline_keyboard=[[button] for button in built])
