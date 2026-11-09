"""Окно свободного катания на странице катка: цена — «/час», если билет почасовой."""

from __future__ import annotations

from src.application.place_page import slot_plan_prices, slot_price_lines

_WINDOW = {
    "currency_code": "RUB",
    "price_adult_minor": 60000,
    "price_child_minor": 50000,
    "price_tiers": [{"label": "Взрослый с прокатом", "minor": 90000}],
    "price_note": "Билет на 1 час, вход в любое время с 11:45 до 16:30",
}


def test_hourly_window_prices_say_per_hour() -> None:
    parts, note = slot_plan_prices(_WINDOW)
    assert parts and all(value.endswith("/час") for _, value in parts)
    assert note == _WINDOW["price_note"]
    lines = slot_price_lines(_WINDOW)
    assert all(line.endswith("/час") for line in lines[:-1])
    assert lines[-1] == _WINDOW["price_note"]


def test_ordinary_and_whole_night_prices_unchanged() -> None:
    for note in (None, "Билет на всю ночь катаний, только в кассе катка"):
        parts, _ = slot_plan_prices({**_WINDOW, "price_note": note})
        assert parts and not any("час" in value for _, value in parts)
