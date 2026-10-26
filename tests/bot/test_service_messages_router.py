"""Служебные сообщения Telegram не доходят до общего fallback бота.

``write_access_allowed`` приходит, когда человек разрешил боту писать из Mini App;
раньше бот отвечал на него «Нажмите кнопку Главная…».
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Chat, Message, Update, User, WriteAccessAllowed

from src.bot.handlers.service_messages import build_service_messages_router, is_service_message


def _message(**content) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=42, type="private"),
        from_user=User(id=42, is_bot=False, first_name="Аня"),
        **content,
    )


def test_write_access_allowed_is_service_and_text_is_not() -> None:
    assert is_service_message(_message(write_access_allowed=WriteAccessAllowed(from_request=True)))
    assert not is_service_message(_message(text="привет"))


@pytest.mark.asyncio
async def test_service_message_never_reaches_fallback() -> None:
    seen: list[str] = []
    fallback = Router()

    @fallback.message()
    async def _fallback(message: Message) -> None:
        seen.append(message.content_type)

    dp = Dispatcher()
    dp.include_router(build_service_messages_router())
    dp.include_router(fallback)
    bot = Bot(token="42:TEST")
    try:
        await dp.feed_update(bot, Update(update_id=1, message=_message(write_access_allowed=WriteAccessAllowed())))
        await dp.feed_update(bot, Update(update_id=2, message=_message(text="привет")))
    finally:
        await bot.session.close()
    assert seen == ["text"]


def test_router_can_be_built_for_each_bot() -> None:
    Dispatcher().include_router(build_service_messages_router())
    Dispatcher().include_router(build_service_messages_router())
