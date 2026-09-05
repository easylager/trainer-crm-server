"""TASK-056 AC-003: booking venue SQL never concatenates trainer arenas."""

from src.application.booking_use_cases import (
    BOOKING_ARENA_UNSPECIFIED_LABEL,
    SQL_BOOKING_ARENA_DISPLAY,
)


def test_sql_booking_arena_display_has_no_string_agg() -> None:
    sql = SQL_BOOKING_ARENA_DISPLAY.lower()
    assert "string_agg" not in sql
    assert "trainer_arenas" not in sql


def test_sql_booking_arena_display_falls_back_to_trainer_clarifies_place() -> None:
    assert BOOKING_ARENA_UNSPECIFIED_LABEL in SQL_BOOKING_ARENA_DISPLAY
    assert BOOKING_ARENA_UNSPECIFIED_LABEL == "место уточняет тренер"
