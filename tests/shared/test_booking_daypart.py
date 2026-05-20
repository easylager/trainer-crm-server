"""booking_daypart: slot start windows for per-client self-booking."""
from datetime import time

from src.shared.booking_daypart import (
    BOOKING_DAYPART_AFTERNOON,
    BOOKING_DAYPART_EVENING,
    BOOKING_DAYPART_MORNING,
    normalize_booking_daypart,
    slot_dict_matches_booking_daypart,
    slot_start_in_booking_daypart,
)


def test_normalize_booking_daypart() -> None:
    assert normalize_booking_daypart(None) is None
    assert normalize_booking_daypart("") is None
    assert normalize_booking_daypart("any") is None
    assert normalize_booking_daypart("morning") == BOOKING_DAYPART_MORNING
    assert normalize_booking_daypart("EVENING") == BOOKING_DAYPART_EVENING
    assert normalize_booking_daypart("noon") is None


def test_slot_start_in_booking_daypart_boundaries() -> None:
    assert slot_start_in_booking_daypart(time(8, 0), BOOKING_DAYPART_MORNING)
    assert slot_start_in_booking_daypart(time(12, 0), BOOKING_DAYPART_MORNING)
    assert not slot_start_in_booking_daypart(time(12, 30), BOOKING_DAYPART_MORNING)
    assert not slot_start_in_booking_daypart(time(7, 59), BOOKING_DAYPART_MORNING)

    assert slot_start_in_booking_daypart(time(13, 0), BOOKING_DAYPART_AFTERNOON)
    assert slot_start_in_booking_daypart(time(16, 0), BOOKING_DAYPART_AFTERNOON)
    assert not slot_start_in_booking_daypart(time(17, 0), BOOKING_DAYPART_AFTERNOON)

    assert slot_start_in_booking_daypart(time(17, 0), BOOKING_DAYPART_EVENING)
    assert slot_start_in_booking_daypart(time(22, 0), BOOKING_DAYPART_EVENING)
    assert slot_start_in_booking_daypart(time(23, 30), BOOKING_DAYPART_EVENING)
    assert not slot_start_in_booking_daypart(time(16, 30), BOOKING_DAYPART_EVENING)


def test_slot_dict_matches_hhmm_string() -> None:
    assert slot_dict_matches_booking_daypart({"start_time": "09:30"}, BOOKING_DAYPART_MORNING)
    assert not slot_dict_matches_booking_daypart({"start_time": "14:00"}, BOOKING_DAYPART_MORNING)
    assert slot_dict_matches_booking_daypart({"start_time": "22:00"}, BOOKING_DAYPART_EVENING)
    assert slot_dict_matches_booking_daypart({"start_time": "23:00"}, BOOKING_DAYPART_EVENING)
