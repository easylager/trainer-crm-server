"""Unit tests for hybrid recurring horizon (window fill + virtual preview helpers)."""
from __future__ import annotations

from datetime import date, time, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.application.recurring_use_cases import (
    _parse_hhmm_string,
    list_recurring_schedule_preview_for_trainer_client,
    materialize_recurring_horizon,
)


def test_parse_hhmm_string() -> None:
    assert _parse_hhmm_string("18:30") == time(18, 30)
    assert _parse_hhmm_string(time(9, 0)) == time(9, 0)
    assert _parse_hhmm_string("bad") is None


@pytest.mark.asyncio
async def test_materialize_horizon_only_scans_window_weeks() -> None:
    """Must not walk beyond horizon_weeks even when near weeks already have bookings."""
    session = AsyncMock()
    rec = {
        "id": 1,
        "client_id": 10,
        "day_of_week": 0,
        "start_time": time(10, 0),
        "end_time": time(11, 0),
    }
    calls: list[date] = []

    async def _fake_mat(_session, _tid, _rec, ws, _sid):
        calls.append(ws)
        return False  # already filled / skip — old bug would keep walking

    with patch(
        "src.application.subscription_tier_use_cases.trainer_has_crm_access",
        new=AsyncMock(return_value=True),
    ), patch(
        "src.application.recurring_use_cases.get_first_service_id_for_trainer",
        new=AsyncMock(return_value=5),
    ), patch(
        "src.application.recurring_use_cases.list_active_recurring_for_trainer_week",
        new=AsyncMock(return_value=[rec]),
    ), patch(
        "src.application.recurring_use_cases.this_week_monday",
        return_value=date(2026, 7, 27),
    ), patch(
        "src.application.recurring_use_cases.materialize_recurring_rule_for_week",
        new=_fake_mat,
    ):
        n = await materialize_recurring_horizon(
            session, 7, horizon_weeks=3, recurring_ids=[1]
        )
    assert n == 0
    assert len(calls) == 3
    assert calls[0] == date(2026, 7, 27)
    assert calls[1] == date(2026, 7, 27) + timedelta(days=7)
    assert calls[2] == date(2026, 7, 27) + timedelta(days=14)


@pytest.mark.asyncio
async def test_schedule_preview_merges_real_and_virtual() -> None:
    session = AsyncMock()
    mono = date(2026, 7, 27)
    with patch(
        "src.application.recurring_use_cases.this_week_monday",
        return_value=mono,
    ), patch(
        "src.application.recurring_use_cases.list_upcoming_recurring_bookings_for_trainer_client",
        new=AsyncMock(
            return_value=[
                {
                    "booking_id": 99,
                    "slot_date": "2026-07-27",
                    "start_time": "10:00",
                    "recurring_slot_id": 1,
                    "status": "confirmed",
                    "kind": "real",
                }
            ]
        ),
    ), patch(
        "src.application.recurring_use_cases.list_active_recurring_slots_for_trainer_client",
        new=AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "day_of_week": 0,
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "label": "Пн 10:00–11:00",
                }
            ]
        ),
    ), patch(
        "src.application.recurring_use_cases._recurring_week_is_skipped",
        new=AsyncMock(return_value=False),
    ), patch(
        "src.application.recurring_use_cases.is_slot_start_in_past_local",
        return_value=False,
    ):
        items = await list_recurring_schedule_preview_for_trainer_client(
            session,
            1,
            2,
            from_date=mono,
            horizon_weeks=2,
            preview_weeks=4,
        )
    kinds = [x["kind"] for x in items]
    assert "real" in kinds
    assert "virtual" in kinds
    # First real Monday kept; later Mondays virtual
    assert items[0]["booking_id"] == 99
    assert any(x["kind"] == "virtual" and x["slot_date"] == "2026-08-03" for x in items)
