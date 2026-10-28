import pytest

from src.shared.place_suggestion import classify_contact, normalize_details, PlaceSuggestionError, validate_core


def test_contact_kinds():
    assert classify_contact("anna@mail.ru") == ("anna@mail.ru", "email")
    assert classify_contact("@anna_skate") == ("@anna_skate", "telegram")
    assert classify_contact("anna_skate") == ("@anna_skate", "telegram")
    assert classify_contact("+7 900 000-00-00") == ("+7 900 000-00-00", "other")
    assert classify_contact("   ") == (None, None)


def test_details_keep_only_fields_of_kind_and_trim():
    d = normalize_details("shop", {
        "services": ["sharpening", "rental", "hack"], "price_adult": "10",
        "hours": "  пн–сб 10–20  ", "more": "x" * 2000, "disciplines": ["figure"],
    })
    assert d == {"services": ["sharpening", "rental"], "hours": "пн–сб 10–20", "more": "x" * 1000}


def test_details_rink_prices():
    d = normalize_details("ice", {"price_adult": " 500 ₽ ", "price_child": "", "services": ["sale"]})
    assert d == {"price_adult": "500 ₽"}


def test_core_requires_kind_city_and_name():
    with pytest.raises(PlaceSuggestionError):
        validate_core(kind="bar", city_id=1, new_city_name=None, name="X")
    with pytest.raises(PlaceSuggestionError):
        validate_core(kind="ice", city_id=None, new_city_name="  ", name="X")
    with pytest.raises(PlaceSuggestionError):
        validate_core(kind="ice", city_id=1, new_city_name=None, name="  ")
    assert validate_core(kind="ice", city_id=None, new_city_name=" Уфа ", name=" Арена ") == ("Уфа", "Арена")
