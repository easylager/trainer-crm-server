"""Fix arena_id=115 when prod row is Moscow CSKA; Конькобежный стадион belongs in Minsk.

Revision ID: 0202_minsk_speed_oval_identity
Revises: 0201_merge_interest_share
"""
from __future__ import annotations

import asyncio

revision = "0202_minsk_speed_oval_identity"
down_revision = "0201_merge_interest_share"
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
