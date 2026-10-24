from src.application.place_visit_blocks import prices_html


def _slots(adult, child, rental):
    return [{"price_adult_minor": adult, "price_child_minor": child, "price_rental_minor": rental}]


def test_equal_adult_and_child_price_render_two_labelled_blocks_without_entry_wording() -> None:
    html = prices_html(_slots(1200, 1200, 500), {}, currency="BYN")
    assert ">Взрослый<" in html
    assert ">Детский<" in html
    assert html.count("12 BYN") == 2
    assert "Вход" not in html
    assert "свои коньки" not in html


def test_rental_row_uses_known_slot_price_instead_of_box_office_wording() -> None:
    from src.application.arena_visit_info import visit_view

    card = {"amenities": {"skate_rental": True}, "opening_hours": {}, "visit_info": {}}
    row = visit_view(card, rental_price="5 BYN")["services"]["rows"][0]
    assert row["price"] == "5 BYN"
    assert row["note"] == ""

    unknown = visit_view(card)["services"]["rows"][0]
    assert unknown["price"] == ""
    assert unknown["note"] == "цена в кассе"
