"""Кнопки и строка решения под сообщением «Своя услуга #N» в админ-боте."""
from __future__ import annotations

import html
from typing import Any, Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

SERVICE_DIRECTION_PREFIX = "svd:"
HIDE_TOKEN = "n"
CHANGE_TOKEN = "c"
HIDE_BUTTON = "Не показывать"
CHANGE_BUTTON = "Сменить"
DECISION_MARK = "\n\n➡️ "


def direction_keyboard(service_id: int, directions: Sequence[dict[str, Any]]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=str(d["name"]), callback_data=f"{SERVICE_DIRECTION_PREFIX}{service_id}:{d['id']}"
        )
        for d in directions
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append(
        [InlineKeyboardButton(text=HIDE_BUTTON, callback_data=f"{SERVICE_DIRECTION_PREFIX}{service_id}:{HIDE_TOKEN}")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def change_keyboard(service_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=CHANGE_BUTTON, callback_data=f"{SERVICE_DIRECTION_PREFIX}{service_id}:{CHANGE_TOKEN}"
                )
            ]
        ]
    )


def decision_line(direction_name: str | None, admin_label: str) -> str:
    who = html.escape(admin_label)
    if direction_name is None:
        return f"Скрыто из каталога · {who}"
    return f"Привязано к: {html.escape(direction_name)} · {who}"


def strip_decision(html_text: str) -> str:
    """Исходный текст сообщения без ранее добавленной строки решения."""
    return html_text.split(DECISION_MARK, 1)[0]
