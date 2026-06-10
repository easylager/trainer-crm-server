"""ProfilePatch / phone and numeric validators (trainer Mini App + REST)."""
import pytest
from pydantic import ValidationError

from src.api.schemas import ProfilePatch, TrainerProfilePatchBody


def test_profile_patch_rejects_phone_with_too_few_digits() -> None:
    with pytest.raises(ValidationError) as exc:
        ProfilePatch(phone="+37529")
    assert "корректный" in str(exc.value).lower()


def test_profile_patch_accepts_russia_phone() -> None:
    p = ProfilePatch(phone="+7 916 123-45-67")
    assert p.phone == "+79161234567"


def test_profile_patch_rejects_invalid_phone() -> None:
    with pytest.raises(ValidationError) as exc:
        ProfilePatch(phone="+49161234567")
    assert "корректный" in str(exc.value).lower()


def test_profile_patch_normalizes_phone_spaces() -> None:
    p = ProfilePatch(phone="+375 29 111 22 33")
    assert p.phone == "+375291112233"


def test_profile_patch_rejects_blank_first_name() -> None:
    with pytest.raises(ValidationError):
        ProfilePatch(first_name="   ")


def test_profile_patch_birth_date_optional_iso_date() -> None:
    assert ProfilePatch(birth_date=None).birth_date is None
    assert ProfilePatch(birth_date="1990-05-20").birth_date.isoformat() == "1990-05-20"
    with pytest.raises(ValidationError):
        ProfilePatch(birth_date="20.05.1990")


def test_trainer_profile_patch_body_nested_phone_error() -> None:
    with pytest.raises(ValidationError):
        TrainerProfilePatchBody.model_validate({"profile": {"phone": "12345"}})


def test_trainer_profile_patch_digest_send_time_normalized() -> None:
    b = TrainerProfilePatchBody.model_validate({"digest_send_time": "8:5"})
    assert b.digest_send_time == "08:05"


def test_trainer_profile_patch_digest_send_time_invalid() -> None:
    with pytest.raises(ValidationError):
        TrainerProfilePatchBody.model_validate({"digest_send_time": "25:00"})
