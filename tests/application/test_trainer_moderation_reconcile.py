"""Stale moderation queue state is cleared when the aggregate is incomplete for moderation."""
import pytest
from sqlalchemy import text

from src.application.trainer_use_cases import (
    create_trainer,
    get_trainer,
    reconcile_trainer_moderation_queue_if_incomplete,
    update_trainer_profile,
    update_trainer_status,
)
from src.infrastructure.db.models import TRAINER_STATUS_ACTIVE


@pytest.mark.asyncio
async def test_moderation_feedback_cleared_when_profile_becomes_incomplete(db_session) -> None:
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
    await db_session.execute(
        text(
            """
            UPDATE trainers
            SET moderation_feedback = :fb, moderation_submitted_at = now()
            WHERE id = :tid
            """
        ),
        {"tid": tid, "fb": "Исправьте описание"},
    )
    await db_session.commit()

    row = await get_trainer(db_session, tid)
    assert row is not None
    assert (row.get("moderation_feedback") or "").strip() == "Исправьте описание"

    await update_trainer_status(db_session, tid, TRAINER_STATUS_ACTIVE)
    # Immediate published field (not revision_pending): breaks submission tier so demote + reconcile run.
    await update_trainer_profile(db_session, tid, profile={"session_duration_minutes": 5})

    row2 = await get_trainer(db_session, tid)
    assert row2 is not None
    assert row2["status"] == "pending_profile"
    assert row2.get("moderation_feedback") is None
    assert row2.get("moderation_submitted_at") is None


@pytest.mark.asyncio
async def test_reconcile_noop_when_profile_complete(db_session) -> None:
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
    await db_session.execute(
        text(
            """
            UPDATE trainers
            SET moderation_feedback = :fb
            WHERE id = :tid
            """
        ),
        {"tid": tid, "fb": "Ок"},
    )
    await db_session.commit()

    await reconcile_trainer_moderation_queue_if_incomplete(db_session, tid)

    row = await get_trainer(db_session, tid)
    assert row is not None
    assert (row.get("moderation_feedback") or "").strip() == "Ок"
