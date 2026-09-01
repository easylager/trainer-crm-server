"""
Pure mapping tests for trainer bot access (no DB).

Onboarding v2 contract: moderation gates the public catalog, not the trainer's own tools.
Every linked trainer is ACTIVE for access purposes unless an admin deactivated the account —
regardless of how empty the profile is.
"""
import pytest

from src.application.trainer_access_state import (
    TrainerAccessState,
    resolve_trainer_access_state,
    trainer_may_use_bot_workflows,
)
from src.infrastructure.db.models import (
    TRAINER_STATUS_ACTIVE,
    TRAINER_STATUS_DEACTIVATED,
    TRAINER_STATUS_PENDING_CONTRACT,
    TRAINER_STATUS_PENDING_PAYMENT,
    TRAINER_STATUS_PENDING_PROFILE,
)


def test_only_three_states_exist() -> None:
    """The tier machinery (BLOCKED_PROFILE / BOOKING_READY / PENDING_MODERATION) is gone for good."""
    assert {s.value for s in TrainerAccessState} == {"not_linked", "active", "deactivated"}


@pytest.mark.parametrize(
    "status",
    [
        TRAINER_STATUS_ACTIVE,
        TRAINER_STATUS_PENDING_PROFILE,
        TRAINER_STATUS_PENDING_CONTRACT,
        TRAINER_STATUS_PENDING_PAYMENT,
    ],
)
def test_every_non_deactivated_status_is_active(status: str) -> None:
    assert resolve_trainer_access_state(status=status, trainer=None) == TrainerAccessState.ACTIVE


def test_empty_profile_does_not_block_access() -> None:
    """A brand-new trainer with nothing filled in still works — that is the whole point."""
    empty = {"id": 1, "status": TRAINER_STATUS_PENDING_PROFILE, "profile": {}, "photos": [], "service_ids": []}
    assert (
        resolve_trainer_access_state(status=TRAINER_STATUS_PENDING_PROFILE, trainer=empty)
        == TrainerAccessState.ACTIVE
    )


def test_deactivated_is_the_only_closed_door() -> None:
    assert (
        resolve_trainer_access_state(status=TRAINER_STATUS_DEACTIVATED, trainer=None)
        == TrainerAccessState.DEACTIVATED
    )


def test_unknown_status_falls_back_to_active() -> None:
    """Never lock a paying trainer out because of a status value we failed to recognise."""
    assert resolve_trainer_access_state(status="something_new", trainer=None) == TrainerAccessState.ACTIVE


def test_bot_workflows_allowed_exactly_for_active() -> None:
    assert trainer_may_use_bot_workflows(TrainerAccessState.ACTIVE) is True
    assert trainer_may_use_bot_workflows(TrainerAccessState.DEACTIVATED) is False
    assert trainer_may_use_bot_workflows(TrainerAccessState.NOT_LINKED) is False
