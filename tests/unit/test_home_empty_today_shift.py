"""Вечером «Сегодня» пусто — главная и список города открывают ближайший день с сеансами."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from zoneinfo import ZoneInfo

from src.application.ice_time_windows import (
    home_empty_today_should_shift,
    home_fallback_periods_after_empty_today,
    home_shift_note_for_period,
    resolve_window,
)

MSK = timezone(timedelta(hours=3))


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=MSK).astimezone(timezone.utc)


def test_should_shift_only_for_today_default_or_explicit() -> None:
    assert home_empty_today_should_shift(None, "today")
    assert not home_empty_today_should_shift("today", "today")
    assert not home_empty_today_should_shift("tomorrow", "tomorrow")
    assert not home_empty_today_should_shift(None, "weekend")


def test_fallback_periods_start_with_tomorrow_minsk_midnight() -> None:
    now = at(2026, 10, 14, 0, 0)
    keys = [k for k, _ in home_fallback_periods_after_empty_today(now)]
    assert keys[0] == "tomorrow"
    assert keys[1] == "day"
    tomorrow = resolve_window("tomorrow", now)
    assert tomorrow is not None
    tz = ZoneInfo("Europe/Minsk")
    # Полночь 14-го по Минску — «завтра» это уже 15-е.
    assert tomorrow.starts_at.astimezone(tz).date() == date(2026, 10, 15)


@pytest.mark.parametrize(
    "now",
    [
        at(2026, 10, 13, 23, 59),
        at(2026, 10, 14, 0, 0),
    ],
)
def test_today_window_ends_at_minsk_midnight(now) -> None:
    today = resolve_window("today", now)
    assert today is not None
    local_end = today.ends_at.astimezone(ZoneInfo("Europe/Minsk"))
    assert local_end.hour == 0 and local_end.minute == 0
    assert local_end.date() == now.astimezone(ZoneInfo("Europe/Minsk")).date() + timedelta(days=1)


def test_shift_note_copy() -> None:
    now = at(2026, 10, 7, 22)
    today = now.astimezone(ZoneInfo("Europe/Minsk")).date()
    tom = resolve_window("tomorrow", now)
    assert tom is not None
    assert "завтра" in home_shift_note_for_period("tomorrow", tom, today=today).lower()
    later_key, later = home_fallback_periods_after_empty_today(now)[1]
    assert later_key == "day"
    assert "окт" in home_shift_note_for_period("day", later, today=today).lower()
