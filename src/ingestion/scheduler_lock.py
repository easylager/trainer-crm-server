"""Database-wide exclusion for routine and one-shot ice-ingest runners."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

_ICE_INGEST_LOCK_ID = 0x494345494E474553


async def run_with_ice_ingest_lock[Result](
    engine: AsyncEngine,
    operation: Callable[[], Awaitable[Result]],
) -> tuple[bool, Result | None]:
    """Run ``operation`` only while holding the shared Postgres session lock.

    The dedicated connection keeps the lock across the operation's per-job commits.
    Closing the connection releases it if the process exits unexpectedly.
    """
    async with engine.connect() as connection:
        acquired = bool(
            (
                await connection.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": _ICE_INGEST_LOCK_ID},
                )
            ).scalar_one()
        )
        if not acquired:
            await connection.commit()
            return False, None

        try:
            await connection.commit()
            return True, await operation()
        finally:
            await connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": _ICE_INGEST_LOCK_ID},
            )
            await connection.commit()
