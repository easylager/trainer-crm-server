"""Persist ice_scrape_runs. Must not write or delete ice_sessions."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.types import (
    RUN_STATUS_BLOCKED,
    RUN_STATUS_EMPTY,
    RUN_STATUS_ERROR,
    RUN_STATUS_OK,
    ScrapeRunRecord,
)

logger = logging.getLogger(__name__)

_NON_OK_STATUSES = {RUN_STATUS_EMPTY, RUN_STATUS_ERROR, RUN_STATUS_BLOCKED}


class IceScrapeRunRequired(ValueError):
    """ice_sessions must not be replaced without a persisted ok scrape run."""


class IceScrapeRunRecorder(Protocol):
    async def record(self, run: ScrapeRunRecord) -> int | None:
        """Persist or log a parser attempt. Must not write ice_sessions."""


def assert_can_replace_ice_sessions(run: ScrapeRunRecord | None, *, run_id: int | None) -> None:
    """TASK-061 publication gate: no silent slot writes without an ok run row."""
    if run is None or run_id is None:
        raise IceScrapeRunRequired("ice_sessions cannot be updated without a scrape run")
    if run.status != RUN_STATUS_OK:
        raise IceScrapeRunRequired("only an ok scrape run may replace ice_sessions")


def snapshot_raw_ref(snapshot: Any) -> str | None:
    if snapshot is None:
        return None
    if isinstance(snapshot, (bytes, bytearray)):
        payload = bytes(snapshot)
    elif isinstance(snapshot, str):
        payload = snapshot.encode("utf-8")
    else:
        payload = json.dumps(snapshot, default=str, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class InMemoryScrapeRunRecorder:
    def __init__(self) -> None:
        self.runs: list[ScrapeRunRecord] = []

    async def record(self, run: ScrapeRunRecord) -> int:
        self.runs.append(run)
        return len(self.runs)


class LoggingScrapeRunRecorder:
    """Fallback when no DB session is available. Does not persist."""

    async def record(self, run: ScrapeRunRecord) -> None:
        logger.info(
            "ice_scrape_run stub job_id=%s arena_id=%s parser_key=%s status=%s slots=%s dropped=%s error=%s",
            run.job_id,
            run.arena_id,
            run.parser_key,
            run.status,
            run.slot_count,
            run.slots_dropped,
            run.error_message,
        )


class SqlAlchemyScrapeRunRecorder:
    """Inserts ice_scrape_runs. empty/error/blocked never delete future slots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, run: ScrapeRunRecord) -> int:
        raw_ref = snapshot_raw_ref(run.snapshot)
        result = await self._session.execute(
            text(
                """
                INSERT INTO ice_scrape_runs (
                    job_id, arena_id, started_at, finished_at, status,
                    http_status, slots_found, slots_dropped,
                    error_code, error_summary, raw_ref
                ) VALUES (
                    :job_id, :arena_id, :started_at, :finished_at, :status,
                    :http_status, :slots_found, :slots_dropped,
                    :error_code, :error_summary, :raw_ref
                )
                RETURNING id
                """
            ),
            {
                "job_id": run.job_id,
                "arena_id": run.arena_id,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "status": run.status,
                "http_status": run.http_status,
                "slots_found": run.slot_count,
                "slots_dropped": run.slots_dropped,
                "error_code": run.error_code,
                "error_summary": run.error_message,
                "raw_ref": raw_ref,
            },
        )
        run_id = int(result.scalar_one())
        await self._retain_future_slots(run)
        return run_id

    async def _retain_future_slots(self, run: ScrapeRunRecord) -> None:
        """empty/error/blocked must not DELETE future ice_sessions (TASK-072 / design §6.1)."""
        if run.status in _NON_OK_STATUSES:
            return
        # ok publication (replace in source horizon) is TASK-061.
        return
