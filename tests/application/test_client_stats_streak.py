"""Unit tests for client activity week streak (Europe/Minsk calendar weeks)."""
from __future__ import annotations

from datetime import date, datetime, time

import pytest

from src.application.client_stats_use_cases import compute_calendar_week_streak_completed

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

MINSK = ZoneInfo("Europe/Minsk")


def test_streak_empty() -> None:
    ref = datetime(2026, 3, 18, 12, 0, 0, tzinfo=MINSK)
    assert compute_calendar_week_streak_completed([], reference_now=ref) == 0


def test_streak_single_week() -> None:
    """One session in previous calendar week; current week (Wed) empty — streak ends at that week."""
    ref = datetime(2026, 3, 18, 12, 0, 0, tzinfo=MINSK)  # Wed; week starts Mon 2026-03-16
    rows = [(date(2026, 3, 10), time(18, 0))]  # Tue in week Mon 2026-03-09
    assert compute_calendar_week_streak_completed(rows, reference_now=ref) == 1


def test_streak_two_consecutive_weeks() -> None:
    ref = datetime(2026, 3, 18, 12, 0, 0, tzinfo=MINSK)
    rows = [
        (date(2026, 3, 10), time(18, 0)),  # week of Mar 9
        (date(2026, 3, 4), time(10, 0)),  # Tue Mar 4 → week of Mar 3
    ]
    assert compute_calendar_week_streak_completed(rows, reference_now=ref) == 2


def test_streak_broken_gap_resets() -> None:
    """Two sessions with a full empty week between → streak is 1 (latest island)."""
    ref = datetime(2026, 3, 18, 12, 0, 0, tzinfo=MINSK)
    rows = [
        (date(2026, 3, 10), time(18, 0)),  # week Mar 9
        (date(2026, 2, 18), time(10, 0)),  # older week, gap in between
    ]
    assert compute_calendar_week_streak_completed(rows, reference_now=ref) == 1


def test_streak_counts_current_week_when_session_exists() -> None:
    ref = datetime(2026, 3, 18, 12, 0, 0, tzinfo=MINSK)
    rows = [
        (date(2026, 3, 17), time(10, 0)),  # Tue in current week (Mon Mar 16)
        (date(2026, 3, 10), time(18, 0)),  # previous week
    ]
    assert compute_calendar_week_streak_completed(rows, reference_now=ref) == 2


@pytest.mark.asyncio
async def test_get_client_activity_snapshot_includes_new_fields(db_session) -> None:
    """Smoke: snapshot shape includes streak/top_trainer/first_completed for a client with no bookings."""
    from sqlalchemy import text

    from src.application.client_stats_use_cases import get_client_activity_snapshot
    from tests.conftest import belarus_test_phone, unique_test_telegram_id

    tg = unique_test_telegram_id()
    phone, pn = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'Ст', 'Рик', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "pn": pn},
    )
    cid = int(r.scalar_one())
    await db_session.commit()

    snap = await get_client_activity_snapshot(db_session, client_id=cid)
    assert snap["completed_total"] == 0
    assert snap["first_completed_at"] is None
    assert snap["streak_weeks"] == 0
    assert snap["top_trainer"] is None
