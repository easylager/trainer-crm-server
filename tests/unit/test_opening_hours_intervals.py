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
    "weekly": {
        "mon": [["11:00", "15:00"], ["19:00", "22:00"]],
        "sat": [["11:00", "22:00"]],
        "sun": [["08:00", "22:00"]],
    },
    "rental_close": "21:00",
    "free_entry": True,
}


def test_intervals_for_weekday_split_day() -> None:
    assert intervals_for_weekday(LYZHEROLLER_HOURS, 0) == [("11:00", "15:00"), ("19:00", "22:00")]
    assert format_intervals_ru(intervals_for_weekday(LYZHEROLLER_HOURS, 0)) == "11:00–15:00 и 19:00–22:00"


def test_open_now_between_split_windows() -> None:
    card = {"opening_hours": LYZHEROLLER_HOURS, "timezone": "Europe/Minsk"}
    # Monday 2026-10-05 16:00 Minsk — between school block and evening window
    now = datetime(2026, 10, 5, 13, 0, tzinfo=ZoneInfo("UTC"))  # 16:00 Minsk
    assert open_now_label(card, now=now) == "Откроется в 19:00"


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
