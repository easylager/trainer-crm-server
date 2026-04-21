"""Unit tests for trainer push notification window helpers."""
from datetime import time

import pytest

from src.application.trainer_notification_prefs import (
    is_local_time_in_push_window,
    validate_push_notification_window,
)


def test_validate_full_day() -> None:
    validate_push_notification_window(0, 24)


def test_validate_day_window() -> None:
    validate_push_notification_window(8, 22)


def test_validate_overnight() -> None:
    validate_push_notification_window(22, 8)


def test_validate_same_invalid() -> None:
    with pytest.raises(ValueError):
        validate_push_notification_window(8, 8)


def test_is_local_time_full_day() -> None:
    assert is_local_time_in_push_window(time(3, 0), 0, 24) is True
    assert is_local_time_in_push_window(time(23, 59), 0, 24) is True


def test_is_local_time_overnight() -> None:
    assert is_local_time_in_push_window(time(23, 0), 22, 8) is True
    assert is_local_time_in_push_window(time(7, 0), 22, 8) is True
    assert is_local_time_in_push_window(time(12, 0), 22, 8) is False
