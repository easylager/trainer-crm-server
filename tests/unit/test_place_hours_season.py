"""Закрытый зимний каток не должен выглядеть как открытый на этой неделе."""

from src.application.place_page import _hours_html

_DAILY = {
    "weekly": {day: ["08:00", "22:00"] for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
}


def test_season_closed_hours_are_not_this_weeks_timetable() -> None:
    html = _hours_html({"schedule_mode": "season_closed", "opening_hours": _DAILY})
    assert "Когда можно приехать" not in html
    assert "Часы в сезоне" in html
    assert "Сейчас приехать нельзя" in html
    assert "Ежедневно" in html
    assert "8:00–22:00" in html
    assert "Пн" not in html


def test_winter_rink_outside_calendar_season_is_not_open_now() -> None:
    html = _hours_html({"schedule_mode": "auto", "in_season": False, "opening_hours": _DAILY})
    assert "Когда можно приехать" not in html
    assert "Сейчас приехать нельзя" in html
    assert "Ежедневно" in html


def test_open_place_keeps_weekday_timetable() -> None:
    html = _hours_html({"schedule_mode": "auto", "in_season": True, "opening_hours": _DAILY})
    assert "Когда можно приехать" in html
    assert "Пн" in html
    assert "Часы в сезоне" not in html
