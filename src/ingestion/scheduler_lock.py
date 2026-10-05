"""Database-wide exclusion for routine and one-shot ice-ingest runners."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_ICE_INGEST_LOCK_ID = 0x494345494E474553

# TASK-176: без PEP 695 (``def f[T]()``) — прод (runtime.txt) живёт на Python 3.11,
# там такой синтаксис — SyntaxError при импорте, и цикл планировщика умирал молча.
Result = TypeVar("Result")


async def run_with_ice_ingest_lock(  # noqa: UP047 — прод на 3.11, см. выше
    engine: AsyncEngine,
    operation: Callable[[], Awaitable[Result]],
) -> tuple[bool, Result | None]:
    """Run ``operation`` only while holding the shared Postgres session lock.

    The dedicated connection keeps the lock across the operation's per-job commits.
    Closing the connection releases it if the process exits unexpectedly.

    Сбой unlock (соединение с локом умерло, пока шла операция) не маскирует результат
    операции: пишем WARNING и закрываем соединение — Postgres снимает session-лок вместе
    с ним, так что лок не утекает в пул.
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
            await _release_lock(connection)


async def _release_lock(connection) -> None:
    try:
        await connection.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": _ICE_INGEST_LOCK_ID},
        )
        await connection.commit()
    except Exception:  # noqa: BLE001 — результат операции важнее аккуратного unlock
        logger.warning(
            "ice ingest lock: unlock failed (lock connection lost?); "
            "dropping the connection so Postgres releases the lock",
            exc_info=True,
        )
        try:
            await connection.invalidate()
        except Exception:  # noqa: BLE001
            logger.warning("ice ingest lock: could not invalidate lock connection", exc_info=True)
