"""Хаб больше не делает отдельный список ради «открытый каток живой»."""

from datetime import date, time

from src.application.arena_public_use_cases import outdoor_live_flag

TODAY = date(2026, 10, 19)


def _row(**overrides):
    base = {
        "id": 1,
        "venue_type": "outdoor",
        "tier": "C",
        "next_session_id": None,
        "next_local_date": TODAY,
        "next_starts_at_local": time(18, 0),
        "future_session_count": 0,
        "currency_code": "BYN",
        "sessions_48h": 0,
    }
    base.update(overrides)
    return base


def test_first_ranked_outdoor_with_a_session_is_live() -> None:
    rows = [
        _row(id=2, venue_type="ice", tier="A", next_session_id=9, future_session_count=1),
        _row(id=3, tier="B", next_session_id=8, future_session_count=1),
    ]
    assert outdoor_live_flag(rows, today=TODAY) is True


def test_better_ranked_outdoor_without_a_session_is_not_live() -> None:
    rows = [
        _row(id=1, tier="A", next_session_id=None),
        _row(id=2, tier="C", next_session_id=8, future_session_count=1),
    ]
    assert outdoor_live_flag(rows, today=TODAY) is False


def test_no_outdoor_rows_is_not_live() -> None:
    assert outdoor_live_flag([_row(venue_type="ice", next_session_id=1)], today=TODAY) is False
