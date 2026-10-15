"""Окно «сегодня» по Минску — границы суток (без сдвига главной на завтра)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from zoneinfo import ZoneInfo

from src.application.ice_time_windows import resolve_window

MSK = timezone(timedelta(hours=3))


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=MSK).astimezone(timezone.utc)


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
