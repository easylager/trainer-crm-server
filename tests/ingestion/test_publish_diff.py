"""Чистый план публикации: id слота не меняется, если ключ жив (TASK-223)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.ingestion.publish import _PUBLISHABLE_KINDS_SQL
from src.ingestion.publish_diff import (
    ExistingParserSession,
    is_replaceable_parser_row,
    keep_known_prices,
    plan_publish,
)
from src.ingestion.types import PARSER_KINDS, CanonicalSlotDraft

_START = datetime(2026, 3, 16, 9, 0, tzinfo=timezone.utc)


def _row(
    session_id: int,
    *,
    starts: datetime = _START,
    kind: str = "public_skate",
    source_id: str | None = "run:1",
    status: str = "active",
) -> ExistingParserSession:
    return ExistingParserSession(
        id=session_id,
        starts_at_utc=starts,
        kind=kind,
        source_id=source_id,
        status=status,
    )


def _draft(
    *,
    starts: datetime = _START,
    kind: str = "public_skate",
    price: int = 1000,
    status: str = "active",
    source_id: str | None = "src",
    label: str | None = None,
) -> CanonicalSlotDraft:
    ends = starts + timedelta(hours=1)
    return CanonicalSlotDraft(
        arena_id=1,
        kind=kind,
        starts_at_utc=starts,
        ends_at_utc=ends,
        local_date=starts.astimezone(timezone.utc).date(),
        starts_at_local=starts.astimezone(timezone.utc).time().replace(tzinfo=None),
        ends_at_local=ends.astimezone(timezone.utc).time().replace(tzinfo=None),
        price_adult_minor=price,
        price_child_minor=None,
        price_rental_minor=None,
        currency_code="BYN",
        status=status,
        observed_at=_START,
        valid_until=ends,
        session_label=label,
        source_id=source_id,
    )


def test_same_key_updates_in_place() -> None:
    draft = _draft(price=2500, label="вечер")
    plan = plan_publish([_row(7)], [draft])
    assert plan.to_update == ((7, draft),)
    assert plan.to_insert == ()
    assert plan.to_delete_ids == ()


def test_new_key_inserts_and_missing_key_deletes() -> None:
    kept = _draft()
    fresh = _draft(starts=_START + timedelta(hours=2), source_id="new")
    gone = _row(3, starts=_START + timedelta(hours=4))
    plan = plan_publish([_row(1), gone], [kept, fresh])
    assert plan.to_update == ((1, kept),)
    assert plan.to_insert == (fresh,)
    assert plan.to_delete_ids == (3,)


def test_duplicate_drafts_first_wins() -> None:
    first = _draft(price=1000, source_id="a")
    second = _draft(price=2000, source_id="b")
    plan = plan_publish([_row(4)], [first, second])
    assert plan.to_update == ((4, first),)
    assert plan.to_insert == ()


def test_duplicate_existing_keeps_lowest_id() -> None:
    draft = _draft()
    plan = plan_publish([_row(11, source_id="run:old"), _row(10, source_id=None)], [draft])
    assert plan.to_update == ((10, draft),)
    assert plan.to_delete_ids == (11,)
    assert plan.to_insert == ()


def test_hockey_practice_is_a_separate_slot() -> None:
    skate = _row(1, kind="public_skate")
    hockey = _row(2, kind="hockey_practice")
    skate_draft = _draft(kind="public_skate", price=1000)
    hockey_draft = _draft(kind="hockey_practice", price=2000)
    plan = plan_publish([skate, hockey], [skate_draft, hockey_draft])
    assert plan.to_update == ((1, skate_draft), (2, hockey_draft))
    assert plan.to_insert == ()
    assert plan.to_delete_ids == ()


def test_same_instant_in_another_timezone_matches() -> None:
    minsk = _START.astimezone(ZoneInfo("Europe/Minsk"))
    draft = _draft(starts=minsk)
    plan = plan_publish([_row(5, starts=_START)], [draft])
    assert plan.to_update == ((5, draft),)
    assert plan.to_insert == ()
    assert plan.to_delete_ids == ()


@pytest.mark.parametrize("old_status", ["expired", "cancelled", "superseded"])
def test_reactivation_takes_status_from_draft(old_status: str) -> None:
    draft = _draft(status="active")
    plan = plan_publish([_row(8, status=old_status)], [draft])
    assert plan.to_update == ((8, draft),)
    assert plan.to_update[0][1].status == "active"
    assert plan.to_delete_ids == ()


def test_admin_and_etalon_are_not_in_the_plan() -> None:
    """Даже если фильтр SQL пропустил ручную строку — план её не удаляет и не переписывает."""
    draft = _draft()
    admin = _row(1, source_id="admin")
    etalon = _row(2, starts=_START + timedelta(hours=3), source_id="etalon_minsk_v1")
    plan = plan_publish([admin, etalon], [draft])
    assert plan.to_insert == (draft,)
    assert plan.to_update == ()
    assert plan.to_delete_ids == ()


def test_null_source_id_is_replaced_like_the_delete_filter() -> None:
    """``source_id IS NULL`` входит в прежний DELETE: без черновика строка удаляется."""
    matched = _draft()
    orphan = _row(2, starts=_START + timedelta(hours=5), source_id=None)
    plan = plan_publish([_row(1, source_id=None), orphan], [matched])
    assert plan.to_update == ((1, matched),)
    assert plan.to_delete_ids == (2,)


def test_empty_drafts_drop_only_replaceable_rows() -> None:
    """Сам план на пустых черновиках всё стирает. Публикатор до плана не доходит."""
    admin = _row(1, source_id="admin")
    live = _row(2, starts=_START + timedelta(hours=2), source_id="run:1")
    plan = plan_publish([admin, live], [])
    assert plan.to_delete_ids == (2,)
    assert plan.to_insert == ()
    assert plan.to_update == ()


@pytest.mark.parametrize(
    ("source_id", "replaceable"),
    [
        (None, True),
        ("admin", False),
        ("etalon_minsk_v1", False),
        ("etalonXfoo", False),  # LIKE 'etalon_%': ``_`` — любой один символ
        ("etalon", True),  # короче шаблона: в DELETE такая строка заменяется
        ("run:42:10:00:00", True),
        ("", True),
    ],
)
def test_replaceable_source_matches_sql_delete_filter(source_id: str | None, replaceable: bool) -> None:
    assert is_replaceable_parser_row(source_id) is replaceable


def test_publishable_kinds_follow_parser_kinds() -> None:
    assert "hockey_practice" in PARSER_KINDS
    for kind in PARSER_KINDS:
        assert f"'{kind}'" in _PUBLISHABLE_KINDS_SQL


# --- runs never erase data: prices and unread days -------------------------------------------

from dataclasses import replace as _replace  # noqa: E402


def _priced_row(session_id: int, *, starts=_START, adult=630, child=530, rental=680):
    return _replace(
        _row(session_id, starts=starts),
        local_date=starts.date(),
        price_adult_minor=adult,
        price_child_minor=child,
        price_rental_minor=rental,
    )


def _priced_draft(*, starts=_START, adult, child=None, rental=None):
    return _replace(_draft(starts=starts), price_adult_minor=adult, price_child_minor=child, price_rental_minor=rental)


@pytest.mark.parametrize("empty", [None, 0])
def test_empty_draft_prices_keep_stored_prices(empty):
    plan = plan_publish([_priced_row(7)], [_priced_draft(adult=empty, child=empty, rental=empty)])
    (sid, merged), = plan.to_update
    assert sid == 7
    assert (merged.price_adult_minor, merged.price_child_minor, merged.price_rental_minor) == (630, 530, 680)


def test_real_price_change_is_accepted_and_missing_one_kept():
    plan = plan_publish([_priced_row(7)], [_priced_draft(adult=700, child=None, rental=750)])
    (_, merged), = plan.to_update
    assert (merged.price_adult_minor, merged.price_child_minor, merged.price_rental_minor) == (700, 530, 750)


def test_unknown_stored_price_takes_draft_value_and_none_stays_none():
    row = _priced_row(7, adult=None, child=None, rental=None)
    (_, merged), = plan_publish([row], [_priced_draft(adult=630)]).to_update
    assert (merged.price_adult_minor, merged.price_child_minor, merged.price_rental_minor) == (630, None, None)


def test_keep_known_prices_returns_same_draft_when_nothing_to_keep():
    draft = _priced_draft(adult=630, child=530, rental=680)
    assert keep_known_prices(_priced_row(1), draft) is draft


def test_inserted_slot_keeps_its_own_prices():
    later = _START + timedelta(days=1)
    plan = plan_publish([_priced_row(7)], [_priced_draft(adult=630), _priced_draft(starts=later, adult=None)])
    assert plan.to_insert[0].price_adult_minor is None  # no stored row to inherit from


def test_replace_dates_keeps_sessions_of_unread_days():
    day2 = _START + timedelta(days=2)
    day3 = _START + timedelta(days=3)
    rows = [_priced_row(1), _priced_row(2, starts=day2), _priced_row(3, starts=day3)]
    drafts = [_priced_draft(adult=630)]  # only day 0 read; day 2 unreadable
    plan = plan_publish(rows, drafts, replace_dates=frozenset({_START.date(), day3.date()}))
    assert plan.to_delete_ids == (3,)  # read day without the session → removed; day 2 kept
    assert [sid for sid, _ in plan.to_update] == [1]


def test_without_replace_dates_whole_window_is_replaced_as_before():
    day2 = _START + timedelta(days=2)
    plan = plan_publish([_priced_row(1), _priced_row(2, starts=day2)], [_priced_draft(adult=630)])
    assert plan.to_delete_ids == (2,)


def test_replace_dates_still_drops_duplicates_of_matched_key():
    plan = plan_publish(
        [_priced_row(1), _priced_row(2)], [_priced_draft(adult=630)], replace_dates=frozenset()
    )
    assert plan.to_delete_ids == (2,)
