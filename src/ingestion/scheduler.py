"""Due-job runner. Extract → normalize → validate; publisher writes ice_sessions."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import replace
from datetime import datetime, timezone
from typing import Awaitable, Callable

from src.application.ice_session_use_cases import IceSessionValidationError
from src.ingestion.cpu_work import IngestTimeoutError
from src.ingestion.freshness import (
    ERROR_CODE_EMPTY_AFTER_FILTER,
    ERROR_CODE_EMPTY_SOURCE,
    next_poll_at,
    next_source_state,
)
from src.ingestion.jobs import config_requires_by_egress
from src.ingestion.source_io import egress_proxy
from src.ingestion.normalize import IceSessionNormalizer, NormalizeReport
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

# TASK-188: лимит на extract целиком (OCR/PDF внутри extract). Переопределяется job.config.
DEFAULT_JOB_TIMEOUT_S = 120.0
CONFIG_JOB_TIMEOUT_S = "job_timeout_s"
ERROR_CODE_INTERNAL = "internal_error"
ERROR_CODE_TIMEOUT = "timeout"

# TASK-188: тик держит advisory-лок ингеста; 20 заданий × 120 с — это ~40 минут. После
# бюджета новые задания не стартуют: остальные просроченные догонит следующий тик.
TICK_BUDGET_S = 300.0


class ExtractDeadlineExceeded(IngestTimeoutError):
    """Внешний дедлайн на extract целиком (job_timeout_s) истёк."""


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
        by_egress_proxy_url: str | None = None,
        rng: random.Random | None = None,
        max_jobs_per_tick: int | None = MAX_JOBS_PER_TICK,
        checkpoint: Callable[[], Awaitable[None]] | None = None,
        job_savepoint: Callable[[], AbstractAsyncContextManager] | None = None,
        tick_budget_s: float | None = TICK_BUDGET_S,
        clock: Callable[[], float] = time.monotonic,
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
        self._by_egress_configured = by_egress_configured or bool(by_egress_proxy_url)
        # Сам адрес прокси: им ходят только задания с requires_by_egress, остальные — напрямую.
        self._by_egress_proxy_url = by_egress_proxy_url
        self._rng = rng
        self._max_jobs_per_tick = max_jobs_per_tick
        # Коммит после каждого задания: новое расписание видно пользователю сразу после
        # своего прогона, а не в конце тика, где до него может быть ещё 20 сайтов.
        self._checkpoint = checkpoint
        # TASK-188: изоляция одного задания (обычно session.begin_nested): сбой его
        # бухгалтерии откатывается до savepoint, и internal_error пишется в чистую сессию.
        self._job_savepoint = job_savepoint
        self._tick_budget_s = tick_budget_s
        self._clock = clock
        # TASK-176: сколько заданий было просрочено на последнем тике (до потолка) — для heartbeat.
        self.last_due_count = 0

    async def run_due(self, now: datetime) -> list[ScrapeRunRecord]:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        outcomes: list[ScrapeRunRecord] = []
        due_jobs = await self._store.list_due(now)
        self.last_due_count = len(due_jobs)
        if self._max_jobs_per_tick is not None:
            due_jobs = due_jobs[: self._max_jobs_per_tick]
        tick_started = self._clock()
        for index, job in enumerate(due_jobs):
            elapsed = self._clock() - tick_started
            if self._tick_budget_s is not None and outcomes and elapsed >= self._tick_budget_s:
                logger.warning(
                    "ice ingest tick budget %.0fs spent after %d job(s) (%.0fs); "
                    "%d due job(s) deferred to next tick",
                    self._tick_budget_s,
                    len(outcomes),
                    elapsed,
                    len(due_jobs) - index,
                )
                break
            outcomes.append(await self._run_due_job(job, now))
        return outcomes

    async def _run_due_job(self, job: ParserJob, now: datetime) -> ScrapeRunRecord:
        savepoint = self._job_savepoint() if self._job_savepoint is not None else nullcontext()
        try:
            async with savepoint:
                record = await self._execute_job_tick(job, now)
        except Exception as exc:  # noqa: BLE001 — isolate one job; siblings must run
            logger.exception(
                "tick bookkeeping failed for job %s (arena %s); advancing with internal_error",
                job.id,
                job.arena_id,
            )
            record = await self._recover_job_after_tick_error(job, now, exc)
        if self._checkpoint is not None:
            await self._checkpoint()
        return record

    async def _execute_job_tick(self, job: ParserJob, now: datetime) -> ScrapeRunRecord:
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
        return record

    async def _recover_job_after_tick_error(
        self, job: ParserJob, now: datetime, exc: BaseException
    ) -> ScrapeRunRecord:
        record = self._record(
            job,
            status=RUN_STATUS_ERROR,
            started_at=now,
            finished_at=now,
            error_message=str(exc),
            error_code=ERROR_CODE_INTERNAL,
        )
        try:
            run_id = await self._recorder.record(record)
            if run_id is not None:
                record = replace(record, persisted_id=run_id)
        except Exception:
            logger.exception(
                "could not persist scrape run after internal_error for job %s",
                job.id,
            )
        try:
            state = await self._next_state(job, record, now)
        except Exception:
            logger.exception("could not compute source state after tick failure for job %s", job.id)
            state = job.state
        try:
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
        except Exception:
            logger.exception("could not mark job %s attempted after tick failure", job.id)
        return record

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
        proxy = self._by_egress_proxy_url if config_requires_by_egress(job.config) else None
        timeout_s = self._job_timeout_seconds(job.config)
        try:
            with egress_proxy(proxy):
                extraction = await self._extract_with_deadline(parser, job, timeout_s)
            drafts, report = self._normalize(extraction, job, now)
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
        except IngestTimeoutError as exc:
            # Наш дедлайн на extract или дедлайн CPU-шага (OCR/PDF): сообщение уже точное.
            logger.warning("parser %s timed out for job %s: %s", job.parser_key, job.id, exc)
            return (
                self._record(
                    job,
                    status=RUN_STATUS_ERROR,
                    started_at=started,
                    finished_at=now,
                    error_message=str(exc),
                    error_code=ERROR_CODE_TIMEOUT,
                ),
                empty,
            )
        except TimeoutError as exc:
            # Таймаут изнутри extract (aiohttp и пр.) — не наш дедлайн: реальное сообщение + traceback.
            logger.exception("parser %s hit an inner timeout for job %s", job.parser_key, job.id)
            return (
                self._record(
                    job,
                    status=RUN_STATUS_ERROR,
                    started_at=started,
                    finished_at=now,
                    error_message=_describe_exception(exc),
                    error_code=ERROR_CODE_TIMEOUT,
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
        # TASK-178: пустой прогон говорит, где потерялись слоты. slots_found — опубликовано,
        # slots_dropped — отброшено; извлечено = found + dropped.
        error_code = None
        error_message = None
        if status == RUN_STATUS_EMPTY:
            error_code = (
                ERROR_CODE_EMPTY_AFTER_FILTER if extraction.slots else ERROR_CODE_EMPTY_SOURCE
            )
            error_message = report.summary()
        return (
            self._record(
                job,
                status=status,
                started_at=started,
                finished_at=now,
                slot_count=len(validated),
                slots_dropped=dropped,
                snapshot=extraction.snapshot,
                error_code=error_code,
                error_message=error_message,
            ),
            validated,
        )

    def _normalize(self, extraction, job: ParserJob, now: datetime):
        with_report = getattr(self._normalizer, "normalize_with_report", None)
        if with_report is not None:
            return with_report(extraction, job, now=now)
        drafts = self._normalizer.normalize(extraction, job, now=now)
        return drafts, NormalizeReport(
            extracted=len(extraction.slots), published=len(drafts)
        )

    @staticmethod
    async def _extract_with_deadline(parser, job: ParserJob, timeout_s: float):
        deadline = asyncio.timeout(timeout_s)
        try:
            async with deadline:
                return await parser.extract(job)
        except TimeoutError as exc:
            if deadline.expired():
                raise ExtractDeadlineExceeded(f"extract timed out after {timeout_s}s") from exc
            raise

    @staticmethod
    def _job_timeout_seconds(config: dict | None) -> float:
        raw = (config or {}).get(CONFIG_JOB_TIMEOUT_S)
        if raw is None or str(raw).strip() == "":
            return DEFAULT_JOB_TIMEOUT_S
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return DEFAULT_JOB_TIMEOUT_S
        return value if value > 0 else DEFAULT_JOB_TIMEOUT_S

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


def _describe_exception(exc: BaseException) -> str:
    text = str(exc)
    name = type(exc).__name__
    return f"{name}: {text}" if text else name
