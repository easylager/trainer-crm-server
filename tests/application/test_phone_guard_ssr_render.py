"""TASK-207: render-layer phone guards on SSR helpers (must stay even if API sanitizes)."""

from src.application.ice_city_day_page import _unconfirmed_html
from src.application.selection_page import _phone_link


def test_unconfirmed_html_omits_tel_for_invalid_phone() -> None:
    html = _unconfirmed_html(
        [
            {
                "name": "Каток",
                "slug": "katok",
                "phone": "123-456",
                "note": "Расписание не обновлялось 4 дня — уточните у катка",
            }
        ],
        city_name="Минск",
    )
    assert "tel:" not in html
    assert "123-456" not in html


def test_unconfirmed_html_includes_tel_for_valid_phone() -> None:
    html = _unconfirmed_html(
        [
            {
                "name": "Каток",
                "slug": "katok",
                "phone": "+375 29 123-45-67",
                "note": "Расписание не обновлялось 4 дня — уточните по телефону",
            }
        ],
        city_name="Минск",
    )
    assert 'href="tel:+375291234567"' in html


def test_phone_link_empty_for_invalid() -> None:
    assert _phone_link({"phone": "123-456"}) == ""
    assert _phone_link({"phone": "Пн-Пт 09:00-18:00"}) == ""


def test_phone_link_for_valid() -> None:
    link = _phone_link({"phone": "+375 29 123-45-67"})
    assert 'href="tel:+375291234567"' in link
