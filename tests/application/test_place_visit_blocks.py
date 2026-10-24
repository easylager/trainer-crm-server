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


def test_arena_with_slots_but_no_buy_link_says_box_office_only() -> None:
    from src.application.arena_visit_info import visit_view

    card = {"opening_hours": {}, "visit_info": {}, "amenities": {}}
    assert visit_view(card, has_slots=True)["tickets"]["mode"] == "box_office"
    assert visit_view({**card, "future_session_count": 3})["tickets"]["mode"] == "box_office"
    assert visit_view(card, has_slots=False)["tickets"]["mode"] is None
    with_link = {**card, "tickets_url": "https://tickets.example/rink"}
    assert visit_view(with_link, has_slots=True)["tickets"]["mode"] == "online"


def test_size_priced_rental_catalog_does_not_add_a_box_office_rental_row() -> None:
    from src.application.arena_visit_info import visit_view

    card = {
        "amenities": {"skate_rental": True},
        "visit_info": {},
        "opening_hours": {
            "rental_title": "Прокат коньков",
            "rental_catalog": [
                {"label": "до 34 размера", "price": "5,00 BYN"},
                {"label": "от 35 размера", "price": "10,00 BYN"},
            ],
        },
    }
    rows = visit_view(card)["services"]["rows"]
    assert [r["price"] for r in rows] == ["5,00 BYN", "10,00 BYN"]
    assert not any("в кассе" in r["note"] for r in rows)
