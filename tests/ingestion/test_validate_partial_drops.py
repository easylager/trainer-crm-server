"""TASK-187: построчная валидация — плохая строка отбрасывается с причиной, прогон живёт."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from src.application.ice_session_use_cases import IceSessionValidationError
from src.ingestion.types import CanonicalSlotDraft
from src.ingestion.validate import (
    DEFAULT_MAX_INVALID_SLOT_RATIO,
    DROP_DURATION,
    IceSessionValidator,
    max_invalid_slot_ratio,
)

_NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


def _slot(minutes: int, arena_id: int = 1, hour_offset: int = 0) -> CanonicalSlotDraft:
    start = _NOW + timedelta(hours=1 + hour_offset)
    end = start + timedelta(minutes=minutes)
    local_start = time(14 + hour_offset, 0)
    return CanonicalSlotDraft(
        arena_id=arena_id,
        kind="public_skate",
        starts_at_utc=start,
        ends_at_utc=end,
        local_date=date(2026, 9, 6),
        starts_at_local=local_start,
        ends_at_local=(datetime.combine(date(2026, 9, 6), local_start) + timedelta(minutes=minutes)).time(),
        price_adult_minor=1000,
        price_child_minor=None,
        price_rental_minor=None,
        currency_code="BYN",
        status="active",
        observed_at=_NOW,
        valid_until=_NOW + timedelta(hours=2),
    )


def test_three_valid_one_150_min_drops_one_with_reason() -> None:
    """AC-3."""
    drafts = [_slot(45, hour_offset=0), _slot(60, hour_offset=2), _slot(90, hour_offset=4), _slot(150, hour_offset=6)]
    outcome = IceSessionValidator().validate_outcome(drafts)
    assert len(outcome.validated) == 3
    assert outcome.slots_dropped == 1
    assert outcome.drop_reasons == [DROP_DURATION]
    assert outcome.reason_counts() == {DROP_DURATION: 1}


def test_all_invalid_raises_with_reasons() -> None:
    with pytest.raises(IceSessionValidationError, match="длительность 2"):
        IceSessionValidator().validate_outcome([_slot(150), _slot(200, hour_offset=3)])


def test_over_threshold_raises() -> None:
    drafts = [_slot(60), _slot(150, hour_offset=2), _slot(150, hour_offset=4)]
    with pytest.raises(IceSessionValidationError, match="отброшено 2 из 3"):
        IceSessionValidator().validate_outcome(drafts, max_drop_ratio=0.5)
    assert len(IceSessionValidator().validate_outcome(drafts, max_drop_ratio=1.0).validated) == 1


def test_empty_drafts_is_ok() -> None:
    """Parser returned no rows — scheduler treats this as RUN_STATUS_EMPTY, not validation_error."""
    outcome = IceSessionValidator().validate_outcome([])
    assert outcome.validated == []
    assert outcome.slots_dropped == 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, DEFAULT_MAX_INVALID_SLOT_RATIO),
        ("abc", DEFAULT_MAX_INVALID_SLOT_RATIO),
        ({"x": 1}, DEFAULT_MAX_INVALID_SLOT_RATIO),
        (True, DEFAULT_MAX_INVALID_SLOT_RATIO),
        (float("nan"), DEFAULT_MAX_INVALID_SLOT_RATIO),
        ("0.25", 0.25),
        (-3, 0.0),
        (7, 1.0),
    ],
)
def test_bad_max_invalid_slot_ratio_config_never_raises(raw, expected) -> None:
    """Ревью #9: кривой конфиг не должен ронять прогон необработанным исключением."""
    assert max_invalid_slot_ratio({"max_invalid_slot_ratio": raw}) == expected
