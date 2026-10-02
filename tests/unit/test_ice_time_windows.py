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
        (at(2026, 10, 1, 16), "today_evening"),  # четверг вечер — ещё не выходные
        (at(2026, 10, 2, 9), "today_evening"),  # пятница утром
        (at(2026, 10, 2, 19), "today_evening"),  # пятница вечером — «сегодня вечером», не «выходные»
        (at(2026, 10, 2, 21), "weekend"),  # пятница поздно — дальше уже суббота
        (at(2026, 10, 3, 9), "weekend"),  # суббота
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


def test_weekend_window_is_saturday_and_sunday() -> None:
    # Пятница вечером в «Выходные» не входит: иначе карточка «Сегодня 16:15» под этим чипом.
    fri = resolve_window("weekend", at(2026, 10, 2, 17))
    assert fri.starts_at == at(2026, 10, 3, 0) and fri.ends_at == at(2026, 10, 5, 0)
    mon = resolve_window("weekend", at(2026, 9, 28, 10))
    assert mon.starts_at == at(2026, 10, 3, 0) and mon.ends_at == at(2026, 10, 5, 0)
    sat = resolve_window("weekend", at(2026, 10, 3, 12))
    assert sat.starts_at == at(2026, 10, 3, 12) and sat.ends_at == at(2026, 10, 5, 0)
    sun = resolve_window("weekend", at(2026, 10, 4, 18))
    assert sun.starts_at == at(2026, 10, 4, 18) and sun.ends_at == at(2026, 10, 5, 0)


def test_tomorrow_is_the_whole_next_day_and_any_means_no_window() -> None:
    w = resolve_window("tomorrow", at(2026, 9, 30, 22))
    assert w.starts_at == at(2026, 10, 1, 0) and w.ends_at == at(2026, 10, 2, 0)
    assert resolve_window("any") is None
    assert resolve_window("nonsense") is None
    assert resolve_window(None) is None
