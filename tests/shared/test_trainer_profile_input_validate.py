from src.application.trainer_profile_completeness import MIN_DESCRIPTION_CHARS
from src.shared.trainer_profile_input_validate import (
    validate_birth_date_line,
    validate_description_for_moderation,
    validate_first_name,
    validate_phone,
)


def test_validate_first_name() -> None:
    v, err = validate_first_name("  Ann  ")
    assert v == "Ann" and err is None
    assert validate_first_name("")[1] is not None


def test_validate_birth_date() -> None:
    assert validate_birth_date_line("1990-05-20")[0].isoformat() == "1990-05-20"
    assert validate_birth_date_line("-") == (None, None)
    assert validate_birth_date_line("abc")[1] is not None


def test_validate_phone() -> None:
    v, err = validate_phone("+375291112233")
    assert v and err is None
    v_ru, err_ru = validate_phone("+79161234567")
    assert v_ru == "+79161234567" and err_ru is None
    assert validate_phone("")[0] is None and validate_phone("")[1] is None
    assert validate_phone("x")[1] is not None
    err_short = validate_phone("+37529")[1]
    assert err_short is not None
    assert "корректный" in err_short.lower()


def test_validate_description_min() -> None:
    assert validate_description_for_moderation("a" * (MIN_DESCRIPTION_CHARS - 1))[1]
    assert validate_description_for_moderation("a" * MIN_DESCRIPTION_CHARS)[0]
