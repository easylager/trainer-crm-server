"""Unit tests for typical session load resolution (TASK-290)."""
from __future__ import annotations

from datetime import date, time

from src.application.session_load import (
    DAY_SAT,
    DAY_SUN,
    LEVEL_BUSY,
    LEVEL_CALM,
    LEVEL_MEDIUM,
    LoadRule,
    SessionLoadContext,
    resolve_level,
    typical_load_fields,
)


def _all_rule(day_group: str, starts_from: time, starts_before: time | None, level: str) -> LoadRule:
    return LoadRule(
        id=1,
        scope="all",
        character=None,
        arena_id=None,
        day_group=day_group,
        starts_from=starts_from,
        starts_before=starts_before,
        level=level,
        source="default",
    )


def _seed_saturday_rules() -> tuple[LoadRule, ...]:
    return (
        _all_rule(DAY_SAT, time(0, 0), time(11, 0), LEVEL_MEDIUM),
        _all_rule(DAY_SAT, time(11, 0), time(20, 0), LEVEL_BUSY),
        _all_rule(DAY_SAT, time(20, 0), None, LEVEL_MEDIUM),
    )


def _seed_sunday_rules() -> tuple[LoadRule, ...]:
    return (
        _all_rule(DAY_SUN, time(0, 0), time(11, 0), LEVEL_MEDIUM),
        _all_rule(DAY_SUN, time(11, 0), time(16, 0), LEVEL_BUSY),
        _all_rule(DAY_SUN, time(16, 0), time(19, 0), LEVEL_MEDIUM),
        _all_rule(DAY_SUN, time(19, 0), None, LEVEL_CALM),
    )


def _seed_mon_thu_rules() -> tuple[LoadRule, ...]:
    return (
        _all_rule("mon_thu", time(0, 0), time(16, 0), LEVEL_CALM),
        _all_rule("mon_thu", time(16, 0), time(19, 0), LEVEL_MEDIUM),
        _all_rule("mon_thu", time(19, 0), None, LEVEL_BUSY),
    )


def test_saturday_steady_hot_quiet() -> None:
    rules = _seed_saturday_rules()
    sat = date(2026, 10, 24)  # Saturday
    assert sat.weekday() == 5
    assert (
        resolve_level(
            rules,
            arena_id=1,
            character="steady",
            local_weekday=sat.weekday(),
            starts_at_local=time(14, 0),
        )
        == LEVEL_BUSY
    )
    assert (
        resolve_level(
            rules,
            arena_id=1,
            character="quiet",
            local_weekday=sat.weekday(),
            starts_at_local=time(14, 0),
        )
        == LEVEL_MEDIUM
    )
    assert (
        resolve_level(
            rules,
            arena_id=1,
            character="hot",
            local_weekday=sat.weekday(),
            starts_at_local=time(14, 0),
        )
        == LEVEL_BUSY
    )


def test_sunday_evening_steady_calm() -> None:
    rules = _seed_sunday_rules()
    sun = date(2026, 10, 18)  # Sunday
    assert (
        resolve_level(
            rules,
            arena_id=1,
            character="steady",
            local_weekday=sun.weekday(),
            starts_at_local=time(20, 0),
        )
        == LEVEL_CALM
    )


def test_arena_rule_not_shifted_by_character() -> None:
    rules = _seed_saturday_rules() + (
        LoadRule(
            id=99,
            scope="arena",
            character=None,
            arena_id=7,
            day_group=DAY_SAT,
            starts_from=time(11, 0),
            starts_before=time(20, 0),
            level=LEVEL_CALM,
            source="admin",
        ),
    )
    sat = date(2026, 10, 24)
    assert (
        resolve_level(
            rules,
            arena_id=7,
            character="hot",
            local_weekday=sat.weekday(),
            starts_at_local=time(14, 0),
        )
        == LEVEL_CALM
    )


def test_narrower_interval_wins() -> None:
    rules = (
        _all_rule("mon_thu", time(0, 0), time(23, 59), LEVEL_BUSY),
        _all_rule("mon_thu", time(16, 0), time(17, 0), LEVEL_CALM),
    )
    mon = date(2026, 10, 20)
    assert (
        resolve_level(
            rules,
            arena_id=1,
            character="steady",
            local_weekday=mon.weekday(),
            starts_at_local=time(16, 30),
        )
        == LEVEL_CALM
    )


def test_monday_boundary_1600_medium() -> None:
    rules = _seed_mon_thu_rules()
    mon = date(2026, 10, 20)
    assert (
        resolve_level(
            rules,
            arena_id=1,
            character="steady",
            local_weekday=mon.weekday(),
            starts_at_local=time(16, 0),
        )
        == LEVEL_MEDIUM
    )


def test_rental_kind_has_no_typical_load_fields() -> None:
    ctx = SessionLoadContext(rules=_seed_mon_thu_rules(), character_by_arena={1: "steady"})
    assert (
        typical_load_fields(
            ctx,
            arena_id=1,
            kind="rental",
            local_date=date(2026, 10, 20),
            starts_at_local="10:00",
        )
        is None
    )


def test_empty_rules_medium() -> None:
    mon = date(2026, 10, 20)
    assert (
        resolve_level(
            (),
            arena_id=1,
            character="steady",
            local_weekday=mon.weekday(),
            starts_at_local=time(10, 0),
        )
        == LEVEL_MEDIUM
    )
