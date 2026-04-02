"""ProfilePatch / phone and numeric validators (trainer Mini App + REST)."""
import pytest
from pydantic import ValidationError

from src.api.schemas import ProfilePatch, TrainerProfilePatchBody


def test_profile_patch_rejects_phone_with_too_few_digits() -> None:
    with pytest.raises(ValidationError) as exc:
        ProfilePatch(phone="+37529")
    assert "корректный" in str(exc.value).lower()


def test_profile_patch_rejects_non_belarus_phone() -> None:
    with pytest.raises(ValidationError) as exc:
        ProfilePatch(phone="+79161234567")
    assert "корректный" in str(exc.value).lower()


def test_profile_patch_normalizes_phone_spaces() -> None:
    p = ProfilePatch(phone="+375 29 111 22 33")
    assert p.phone == "+375291112233"


def test_profile_patch_rejects_blank_first_name() -> None:
    with pytest.raises(ValidationError):
        ProfilePatch(first_name="   ")


def test_profile_patch_age_integer() -> None:
    assert ProfilePatch(age=0).age == 0
    assert ProfilePatch(age=200).age == 200
    assert ProfilePatch(age=30).age == 30
    with pytest.raises(ValidationError):
        ProfilePatch(age=True)


def test_trainer_profile_patch_body_nested_phone_error() -> None:
    with pytest.raises(ValidationError):
        TrainerProfilePatchBody.model_validate({"profile": {"phone": "12345"}})
