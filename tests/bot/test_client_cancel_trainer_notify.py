"""Client-cancel → trainer notify: resilient Telegram keyboard."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot import messages as msg
from src.bot.booking_party_notify import _send_client_cancel_trainer


def test_cancel_keyboard_skips_write_when_client_is_trainer() -> None:
    kb = msg.build_trainer_client_cancel_notification_keyboard(
        webapp_base_url="https://example.com",
        slot_id=1,
        exclude_client_id=2,
        client_telegram_id=1001,
        trainer_telegram_id=1001,
    )
    assert kb is not None
    urls = [
        getattr(btn, "url", None)
        for row in kb.inline_keyboard
        for btn in row
    ]
    assert not any(u and str(u).startswith("tg://user") for u in urls)


def test_cancel_keyboard_includes_write_for_other_client() -> None:
    kb = msg.build_trainer_client_cancel_notification_keyboard(
        webapp_base_url="https://example.com",
        slot_id=1,
        exclude_client_id=2,
        client_telegram_id=2002,
        trainer_telegram_id=1001,
    )
    assert kb is not None
    urls = [
        getattr(btn, "url", None)
        for row in kb.inline_keyboard
        for btn in row
    ]
    assert any(u and str(u).startswith("tg://user?id=2002") for u in urls)


@pytest.mark.asyncio
async def test_send_client_cancel_trainer_retries_without_markup_on_privacy() -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(
        side_effect=[
            RuntimeError("Telegram server says - Bad Request: BUTTON_USER_PRIVACY_RESTRICTED"),
            None,
        ]
    )
    row = {
        "recipient_telegram_id": 1001,
        "payload": {
            "client_name": "Анна",
            "date_str": "01.01",
            "day_label": "пн",
            "time_str": "10:00",
            "reason": None,
            "slot_id": 5,
            "client_id": 9,
            "client_telegram_id": 2002,
        },
    }
    await _send_client_cancel_trainer(bot, row)
    assert bot.send_message.await_count == 2
    # Second attempt must not include tg://user write button (privacy-safe retry).
    second_kb = bot.send_message.await_args_list[1].kwargs.get("reply_markup")
    if second_kb is not None:
        urls = [
            getattr(btn, "url", None)
            for row_kb in second_kb.inline_keyboard
            for btn in row_kb
        ]
        assert not any(u and str(u).startswith("tg://user") for u in urls)
