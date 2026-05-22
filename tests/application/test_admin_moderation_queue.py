"""Tests for admin moderation queue eligibility (aligned with /pending)."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.admin_moderation_queue import count_trainers_eligible_for_admin_moderation
from src.application.stats_use_cases import get_platform_stats


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
async def test_platform_stats_pending_moderation_matches_queue_helper(db_session: AsyncSession) -> None:
    stats = await get_platform_stats(db_session)
    expected = await count_trainers_eligible_for_admin_moderation(db_session)
    assert stats["trainers_pending_moderation"] == expected
