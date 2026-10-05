"""TASK-187: per-row validation drops bad slots instead of failing the whole batch."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from src.application.ice_session_use_cases import IceSessionValidationError
from src.ingestion.types import CanonicalSlotDraft
from src.ingestion.validate import IceSessionValidator

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


def test_three_valid_one_150_min_drops_one() -> None:
    """AC-3."""
    drafts = [_slot(45, hour_offset=0), _slot(60, hour_offset=2), _slot(90, hour_offset=4), _slot(150, hour_offset=6)]
    outcome = IceSessionValidator().validate_outcome(drafts, max_drop_ratio=1.0)
    assert len(outcome.validated) == 3
    assert outcome.slots_dropped == 1
    assert outcome.drop_reasons


def test_all_invalid_raises() -> None:
    with pytest.raises(IceSessionValidationError):
        IceSessionValidator().validate_outcome([_slot(150), _slot(200)])
