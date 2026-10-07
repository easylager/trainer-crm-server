"""Юнит-тесты сортировки и заголовка главной каталога (TASK-191)."""

from __future__ import annotations

from src.application.catalog_home_page import (
    catalog_home_headline,
    group_catalog_cities_by_country,
)


def test_group_catalog_cities_minsk_first_then_sessions_and_places() -> None:
    cities = [
        {"name": "Брест", "slug": "brest", "country": "BY", "place_count": 5, "session_count": 2},
        {"name": "Минск", "slug": "minsk", "country": "BY", "place_count": 1, "session_count": 0},
        {"name": "Гомель", "slug": "gomel", "country": "BY", "place_count": 3, "session_count": 4},
    ]
    groups = group_catalog_cities_by_country(cities)
    assert [c["name"] for c in groups[0][1]] == ["Минск", "Гомель", "Брест"]


def test_group_catalog_cities_by_country_order() -> None:
    cities = [
        {"name": "СПб", "slug": "spb", "country": "RU", "place_count": 2, "session_count": 0},
        {"name": "Минск", "slug": "minsk", "country": "BY", "place_count": 1, "session_count": 0},
    ]
    groups = group_catalog_cities_by_country(cities)
    assert [code for code, _ in groups] == ["BY", "RU"]


def test_catalog_home_headline_only_by_vs_mixed() -> None:
    h1_by, title_by = catalog_home_headline({"BY"})
    assert h1_by == "Катки Беларуси"
    assert "Беларуси" in title_by
    h1_mix, title_mix = catalog_home_headline({"BY", "RU"})
    assert h1_mix == "Катки — расписание по городам"
    assert "России" in title_mix
