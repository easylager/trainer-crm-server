"""TASK-207: phone_guard normalization and validation."""

from src.shared.phone_guard import is_valid_public_phone, tel_href


def test_unicode_superscript_digits_are_not_counted() -> None:
    assert not is_valid_public_phone("¹²³⁴⁵⁶⁷")
    assert tel_href("¹²³⁴⁵⁶⁷") == ""


def test_tel_href_first_of_semicolon_separated_numbers() -> None:
    assert tel_href("+375 29 111-11-11; +375 17 222-22-22") == "+375291111111"


def test_tel_href_strips_extension_dob() -> None:
    assert tel_href("+375 29 123-45-67 доб. 12") == "+375291234567"


def test_business_hours_are_not_valid_phones() -> None:
    hours = "Пн-Пт 09:00-18:00"
    assert not is_valid_public_phone(hours)
    assert tel_href(hours) == ""


def test_short_ascii_phone_invalid() -> None:
    assert not is_valid_public_phone("123-456")


def test_valid_by_phone_normalized() -> None:
    assert is_valid_public_phone("+375 (29) 123-45-67")
    assert tel_href("+375 (29) 123-45-67") == "+375291234567"
