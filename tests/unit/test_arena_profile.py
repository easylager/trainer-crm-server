"""TASK-048: arena profile domain — slug, amenities, season, district, list rows."""
from __future__ import annotations

import pytest

from src.application.arena_profile import (
    AMENITY_KEYS,
    InvalidAmenitiesError,
    choose_arena_slug,
    district_from_nominatim_address,
    is_in_season,
    serialize_arena_list_item,
    slugify_arena_name,
    validate_amenities,
)


def test_slugify_transliterates_cyrillic_name() -> None:
    assert slugify_arena_name("Ледовый дворец «Чижовка»") == "ledovyy-dvorets-chizhovka"


def test_slugify_is_stable_for_same_name() -> None:
    name = "Минск-Арена"
    assert slugify_arena_name(name) == slugify_arena_name(name)


def test_choose_slug_uses_district_then_id_on_name_collision() -> None:
    """EDGE-001: two «Ледовый дворец» in one city get distinct predictable slugs."""
    base = slugify_arena_name("Ледовый дворец")
    taken = {base}
    with_district = choose_arena_slug(base, taken=taken, district="Заводской", arena_id=41)
    assert with_district != base
    assert with_district.startswith(base)
    taken.add(with_district)
    with_id = choose_arena_slug(base, taken=taken, district="Заводской", arena_id=42)
    assert with_id != with_district
    assert with_id.endswith("42")


def test_validate_amenities_accepts_known_keys_only() -> None:
    raw = {key: True for key in sorted(AMENITY_KEYS)}
    assert validate_amenities(raw) == raw


def test_validate_amenities_rejects_unknown_key() -> None:
    with pytest.raises(InvalidAmenitiesError):
        validate_amenities({"skate_rental": True, "sauna": True})


def test_validate_amenities_empty_is_ok() -> None:
    assert validate_amenities({}) == {}
    assert validate_amenities(None) == {}


def test_is_in_season_wraps_new_year() -> None:
    """EDGE-003: open October–March is in season in December and January, not June."""
    assert is_in_season(10, 3, month=12) is True
    assert is_in_season(10, 3, month=1) is True
    assert is_in_season(10, 3, month=6) is False


def test_is_in_season_year_round_when_months_missing() -> None:
    assert is_in_season(None, None, month=8) is True


def test_district_prefers_city_district_over_suburb() -> None:
    assert (
        district_from_nominatim_address(
            {"city_district": "Заводской район", "suburb": "Чижовка", "city": "Минск"}
        )
        == "Заводской район"
    )


def test_district_falls_back_to_suburb() -> None:
    assert district_from_nominatim_address({"suburb": "Уручье", "city": "Минск"}) == "Уручье"


def test_nominatim_city_mismatch_is_rejected() -> None:
    from src.application.arena_profile import nominatim_result_matches_city

    assert nominatim_result_matches_city({"city": "Минск"}, "Минск") is True
    assert nominatim_result_matches_city({"city": "Москва"}, "Минск") is False
    assert nominatim_result_matches_city({"suburb": "Уручье"}, "Минск") is True


def test_serialize_list_item_keeps_row_when_district_is_null() -> None:
    """AC-002: missing district must not drop the arena from a list payload."""
    row = serialize_arena_list_item(
        {
            "id": 7,
            "city_id": 1,
            "name": "Каток без района",
            "sort_order": 0,
            "address": "ул. Тестовая, 1",
            "latitude": 53.9,
            "longitude": 27.5,
            "is_confirmed": True,
        },
        district=None,
    )
    assert row["id"] == 7
    assert row["district"] is None
    assert row["name"] == "Каток без района"
