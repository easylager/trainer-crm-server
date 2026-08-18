"""Admin platform stats: North Star, activation funnel keys (get_platform_stats)."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.stats_use_cases import ACTIVATION_STAGE_ORDER, get_platform_stats


@pytest.mark.asyncio
async def test_get_platform_stats_includes_north_star_and_activation(db_session: AsyncSession) -> None:
    data = await get_platform_stats(db_session)
    assert "north_star_completed_booking_cycles_week" in data
    assert "north_star_completed_booking_cycles_prev_week" in data
    assert "prev_week_start" in data and "prev_week_end" in data
    assert "activation_stage_counts" in data
    assert "trainers_activation" in data
    assert "activation_stage_labels_ru" in data
    assert data["activation_stage_order"] == list(ACTIVATION_STAGE_ORDER)
    for k in ACTIVATION_STAGE_ORDER:
        assert k in data["activation_stage_counts"]
    assert "live_trainers" in data
    assert "sessions_7d" in data
    assert "trainers_live_7d" in data
    assert "mrr_cents" in data
    assert "action_moderation" in data
    assert "ghost_trainers_count" in data
    assert isinstance(data["live_trainers"], list)
    assert len(data["live_trainers"]) <= 15


@pytest.mark.asyncio
async def test_platform_stats_hides_empty_pending_trainers_from_live_list(db_session: AsyncSession) -> None:
    """Bare pending_profile rows must not appear as «working trainers»."""
    before_ghosts = (await get_platform_stats(db_session))["ghost_trainers_count"]
    await db_session.execute(
        text(
            """
            INSERT INTO trainers (status, schedule_grid_step_minutes)
            VALUES ('pending_profile', 15)
            """
        )
    )
    await db_session.commit()
    data = await get_platform_stats(db_session)
    assert data["ghost_trainers_count"] == before_ghosts + 1
    for row in data["live_trainers"]:
        assert row.get("status") == "active" or row.get("stage_key") == "active"
