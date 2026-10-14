"""Закрытый зимний каток не должен выглядеть как открытый на этой неделе."""

from src.application.place_page import _b_hours_rows

_DAILY = {
    "weekly": {day: ["08:00", "22:00"] for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
}


def test_season_closed_hours_are_not_this_weeks_timetable() -> None:
    rows = _b_hours_rows({"schedule_mode": "season_closed", "opening_hours": _DAILY})
    assert rows == [("В сезоне", "каждый день 8:00–22:00")]


def test_winter_rink_outside_calendar_season_is_not_open_now() -> None:
    rows = _b_hours_rows({"schedule_mode": "auto", "in_season": False, "opening_hours": _DAILY})
    assert rows == [("В сезоне", "каждый день 8:00–22:00")]


def test_open_place_says_open_every_day() -> None:
    rows = _b_hours_rows({"schedule_mode": "auto", "in_season": True, "opening_hours": _DAILY})
    assert rows == [("Открыто", "каждый день 8:00–22:00")]
