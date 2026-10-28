from src.application.catalog_icons import icon_svg
from src.shared.venue_types import (
    DEFAULT_HIDDEN_VENUE_TYPES, TRAINER_VENUE_TYPE_KEYS, VENUE_TYPE_KEYS,
    normalize_venue_type, venue_type_noun, venue_type_options,
)


def test_school_is_a_known_venue_type():
    assert "school" in VENUE_TYPE_KEYS
    assert normalize_venue_type("school") == "school"
    assert venue_type_noun("school")


def test_school_is_not_offered_to_trainers_and_not_hidden_by_default():
    assert "school" not in TRAINER_VENUE_TYPE_KEYS
    assert "school" not in DEFAULT_HIDDEN_VENUE_TYPES
    assert "school" not in {o["key"] for o in venue_type_options()}
    assert "school" in {o["key"] for o in venue_type_options(include_shop=True)}


def test_school_has_a_line_icon():
    assert "M2.5 9L12 4.5 21.5 9 12 13.5z" in icon_svg("school")
