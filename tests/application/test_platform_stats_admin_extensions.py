"""Admin platform stats: North Star, activation funnel keys (get_platform_stats)."""

import pytest
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
