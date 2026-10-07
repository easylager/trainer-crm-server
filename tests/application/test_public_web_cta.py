"""TASK-207: tel: CTA only for phones with at least 7 digits."""

from src.application.public_web_cta import render_place_primary_actions


def test_place_primary_actions_skips_short_phone() -> None:
    html = render_place_primary_actions(
        {"id": 1, "phone": "123-456"},
        base_url="https://example.test",
        surface="place_page",
        city_id=1,
        city_name="Минск",
        telegram_url=None,
    )
    assert "tel:" not in html
    assert "Позвонить" not in html


def test_place_primary_actions_renders_valid_phone() -> None:
    html = render_place_primary_actions(
        {"id": 1, "phone": "+375 29 123-45-67"},
        base_url="https://example.test",
        surface="place_page",
        city_id=1,
        city_name="Минск",
        telegram_url=None,
    )
    assert 'href="tel:+375291234567"' in html
    assert "Позвонить" in html
