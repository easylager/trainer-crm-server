"""Прайс на карточке места: Minikatok — услуги, сноска ФК «Минск» не общая."""

from src.application.place_page import _b_rental


def test_minikatok_price_list_is_services_without_fk_minsk_note() -> None:
    html = _b_rental(
        {
            "name": "Minikatok.by",
            "website_url": "https://minikatok.by/",
            "opening_hours": {
                "rental_catalog": [
                    {"label": "Каток на компанию, 45 мин", "price": "100 BYN", "note": "до 8 человек"},
                ]
            },
        }
    )
    assert "Услуги" in html
    assert "Прокат инвентаря" not in html
    assert "ФК" not in html
    assert "100 BYN" in html


def test_explicit_rental_note_stays_on_the_place_that_owns_it() -> None:
    html = _b_rental(
        {
            "name": "Лыжероллерная трасса",
            "opening_hours": {
                "rental_catalog": [{"label": "Роликовые коньки", "price": "8 BYN", "per": "час"}],
                "rental_note": "Ориентиры проката ФК «Минск» — на кассе могут отличаться.",
            },
        }
    )
    assert "Прокат инвентаря" in html
    assert "ФК «Минск»" in html
    assert '8 BYN/час' in html
    assert "8 BYN" in html
    assert 'class="row"' not in html
