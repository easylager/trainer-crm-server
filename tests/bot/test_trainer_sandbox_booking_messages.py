"""Trainer bot copy for onboarding demo (sandbox) bookings."""

from __future__ import annotations

from src.bot import messages as msg


def test_sandbox_booking_done_message_is_onboarding_friendly() -> None:
    text = msg.TRAINER_CREATE_BOOKING_SANDBOX_DONE.format(
        client_name="Александр К.",
        date="31.08",
        day="Пн",
        time="16:30",
    )
    assert "Тестовая запись" in text
    assert "учебный пример" in text
    assert "Ближайшие записи" in text
    assert "Детали записи" not in text
    assert "не отправляются — это пример" not in text


def test_sandbox_booking_done_reply_markup_opens_hub() -> None:
    kb = msg.build_trainer_sandbox_booking_done_reply_markup(
        webapp_base="https://example.com",
    )
    assert kb is not None
    btn = kb.inline_keyboard[0][0]
    assert btn.text == msg.TRAINER_BUTTON_HOME_WEBAPP
    assert btn.web_app is not None
    assert btn.web_app.url.endswith("/webapp/trainer-home")
