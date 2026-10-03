"""Подборка /c/: карточка места несёт тот же кадр, что мини-карточка каталога."""

from src.application.selection_page import _place_html, _place_photo_url


def test_place_card_uses_list_card_photo() -> None:
    html = _place_html(
        {
            "id": 3,
            "name": "ТЦ Замок",
            "slug": "tts-zamok",
            "district": "Центральный",
            "address": "пр-т Победителей, 65",
            "card": "/api/public/photos/arenas/3/x_card.jpg",
            "thumb": "/api/public/photos/arenas/3/x_thumb.jpg",
            "venue_icon": "❄️",
        },
        city_name="Минск",
        slots=[],
    )
    assert 'class="pick__photo"' in html
    assert "/api/public/photos/arenas/3/x_card.jpg" in html
    assert 'data-icon="❄️"' in html
    assert "pick__icon" not in html


def test_place_card_without_photo_has_type_icon_not_empty_hole() -> None:
    html = _place_html(
        {
            "id": 1,
            "name": "Юность",
            "slug": "yunost",
            "venue_icon": "❄️",
            "live_line": "завтра 10:00",
        },
        city_name="Минск",
        slots=[],
    )
    assert "pick__photo" not in html
    assert "pick__icon" in html
    assert "❄️" in html


def test_place_photo_url_skips_javascript_and_empty() -> None:
    assert _place_photo_url({"card": "javascript:alert(1)", "thumb": "/t.jpg"}) == "/t.jpg"
    assert _place_photo_url({}) is None


def test_share_page_hides_broken_photo_and_stays_light() -> None:
    from pathlib import Path

    html = (Path(__file__).resolve().parents[2] / "static" / "share" / "place.html").read_text(
        encoding="utf-8"
    )
    assert "dropBrokenPhoto" in html
    assert "color-scheme: light;" in html
    assert "prefers-color-scheme: dark" not in html
