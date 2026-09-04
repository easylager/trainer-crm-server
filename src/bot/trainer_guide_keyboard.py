"""Inline support + FAQ keyboard for trainer bot help surfaces (TASK-013).

Shared by ``/guide``, gate middleware, and welcome/conflict messages so the empty
slash-command menu is not the only path to support.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from src.shared.config import Settings

TRAINER_SUPPORT_CALLBACK = "trainer:support"
TRAINER_FAQ_CALLBACK = "trainer:faq"


def trainer_faq_webapp_url() -> str | None:
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.lower().startswith("https://"):
        return f"{base}/webapp/trainer-faq"
    return None


def trainer_guide_keyboard() -> InlineKeyboardMarkup:
    """Support + FAQ Mini App (HTTPS); without HTTPS — FAQ callback stub."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="💬 Написать в поддержку", callback_data=TRAINER_SUPPORT_CALLBACK)],
    ]
    faq_url = trainer_faq_webapp_url()
    if faq_url:
        rows.append([InlineKeyboardButton(text="FAQ", web_app=WebAppInfo(url=faq_url))])
    else:
        rows.append([InlineKeyboardButton(text="FAQ", callback_data=TRAINER_FAQ_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def merge_inline_keyboards(*markups: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    """Concatenate inline rows; skip empty markups. Returns None if nothing left."""
    rows: list[list[InlineKeyboardButton]] = []
    for m in markups:
        if m and m.inline_keyboard:
            rows.extend(list(m.inline_keyboard))
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def keyboard_has_support_button(markup: InlineKeyboardMarkup | None) -> bool:
    if not markup or not markup.inline_keyboard:
        return False
    for row in markup.inline_keyboard:
        for btn in row:
            if getattr(btn, "callback_data", None) == TRAINER_SUPPORT_CALLBACK:
                return True
    return False
