"""Multi-country phone normalize/validate (BY + RU)."""
from src.shared.profile_phone import (
    coerce_required_phone,
    normalize_phone_input,
    validate_phone_non_empty,
)


def test_normalize_by_from_national_nine_digits() -> None:
    assert normalize_phone_input("29 111 22 33") == "+375291112233"


def test_normalize_ru_from_eight_prefix() -> None:
    assert normalize_phone_input("8 916 123-45-67") == "+79161234567"


def test_normalize_ru_from_ten_digits() -> None:
    assert normalize_phone_input("9161234567") == "+79161234567"


def test_normalize_ru_from_plus_seven() -> None:
    assert normalize_phone_input("+7 916 123 45 67") == "+79161234567"


def test_validate_accepts_ru() -> None:
    ok, err = validate_phone_non_empty("+79161234567")
    assert ok == "+79161234567"
    assert err is None


def test_validate_rejects_short() -> None:
    ok, err = validate_phone_non_empty("+37529")
    assert ok is None
    assert err is not None


def test_coerce_required_phone_ru() -> None:
    assert coerce_required_phone("89161234567") == "+79161234567"
