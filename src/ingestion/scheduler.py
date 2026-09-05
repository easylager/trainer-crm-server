"""Due-job runner. Extract → normalize → validate; publisher writes ice_sessions."""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timezone

from src.application.ice_session_use_cases import IceSessionValidationError
from src.ingestion.jobs import advance_next_run_at, config_requires_by_egress
from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.parsers import ParserRegistry, default_registry
from src.ingestion.publish import IceSessionPublisher
from src.ingestion.scrape_runs import IceScrapeRunRecorder, LoggingScrapeRunRecorder
from src.ingestion.types import (
    RUN_STATUS_BLOCKED,
    RUN_STATUS_EMPTY,
    RUN_STATUS_ERROR,
    RUN_STATUS_OK,
    ParserJob,
    ScrapeRunRecord,
)
from src.ingestion.validate import IceSessionValidator

logger = logging.getLogger(__name__)


class IceIngestScheduler:
    def __init__(
        self,
        store,
        recorder: IceScrapeRunRecorder | None = None,
        registry: ParserRegistry | None = None,
        normalizer: IceSessionNormalizer | None = None,
        validator: IceSessionValidator | None = None,
        publisher: IceSessionPublisher | None = None,
    ) -> None:
        self._store = store
        self._recorder = recorder or LoggingScrapeRunRecorder()
        self._registry = registry or default_registry()
        self._normalizer = normalizer or IceSessionNormalizer()
        self._validator = validator or IceSessionValidator()
        self._publisher = publisher

    async def run_due(self, now: datetime) -> list[ScrapeRunRecord]:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        outcomes: list[ScrapeRunRecord] = []
        due_jobs = await self._store.list_due(now)
        for job in due_jobs:
            record, drafts = await self._run_one(job, now)
            run_id = await self._recorder.record(record)
            if run_id is not None:
                record = replace(record, persisted_id=run_id)
            if (
                self._publisher is not None
                and record.status == RUN_STATUS_OK
                and drafts
                and run_id is not None
            ):
                await self._publisher.publish(record, drafts, run_id=run_id)
            outcomes.append(record)
            await self._store.mark_attempted(
                job.id,
                last_run_at=now,
                next_run_at=advance_next_run_at(job.cadence, now),
            )
        return outcomes

    async def _run_one(self, job: ParserJob, now: datetime) -> tuple[ScrapeRunRecord, list]:
        started = now
        empty: list = []
        if config_requires_by_egress(job.config):
            return (
                self._record(
                    job,
                    status=RUN_STATUS_BLOCKED,
                    started_at=started,
                    finished_at=now,
                    error_message="requires_by_egress is not enabled on this worker",
                    error_code="requires_by_egress",
                ),
                empty,
            )
        parser = self._registry.get(job.parser_key)
        if parser is None:
            return (
                self._record(
                    job,
                    status=RUN_STATUS_ERROR,
                    started_at=started,
                    finished_at=now,
                    error_message=f"unknown parser_key={job.parser_key!r}",
                    error_code="unknown_parser_key",
                ),
                empty,
            )
        try:
            extraction = await parser.extract(job)
            drafts = self._normalizer.normalize(extraction, job, now=now)
            validated = self._validator.validate(drafts)
        except IceSessionValidationError as exc:
            return (
                self._record(
                    job,
                    status=RUN_STATUS_ERROR,
                    started_at=started,
                    finished_at=now,
                    error_message=str(exc),
                    error_code="validation_error",
                ),
                empty,
            )
        except Exception as exc:  # noqa: BLE001 — one job must not block the queue
            logger.exception("parser %s failed for job %s", job.parser_key, job.id)
            return (
                self._record(
                    job,
                    status=RUN_STATUS_ERROR,
                    started_at=started,
                    finished_at=now,
                    error_message=str(exc),
                    error_code="extract_error",
                ),
                empty,
            )
        status = RUN_STATUS_OK if validated else RUN_STATUS_EMPTY
        dropped = max(0, len(extraction.slots) - len(validated))
        return (
            self._record(
                job,
                status=status,
                started_at=started,
                finished_at=now,
                slot_count=len(validated),
                slots_dropped=dropped,
                snapshot=extraction.snapshot,
            ),
            validated,
        )

    @staticmethod
    def _record(
        job: ParserJob,
        *,
        status: str,
        started_at: datetime,
        finished_at: datetime,
        error_message: str | None = None,
        error_code: str | None = None,
        slot_count: int = 0,
        slots_dropped: int = 0,
        snapshot=None,
    ) -> ScrapeRunRecord:
        return ScrapeRunRecord(
            job_id=job.id,
            arena_id=job.arena_id,
            parser_key=job.parser_key,
            status=status,
            slot_count=slot_count,
            slots_dropped=slots_dropped,
            error_message=error_message,
            started_at=started_at,
            finished_at=finished_at,
            snapshot=snapshot,
            error_code=error_code,
        )
