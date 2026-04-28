"""Pure tests for client booking reminder scheduling (Europe/Minsk wall clock)."""

from datetime import date, datetime, time

import pytest

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

from src.application.booking_use_cases import compute_booking_reminder_schedule

_TZ = ZoneInfo("Europe/Minsk")


@pytest.mark.parametrize(
    "anchor, slot_date, slot_t, expected_kind",
    [
        # Next morning 08:00 booked previous afternoon: strict -24h and -2h in night → evening prior.
        (
            datetime(2026, 4, 28, 14, 30, tzinfo=_TZ),
            date(2026, 4, 29),
            time(8, 0),
            "before_evening_prior",
        ),
        # Far-ahead slot still gets classic 24h + 2h (no evening).
        (
            datetime(2026, 4, 28, 12, 0, tzinfo=_TZ),
            date(2026, 5, 1),
            time(14, 0),
            "before_24h",
        ),
    ],
)
def test_reminder_schedule_kinds(anchor, slot_date, slot_t, expected_kind):
    plan = compute_booking_reminder_schedule(
        anchor_local=anchor,
        slot_date=slot_date,
        start_time=slot_t,
    )
    assert plan, "expected at least one reminder"
    assert plan[0][0] == expected_kind


def test_early_slot_next_day_gets_evening_at_20_00():
    anchor = datetime(2026, 4, 28, 16, 0, tzinfo=_TZ)
    plan = compute_booking_reminder_schedule(
        anchor_local=anchor,
        slot_date=date(2026, 4, 29),
        start_time=time(8, 0),
    )
    assert len(plan) == 1
    kind, dt = plan[0]
    assert kind == "before_evening_prior"
    assert dt == datetime(2026, 4, 28, 20, 0, tzinfo=_TZ)


def test_two_hour_before_snaps_from_quiet_to_0800():
    """Slot at 10:00 → raw -2h is 08:00 (not night); 11:00 → raw 09:00."""
    anchor = datetime(2026, 4, 28, 8, 0, tzinfo=_TZ)
    plan = compute_booking_reminder_schedule(
        anchor_local=anchor,
        slot_date=date(2026, 4, 28),
        start_time=time(11, 0),
    )
    kinds = [k for k, _ in plan]
    assert "before_2h" in kinds
    send_times = [dt for k, dt in plan if k == "before_2h"]
    assert send_times[0].hour == 9


def test_night_snap_for_2h_candidate():
    """Raw -2h in 07:xx snaps to 08:00 same day when slot starts after 08:00."""
    anchor = datetime(2026, 4, 27, 12, 0, tzinfo=_TZ)
    plan = compute_booking_reminder_schedule(
        anchor_local=anchor,
        slot_date=date(2026, 4, 29),
        start_time=time(9, 0),
    )
    by_kind = {k: t for k, t in plan}
    assert "before_2h" in by_kind
    assert by_kind["before_2h"] == datetime(2026, 4, 29, 8, 0, tzinfo=_TZ)
