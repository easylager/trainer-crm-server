"""Welcome trial length resolves to landing promise (14 days)."""

import pytest
from sqlalchemy import text

from src.application.subscription_use_cases import (
    WELCOME_TRIAL_PERIOD_DAYS_KEY,
    get_resolved_welcome_trial_days_for_display,
    resolve_trial_period_days,
)


@pytest.mark.asyncio
async def test_resolve_trial_period_days_prefers_platform_setting(db_session) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO platform_settings (key, value_int)
            VALUES (:key, :val)
            ON CONFLICT (key) DO UPDATE SET value_int = EXCLUDED.value_int
            """
        ),
        {"key": WELCOME_TRIAL_PERIOD_DAYS_KEY, "val": 14},
    )
    await db_session.commit()
    assert await resolve_trial_period_days(db_session, 30) == 14
    assert await get_resolved_welcome_trial_days_for_display(db_session) == 14
