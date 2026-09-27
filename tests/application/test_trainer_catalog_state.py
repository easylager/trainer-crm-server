"""
The catalog state machine: every transition, its journal entry, and the invariant that keeps
them inseparable (TASK-140).

The point of the whole task is that a card cannot leave the public catalog silently. That holds
only while ``set_catalog_state`` is the single writer of the column — hence the static test at
the bottom, which is as much a part of the contract as the behavioural ones.
"""
import pathlib
import re

import pytest
from sqlalchemy import text

from src.application.trainer_catalog_state import (
    CATALOG_ACTOR_MODERATOR,
    CATALOG_ACTOR_SYSTEM,
    CATALOG_ACTOR_TRAINER,
    REASON_MISSING_FIELDS,
    REASON_MODERATOR_APPROVED,
    REASON_TRAINER_HIDDEN,
    REASON_TRAINER_RESTORED,
    REASON_TRAINER_SUBMITTED,
    CatalogStateError,
    CatalogStateTransitionError,
    get_catalog_state,
    list_catalog_events,
    missing_fields_reason_detail,
    set_catalog_state,
)
from src.infrastructure.db.models import (
    CATALOG_STATE_DRAFT,
    CATALOG_STATE_HIDDEN,
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_PUBLISHED,
    TRAINER_STATUS_ACTIVE,
    TRAINER_STATUS_DEACTIVATED,
)

SRC_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src"


async def _bare_trainer(session, *, status: str = TRAINER_STATUS_ACTIVE) -> int:
    r = await session.execute(
        text("INSERT INTO trainers (status) VALUES (:s) RETURNING id"), {"s": status}
    )
    (tid,) = r.fetchone()
    await session.commit()
    return tid


async def _publish(session, tid: int) -> None:
    await set_catalog_state(
        session, tid, CATALOG_STATE_PENDING_REVIEW,
        reason=REASON_TRAINER_SUBMITTED, actor_type=CATALOG_ACTOR_TRAINER, notify=False,
    )
    await set_catalog_state(
        session, tid, CATALOG_STATE_PUBLISHED,
        reason=REASON_MODERATOR_APPROVED, actor_type=CATALOG_ACTOR_MODERATOR, notify=False,
    )


@pytest.mark.asyncio
async def test_new_trainer_starts_in_draft(db_session) -> None:
    tid = await _bare_trainer(db_session)
    state = await get_catalog_state(db_session, tid)
    assert state is not None
    assert state["catalog_state"] == CATALOG_STATE_DRAFT


@pytest.mark.asyncio
async def test_every_transition_writes_one_event_with_author(db_session) -> None:
    tid = await _bare_trainer(db_session)
    await _publish(db_session, tid)
    await set_catalog_state(
        db_session, tid, CATALOG_STATE_HIDDEN,
        reason=REASON_TRAINER_HIDDEN, actor_type=CATALOG_ACTOR_TRAINER, actor_id=tid, notify=False,
    )
    events = await list_catalog_events(db_session, tid, limit=10)
    assert [(e["from_state"], e["to_state"]) for e in events] == [
        (CATALOG_STATE_PUBLISHED, CATALOG_STATE_HIDDEN),
        (CATALOG_STATE_PENDING_REVIEW, CATALOG_STATE_PUBLISHED),
        (CATALOG_STATE_DRAFT, CATALOG_STATE_PENDING_REVIEW),
    ]
    assert events[0]["actor_type"] == CATALOG_ACTOR_TRAINER
    assert events[0]["actor_id"] == str(tid)
    assert events[1]["actor_type"] == CATALOG_ACTOR_MODERATOR


@pytest.mark.asyncio
async def test_same_state_same_reason_is_a_noop_without_a_journal_entry(db_session) -> None:
    """Re-approving an already published card must not litter the history."""
    tid = await _bare_trainer(db_session)
    await _publish(db_session, tid)
    before = len(await list_catalog_events(db_session, tid, limit=10))
    changed = await set_catalog_state(
        db_session, tid, CATALOG_STATE_PUBLISHED,
        reason=REASON_MODERATOR_APPROVED, actor_type=CATALOG_ACTOR_MODERATOR, notify=False,
    )
    assert changed is False
    assert len(await list_catalog_events(db_session, tid, limit=10)) == before


@pytest.mark.asyncio
async def test_hidden_returns_to_published_in_one_step(db_session) -> None:
    tid = await _bare_trainer(db_session)
    await _publish(db_session, tid)
    await set_catalog_state(
        db_session, tid, CATALOG_STATE_HIDDEN,
        reason=REASON_TRAINER_HIDDEN, actor_type=CATALOG_ACTOR_TRAINER, notify=False,
    )
    assert await set_catalog_state(
        db_session, tid, CATALOG_STATE_PUBLISHED,
        reason=REASON_TRAINER_RESTORED, actor_type=CATALOG_ACTOR_TRAINER, notify=False,
    )
    state = await get_catalog_state(db_session, tid)
    assert state["catalog_state"] == CATALOG_STATE_PUBLISHED


@pytest.mark.asyncio
async def test_deactivated_account_cannot_be_published(db_session) -> None:
    tid = await _bare_trainer(db_session, status=TRAINER_STATUS_DEACTIVATED)
    with pytest.raises(CatalogStateError):
        await set_catalog_state(
            db_session, tid, CATALOG_STATE_PENDING_REVIEW,
            reason=REASON_TRAINER_SUBMITTED, actor_type=CATALOG_ACTOR_TRAINER, notify=False,
        )
        await set_catalog_state(
            db_session, tid, CATALOG_STATE_PUBLISHED,
            reason=REASON_MODERATOR_APPROVED, actor_type=CATALOG_ACTOR_MODERATOR, notify=False,
        )


@pytest.mark.asyncio
async def test_any_state_may_drop_to_draft(db_session) -> None:
    """Deactivation has to work from anywhere — a card must not outlive its account."""
    tid = await _bare_trainer(db_session)
    await _publish(db_session, tid)
    assert await set_catalog_state(
        db_session, tid, CATALOG_STATE_DRAFT,
        reason="account_deactivated", actor_type=CATALOG_ACTOR_SYSTEM, notify=False,
    )


@pytest.mark.asyncio
async def test_transition_outside_the_machine_is_refused(db_session) -> None:
    """A draft cannot skip review. An unlisted edge is a caller bug, not a case to tolerate."""
    tid = await _bare_trainer(db_session)
    with pytest.raises(CatalogStateTransitionError):
        await set_catalog_state(
            db_session, tid, CATALOG_STATE_PUBLISHED,
            reason=REASON_MODERATOR_APPROVED, actor_type=CATALOG_ACTOR_MODERATOR, notify=False,
        )


@pytest.mark.asyncio
async def test_unknown_state_and_actor_are_refused(db_session) -> None:
    tid = await _bare_trainer(db_session)
    with pytest.raises(CatalogStateError):
        await set_catalog_state(
            db_session, tid, "listed", actor_type=CATALOG_ACTOR_TRAINER, notify=False
        )
    with pytest.raises(CatalogStateError):
        await set_catalog_state(
            db_session, tid, CATALOG_STATE_PENDING_REVIEW, actor_type="robot", notify=False
        )


@pytest.mark.asyncio
async def test_mirror_flag_tracks_published(db_session) -> None:
    """``is_catalog_visible`` survives one release as a derived mirror for admin tooling."""
    tid = await _bare_trainer(db_session)
    await _publish(db_session, tid)
    r = await db_session.execute(
        text("SELECT is_catalog_visible FROM trainers WHERE id = :tid"), {"tid": tid}
    )
    assert r.scalar() is True
    await set_catalog_state(
        db_session, tid, CATALOG_STATE_HIDDEN,
        reason=REASON_TRAINER_HIDDEN, actor_type=CATALOG_ACTOR_TRAINER, notify=False,
    )
    r2 = await db_session.execute(
        text("SELECT is_catalog_visible FROM trainers WHERE id = :tid"), {"tid": tid}
    )
    assert r2.scalar() is False


def test_missing_fields_reason_detail_names_the_fields() -> None:
    assert "телефон" in missing_fields_reason_detail(["phone"])
    both = missing_fields_reason_detail(["phone", "arenas"])
    assert "телефон" in both and "арена" in both
    # Never an empty sentence: a paused card always says something.
    assert missing_fields_reason_detail([]).strip()


def test_only_set_catalog_state_writes_the_column() -> None:
    """
    The invariant the whole design rests on: no transition without a journal entry.

    A raw ``UPDATE trainers SET catalog_state`` anywhere else is exactly how a card would end up
    leaving the catalog with nothing recorded and nobody notified — the bug this task fixes.
    """
    owner = SRC_ROOT / "application" / "trainer_catalog_state.py"
    pattern = re.compile(r"UPDATE\s+trainers\s+SET[^\"';]*catalog_state\s*=", re.IGNORECASE | re.DOTALL)
    offenders = []
    for path in SRC_ROOT.rglob("*.py"):
        if path == owner:
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(SRC_ROOT.parent)))
    assert offenders == [], (
        "catalog_state must only be written through set_catalog_state; found raw updates in: "
        + ", ".join(offenders)
    )
