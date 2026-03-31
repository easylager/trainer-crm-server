"""Regression: trainer bot UX strings live in messages.py (constitution § VII)."""

from src.bot import messages as msg


def test_trainer_webapp_and_error_constants_non_empty() -> None:
    assert len(msg.TRAINER_EDITOR_OPEN_HINT) > 20
    assert len(msg.TRAINER_BOOKINGS_OPEN_WEBAPP) > 10
    assert len(msg.TRAINER_ERROR_REQUEST_GONE) > 10
    assert len(msg.TRAINER_ERROR_NO_SERVICES) > 10
    assert len(msg.TRAINER_INVITE_INTRO_HTML) > 30
    assert len(msg.TRAINER_INVITE_PLAIN_CLIENT_WITH_CATALOG) > 40
    assert "{deep_link}" in msg.TRAINER_INVITE_PLAIN_CLIENT_WITH_CATALOG
