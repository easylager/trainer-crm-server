"""«Кто кого»: журнал решений (TASK-426). Отдельный модуль, чтобы его звали и ``hockey_notices``, и ``kk_notify``.

Одна запись на решение по игроку и проход. Без кандидата записи нет; повтор одного и того же отказа
в течение часа не пишется заново. Кроме ``player_key`` персональных данных нет. Таблица пока не чистится.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import text

logger = logging.getLogger(__name__)

JOURNAL_DEDUPE = timedelta(hours=1)
# Журнал хранится 90 дней; чистится вместе с ``hockey_notices`` (``cleanup_old_notices``), порциями.
JOURNAL_KEEP = timedelta(days=90)
JOURNAL_CLEANUP_BATCH = 2000
JOURNAL_CLEANUP_MAX_BATCHES = 10
UNKNOWN_PHASE = "unknown"

_JOURNAL_RECENT = text("""
    SELECT 1 FROM kk_notify_decisions
    WHERE player_key = :player_key AND kind IS NOT DISTINCT FROM :kind AND decision = :decision
      AND reason IS NOT DISTINCT FROM :reason AND tick_at >= :since
    LIMIT 1
    """)

_JOURNAL_INSERT = text("""
    INSERT INTO kk_notify_decisions (tick_at, player_key, phase, kind, decision, reason, result)
    VALUES (:tick_at, :player_key, :phase, :kind, :decision, :reason, :result)
    """)


async def write_journal(
    session_factory,
    *,
    tick_at: datetime,
    player_key: int,
    phase: str,
    kind: str | None,
    decision: str,
    reason: str | None = None,
    result: str | None = None,
) -> None:
    """Записать решение. Сбой журнала не должен ни остановить рассылку, ни отправить лишнего — только лог."""
    try:
        params = {
            "tick_at": tick_at,
            "player_key": player_key,
            "phase": phase,
            "kind": kind,
            "decision": decision,
            "reason": reason,
            "result": result,
        }
        async with session_factory() as session:
            if decision != "send":
                recent = await session.execute(_JOURNAL_RECENT, {**params, "since": tick_at - JOURNAL_DEDUPE})
                if recent.first() is not None:
                    return
            await session.execute(_JOURNAL_INSERT, params)
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("kk_notify journal write failed for %s", player_key, exc_info=True)



_DELETE_OLD = text("""
    DELETE FROM kk_notify_decisions
    WHERE id IN (SELECT id FROM kk_notify_decisions WHERE tick_at < :cutoff ORDER BY id LIMIT :batch)
    """)


async def cleanup_journal(session_factory, *, now: datetime) -> int:
    """Удалить записи старше ``JOURNAL_KEEP`` порциями; сбой чистки ничего не ломает. Возвращает число удалённых."""
    total = 0
    try:
        for _ in range(JOURNAL_CLEANUP_MAX_BATCHES):
            async with session_factory() as session:
                result = await session.execute(
                    _DELETE_OLD, {"cutoff": now - JOURNAL_KEEP, "batch": JOURNAL_CLEANUP_BATCH}
                )
                await session.commit()
            deleted = getattr(result, "rowcount", 0) or 0
            total += deleted
            if deleted < JOURNAL_CLEANUP_BATCH:
                break
    except Exception:  # noqa: BLE001
        logger.warning("kk_notify journal cleanup failed", exc_info=True)
    return total


__all__ = ["JOURNAL_DEDUPE", "JOURNAL_KEEP", "UNKNOWN_PHASE", "cleanup_journal", "write_journal"]
