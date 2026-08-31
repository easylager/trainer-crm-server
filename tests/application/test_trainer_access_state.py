"""Pure mapping tests for trainer bot access (no DB)."""
import pytest

from src.application.trainer_access_state import TrainerAccessState, resolve_trainer_access_state
from src.infrastructure.db.models import (
    TRAINER_STATUS_ACTIVE,
    TRAINER_STATUS_DEACTIVATED,
    TRAINER_STATUS_PENDING_CONTRACT,
    TRAINER_STATUS_PENDING_PAYMENT,
    TRAINER_STATUS_PENDING_PROFILE,
)


def _trainer_moderation_complete() -> dict:
    return {
        "id": 1,
        "status": TRAINER_STATUS_PENDING_PROFILE,
        "profile": {
            "first_name": "Ann",
            "last_name": "Bee",
            "age": 30,
            "phone": "+375291234567",
            "contacts": "@ann",
            "description": "x" * 25,
            "city_id": 1,
            "education": "higher",
            "experience_years": 5,
            "session_duration_minutes": 45,
            "min_hours_before_booking": 24,
        },
        "photos": [{"file_key": "trainers/1/p.jpg", "file_key_list": None, "sort_order": 0}],
        "service_ids": [1],
        "arena_ids": [1],
        "education_entries_count": 0,
    }


def test_blocked_profile_when_pending_and_no_trainer_aggregate() -> None:
    assert (
        resolve_trainer_access_state(status=TRAINER_STATUS_PENDING_PROFILE, trainer=None)
        == TrainerAccessState.BLOCKED_PROFILE
    )


def test_blocked_profile_when_pending_and_incomplete_trainer() -> None:
    t = {"profile": {"first_name": "A", "last_name": "B", "age": 30}, "photos": [], "service_ids": [1]}
    assert resolve_trainer_access_state(status=TRAINER_STATUS_PENDING_PROFILE, trainer=t) == TrainerAccessState.BLOCKED_PROFILE


def _trainer_tt_minimal_only() -> dict:
    """5-field TTV gate: no photo/description/education or session/booking settings required."""
    return {
        "id": 2,
        "status": TRAINER_STATUS_PENDING_PROFILE,
        "profile": {
            "first_name": "Sam",
            "last_name": "Lee",
            "phone": "+375291112233",
            "city_id": 1,
        },
        "photos": [],
        "service_ids": [1],
        "arena_ids": [1],
        "education_entries_count": 0,
    }


def test_booking_ready_when_pending_and_tt_minimal_not_submission_complete() -> None:
    assert (
        resolve_trainer_access_state(status=TRAINER_STATUS_PENDING_PROFILE, trainer=_trainer_tt_minimal_only())
        == TrainerAccessState.BOOKING_READY
    )


def test_booking_ready_with_mobile_format_and_no_arenas() -> None:
    t = {
        "profile": {
            "first_name": "Sam",
            "last_name": "Lee",
            "phone": "+375291112233",
            "city_id": 1,
        },
        "photos": [],
        "service_ids": [1],
        "arena_ids": [],
        "arena_work_format": "mobile",
        "education_entries_count": 0,
    }
    assert (
        resolve_trainer_access_state(status=TRAINER_STATUS_PENDING_PROFILE, trainer=t)
        == TrainerAccessState.BOOKING_READY
    )


def test_pending_moderation_when_pending_and_complete_trainer() -> None:
    assert (
        resolve_trainer_access_state(status=TRAINER_STATUS_PENDING_PROFILE, trainer=_trainer_moderation_complete())
        == TrainerAccessState.PENDING_MODERATION
    )


@pytest.mark.parametrize(
    "status",
    [TRAINER_STATUS_PENDING_CONTRACT, TRAINER_STATUS_PENDING_PAYMENT],
)
def test_pending_moderation_contract_payment(status: str) -> None:
    assert resolve_trainer_access_state(status=status, trainer=None) == TrainerAccessState.PENDING_MODERATION


def test_active_and_deactivated() -> None:
    assert resolve_trainer_access_state(status=TRAINER_STATUS_ACTIVE, trainer=None) == TrainerAccessState.ACTIVE
    assert resolve_trainer_access_state(status=TRAINER_STATUS_DEACTIVATED, trainer=None) == TrainerAccessState.DEACTIVATED
