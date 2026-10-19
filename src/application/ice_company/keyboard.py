"""Сборка inline-кнопок для Telegram (aiogram и сырой Bot API)."""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton


def _style_kwargs(button: dict[str, str]) -> dict[str, str]:
    style = (button.get("style") or "").strip()
    if style in ("primary", "danger", "success"):
        return {"style": style}
    return {}


def inline_button(button: dict[str, str]) -> InlineKeyboardButton:
    text = button["text"]
    extra = _style_kwargs(button)
    if button.get("url"):
        return InlineKeyboardButton(text=text, url=button["url"], **extra)
    if button.get("data"):
        return InlineKeyboardButton(text=text, callback_data=button["data"], **extra)
    if button.get("switch_inline"):
        return InlineKeyboardButton(
            text=text,
            switch_inline_query=button["switch_inline"],
            **extra,
        )
    raise ValueError(f"unsupported inline button: {button!r}")


def inline_button_json(button: dict[str, str]) -> dict[str, Any]:
    payload: dict[str, Any] = {"text": button["text"]}
    payload.update(_style_kwargs(button))
    if button.get("url"):
        payload["url"] = button["url"]
    elif button.get("data"):
        payload["callback_data"] = button["data"]
    elif button.get("switch_inline"):
        payload["switch_inline_query"] = button["switch_inline"]
    else:
        raise ValueError(f"unsupported inline button: {button!r}")
    return payload
