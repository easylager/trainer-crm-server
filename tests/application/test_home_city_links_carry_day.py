"""Главная: город всегда открывает страницу города, день фильтра в ссылку не уезжает."""

from pathlib import Path

from src.application.catalog_home_page import _b_city_tile, _b_home_city_card

CITY = {"slug": "minsk", "name": "Минск", "session_count": 24}
HOME = Path(__file__).resolve().parents[2] / "static/share/catalog-home.html"


def test_tile_opens_the_city_page_even_when_a_day_is_selected() -> None:
    html = _b_city_tile(CITY, when_key="tomorrow")
    assert 'href="/c/minsk"' in html
    assert "t=ice" not in html
    assert "завтра" in html


def test_tile_without_sessions_opens_the_city_page() -> None:
    empty = {**CITY, "session_count": 0}
    assert 'href="/c/minsk"' in _b_city_tile(empty, when_key="tomorrow")


def test_your_city_card_opens_the_city_page_and_keeps_a_sole_place() -> None:
    card = {**CITY, "href": "/c/minsk"}
    html = _b_home_city_card(card)
    assert 'href="/c/minsk"' in html
    assert "t=ice" not in html
    sole = {**CITY, "href": "/p/minsk/zamok"}
    assert 'href="/p/minsk/zamok"' in _b_home_city_card(sole)


def test_leaving_home_drops_the_when_strip_from_the_view_transition() -> None:
    html = HOME.read_text(encoding="utf-8")
    assert "pageswap" in html
    assert "viewTransitionName = 'none'" in html
