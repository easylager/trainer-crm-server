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
    assert d == {"services": ["sharpening", "rental"], "disciplines": ["figure"],
                 "hours": "пн–сб 10–20", "more": "x" * 1000}


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


@pytest.mark.parametrize("bad", [5, "sharpening,sale", {"sharpening": True}, None])
def test_non_list_services_and_disciplines_are_ignored(bad):
    assert "services" not in normalize_details("shop", {"services": bad})
    assert "disciplines" not in normalize_details("school", {"disciplines": bad})


def test_shop_repair_and_disciplines():
    d = normalize_details("shop", {
        "services": ["repair", "sale"], "disciplines": ["roller", "hockey", "curling"],
    })
    assert d == {"services": ["repair", "sale"], "disciplines": ["hockey", "roller"]}


def test_other_kind_is_accepted_with_common_fields_only():
    assert validate_core(kind="other", city_id=1, new_city_name=None, name="Ледовый лагерь") == (None, "Ледовый лагерь")
    assert normalize_details("other", {"more": " что-то ", "price_adult": "5", "services": ["sale"]}) == {"more": "что-то"}
