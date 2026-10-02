"""TASK-146 (Q-006): умный дефолт окна времени по дню и часу в Минске."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.application.ice_time_windows import auto_window_key, resolve_window

MSK = timezone(timedelta(hours=3))  # Минск, UTC+3


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=MSK).astimezone(timezone.utc)


@pytest.mark.parametrize(
    "now, key",
    [
        (at(2026, 9, 28, 10), "today_evening"),  # понедельник утром
        (at(2026, 9, 30, 15, 59), "today_evening"),  # среда до 16
        (at(2026, 9, 30, 19), "today_evening"),  # среда вечером
        (at(2026, 9, 30, 21, 30), "tomorrow"),  # среда поздно
        (at(2026, 10, 1, 15), "today_evening"),  # четверг днём
        (at(2026, 10, 1, 16), "weekend"),  # четверг вечер — уже выходные
        (at(2026, 10, 2, 9), "weekend"),  # пятница
        (at(2026, 10, 4, 20, 59), "weekend"),  # воскресенье до 21
        (at(2026, 10, 4, 21), "tomorrow"),  # воскресенье поздно — понедельник
    ],
)
def test_auto_rules(now, key) -> None:
    assert auto_window_key(now) == key


def test_today_evening_starts_at_16_or_now() -> None:
    w = resolve_window("auto", at(2026, 9, 28, 10))
    assert w.label == "Сегодня вечером"
    assert w.starts_at == at(2026, 9, 28, 16) and w.ends_at == at(2026, 9, 29, 0)
    late = resolve_window("today_evening", at(2026, 9, 28, 18, 30))
    assert late.starts_at == at(2026, 9, 28, 18, 30)


def test_weekend_window_from_friday_evening_to_monday() -> None:
    thu = resolve_window("weekend", at(2026, 10, 1, 17))
    assert thu.starts_at == at(2026, 10, 2, 16) and thu.ends_at == at(2026, 10, 5, 0)
    sat = resolve_window("weekend", at(2026, 10, 3, 12))
    assert sat.starts_at == at(2026, 10, 3, 12) and sat.ends_at == at(2026, 10, 5, 0)


def test_tomorrow_is_the_whole_next_day_and_any_means_no_window() -> None:
    w = resolve_window("tomorrow", at(2026, 9, 30, 22))
    assert w.starts_at == at(2026, 10, 1, 0) and w.ends_at == at(2026, 10, 2, 0)
    assert resolve_window("any") is None
    assert resolve_window("nonsense") is None
    assert resolve_window(None) is None
