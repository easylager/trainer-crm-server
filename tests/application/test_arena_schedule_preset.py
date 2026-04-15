"""Unit tests for arena schedule grid presets (duration + start grid)."""
from __future__ import annotations

import pytest

from src.application.arena_schedule_preset import (
    allowed_start_minutes_from_preset,
    default_quarter_preset,
    fixed_slot_duration_minutes,
    trainer_uniform_preset,
    validate_duration_for_preset,
)


def test_default_preset_has_no_fixed_duration() -> None:
    assert fixed_slot_duration_minutes(default_quarter_preset()) is None


def test_validate_duration_accepts_any_when_not_fixed() -> None:
    validate_duration_for_preset(60, default_quarter_preset())


def test_validate_duration_rejects_mismatch_when_fixed() -> None:
    p = {**default_quarter_preset(), "slot_duration_minutes": 45}
    validate_duration_for_preset(45, p)
    with pytest.raises(ValueError, match="зафиксирована"):
        validate_duration_for_preset(60, p)


def test_trainer_uniform_step_30_allows_half_hours() -> None:
    p = trainer_uniform_preset(30)
    allowed = allowed_start_minutes_from_preset(p)
    assert 8 * 60 in allowed
    assert 8 * 60 + 30 in allowed
    assert 8 * 60 + 15 not in allowed
