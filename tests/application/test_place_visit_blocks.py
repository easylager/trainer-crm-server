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
