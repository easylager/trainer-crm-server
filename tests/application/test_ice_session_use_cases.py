"""TASK-050 unit tests: timezone, duration, overlap, prices (AC-003/004/005, EDGE-001)."""
from __future__ import annotations

import os
import time as time_mod
from datetime import date, datetime, time, timezone

import pytest

from src.application.ice_session_use_cases import (
    IceSessionDurationError,
    IceSessionOverlapError,
    IceSessionPriceError,
    IceSessionValidationError,
    compute_price_minor,
    compute_session_datetimes,
    duration_minutes,
    intervals_overlap,
    totals_by_currency,
    validate_duration_minutes,
    validate_kind,
    validate_prices,
    validate_no_overlap,
)


def test_minsk_11am_stores_utc_and_local_independent_of_process_tz(monkeypatch) -> None:
    """AC-003: 11:00 at UTC+3 arena stays 11:00 local even if the process TZ changes."""
    previous = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time_mod.tzset()
    try:
        parts = compute_session_datetimes(
            local_date=date(2026, 9, 6),
            starts_at_local=time(11, 0),
            duration_minutes=45,
            tz_name="Europe/Minsk",
        )
        assert parts.starts_at_local == time(11, 0)
        assert parts.ends_at_local == time(11, 45)
        assert parts.local_date == date(2026, 9, 6)
        assert parts.starts_at_utc == datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)
        assert parts.ends_at_utc == datetime(2026, 9, 6, 8, 45, tzinfo=timezone.utc)
    finally:
        if previous is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", previous)
        time_mod.tzset()


def test_missing_timezone_defaults_to_europe_minsk() -> None:
    parts = compute_session_datetimes(
        local_date=date(2026, 9, 6),
        starts_at_local=time(11, 0),
        duration_minutes=60,
        tz_name=None,
    )
    assert parts.starts_at_utc == datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)


def test_midnight_crossing_keeps_start_local_date(monkeypatch) -> None:
    """EDGE-001: 22:30–00:30 belongs to the start local_date, not the UTC day."""
    previous = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "UTC")
    time_mod.tzset()
    try:
        parts = compute_session_datetimes(
            local_date=date(2026, 9, 5),
            starts_at_local=time(22, 30),
            duration_minutes=120,
            tz_name="Europe/Minsk",
        )
        assert parts.local_date == date(2026, 9, 5)
        assert parts.starts_at_local == time(22, 30)
        assert parts.ends_at_local == time(0, 30)
        assert parts.starts_at_utc == datetime(2026, 9, 5, 19, 30, tzinfo=timezone.utc)
        assert parts.ends_at_utc == datetime(2026, 9, 5, 21, 30, tzinfo=timezone.utc)
    finally:
        if previous is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", previous)
        time_mod.tzset()


def test_duration_minutes_from_utc_span() -> None:
    start = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 6, 8, 45, tzinfo=timezone.utc)
    assert duration_minutes(start, end) == 45


@pytest.mark.parametrize("minutes", [30, 45, 60, 90, 120])
def test_valid_durations_pass(minutes: int) -> None:
    validate_duration_minutes(minutes)


@pytest.mark.parametrize("minutes", [0, 15, 29, 121, 180])
def test_invalid_durations_rejected(minutes: int) -> None:
    with pytest.raises(IceSessionDurationError):
        validate_duration_minutes(minutes)


def test_intervals_overlap_half_open() -> None:
    a1 = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)
    a2 = datetime(2026, 9, 6, 8, 45, tzinfo=timezone.utc)
    b1 = datetime(2026, 9, 6, 8, 45, tzinfo=timezone.utc)
    b2 = datetime(2026, 9, 6, 9, 30, tzinfo=timezone.utc)
    c1 = datetime(2026, 9, 6, 8, 30, tzinfo=timezone.utc)
    c2 = datetime(2026, 9, 6, 9, 0, tzinfo=timezone.utc)
    assert intervals_overlap(a1, a2, b1, b2) is False
    assert intervals_overlap(a1, a2, c1, c2) is True


def test_validate_no_overlap_ignores_cancelled() -> None:
    existing = [
        {
            "id": 1,
            "status": "cancelled",
            "starts_at_utc": datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc),
            "ends_at_utc": datetime(2026, 9, 6, 8, 45, tzinfo=timezone.utc),
        }
    ]
    validate_no_overlap(
        existing,
        starts_at_utc=datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc),
        ends_at_utc=datetime(2026, 9, 6, 8, 45, tzinfo=timezone.utc),
    )


def test_validate_no_overlap_rejects_active_conflict() -> None:
    existing = [
        {
            "id": 1,
            "status": "active",
            "starts_at_utc": datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc),
            "ends_at_utc": datetime(2026, 9, 6, 8, 45, tzinfo=timezone.utc),
        }
    ]
    with pytest.raises(IceSessionOverlapError):
        validate_no_overlap(
            existing,
            starts_at_utc=datetime(2026, 9, 6, 8, 30, tzinfo=timezone.utc),
            ends_at_utc=datetime(2026, 9, 6, 9, 0, tzinfo=timezone.utc),
        )


def test_validate_no_overlap_skips_self_on_update() -> None:
    existing = [
        {
            "id": 9,
            "status": "active",
            "starts_at_utc": datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc),
            "ends_at_utc": datetime(2026, 9, 6, 8, 45, tzinfo=timezone.utc),
        }
    ]
    validate_no_overlap(
        existing,
        starts_at_utc=datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc),
        ends_at_utc=datetime(2026, 9, 6, 8, 45, tzinfo=timezone.utc),
        ignore_session_id=9,
    )


def test_negative_prices_rejected() -> None:
    with pytest.raises(IceSessionPriceError):
        validate_prices(price_adult_minor=-1, price_child_minor=None, price_rental_minor=None)


def test_price_minor_is_min_of_adult_and_child() -> None:
    """EDGE-003: sort key is the cheaper of adult/child, not a concatenated string."""
    assert compute_price_minor(1200, 800, 600) == 800
    assert compute_price_minor(850, None, 1200) == 850
    assert compute_price_minor(None, None, 400) is None


def test_byn_and_rub_sessions_are_not_summed_together() -> None:
    """AC-004: reports must keep currencies in separate buckets."""
    sessions = [
        {"currency_code": "BYN", "price_minor": 850},
        {"currency_code": "BYN", "price_minor": 600},
        {"currency_code": "RUB", "price_minor": 40000},
    ]
    totals = totals_by_currency(sessions)
    assert totals == {"BYN": 1450, "RUB": 40000}
    assert totals["BYN"] != totals["BYN"] + totals["RUB"]


def test_kind_allowlist() -> None:
    for kind in ("public_skate", "open_ice", "rental", "school_group", "event"):
        validate_kind(kind)
    with pytest.raises(IceSessionValidationError):
        validate_kind("hockey_game")
