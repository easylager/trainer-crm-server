"""Чипы ОХМ / Центры на веб-подборке хоккея."""

from src.application.selection_page import SEG_CENTERS, _hockey_segment_chips_html


def test_city_without_centers_has_no_segment_chips() -> None:
    assert _hockey_segment_chips_html({"kind": "ohm", "center_count": 0}, city_name="Гродно") == ""


def test_city_with_centers_links_both_segments() -> None:
    html = _hockey_segment_chips_html({"kind": "ohm", "center_count": 3}, city_name="Минск")
    assert "?kind=ohm&amp;seg=centers" in html or "?kind=ohm&seg=centers" in html
    assert "Центры <small>3</small>" in html


def test_centers_page_keeps_chips() -> None:
    html = _hockey_segment_chips_html({"kind": "ohm", "seg": SEG_CENTERS, "center_count": 3}, city_name="Минск")
    assert "chip--on" in html and "Центры" in html
