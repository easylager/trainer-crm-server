"""Fix arena_id=115 when prod row is Moscow CSKA; Конькобежный стадион belongs in Minsk.

Revision ID: 0200_minsk_speed_oval_identity
Revises: 0199_ice_city_interest
"""
from __future__ import annotations

import asyncio

from alembic import op

revision = "0200_minsk_speed_oval_identity"
down_revision = "0199_ice_city_interest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.application.minsk_speed_oval_identity import repair_speed_oval_identity
    from src.shared.config import Settings

    settings = Settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _run() -> None:
        async with factory() as session:
            await repair_speed_oval_identity(session)
            await session.commit()
        await engine.dispose()

    asyncio.run(_run())


def downgrade() -> None:
    """Data repair — no downgrade."""
