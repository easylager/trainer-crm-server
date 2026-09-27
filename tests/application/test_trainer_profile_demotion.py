"""
An incomplete profile pauses the CARD, not the account (TASK-140).

This file used to assert the opposite: clearing a required field demoted the account to
``pending_profile``. That behaviour is gone — it conflated "this trainer never passed
moderation" with "this trainer's card stopped meeting the bar", wrote one ``logger.info`` line
and told the trainer nothing. Now the account stays where it is, the card moves to ``paused``
with the missing fields named, and the move is journalled and pushed.

(The old test was also red before this change: for an ``active`` trainer ``first_name`` lands in
``profile_pending``, so the published name never actually emptied and no demotion ever ran.)
"""
import pytest
from sqlalchemy import text

from src.application.trainer_catalog_state import (
    CATALOG_ACTOR_MODERATOR,
    REASON_MISSING_FIELDS,
    REASON_MODERATOR_APPROVED,
    REASON_TRAINER_SUBMITTED,
    list_catalog_events,
    set_catalog_state,
)
from src.application.trainer_use_cases import (
    create_trainer,
    get_trainer,
    update_trainer_profile,
    update_trainer_status,
)
from src.infrastructure.db.models import (
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_PUBLISHED,
    TRAINER_STATUS_ACTIVE,
)


async def _published_trainer(db_session) -> int:
    """A trainer whose card went the full way: submitted, approved, listed."""
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    r2 = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r2.scalar()
    r3 = await db_session.execute(text("SELECT id FROM arenas ORDER BY id LIMIT 1"))
    aid = r3.scalar()
    if sid is None or cid is None or aid is None:
        pytest.skip("need seed services, cities, and arenas")

    tid = await create_trainer(
        db_session,
        profile={
            "first_name": "Иван",
            "last_name": "Петров",
            "age": 25,
            "phone": "+375291112233",
            "contacts": "@ivan",
            "description": "x" * 30,
            "city_id": cid,
            "education": "Высшее профильное",
            "experience_years": 3,
            "session_duration_minutes": 45,
            "min_hours_before_booking": 24,
        },
        service_ids=[sid],
        arena_ids=[aid],
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_photos (trainer_id, file_key, sort_order) "
            "VALUES (:tid, :fk, 0)"
        ),
        {"tid": tid, "fk": "trainers/1/test.jpg"},
    )
    await db_session.commit()
    await update_trainer_status(db_session, tid, TRAINER_STATUS_ACTIVE)
    await set_catalog_state(
        db_session,
        tid,
        CATALOG_STATE_PENDING_REVIEW,
        reason=REASON_TRAINER_SUBMITTED,
        actor_type=CATALOG_ACTOR_MODERATOR,
        notify=False,
    )
    await set_catalog_state(
        db_session,
        tid,
        CATALOG_STATE_PUBLISHED,
        reason=REASON_MODERATOR_APPROVED,
        actor_type=CATALOG_ACTOR_MODERATOR,
        notify=False,
    )
    return tid


@pytest.mark.asyncio
async def test_clearing_phone_pauses_card_and_leaves_account_active(db_session) -> None:
    tid = await _published_trainer(db_session)

    # Phone applies immediately even for an active trainer (it is not a moderated text field),
    # so clearing it really does break the published card.
    await update_trainer_profile(db_session, tid, profile={"phone": ""})

    row = await get_trainer(db_session, tid)
    assert row is not None
    assert row["status"] == TRAINER_STATUS_ACTIVE, "the account must not be punished for this"
    assert row["catalog_state"] == CATALOG_STATE_PAUSED
    assert row["catalog_state_reason"] == REASON_MISSING_FIELDS


@pytest.mark.asyncio
async def test_pause_is_journalled_with_reason_and_author(db_session) -> None:
    tid = await _published_trainer(db_session)
    await update_trainer_profile(db_session, tid, profile={"phone": ""})

    events = await list_catalog_events(db_session, tid, limit=5)
    latest = events[0]
    assert latest["from_state"] == CATALOG_STATE_PUBLISHED
    assert latest["to_state"] == CATALOG_STATE_PAUSED
    assert latest["reason"] == REASON_MISSING_FIELDS
    # The sentence the trainer reads, naming what went missing — not a bare code.
    assert "телефон" in (latest["reason_detail"] or "")
    assert latest["actor_type"] == "system"


@pytest.mark.asyncio
async def test_restoring_the_field_returns_the_card_without_re_review(db_session) -> None:
    tid = await _published_trainer(db_session)
    await update_trainer_profile(db_session, tid, profile={"phone": ""})
    await update_trainer_profile(db_session, tid, profile={"phone": "+375291112233"})

    row = await get_trainer(db_session, tid)
    assert row is not None
    # Published content never changed, so there is nothing for a moderator to look at.
    assert row["catalog_state"] == CATALOG_STATE_PUBLISHED
    assert row["moderation_submitted_at"] is None
