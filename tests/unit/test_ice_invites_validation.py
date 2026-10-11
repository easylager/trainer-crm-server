"""TASK-231: invite name rules and the short code alphabet."""

from __future__ import annotations

import pytest

from src.application.ice_invites import (
    INVITE_CODE_ALPHABET,
    INVITE_CODE_LENGTH,
    INVITE_NAME_STOP_ROOTS,
    INVITE_NAME_STOP_WORDS,
    InviteRejected,
    generate_invite_code,
    normalize_invite_name,
    validate_answer_payload,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Аня", "Аня"),
        ("Ёлка", "Ёлка"),
        ("Ірына", "Ірына"),
        ("Яўген", "Яўген"),
        ("Анна-Мария", "Анна-Мария"),
        ("O'Brien", "O'Brien"),
        ("О’Нил", "О’Нил"),
        ("  Макс   Петров  ", "Макс Петров"),
        ("Анна—Мария", "Анна-Мария"),
    ],
)
def test_names_keep_letters_hyphen_and_apostrophe(raw: str, expected: str) -> None:
    assert normalize_invite_name(raw, field="from_name", required=True) == expected


def test_blank_optional_name_is_absent() -> None:
    assert normalize_invite_name(None, field="to_name", required=False) is None
    assert normalize_invite_name("   ", field="to_name", required=False) is None


def test_digits_are_rejected() -> None:
    with pytest.raises(InviteRejected) as caught:
        normalize_invite_name("Макс1", field="to_name", required=True)
    assert caught.value.status_code == 422
    assert "to_name" in caught.value.detail


def test_name_longer_than_20_is_rejected() -> None:
    assert len(normalize_invite_name("А" * 20, field="from_name", required=True) or "") == 20
    with pytest.raises(InviteRejected) as caught:
        normalize_invite_name("Б" * 21, field="from_name", required=True)
    assert caught.value.status_code == 422
    assert "from_name" in caught.value.detail
    assert "20" in caught.value.detail


def test_stop_word_is_rejected() -> None:
    assert "хуй" in INVITE_NAME_STOP_ROOTS
    assert "сука" in INVITE_NAME_STOP_WORDS
    for raw in ("хуй", "Хуйло", "Fuck", "нацист", "Сука", "Nazi", "Аня сука"):
        with pytest.raises(InviteRejected) as caught:
            normalize_invite_name(raw, field="from_name", required=True)
        assert "from_name" in caught.value.detail


@pytest.mark.parametrize("raw", ["Nazim", "Nazira", "Rashit", "Ashita", "Сукачёв", "Себастьян"])
def test_real_names_are_not_caught_by_short_stop_words(raw: str) -> None:
    """Короткие слова сверяются целым словом: подстрокой они задевали настоящие имена."""
    assert normalize_invite_name(raw, field="to_name", required=False) == raw


def test_code_alphabet_and_length() -> None:
    assert INVITE_CODE_ALPHABET == "23456789abcdefghjkmnpqrstuvwxyz"
    assert len(INVITE_CODE_ALPHABET) == len(set(INVITE_CODE_ALPHABET))
    for banned in "01iloILO":
        assert banned not in INVITE_CODE_ALPHABET
    for _ in range(30):
        code = generate_invite_code()
        assert len(code) == INVITE_CODE_LENGTH == 8
        assert set(code) <= set(INVITE_CODE_ALPHABET)


def test_answer_payload_bounds() -> None:
    ok = validate_answer_payload(device_token="a" * 16, tries=0, resist_ms=0, falls=0, tricked=False)
    assert ok["tries"] == 0
    validate_answer_payload(device_token="b" * 128, tries=10, resist_ms=600_000, falls=5, tricked=True)
    with pytest.raises(InviteRejected):
        validate_answer_payload(device_token="short", tries=0, resist_ms=0, falls=0, tricked=False)
    with pytest.raises(InviteRejected):
        validate_answer_payload(device_token="c" * 16, tries=11, resist_ms=0, falls=0, tricked=False)
    with pytest.raises(InviteRejected):
        validate_answer_payload(device_token="c" * 16, tries=0, resist_ms=600_001, falls=0, tricked=False)
    with pytest.raises(InviteRejected):
        validate_answer_payload(device_token="c" * 16, tries=0, resist_ms=0, falls=6, tricked=False)
