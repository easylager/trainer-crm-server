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
    ALERT_STATE_OK,
    CADENCE_DAILY,
    CADENCE_HOURLY,
    CADENCE_WEEKLY,
    ParserJob,
    SourceState,
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


def state_from_row(row: Any) -> SourceState:
    """Колонки состояния 0211; строка без них (старый SELECT) — пустое состояние."""
    def _get(name: str, default: Any = None) -> Any:
        return getattr(row, name, default)

    return SourceState(
        last_ok_at=_get("last_ok_at"),
        last_ok_slot_count=_get("last_ok_slot_count"),
        failing_since=_get("failing_since"),
        failure_streak=int(_get("failure_streak", 0) or 0),
        last_error_code=_get("last_error_code"),
        last_error_summary=_get("last_error_summary"),
        alert_state=str(_get("alert_state", ALERT_STATE_OK) or ALERT_STATE_OK),
        alert_sent_at=_get("alert_sent_at"),
    )


def job_from_row(row: Any) -> ParserJob:
    config = row.config if isinstance(getattr(row, "config", None), dict) else {}
    if not config and isinstance(row, dict):
        config = row.get("config") or {}

    def _arena_timezone() -> str | None:
        # TASK-196: arena_profiles.timezone, если SELECT его принёс (см. list_due).
        raw = getattr(row, "arena_timezone", None)
        if raw is None and isinstance(row, dict):
            raw = row.get("arena_timezone")
        return str(raw).strip() or None if raw is not None else None

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
        state=state_from_row(row),
        arena_timezone=_arena_timezone(),
    )


class InMemoryParserJobStore:
    def __init__(
        self,
        jobs: Sequence[ParserJob],
        *,
        shown_sessions: dict[int, int] | None = None,
    ) -> None:
        self._jobs = {job.id: job for job in jobs}
        # arena_id → сколько будущих сеансов парсера сейчас видит пользователь.
        self.shown_sessions = dict(shown_sessions or {})

    async def count_shown_sessions(self, arena_id: int, now: datetime) -> int:
        return int(self.shown_sessions.get(arena_id, 0))

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
        state: SourceState | None = None,
    ) -> None:
        current = self._jobs[job_id]
        self._jobs[job_id] = replace(
            current,
            last_run_at=last_run_at,
            next_run_at=next_run_at,
            state=state if state is not None else current.state,
        )


class SqlAlchemyParserJobStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_due(self, now: datetime) -> list[ParserJob]:
        result = await self._session.execute(
            text(
                """
                SELECT j.id, j.arena_id, j.parser_key, j.is_enabled, j.cadence,
                       j.next_run_at, j.last_run_at, j.config, j.notes,
                       j.last_ok_at, j.last_ok_slot_count, j.failing_since, j.failure_streak,
                       j.last_error_code, j.last_error_summary, j.alert_state, j.alert_sent_at,
                       ap.timezone AS arena_timezone
                FROM ice_parser_jobs j
                LEFT JOIN arena_profiles ap ON ap.arena_id = j.arena_id
                WHERE j.is_enabled = true AND j.next_run_at <= :now
                ORDER BY j.next_run_at, j.id
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
        state: SourceState | None = None,
    ) -> None:
        if state is None:
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
            return
        # Алертные поля (alert_state / alert_sent_at) здесь не пишем: их ведёт тик
        # алертов в своей транзакции, и планировщик не должен их перетирать.
        await self._session.execute(
            text(
                """
                UPDATE ice_parser_jobs
                SET last_run_at = :last_run_at,
                    next_run_at = :next_run_at,
                    last_ok_at = :last_ok_at,
                    last_ok_slot_count = :last_ok_slot_count,
                    failing_since = :failing_since,
                    failure_streak = :failure_streak,
                    last_error_code = :last_error_code,
                    last_error_summary = :last_error_summary
                WHERE id = :job_id
                """
            ),
            {
                "job_id": job_id,
                "last_run_at": last_run_at,
                "next_run_at": next_run_at,
                "last_ok_at": state.last_ok_at,
                "last_ok_slot_count": state.last_ok_slot_count,
                "failing_since": state.failing_since,
                "failure_streak": state.failure_streak,
                "last_error_code": state.last_error_code,
                "last_error_summary": state.last_error_summary,
            },
        )

    async def count_shown_sessions(self, arena_id: int, now: datetime) -> int:
        """Будущие сеансы арены из парсера, которые сейчас видит пользователь.

        Ручные (admin) и эталонные (etalon_*) сеансы парсер не трогает — не считаем.
        """
        result = await self._session.execute(
            text(
                """
                SELECT COUNT(*)::int
                FROM ice_sessions AS s
                WHERE s.arena_id = :arena_id
                  AND s.status = 'active'
                  AND s.kind IN ('public_skate', 'open_ice')
                  AND s.starts_at_utc > :now
                  AND (s.valid_until IS NULL OR s.valid_until >= :now)
                  AND (s.source_id IS NULL OR s.source_id NOT LIKE 'etalon_%')
                  AND (s.source_id IS NULL OR s.source_id <> 'admin')
                """
            ),
            {"arena_id": arena_id, "now": now},
        )
        return int(result.scalar() or 0)


def config_requires_by_egress(config: dict[str, Any]) -> bool:
    raw = config.get("requires_by_egress", False)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes"}
    return bool(raw)
