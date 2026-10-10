from datetime import datetime, timezone

from src.application.client_ice_watch_filters import filter_label, session_matches_filter


def test_filter_label_weekend() -> None:
    assert "выходные" in filter_label({"when": "weekend"})


def test_session_matches_weekend_window() -> None:
    now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)  # Saturday
    session = {
        "starts_at_utc": datetime(2026, 10, 11, 15, 0, tzinfo=timezone.utc),
    }
    assert session_matches_filter(session, {"when": "weekend"}, now=now)
