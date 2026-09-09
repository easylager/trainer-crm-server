"""Admin SQL/API: success % per ice_parser_jobs and «результата нет»."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class JobSuccessRate:
    job_id: int
    ok_7d: int
    finished_7d: int
    success_rate_7d: float | None
    ok_30d: int
    finished_30d: int
    success_rate_30d: float | None


@dataclass(frozen=True)
class ArenaNoResult:
    job_id: int
    arena_id: int
    last_status: str
    last_finished_at: datetime


def _ratio(ok_count: int, finished_count: int) -> float | None:
    if finished_count <= 0:
        return None
    return ok_count / finished_count


async def job_success_rates(
    session: AsyncSession,
    *,
    now: datetime,
    window_days: Iterable[int] = (7, 30),
) -> list[JobSuccessRate]:
    """ok / all_finished per job. Does not auto-disable jobs on a low percentage."""
    windows = tuple(window_days)
    if windows != (7, 30):
        raise ValueError("job_success_rates supports window_days=(7, 30) only")
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)
    result = await session.execute(
        text(
            """
            SELECT
                job_id,
                COUNT(*) FILTER (WHERE finished_at >= :c7 AND finished_at <= :now) AS finished_7d,
                COUNT(*) FILTER (
                    WHERE status = 'ok' AND finished_at >= :c7 AND finished_at <= :now
                ) AS ok_7d,
                COUNT(*) FILTER (WHERE finished_at >= :c30 AND finished_at <= :now) AS finished_30d,
                COUNT(*) FILTER (
                    WHERE status = 'ok' AND finished_at >= :c30 AND finished_at <= :now
                ) AS ok_30d
            FROM ice_scrape_runs
            GROUP BY job_id
            ORDER BY job_id
            """
        ),
        {"now": now, "c7": cutoff_7d, "c30": cutoff_30d},
    )
    rows: list[JobSuccessRate] = []
    for row in result.fetchall():
        finished_7d = int(row.finished_7d)
        ok_7d = int(row.ok_7d)
        finished_30d = int(row.finished_30d)
        ok_30d = int(row.ok_30d)
        rows.append(
            JobSuccessRate(
                job_id=int(row.job_id),
                ok_7d=ok_7d,
                finished_7d=finished_7d,
                success_rate_7d=_ratio(ok_7d, finished_7d),
                ok_30d=ok_30d,
                finished_30d=finished_30d,
                success_rate_30d=_ratio(ok_30d, finished_30d),
            )
        )
    return rows


async def list_arenas_with_no_result(
    session: AsyncSession,
    *,
    now: datetime,
) -> list[ArenaNoResult]:
    """Last finished run is not ok AND no future public_skate|open_ice slot."""
    result = await session.execute(
        text(
            """
            SELECT j.id AS job_id, j.arena_id, r.status AS last_status, r.finished_at AS last_finished_at
            FROM ice_parser_jobs AS j
            JOIN LATERAL (
                SELECT status, finished_at
                FROM ice_scrape_runs
                WHERE job_id = j.id
                ORDER BY finished_at DESC, id DESC
                LIMIT 1
            ) AS r ON true
            WHERE r.status <> 'ok'
              AND NOT EXISTS (
                SELECT 1
                FROM ice_sessions AS s
                WHERE s.arena_id = j.arena_id
                  AND s.kind IN ('public_skate', 'open_ice')
                  AND s.status = 'active'
                  AND s.starts_at_utc > :now
                  AND (s.valid_until IS NULL OR s.valid_until > :now)
              )
            ORDER BY j.id
            """
        ),
        {"now": now},
    )
    return [
        ArenaNoResult(
            job_id=int(row.job_id),
            arena_id=int(row.arena_id),
            last_status=str(row.last_status),
            last_finished_at=row.last_finished_at,
        )
        for row in result.fetchall()
    ]
