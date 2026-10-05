"""TTL for ice_scrape_runs (90d keep last any + last ok) and ice_sessions.

ice_sessions lifecycle after the session is over (TASK-177):

* ended > ``SESSION_EXPIRE_AFTER`` (1 day) ago and still ``active`` → ``expired``.
  Public reads already filter by time, but reports, health counters and exports that
  count ``status = 'active'`` kept ~1 000 past rows as if they were live schedule.
  Status instead of delete: the recent past stays queryable (what was on the ice when a
  demand event happened) until the 14-day delete below.
* ended > ``SESSION_TTL_DAYS`` (14 days) ago → deleted (any status).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RUN_TTL_DAYS = 90
SESSION_TTL_DAYS = 14
SESSION_EXPIRE_AFTER = timedelta(days=1)


@dataclass(frozen=True)
class IceTtlStats:
    runs_deleted: int
    sessions_deleted: int
    sessions_expired: int = 0


async def expire_past_ice_sessions(session: AsyncSession, *, now: datetime) -> int:
    """``active`` sessions that ended more than a day ago → ``expired``. Returns row count."""
    result = await session.execute(
        text(
            """
            UPDATE ice_sessions
            SET status = 'expired'
            WHERE status = 'active'
              AND ends_at_utc < :cutoff
            """
        ),
        {"cutoff": now - SESSION_EXPIRE_AFTER},
    )
    return int(result.rowcount or 0)


async def purge_ice_scrape_ttl(session: AsyncSession, *, now: datetime) -> IceTtlStats:
    """Delete old runs except last-any and last-ok per job. Expire sessions ended > 1 day
    ago, delete sessions ended > 14 days ago.

    Does not auto-disable jobs. Does not touch future ice_sessions.
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
    expired = await expire_past_ice_sessions(session, now=now)
    return IceTtlStats(
        runs_deleted=int(runs.rowcount or 0),
        sessions_deleted=int(sessions.rowcount or 0),
        sessions_expired=expired,
    )
