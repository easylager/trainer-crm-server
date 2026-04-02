"""Key/value platform settings (admin-editable integers)."""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

WELCOME_TRIAL_PERIOD_DAYS_KEY = "welcome_trial_period_days"


async def get_platform_int(session: AsyncSession, key: str) -> int | None:
    r = await session.execute(
        text("SELECT value_int FROM platform_settings WHERE key = :k"),
        {"k": key},
    )
    row = r.fetchone()
    if not row or row[0] is None:
        return None
    return int(row[0])


async def set_platform_int(session: AsyncSession, key: str, value: int) -> None:
    await session.execute(
        text("""
            INSERT INTO platform_settings (key, value_int, updated_at)
            VALUES (:k, :v, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET
                value_int = EXCLUDED.value_int,
                updated_at = CURRENT_TIMESTAMP
        """),
        {"k": key, "v": value},
    )
    await session.commit()


async def get_welcome_trial_period_days_stored(session: AsyncSession) -> int | None:
    """DB value only (admin display); business logic also uses env override."""
    return await get_platform_int(session, WELCOME_TRIAL_PERIOD_DAYS_KEY)
