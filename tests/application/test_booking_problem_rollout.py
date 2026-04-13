"""PRD E7 T7.2: rollout gate for Client problem API."""
from __future__ import annotations

import pytest

from src.application.booking_problem_rollout import trainer_may_use_booking_problem_api


@pytest.mark.parametrize(
    ("rollout", "pilot_ids", "tid", "expected"),
    [
        ("full", [], 1, True),
        ("full", None, 99, True),
        ("off", [], 1, False),
        ("off", [1, 2], 1, False),
        ("pilot", [10, 20], 10, True),
        ("pilot", [10, 20], 99, False),
        ("pilot", [], 10, False),
        ("pilot", None, 10, False),
        ("FULL", None, 5, True),
        ("bogus", [], 1, False),
    ],
)
def test_trainer_may_use_booking_problem_api(
    rollout: str,
    pilot_ids: list[int] | None,
    tid: int,
    expected: bool,
) -> None:
    assert (
        trainer_may_use_booking_problem_api(
            tid,
            rollout=rollout,
            pilot_trainer_ids=pilot_ids,
        )
        is expected
    )
