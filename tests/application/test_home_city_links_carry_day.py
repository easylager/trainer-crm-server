"""Главная: выбранный день едет в ссылку города, иначе выбор теряется на тапе."""

from datetime import date

from src.application.catalog_home_page import (
    _b_city_tile,
    _b_home_city_card,
    _city_list_when,
    _home_tile_when,
)

TODAY = date(2026, 10, 14)
CITY = {"slug": "minsk", "name": "Минск", "session_count": 24}


def test_explicit_window_goes_to_the_list() -> None:
    for key in ("today", "tomorrow", "weekend"):
        assert _city_list_when(key, key, selected_day=None, today=TODAY) == key


def test_default_home_keeps_the_city_page() -> None:
    assert _city_list_when(None, "weekend", selected_day=None, today=TODAY) is None


def test_picked_date_maps_only_to_what_the_list_understands() -> None:
    assert _city_list_when("day", "day", selected_day=TODAY, today=TODAY) == "today"
    assert _city_list_when("day", "day", selected_day=date(2026, 10, 15), today=TODAY) == "tomorrow"
    assert _city_list_when("day", "day", selected_day=date(2026, 10, 17), today=TODAY) is None


def test_tile_with_sessions_opens_that_window() -> None:
    assert 'href="/c/minsk?t=ice&amp;w=tomorrow"' in _b_city_tile(CITY, when_key="tomorrow", city_when="tomorrow")
    assert 'href="/c/minsk"' in _b_city_tile(CITY, when_key="today")


def test_tile_without_sessions_in_window_keeps_the_city_page() -> None:
    empty = {**CITY, "session_count": 0}
    assert 'href="/c/minsk"' in _b_city_tile(empty, when_key="tomorrow", city_when="tomorrow")


def test_home_shift_carries_tomorrow_into_city_tiles() -> None:
    note = "На сегодня всё — вот завтра"
    assert _home_tile_when(None, "tomorrow", selected_day=None, today=TODAY, home_shift_note=note) == "tomorrow"
    assert _home_tile_when(None, "today", selected_day=None, today=TODAY, home_shift_note=note) is None


def test_your_city_card_carries_the_day_but_not_over_a_sole_place() -> None:
    card = {**CITY, "href": "/c/minsk"}
    assert 'href="/c/minsk?t=ice&amp;w=weekend"' in _b_home_city_card(card, city_when="weekend")
    sole = {**CITY, "href": "/p/minsk/zamok"}
    assert 'href="/p/minsk/zamok"' in _b_home_city_card(sole, city_when="weekend")
