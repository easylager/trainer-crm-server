"""TASK-222: число мест и сеансов в превью считается по всей подборке, а не по странице."""

from __future__ import annotations

from datetime import date

from src.application.selection_page import (
    _b_place_card,
    selection_count_noun,
    selection_description,
    selection_place_count,
    selection_share_description,
    sessions_left_label,
)

_ELEVEN_PLACES = [{"id": n, "name": f"Каток {n}", "venue_type": "ice"} for n in range(11)]


def _view(**over):
    view = {
        "venue": None,
        "when": None,
        "total": 15,
        "session_count": 10,
        "items": list(_ELEVEN_PLACES),
        "venue_type_facets": [{"key": "ice", "count": 15}],
    }
    view.update(over)
    return view


def test_site_card_names_how_many_sessions_remain() -> None:
    item = {
        "id": 3,
        "slug": "tts-zamok",
        "name": "ТЦ Замок",
        "venue_type": "ice",
        "live": {"kind": "session", "more_count": 78},
    }
    assert sessions_left_label(item) == "Ещё 78 сеансов в расписании"
    assert sessions_left_label({"live": {"more_count": 1}}) == "Ещё 1 сеанс в расписании"
    assert sessions_left_label({"live": {"more_count": 0}}) == ""
    html = _b_place_card(
        item,
        city_name="Минск",
        slots=[
            {
                "id": 1,
                "local_date": date(2026, 10, 17),
                "starts_at_local": "22:15",
                "price_adult_minor": 1100,
                "currency_code": "BYN",
            }
        ],
        more_anchor="schedule",
        service_mode=False,
        service_highlight_keys=frozenset(),
    )
    assert "Ещё 78 сеансов в расписании" in html
    assert 'href="/p/minsk/tts-zamok#schedule"' in html


def test_place_count_is_the_whole_selection_not_the_page() -> None:
    view = _view()
    assert len(view["items"]) < view["total"], "страница меньше подборки — иначе тест ничего не проверяет"
    assert selection_place_count(view) == 15
    text = selection_description(view)
    assert text == "15 катков · 10 сеансов"


def test_place_count_with_window_counts_places_that_have_a_session_in_it() -> None:
    view = _view(when="today_evening", window_places=7)
    assert selection_place_count(view) == 7
    assert selection_description(view).startswith("7 катков")


def test_empty_window_falls_back_to_the_whole_selection() -> None:
    view = _view(
        when="today_evening",
        window_places=0,
        window={"label": "Сегодня вечером", "key": "today_evening"},
        window_empty=True,
        skating=True,
    )
    assert selection_place_count(view) == 15
    # Как подпись в Mini App: пустое окно говорит о себе, а не о числе катков.
    assert selection_share_description(view) == "Сегодня вечером сеансов нет · показываем ближайшие"


def test_noun_comes_from_city_facets_not_the_page() -> None:
    mixed = _view(venue_type_facets=[{"key": "ice", "count": 3}, {"key": "gym", "count": 1}])
    assert selection_count_noun(mixed) == ("место", "места", "мест")
    rinks = _view(venue_type_facets=[{"key": "ice", "count": 4}, {"key": "outdoor", "count": 2}])
    assert selection_count_noun(rinks) == ("каток", "катка", "катков")
    hidden_only = _view(venue_type_facets=[{"key": "shop", "count": 4}, {"key": "ice", "count": 1}])
    assert selection_count_noun(hidden_only) == ("каток", "катка", "катков"), "магазин прячется, каток остаётся"


def test_explicit_chip_keeps_its_own_noun() -> None:
    assert selection_count_noun({"venue": "shop", "venue_type_facets": [{"key": "ice", "count": 9}]}) == (
        "место",
        "места",
        "мест",
    )
    assert selection_count_noun({"venue": "gym"}) == ("зал", "зала", "залов")
    assert selection_count_noun({"venue": "ice", "venue_type_facets": []}) == ("каток", "катка", "катков")
