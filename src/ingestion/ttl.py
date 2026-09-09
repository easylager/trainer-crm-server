"""TTL for ice_scrape_runs (90d keep last any + last ok) and stale ice_sessions (14d)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RUN_TTL_DAYS = 90
SESSION_TTL_DAYS = 14


@dataclass(frozen=True)
class IceTtlStats:
    runs_deleted: int
    sessions_deleted: int


async def purge_ice_scrape_ttl(session: AsyncSession, *, now: datetime) -> IceTtlStats:
    """Delete old runs except last-any and last-ok per job. Delete sessions ended > 14 days ago.

    Does not auto-disable jobs. Does not delete future ice_sessions.
    """
    run_cutoff = now - timedelta(days=RUN_TTL_DAYS)
    session_cutoff = now - timedelta(days=SESSION_TTL_DAYS)
    runs = await session.execute(
        text(
            """
            WITH last_any AS (
                SELECT DISTINCT ON (job_id) id
                FROM ice_scrape_runs
                ORDER BY job_id, finished_at DESC, id DESC
            ),
            last_ok AS (
                SELECT DISTINCT ON (job_id) id
                FROM ice_scrape_runs
                WHERE status = 'ok'
                ORDER BY job_id, finished_at DESC, id DESC
            )
            DELETE FROM ice_scrape_runs AS r
            WHERE r.finished_at < :run_cutoff
              AND r.id NOT IN (
                  SELECT id FROM last_any
                  UNION
                  SELECT id FROM last_ok
              )
            """
        ),
        {"run_cutoff": run_cutoff},
    )
    sessions = await session.execute(
        text(
            """
            DELETE FROM ice_sessions
            WHERE ends_at_utc < :session_cutoff
            """
        ),
        {"session_cutoff": session_cutoff},
    )
    return IceTtlStats(
        runs_deleted=int(runs.rowcount or 0),
        sessions_deleted=int(sessions.rowcount or 0),
    )
