"""trainer_profile_completeness: submission tier vs full dossier."""
import pytest

from src.application.trainer_profile_completeness import (
    MIN_DESCRIPTION_CHARS,
    MODERATION_CRITERIA_TOTAL,
    MODERATION_SUBMISSION_CRITERIA_TOTAL,
    TT_MINIMAL_CRITERIA_TOTAL,
    analyze_moderation_profile_completeness,
    analyze_moderation_submission_readiness,
    analyze_tt_minimal_profile_readiness,
    is_ready_for_moderation_submission,
    missing_labels_ru,
    moderation_readiness_dict,
)


def _base() -> dict:
    return {
        "profile": {
            "first_name": "A",
            "last_name": "B",
            "birth_date": "1990-05-20",
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
    """Aggregate satisfying both submission and full-profile tiers."""
    return _base()


@pytest.fixture
def trainer_aggregate_incomplete_no_photo() -> dict:
    """Complete except photo — both tiers should fail."""
    t = _base()
    t["photos"] = []
    return t


@pytest.fixture
def trainer_aggregate_incomplete_no_services() -> dict:
    """Complete except services — both tiers should fail."""
    t = _base()
    t["service_ids"] = []
    return t


def test_is_ready_for_moderation_submission_true(trainer_aggregate_complete: dict) -> None:
    assert is_ready_for_moderation_submission(trainer_aggregate_complete) is True


def test_is_ready_for_moderation_submission_false_without_photo(
    trainer_aggregate_incomplete_no_photo: dict,
) -> None:
    assert is_ready_for_moderation_submission(trainer_aggregate_incomplete_no_photo) is False


def test_is_ready_for_moderation_submission_false_without_services(
    trainer_aggregate_incomplete_no_services: dict,
) -> None:
    assert is_ready_for_moderation_submission(trainer_aggregate_incomplete_no_services) is False


def test_complete_minimal_aggregate() -> None:
    t = _base()
    ok, missing = analyze_moderation_profile_completeness(t)
    assert ok and missing == []
    assert is_ready_for_moderation_submission(t) is True


def test_missing_photo() -> None:
    t = _base()
    t["photos"] = []
    ok, missing = analyze_moderation_profile_completeness(t)
    assert not ok and "photo" in missing
    assert analyze_moderation_submission_readiness(t)[0] is False


def test_phone_required_contacts_optional() -> None:
    t = _base()
    t["profile"] = {**t["profile"], "phone": "", "contacts": "  @user  "}
    assert analyze_moderation_profile_completeness(t)[0] is False
    assert analyze_moderation_submission_readiness(t)[0] is False
    t2 = _base()
    t2["profile"] = {**t2["profile"], "phone": "  123  ", "contacts": ""}
    assert analyze_moderation_profile_completeness(t2)[0] is True
    assert analyze_moderation_submission_readiness(t2)[0] is True


def test_missing_description_length_full_tier_only() -> None:
    t = _base()
    t["profile"] = {**t["profile"], "description": "short"}
    ok, missing = analyze_moderation_profile_completeness(t)
    assert not ok and "description" in missing
    s_ok, s_miss = analyze_moderation_submission_readiness(t)
    assert s_ok and s_miss == []


def test_submission_ready_when_optional_bio_block_empty() -> None:
    """Birth date, bio, education, experience omitted — still queueable (8/8 submission)."""
    t = _base()
    t["profile"] = {
        **t["profile"],
        "birth_date": None,
        "description": "",
        "education": "",
        "experience_years": None,
    }
    t["education_entries_count"] = 0
    s_ok, s_miss = analyze_moderation_submission_readiness(t)
    assert s_ok and s_miss == []
    f_ok, f_miss = analyze_moderation_profile_completeness(t)
    assert not f_ok
    assert {"description", "education", "experience_years"} <= set(f_miss)
    assert "birth_date" not in f_miss


def test_missing_arenas() -> None:
    t = _base()
    t["arena_ids"] = []
    assert analyze_moderation_profile_completeness(t)[0] is False
    assert analyze_moderation_submission_readiness(t)[0] is False


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


def test_moderation_readiness_dual_tier(trainer_aggregate_complete: dict) -> None:
    d = moderation_readiness_dict(trainer_aggregate_complete, trainer_status="pending_profile")
    assert d.get("moderation_criteria_total") == MODERATION_SUBMISSION_CRITERIA_TOTAL
    assert d.get("complete") is True
    assert d.get("full_profile_complete") is True
    assert d.get("full_profile_criteria_total") == MODERATION_CRITERIA_TOTAL
    assert d.get("full_profile_missing_fields") == []
    assert d.get("already_submitted_for_moderation") is False


def test_moderation_readiness_submit_complete_full_incomplete() -> None:
    t = _base()
    t["profile"] = {**t["profile"], "description": "x"}
    d = moderation_readiness_dict(t, trainer_status="pending_profile")
    assert d["complete"] is True
    assert d["full_profile_complete"] is False
    assert "description" in (d.get("full_profile_missing_fields") or [])


def test_tt_minimal_ignores_session_duration_and_booking_window() -> None:
    """Defaults / settings handle these; full tier still requires valid ranges."""
    t = {
        "profile": {
            "first_name": "Ann",
            "last_name": "Xu",
            "phone": "+375291112233",
            "city_id": 1,
            "session_duration_minutes": None,
            "min_hours_before_booking": None,
        },
        "photos": [],
        "service_ids": [1],
        "arena_ids": [2],
        "education_entries_count": 0,
    }
    ok, miss = analyze_tt_minimal_profile_readiness(t)
    assert ok is True
    assert miss == []


def test_tt_minimal_complete_without_photo_or_long_bio() -> None:
    t = {
        "profile": {
            "first_name": "Ann",
            "last_name": "Xu",
            "phone": "+375291112233",
            "city_id": 1,
        },
        "photos": [],
        "service_ids": [1],
        "arena_ids": [2],
        "education_entries_count": 0,
    }
    ok, miss = analyze_tt_minimal_profile_readiness(t)
    assert ok is True
    assert miss == []


def test_tt_minimal_complete_with_mobile_format_without_arenas() -> None:
    t = {
        "profile": {
            "first_name": "Ann",
            "last_name": "Xu",
            "phone": "+375291112233",
            "city_id": 1,
        },
        "photos": [],
        "service_ids": [1],
        "arena_ids": [],
        "arena_work_format": "mobile",
        "education_entries_count": 0,
    }
    ok, miss = analyze_tt_minimal_profile_readiness(t)
    assert ok is True
    assert miss == []


def test_tt_minimal_complete_with_pending_arena_request() -> None:
    t = {
        "profile": {
            "first_name": "Ann",
            "last_name": "Xu",
            "phone": "+375291112233",
            "city_id": 1,
        },
        "photos": [],
        "service_ids": [1],
        "arena_ids": [],
        "arena_work_format": "pending_request",
        "arena_request_text": "Ледовый дворец",
        "education_entries_count": 0,
    }
    ok, miss = analyze_tt_minimal_profile_readiness(t)
    assert ok is True
    assert miss == []


def test_full_profile_still_requires_real_arena_not_mobile() -> None:
    t = {
        "profile": {
            "first_name": "Ann",
            "last_name": "Xu",
            "phone": "+375291112233",
            "city_id": 1,
            "description": "x" * 30,
            "experience_years": 5,
            "session_duration_minutes": 45,
            "min_hours_before_booking": 3,
            "education": "Coach school",
        },
        "photos": [{"file_key": "k.jpg"}],
        "service_ids": [1],
        "arena_ids": [],
        "arena_work_format": "mobile",
        "education_entries_count": 0,
    }
    ok, miss = analyze_moderation_profile_completeness(t)
    assert ok is False
    assert "arenas" in miss


def test_moderation_readiness_includes_tt_minimal_keys() -> None:
    t = {
        "profile": {
            "first_name": "Ann",
            "last_name": "Xu",
            "phone": "+375291112233",
            "city_id": 1,
        },
        "photos": [],
        "service_ids": [1],
        "arena_ids": [2],
        "education_entries_count": 0,
    }
    d = moderation_readiness_dict(t, trainer_status="pending_profile")
    assert d.get("tt_minimal_criteria_total") == TT_MINIMAL_CRITERIA_TOTAL


def test_submission_allows_missing_last_name_but_full_dossier_does_not() -> None:
    t = _base()
    t["profile"]["last_name"] = ""
    full_ok, full_miss = analyze_moderation_profile_completeness(t)
    assert full_ok is False
    assert "full_name" in full_miss
    submit_ok, submit_miss = analyze_moderation_submission_readiness(t)
    assert submit_ok is True
    assert "full_name" not in submit_miss
    tt_ok, tt_miss = analyze_tt_minimal_profile_readiness(t)
    assert tt_ok is True
    assert "full_name" not in tt_miss
