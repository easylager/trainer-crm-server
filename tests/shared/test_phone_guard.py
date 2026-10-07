"""TASK-207: phone_guard normalization and validation."""

import time

import pytest

from src.shared.phone_guard import is_valid_public_phone, tel_href


def test_unicode_superscript_digits_are_not_counted() -> None:
    assert not is_valid_public_phone("¹²³⁴⁵⁶⁷")
    assert tel_href("¹²³⁴⁵⁶⁷") == ""


def test_tel_href_first_of_semicolon_separated_numbers() -> None:
    assert tel_href("+375 29 111-11-11; +375 17 222-22-22") == "+375291111111"


def test_tel_href_strips_extension_dob() -> None:
    assert tel_href("+375 29 123-45-67 доб. 12") == "+375291234567"


def test_business_hours_only_strings_invalid() -> None:
    for hours in (
        "Пн-Пт 09:00-18:00",
        "09:00–18:00",
        "10.00-22.00",
        "ежедневно 10:00-22:00",
        "2024-10-07",
    ):
        assert not is_valid_public_phone(hours)
        assert tel_href(hours) == ""


def test_short_ascii_phone_invalid() -> None:
    assert not is_valid_public_phone("123-456")


def test_valid_by_phone_normalized() -> None:
    assert is_valid_public_phone("+375 (29) 123-45-67")
    assert tel_href("+375 (29) 123-45-67") == "+375291234567"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("8 017 222-22-22 (касса с 10:00)", "80172222222"),
        ("+375 29 592 41 09 (24/7)", "+375295924109"),
        ("администратор +375 29 323-22-09 (A1)", "+375293232209"),
        ("+375 (29) 33 00 749 (+ Telegram)", "+375293300749"),
        ("+375 17 222-22-22 вн. 5", "+375172222222"),
        ("+375 29 123-45-67\n+375 17 222-22-22", "+375291234567"),
    ],
)
def test_tel_href_extracts_first_phone_like_span(raw: str, expected: str) -> None:
    assert tel_href(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "8 017 222-22-22 (10:00-22:00)",
        "8 017 222-22-22 с 10:00 до 22:00",
        "автоинформатор 8 017 348-26-87 (с 9:00)",
        "ресепшн 24/7: +375 29 592 41 09",
        "Пн-Пт 09:00-18:00; +375 29 123-45-67",
    ],
)
def test_phone_with_opening_hours_still_valid(raw: str) -> None:
    assert is_valid_public_phone(raw)
    assert tel_href(raw)


def test_hours_then_phone_takes_valid_number_not_hours() -> None:
    assert tel_href("Пн-Пт 09:00-18:00; +375 29 123-45-67") == "+375291234567"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("8.017.222.22.22", "80172222222"),
        ("+375.29.123.45.67", "+375291234567"),
        ("8 017 222-22-22, с 01.11.2026", "80172222222"),
    ],
)
def test_dot_separated_phones_stay_valid(raw: str, expected: str) -> None:
    assert is_valid_public_phone(raw)
    assert tel_href(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "2024.10.07",
        "07.10.2026",
        "1.01.2026",
        "01.01.2026-31.12.2026",
        "закрыто до 01.11.2026",
    ],
)
def test_calendar_dates_are_not_phones(raw: str) -> None:
    assert not is_valid_public_phone(raw)
    assert tel_href(raw) == ""


def test_phone_before_ezhednevno_hours() -> None:
    assert tel_href("8 017 222-22-22 ежедневно 10:00-22:00") == "80172222222"


def test_clip_does_not_return_a_partial_number() -> None:
    got = tel_href("x" * 50 + " +375 29 123-45-67")
    assert got in ("", "+375291234567")


def test_clipped_input_does_not_hang_on_long_strings() -> None:
    junk = "1" + " " * 10000 + "1"
    started = time.perf_counter()
    assert not is_valid_public_phone(junk)
    assert tel_href(junk) == ""
    assert time.perf_counter() - started < 0.05
