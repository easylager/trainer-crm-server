"""Кнопка «сообщать о новом расписании» только на неполной неделе."""

from datetime import date, timedelta

from src.application.place_page import _b_schedule_watch, schedule_strip_has_gap

TODAY = date(2026, 11, 14)


def test_gap_needs_both_a_session_and_a_dash() -> None:
    one = {TODAY: [{"id": 1}]}
    assert schedule_strip_has_gap(TODAY, one) is True
    full = {TODAY + timedelta(days=i): [{"id": i}] for i in range(7)}
    assert schedule_strip_has_gap(TODAY, full) is False
    assert schedule_strip_has_gap(TODAY, {}) is False


def test_watch_button_names_the_promise_and_carries_telegram() -> None:
    html = _b_schedule_watch("https://t.me/glide_test_bot?start=watch_9")
    assert "сообщать о новом расписании" in html
    assert "b-watch__arrow" in html and "b-watch__tg" in html
    assert html.index("сообщать о новом расписании") < html.index("b-watch__arrow") < html.index("b-watch__tg")
    assert "watch_9" in html
