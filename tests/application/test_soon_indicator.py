"""Ближайший сеанс: точка и «через N мин» только внутри двух часов."""

from datetime import datetime, timedelta, timezone

from src.application.place_page import minutes_until_start, soon_html


def test_soon_label_only_inside_two_hours() -> None:
    now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    soon = {"id": 1, "starts_at_utc": (now + timedelta(minutes=40)).isoformat()}
    later = {"id": 2, "starts_at_utc": (now + timedelta(minutes=150)).isoformat()}
    past = {"id": 3, "starts_at_utc": (now - timedelta(minutes=5)).isoformat()}

    assert minutes_until_start(soon, now=now) == 40
    assert minutes_until_start(later, now=now) is None
    assert minutes_until_start(past, now=now) is None

    html = soon_html(soon, now=now)
    assert 'class="b-soon"' in html
    assert "через 40 мин" in html
    assert "data-starts=" in html
    assert soon_html(later, now=now) == ""
