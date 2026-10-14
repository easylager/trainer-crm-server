"""FEEL-C: счётчики мест города по типам — одна функция для og и шера."""

from __future__ import annotations

from src.application.city_place_counts import (
    city_place_count_noun,
    city_place_counts_from_facets,
    city_place_counts_from_places,
    city_place_inventory_line,
)


def test_counts_from_places_splits_rinks_shops_and_other() -> None:
    places = [
        {"venue_type": "ice"},
        {"venue_type": "outdoor"},
        {"venue_type": "shop"},
        {"venue_type": "shop"},
        {"venue_type": "gym"},
    ]
    counts = city_place_counts_from_places(places)
    assert counts.total == 5
    assert counts.rinks == 2
    assert counts.shops == 2
    assert counts.other == 1
    assert city_place_count_noun(counts) == ("место", "места", "мест")
    assert city_place_inventory_line(counts, 10) == "5 мест · 10 сеансов"


def test_counts_from_facets_matches_places() -> None:
    facets = [
        {"key": "ice", "count": 12},
        {"key": "shop", "count": 2},
        {"key": "gym", "count": 1},
    ]
    counts = city_place_counts_from_facets(facets)
    assert counts.total == 15
    assert counts.rinks == 12
    assert counts.shops == 2
    assert counts.other == 1
    assert city_place_count_noun(counts) == ("место", "места", "мест")
