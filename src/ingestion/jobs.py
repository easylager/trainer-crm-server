"""Parser job store + cadence. SQL store reads ice_parser_jobs via text SQL.

Do not ``select(IceParserJob)``: configuring Base mappers trips a pre-existing
``Trainer.services`` secondary lookup. Same raw-SQL style as ice_sessions.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.types import (
    CADENCE_DAILY,
    CADENCE_HOURLY,
    CADENCE_WEEKLY,
    ParserJob,
)

_CADENCE_DELTA = {
    CADENCE_HOURLY: timedelta(hours=1),
    CADENCE_DAILY: timedelta(days=1),
    CADENCE_WEEKLY: timedelta(weeks=1),
}


def cadence_timedelta(cadence: str) -> timedelta:
    return _CADENCE_DELTA.get(cadence, timedelta(days=1))


def advance_next_run_at(cadence: str, from_dt: datetime) -> datetime:
    return from_dt + cadence_timedelta(cadence)


def job_from_row(row: Any) -> ParserJob:
    config = row.config if isinstance(getattr(row, "config", None), dict) else {}
    if not config and isinstance(row, dict):
        config = row.get("config") or {}
    return ParserJob(
        id=int(row.id),
        arena_id=int(row.arena_id),
        parser_key=str(row.parser_key),
        is_enabled=bool(row.is_enabled),
        cadence=str(row.cadence),
        next_run_at=row.next_run_at,
        last_run_at=row.last_run_at,
        config=dict(config or {}),
        notes=row.notes,
    )


class InMemoryParserJobStore:
    def __init__(self, jobs: Sequence[ParserJob]) -> None:
        self._jobs = {job.id: job for job in jobs}

    def get(self, job_id: int) -> ParserJob:
        return self._jobs[job_id]

    async def list_due(self, now: datetime) -> list[ParserJob]:
        due = [
            job
            for job in self._jobs.values()
            if job.is_enabled and job.next_run_at <= now
        ]
        due.sort(key=lambda job: (job.next_run_at, job.id))
        return due

    async def mark_attempted(
        self,
        job_id: int,
        *,
        last_run_at: datetime,
        next_run_at: datetime,
    ) -> None:
        current = self._jobs[job_id]
        self._jobs[job_id] = replace(current, last_run_at=last_run_at, next_run_at=next_run_at)


class SqlAlchemyParserJobStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_due(self, now: datetime) -> list[ParserJob]:
        result = await self._session.execute(
            text(
                """
                SELECT id, arena_id, parser_key, is_enabled, cadence,
                       next_run_at, last_run_at, config, notes
                FROM ice_parser_jobs
                WHERE is_enabled = true AND next_run_at <= :now
                ORDER BY next_run_at, id
                """
            ),
            {"now": now},
        )
        return [job_from_row(row) for row in result.fetchall()]

    async def mark_attempted(
        self,
        job_id: int,
        *,
        last_run_at: datetime,
        next_run_at: datetime,
    ) -> None:
        await self._session.execute(
            text(
                """
                UPDATE ice_parser_jobs
                SET last_run_at = :last_run_at, next_run_at = :next_run_at
                WHERE id = :job_id
                """
            ),
            {"job_id": job_id, "last_run_at": last_run_at, "next_run_at": next_run_at},
        )


def config_requires_by_egress(config: dict[str, Any]) -> bool:
    raw = config.get("requires_by_egress", False)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes"}
    return bool(raw)
