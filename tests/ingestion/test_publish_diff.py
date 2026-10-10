"""Чистый план публикации: id слота не меняется, если ключ жив (TASK-223)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.ingestion.publish import _PUBLISHABLE_KINDS_SQL
from src.ingestion.publish_diff import ExistingParserSession, is_replaceable_parser_row, plan_publish
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
