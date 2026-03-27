"""trainer_profile_completeness: rules for moderation queue."""
import pytest

from src.application.trainer_profile_completeness import (
    MIN_DESCRIPTION_CHARS,
    analyze_moderation_profile_completeness,
    is_profile_complete_for_moderation,
    missing_labels_ru,
)


def _base() -> dict:
    return {
        "profile": {
            "first_name": "A",
            "last_name": "B",
            "age": 22,
            "phone": "123",
            "contacts": "@client",
            "description": "d" * MIN_DESCRIPTION_CHARS,
            "city_id": 1,
            "education": "higher",
            "experience_years": 2,
            "session_duration_minutes": 45,
            "min_hours_before_booking": 24,
        },
        "photos": [{"file_key": "trainers/1/x.jpg"}],
        "service_ids": [9],
        "arena_ids": [3],
        "education_entries_count": 0,
    }


@pytest.fixture
def trainer_aggregate_complete() -> dict:
    """Minimal valid aggregate for moderation (same shape as get_trainer)."""
    return _base()


@pytest.fixture
def trainer_aggregate_incomplete_no_photo() -> dict:
    """Complete except photo — gate / completeness should fail."""
    t = _base()
    t["photos"] = []
    return t


@pytest.fixture
def trainer_aggregate_incomplete_no_services() -> dict:
    """Complete except services."""
    t = _base()
    t["service_ids"] = []
    return t


def test_is_profile_complete_for_moderation_true(trainer_aggregate_complete: dict) -> None:
    assert is_profile_complete_for_moderation(trainer_aggregate_complete) is True


def test_is_profile_complete_for_moderation_false_without_photo(trainer_aggregate_incomplete_no_photo: dict) -> None:
    assert is_profile_complete_for_moderation(trainer_aggregate_incomplete_no_photo) is False


def test_is_profile_complete_for_moderation_false_without_services(
    trainer_aggregate_incomplete_no_services: dict,
) -> None:
    assert is_profile_complete_for_moderation(trainer_aggregate_incomplete_no_services) is False


def test_complete_minimal_aggregate() -> None:
    t = _base()
    ok, missing = analyze_moderation_profile_completeness(t)
    assert ok and missing == []
    assert is_profile_complete_for_moderation(t) is True


def test_missing_photo() -> None:
    t = _base()
    t["photos"] = []
    ok, missing = analyze_moderation_profile_completeness(t)
    assert not ok and "photo" in missing


def test_phone_required_contacts_optional() -> None:
    t = _base()
    t["profile"] = {**t["profile"], "phone": "", "contacts": "  @user  "}
    assert analyze_moderation_profile_completeness(t)[0] is False
    t2 = _base()
    t2["profile"] = {**t2["profile"], "phone": "  123  ", "contacts": ""}
    assert analyze_moderation_profile_completeness(t2)[0] is True


def test_missing_description_length() -> None:
    t = _base()
    t["profile"] = {**t["profile"], "description": "short"}
    ok, missing = analyze_moderation_profile_completeness(t)
    assert not ok and "description" in missing


def test_missing_arenas() -> None:
    t = _base()
    t["arena_ids"] = []
    assert analyze_moderation_profile_completeness(t)[0] is False


def test_education_satisfied_by_structured_entries_only() -> None:
    t = _base()
    t["profile"] = {**t["profile"], "education": ""}
    t["education_entries_count"] = 1
    assert analyze_moderation_profile_completeness(t)[0] is True


def test_missing_labels_order() -> None:
    t = {"profile": {}, "photos": [], "service_ids": []}
    _, missing = analyze_moderation_profile_completeness(t)
    labels = missing_labels_ru(missing)
    assert len(labels) == len(missing)
    assert all(isinstance(x, str) for x in labels)
