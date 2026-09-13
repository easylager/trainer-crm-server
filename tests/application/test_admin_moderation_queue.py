"""Tests for admin moderation queue eligibility (aligned with /pending)."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.admin_moderation_queue import (
    count_trainers_eligible_for_admin_moderation,
    list_trainer_ids_eligible_for_admin_moderation,
)
from src.application.stats_use_cases import get_platform_stats
from src.application.trainer_use_cases import create_trainer


@pytest.mark.asyncio
async def test_pending_moderation_count_excludes_incomplete_pending_profile(
    db_session: AsyncSession,
) -> None:
    """Bare pending_profile rows must not inflate moderation queue stats."""
    before = await count_trainers_eligible_for_admin_moderation(db_session)
    await db_session.execute(
        text(
            """
            INSERT INTO trainers (status, schedule_grid_step_minutes)
            VALUES ('pending_profile', 15), ('pending_profile', 15)
            """
        )
    )
    await db_session.commit()
    after = await count_trainers_eligible_for_admin_moderation(db_session)
    assert after == before


@pytest.mark.asyncio
async def test_pending_moderation_excludes_opted_out_complete_profile(db_session: AsyncSession) -> None:
    """
    A pending_profile trainer with a complete-enough profile but is_catalog_visible=false must
    not show up in /pending — "publication is the trainer's decision" (see
    try_submit_trainer_for_moderation_review) applies to the admin listing too, not just the
    submit endpoint. Without this, opting out doesn't pull a trainer out of the queue and an
    admin could approve someone who withdrew.
    """
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
            "first_name": "Отказался",
            "phone": "+375291110000",
            "city_id": cid,
            "session_duration_minutes": 45,
            "min_hours_before_booking": 24,
        },
        service_ids=[sid],
        arena_ids=[aid],
    )
    await db_session.execute(
        text("INSERT INTO trainer_photos (trainer_id, file_key, sort_order) VALUES (:tid, :fk, 0)"),
        {"tid": tid, "fk": "trainers/1/test.jpg"},
    )
    await db_session.commit()

    # is_catalog_visible defaults to false — never opted in.
    ids_before = await list_trainer_ids_eligible_for_admin_moderation(db_session)
    assert tid not in ids_before

    await db_session.execute(
        text(
            "UPDATE trainers SET is_catalog_visible = true, moderation_submitted_at = now() "
            "WHERE id = :tid"
        ),
        {"tid": tid},
    )
    await db_session.commit()
    ids_opted_in = await list_trainer_ids_eligible_for_admin_moderation(db_session)
    assert tid in ids_opted_in

    # Opts back out before the admin gets to it — must drop out of the queue again.
    await db_session.execute(
        text("UPDATE trainers SET is_catalog_visible = false WHERE id = :tid"), {"tid": tid}
    )
    await db_session.commit()
    ids_opted_out = await list_trainer_ids_eligible_for_admin_moderation(db_session)
    assert tid not in ids_opted_out


@pytest.mark.asyncio
async def test_platform_stats_pending_moderation_matches_queue_helper(db_session: AsyncSession) -> None:
    stats = await get_platform_stats(db_session)
    expected = await count_trainers_eligible_for_admin_moderation(db_session)
    assert stats["trainers_pending_moderation"] == expected
