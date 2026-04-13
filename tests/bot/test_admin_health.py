"""Unit tests for admin /version message formatting (no Telegram, no HTTP)."""
from __future__ import annotations

from src.bot.admin_health import format_admin_version_message
from src.shared.config import Settings


def test_format_admin_version_message_success_dict() -> None:
    s = Settings()
    # pydantic may load .env; we only assert structure
    text = format_admin_version_message(
        s,
        {"status": "ok", "db": "ok", "s3": "skip"},
    )
    assert "Версия и health" in text
    assert "status=" in text or "<code>ok</code>" in text
    assert "db=" in text or "ok</code>" in text
    assert "Notification-service" in text


def test_format_admin_version_message_error_string() -> None:
    s = Settings()
    text = format_admin_version_message(s, "таймаут")
    assert "недоступен" in text
    assert "таймаут" in text
    assert "Notification-service" in text
