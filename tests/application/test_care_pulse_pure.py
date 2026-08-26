"""Pure tests for care-pulse picker — no DB, no Telegram."""
from __future__ import annotations

from datetime import date, time

from src.application.care_pulse_use_cases import (
    is_within_care_pulse_window,
    pick_client_pulse,
    pick_trainer_pulse,
)
from src.infrastructure.db.models import (
    CARE_PULSE_KIND_CONFIRMED_BOOKING,
    CARE_PULSE_KIND_INVITE_BACK,
    CARE_PULSE_KIND_OPEN_SLOTS,
    CARE_PULSE_KIND_QUIET_CHECKIN,
    CARE_PULSE_KIND_TOMORROW_PLAN,
)


def _trainer_kwargs(**overrides):
    base = {
        "digest_sent_today": False,
        "hours_since_last_pulse": None,
        "weekday_mon0": 0,  # Monday
        "tomorrow_sessions": 0,
        "tomorrow_first_time": None,
        "tomorrow_first_name": "",
        "open_slots_7d": 0,
        "dormant_name": "",
        "dormant_days": None,
        "today_iso": "2026-08-20",
    }
    base.update(overrides)
    return base


def _client_kwargs(**overrides):
    base = {
        "hours_since_last_pulse": None,
        "inactive_sent_recent": False,
        "days_until_upcoming": None,
        "upcoming_booking_id": None,
        "upcoming_date": None,
        "upcoming_time": None,
        "upcoming_duration_minutes": None,
        "upcoming_trainer_name": "",
        "upcoming_arena_name": "",
        "has_future_booking": False,
        "days_since_last_completed": None,
        "last_trainer_name": "",
        "today_iso": "2026-08-20",
    }
    base.update(overrides)
    return base


class TestPickTrainerPulse:
    def test_sunday_stays_silent_for_weekly_digest(self):
        assert (
            pick_trainer_pulse(
                **_trainer_kwargs(weekday_mon0=6, tomorrow_sessions=4)
            )
            is None
        )
        assert (
            pick_trainer_pulse(
                **_trainer_kwargs(digest_sent_today=True, tomorrow_sessions=3)
            )
            is None
        )

    def test_cooldown_blocks(self):
        assert (
            pick_trainer_pulse(
                **_trainer_kwargs(hours_since_last_pulse=12, tomorrow_sessions=2)
            )
            is None
        )

    def test_tomorrow_plan_wins(self):
        choice = pick_trainer_pulse(
            **_trainer_kwargs(
                tomorrow_sessions=2,
                tomorrow_first_time=time(10, 0),
                tomorrow_first_name="Анна Смирнова",
                open_slots_7d=9,
            )
        )
        assert choice is not None
        assert choice.kind == CARE_PULSE_KIND_TOMORROW_PLAN
        assert choice.payload["sessions_count"] == 2

    def test_open_slots_when_tomorrow_empty(self):
        choice = pick_trainer_pulse(**_trainer_kwargs(open_slots_7d=4))
        assert choice is not None
        assert choice.kind == CARE_PULSE_KIND_OPEN_SLOTS

    def test_open_slots_below_threshold_skip(self):
        assert pick_trainer_pulse(**_trainer_kwargs(open_slots_7d=2)) is None

    def test_dormant_invite(self):
        choice = pick_trainer_pulse(
            **_trainer_kwargs(dormant_name="Кирилл", dormant_days=19)
        )
        assert choice is not None
        assert choice.kind == CARE_PULSE_KIND_INVITE_BACK

    def test_quiet_only_wednesday(self):
        assert pick_trainer_pulse(**_trainer_kwargs(weekday_mon0=0)) is None
        choice = pick_trainer_pulse(**_trainer_kwargs(weekday_mon0=2))
        assert choice is not None
        assert choice.kind == CARE_PULSE_KIND_QUIET_CHECKIN

    def test_quiet_respects_72h(self):
        assert (
            pick_trainer_pulse(
                **_trainer_kwargs(weekday_mon0=2, hours_since_last_pulse=50)
            )
            is None
        )


class TestPickClientPulse:
    def test_inactive_recent_blocks(self):
        assert (
            pick_client_pulse(
                **_client_kwargs(
                    inactive_sent_recent=True,
                    days_until_upcoming=3,
                    upcoming_booking_id=1,
                    upcoming_date=date(2026, 8, 23),
                )
            )
            is None
        )

    def test_confirmed_booking_in_window(self):
        choice = pick_client_pulse(
            **_client_kwargs(
                days_until_upcoming=3,
                upcoming_booking_id=42,
                upcoming_date=date(2026, 8, 23),
                upcoming_time=time(18, 0),
                upcoming_trainer_name="Максим",
                has_future_booking=True,
            )
        )
        assert choice is not None
        assert choice.kind == CARE_PULSE_KIND_CONFIRMED_BOOKING
        assert choice.context_key == "b:42"

    def test_tomorrow_is_reminder_territory(self):
        assert (
            pick_client_pulse(
                **_client_kwargs(
                    days_until_upcoming=1,
                    upcoming_booking_id=7,
                    upcoming_date=date(2026, 8, 21),
                    has_future_booking=True,
                )
            )
            is None
        )

    def test_invite_back_between_inactive_windows(self):
        choice = pick_client_pulse(
            **_client_kwargs(
                days_since_last_completed=6,
                last_trainer_name="Максим",
                has_future_booking=False,
            )
        )
        assert choice is not None
        assert choice.kind == CARE_PULSE_KIND_INVITE_BACK

    def test_invite_back_skipped_if_future_booking(self):
        assert (
            pick_client_pulse(
                **_client_kwargs(
                    days_since_last_completed=6,
                    has_future_booking=True,
                )
            )
            is None
        )

    def test_too_soon_after_session(self):
        assert (
            pick_client_pulse(
                **_client_kwargs(days_since_last_completed=2, has_future_booking=False)
            )
            is None
        )


class TestCarePulseWindow:
    def test_lunch_hours_only(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Europe/Minsk")
        assert is_within_care_pulse_window(datetime(2026, 8, 20, 12, 0, tzinfo=tz))
        assert is_within_care_pulse_window(datetime(2026, 8, 20, 13, 59, tzinfo=tz))
        assert not is_within_care_pulse_window(datetime(2026, 8, 20, 8, 0, tzinfo=tz))
        assert not is_within_care_pulse_window(datetime(2026, 8, 20, 14, 0, tzinfo=tz))
