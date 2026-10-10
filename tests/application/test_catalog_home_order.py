"""Юнит-тесты сортировки и раскладки главной каталога (TASK-191, TASK-210)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.application.catalog_home_page import (
    _BY_REGIONS,
    _minutes_until,
    _price_with_rental,
    _trainer_card_href,
    build_city_layout,
    group_catalog_cities_by_country,
)
from src.application.ice_city_day import city_slug


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


_ROOT = Path(__file__).resolve().parents[2]
_OBLAST = {
    "Бобруйск": "Могилёвская область",
    "Ивацевичи": "Брестская область",
    "Лунинец": "Брестская область",
    "Островец": "Гродненская область",
    "Речица": "Гомельская область",
    "Слуцк": "Минская область",
    "Полоцк": "Витебская область",
}
_HAND_SLUGS = ("bobruisk", "ivatsevichi", "luninets", "ostrovets", "rechitsa", "slutsk", "polotsk")


def _real_by_city_names() -> list[str]:
    names: list[str] = []
    for line in (_ROOT / "data" / "by-cities-prod.csv").read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 3 and parts[2] == "BY" and parts[1]:
            names.append(parts[1])
    for path in ("scripts/seed_cities.py", "scripts/seed_regional_arenas.py"):
        text = (_ROOT / path).read_text(encoding="utf-8")
        names.extend(re.findall(r'\("([А-ЯЁ][^"]+)",\s*\d+', text))
    names.extend(_OBLAST)
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def _placed_names(layout: dict) -> list[str]:
    names: list[str] = []
    if layout["minsk"]:
        names.append(layout["minsk"]["name"])
    names.extend(city["name"] for city in layout["oblast_centers"])
    for region in layout["regions"]:
        names.extend(city["name"] for city in region["cities"])
    names.extend(city["name"] for city in layout["ru_cities"])
    return names


def _region_of(layout: dict, city_name: str) -> str | None:
    for region in layout["regions"]:
        if any(city["name"] == city_name for city in region["cities"]):
            return str(region["name"])
    return None


def test_by_regions_follow_city_slug_and_keep_every_real_city() -> None:
    for bad in _HAND_SLUGS:
        assert bad not in _BY_REGIONS
    for name, region in _OBLAST.items():
        assert _BY_REGIONS[city_slug(name)] == region

    catalog = [
        {"name": name, "slug": city_slug(name), "country": "BY", "session_count": 0, "place_count": 1}
        for name in _real_by_city_names()
    ]
    layout = build_city_layout(catalog)
    placed = _placed_names(layout)
    assert sorted(placed) == sorted(city["name"] for city in catalog)
    other = _region_of(layout, "Бобруйск")
    assert other == "Могилёвская область"
    for name, region in _OBLAST.items():
        assert _region_of(layout, name) == region
    other_names = [
        city["name"] for region in layout["regions"] if region["name"] == "Прочие" for city in region["cities"]
    ]
    assert not other_names


def test_unknown_by_city_is_kept_in_other_and_logged(caplog) -> None:
    city = {"name": "Атлантида", "slug": "atlantida", "country": "BY", "session_count": 1, "place_count": 1}
    with caplog.at_level(logging.WARNING):
        layout = build_city_layout([city])
    assert _region_of(layout, "Атлантида") == "Прочие"
    assert any("Атлантида" in record.message and "atlantida" in record.message for record in caplog.records)


def test_minutes_until_is_live_and_under_two_hours_only() -> None:
    now = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
    soon = now + timedelta(minutes=30)
    assert _minutes_until("projected", soon, now) is None
    assert _minutes_until("manual", soon, now) is None
    assert _minutes_until("live", soon, now) == 30
    assert _minutes_until("live", now + timedelta(minutes=119), now) == 119
    assert _minutes_until("live", now + timedelta(minutes=120), now) is None
    assert _price_with_rental({"price_adult_minor": 1000, "price_rental_minor": 500, "currency_code": "BYN"}) == (
        "с прокатом 15 BYN"
    )
    assert _price_with_rental({"price_adult_minor": 1000, "currency_code": "BYN"}) is None


def test_trainer_card_href_opens_telegram_until_trainer_pages_exist() -> None:
    href = _trainer_card_href(12)
    assert href.startswith("/api/public/catalog/open-telegram?")
    assert "startapp=catalog_12_coach" in href
    assert "surface=catalog_home" in href
    assert "/t/" not in href
    assert "/trainers" not in href
