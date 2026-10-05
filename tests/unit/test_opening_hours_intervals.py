from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.application.arena_profile import (
    format_intervals_ru,
    intervals_for_weekday,
    normalize_hhmm,
)
from src.application.arena_public_use_cases import _place_line
from src.application.place_page import open_now_label

LYZHEROLLER_HOURS = {
    "daily": {"open": "09:00", "close": "23:00"},
    "rental_close": "21:00",
    "track_close": "23:00",
    "free_entry": True,
}


def test_intervals_for_weekday_daily_uniform() -> None:
    assert intervals_for_weekday(LYZHEROLLER_HOURS, 0) == [("09:00", "23:00")]
    assert format_intervals_ru(intervals_for_weekday(LYZHEROLLER_HOURS, 0)) == "09:00–23:00"


def test_open_now_during_evening_track_window() -> None:
    card = {"opening_hours": LYZHEROLLER_HOURS, "timezone": "Europe/Minsk"}
    # Monday 2026-10-05 22:00 Minsk — after rental close, track still open until 23:00
    now = datetime(2026, 10, 5, 19, 0, tzinfo=ZoneInfo("UTC"))  # 22:00 Minsk
    assert open_now_label(card, now=now) == "Открыто до 23:00"


def test_place_line_mass_access() -> None:
    line = _place_line(
        {
            "venue_type": "other",
            "opening_hours": LYZHEROLLER_HOURS,
            "amenities": {"skate_rental": True},
        }
    )
    assert "прокат до 21:00" in line
    assert "вход бесплатно" in line
    assert "сегодня" in line.lower() or "ежедневно" in line.lower()


def test_normalize_hhmm() -> None:
    assert normalize_hhmm("7:00") == "07:00"
