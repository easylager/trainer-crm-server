"""TASK-291: ряд «Для вас» на странице города."""

from src.application.city_hub_page import _b_for_you


def _item(i: int, **extra):
    return {
        "arena_id": i,
        "slug": f"p{i}",
        "name": f"Место {i}",
        "kind_label": "Магазин",
        "photo_url": None,
        "path": f"/p/minsk/p{i}",
        "pinned": False,
        **extra,
    }


def test_no_row_without_picks() -> None:
    assert _b_for_you({"for_you": []}) == ""
    assert _b_for_you({}) == ""


def test_row_has_up_to_three_tiles_linking_to_places() -> None:
    html = _b_for_you({"for_you": [_item(1), _item(2), _item(3), _item(4)]})
    assert ">Для вас<" in html
    assert html.count('class="b-tile__name"') == 3
    assert 'href="/p/minsk/p1"' in html and "p4" not in html
    assert "Магазин" in html
