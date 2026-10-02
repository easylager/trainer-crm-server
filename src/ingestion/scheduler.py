"""Due-job runner. Extract → normalize → validate; publisher writes ice_sessions."""
from __future__ import annotations

import logging
import random
from dataclasses import replace
from datetime import datetime, timezone
from typing import Awaitable, Callable

from src.application.ice_session_use_cases import IceSessionValidationError
from src.ingestion.freshness import next_poll_at, next_source_state
from src.ingestion.jobs import config_requires_by_egress
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

# TASK-146: опрос раз в ~45 минут на десятки арен даёт пару заданий в минуту. Потолок
# на тик гасит залп после простоя воркера: остальное догонит следующий тик (60 с).
MAX_JOBS_PER_TICK = 20


class IceIngestScheduler:
    def __init__(
        self,
        store,
        recorder: IceScrapeRunRecorder | None = None,
        registry: ParserRegistry | None = None,
        normalizer: IceSessionNormalizer | None = None,
        validator: IceSessionValidator | None = None,
        publisher: IceSessionPublisher | None = None,
        by_egress_configured: bool = False,
        rng: random.Random | None = None,
        max_jobs_per_tick: int | None = MAX_JOBS_PER_TICK,
        checkpoint: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._store = store
        self._recorder = recorder or LoggingScrapeRunRecorder()
        self._registry = registry or default_registry()
        self._normalizer = normalizer or IceSessionNormalizer()
        self._validator = validator or IceSessionValidator()
        self._publisher = publisher
        # TASK-083 / PDEC-004: worker-level proof a real BY egress path (VPS tunnel) is
        # wired up. job.config["requires_by_egress"] stays True forever once set — this
        # only says the flag is now satisfied on *this* worker, never mutate the flag.
        self._by_egress_configured = by_egress_configured
        self._rng = rng
        self._max_jobs_per_tick = max_jobs_per_tick
        # Коммит после каждого задания: новое расписание видно пользователю сразу после
        # своего прогона, а не в конце тика, где до него может быть ещё 20 сайтов.
        self._checkpoint = checkpoint

    async def run_due(self, now: datetime) -> list[ScrapeRunRecord]:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        outcomes: list[ScrapeRunRecord] = []
        due_jobs = await self._store.list_due(now)
        if self._max_jobs_per_tick is not None:
            due_jobs = due_jobs[: self._max_jobs_per_tick]
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
                try:
                    await self._publisher.publish(record, drafts, run_id=run_id)
                except Exception as exc:  # noqa: BLE001 — one job's publish must not sink the tick
                    logger.exception(
                        "publish failed for job %s (arena %s); leaving ice_sessions untouched",
                        job.id,
                        job.arena_id,
                    )
                    record = replace(
                        record,
                        status=RUN_STATUS_ERROR,
                        error_code="publish_error",
                        error_message=str(exc),
                    )
                    await self._recorder.mark_publish_error(
                        run_id, error_code="publish_error", error_message=str(exc)
                    )
            outcomes.append(record)
            state = await self._next_state(job, record, now)
            await self._store.mark_attempted(
                job.id,
                last_run_at=now,
                next_run_at=next_poll_at(
                    job_id=job.id,
                    config=job.config,
                    status=record.status,
                    state=state,
                    now=now,
                    rng=self._rng,
                ),
                state=state,
            )
            if self._checkpoint is not None:
                await self._checkpoint()
        return outcomes

    async def _next_state(self, job: ParserJob, record: ScrapeRunRecord, now: datetime):
        """Серия сбоев / last_ok_at. Пустой прогон — сбой, только если витрина не пуста."""
        shown = 0
        counter = getattr(self._store, "count_shown_sessions", None)
        if record.status == RUN_STATUS_EMPTY and counter is not None:
            shown = await counter(job.arena_id, now)
        return next_source_state(job.state, record, shown_sessions=shown)

    async def _run_one(self, job: ParserJob, now: datetime) -> tuple[ScrapeRunRecord, list]:
        started = now
        empty: list = []
        if config_requires_by_egress(job.config) and not self._by_egress_configured:
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
