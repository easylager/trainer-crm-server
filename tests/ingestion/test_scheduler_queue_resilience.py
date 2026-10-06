"""TASK-188 AC-2 / AC-4: stuck queue head and whole-job extract timeout."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.ingestion.cpu_work import IngestTimeoutError
from src.ingestion.jobs import InMemoryParserJobStore
from src.ingestion.parsers import ParserRegistry
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import InMemoryScrapeRunRecorder
from src.ingestion.types import Extraction, ParserJob, RUN_STATUS_ERROR
from tests.ingestion.fakes import RecordingParser

_NOW = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)


def _job(**overrides) -> ParserJob:
    base = ParserJob(
        id=1,
        arena_id=100,
        parser_key=RecordingParser.parser_key,
        is_enabled=True,
        cadence="daily",
        next_run_at=_NOW - timedelta(minutes=10),
        last_run_at=None,
        config={"url": "https://example.test/ice", "prices_already_minor": True},
    )
    return replace(base, **overrides) if overrides else base


class _FlakyRecorder(InMemoryScrapeRunRecorder):
    def __init__(self, *, fail_job_ids: set[int]) -> None:
        super().__init__()
        self.fail_job_ids = fail_job_ids

    async def record(self, run):
        if run.job_id in self.fail_job_ids:
            raise RuntimeError("simulated recorder failure")
        return await super().record(run)


class _HungParser(RecordingParser):
    async def extract(self, job: ParserJob) -> Extraction:
        await asyncio.sleep(3600)
        return await super().extract(job)


class _OcrTimeoutParser(RecordingParser):
    parser_key = "ocr_timeout_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        raise IngestTimeoutError("simulated OCR timeout")


def _within(value: datetime, minutes: float, *, jitter: float = 0.15) -> bool:
    lo = _NOW + timedelta(minutes=minutes * (1 - jitter))
    hi = _NOW + timedelta(minutes=minutes * (1 + jitter))
    return lo <= value <= hi


@pytest.mark.asyncio
async def test_recorder_failure_on_job_a_does_not_block_job_b_in_same_tick() -> None:
    """AC-2: голова очереди не застревает — B выполняется, A получает backoff."""
    recording = RecordingParser()
    job_a = _job(
        id=1,
        arena_id=1,
        next_run_at=_NOW - timedelta(hours=1),
        parser_key=recording.parser_key,
    )
    job_b = _job(
        id=2,
        arena_id=2,
        next_run_at=_NOW - timedelta(minutes=5),
        parser_key=recording.parser_key,
    )
    store = InMemoryParserJobStore([job_a, job_b])
    recorder = _FlakyRecorder(fail_job_ids={job_a.id})
    registry = ParserRegistry()
    registry.register(recording)
    sched = IceIngestScheduler(store=store, recorder=recorder, registry=registry)

    outcomes = await sched.run_due(_NOW)

    assert len(outcomes) == 2
    assert recording.seen_configs
    updated_a = store.get(job_a.id)
    assert updated_a.last_run_at == _NOW
    assert _within(updated_a.next_run_at, 15)
    assert updated_a.state.last_error_code == "internal_error"
    assert _within(store.get(job_b.id).next_run_at, 45)


@pytest.mark.asyncio
async def test_stuck_extract_records_timeout_error_code() -> None:
    """AC-4: asyncio.wait_for на extract → error_code timeout."""
    hung = _HungParser()
    job = _job(
        parser_key=hung.parser_key,
        config={"url": "https://example.test", "job_timeout_s": 0.05},
    )
    store = InMemoryParserJobStore([job])
    recorder = InMemoryScrapeRunRecorder()
    registry = ParserRegistry()
    registry.register(hung)
    sched = IceIngestScheduler(store=store, recorder=recorder, registry=registry)

    outcomes = await sched.run_due(_NOW)

    assert len(outcomes) == 1
    assert outcomes[0].status == RUN_STATUS_ERROR
    assert outcomes[0].error_code == "timeout"
    assert recorder.runs[0].error_code == "timeout"


@pytest.mark.asyncio
async def test_ingest_timeout_error_maps_to_timeout_error_code() -> None:
    """AC-4: IngestTimeoutError из OCR → error_code timeout."""
    parser = _OcrTimeoutParser()
    job = _job(parser_key=parser.parser_key)
    store = InMemoryParserJobStore([job])
    recorder = InMemoryScrapeRunRecorder()
    registry = ParserRegistry()
    registry.register(parser)
    sched = IceIngestScheduler(store=store, recorder=recorder, registry=registry)

    outcomes = await sched.run_due(_NOW)

    assert len(outcomes) == 1
    assert outcomes[0].error_code == "timeout"
    assert recorder.runs[0].error_code == "timeout"


class _InnerFetchTimeoutParser(RecordingParser):
    parser_key = "inner_fetch_timeout_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        raise TimeoutError("Connection timeout to host https://example.test")


@pytest.mark.asyncio
async def test_outer_deadline_message_names_job_timeout() -> None:
    """Review: только наш дедлайн даёт «extract timed out after Ns»."""
    hung = _HungParser()
    job = _job(parser_key=hung.parser_key, config={"url": "https://example.test", "job_timeout_s": 0.05})
    store = InMemoryParserJobStore([job])
    recorder = InMemoryScrapeRunRecorder()
    registry = ParserRegistry()
    registry.register(hung)

    outcomes = await IceIngestScheduler(store=store, recorder=recorder, registry=registry).run_due(_NOW)

    assert outcomes[0].error_code == "timeout"
    assert outcomes[0].error_message == "extract timed out after 0.05s"


@pytest.mark.asyncio
async def test_inner_fetch_timeout_keeps_real_message_and_traceback(caplog) -> None:
    """Review: TimeoutError изнутри extract (aiohttp) — не «extract timed out», с traceback."""
    parser = _InnerFetchTimeoutParser()
    job = _job(parser_key=parser.parser_key)
    store = InMemoryParserJobStore([job])
    recorder = InMemoryScrapeRunRecorder()
    registry = ParserRegistry()
    registry.register(parser)

    with caplog.at_level("ERROR", logger="src.ingestion.scheduler"):
        outcomes = await IceIngestScheduler(store=store, recorder=recorder, registry=registry).run_due(_NOW)

    assert outcomes[0].error_code == "timeout"
    assert outcomes[0].error_message == "TimeoutError: Connection timeout to host https://example.test"
    logged = [r for r in caplog.records if r.levelname == "ERROR" and r.exc_info]
    assert logged, "inner timeout must be logged with traceback"


class _Savepoint:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def __aenter__(self):
        self._log.append("enter")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._log.append("rollback" if exc_type else "release")
        return False


@pytest.mark.asyncio
async def test_job_savepoint_factory_is_explicit_and_wraps_each_job() -> None:
    """Review: savepoint передаётся явно; сбой job откатывается до своего savepoint."""
    recording = RecordingParser()
    job_a = _job(id=1, arena_id=1, next_run_at=_NOW - timedelta(hours=1))
    job_b = _job(id=2, arena_id=2, next_run_at=_NOW - timedelta(minutes=5))
    store = InMemoryParserJobStore([job_a, job_b])
    recorder = _FlakyRecorder(fail_job_ids={job_a.id})
    registry = ParserRegistry()
    registry.register(recording)
    log: list[str] = []

    sched = IceIngestScheduler(
        store=store, recorder=recorder, registry=registry, job_savepoint=lambda: _Savepoint(log)
    )
    outcomes = await sched.run_due(_NOW)

    assert outcomes[0].error_code == "internal_error"
    assert log == ["enter", "rollback", "enter", "release"]


class _ClockParser(RecordingParser):
    """Каждый extract «длится» step секунд по фейковым часам."""

    def __init__(self, clock: list[float], step: float) -> None:
        super().__init__()
        self._clock = clock
        self._step = step
        self.calls = 0

    async def extract(self, job: ParserJob) -> Extraction:
        self.calls += 1
        self._clock[0] += self._step
        return await super().extract(job)


@pytest.mark.asyncio
async def test_tick_budget_defers_remaining_due_jobs_to_next_tick() -> None:
    """Review: после бюджета тика новые job не стартуют; остальные остаются просроченными."""
    clock = [0.0]
    parser = _ClockParser(clock, step=120.0)
    jobs = [_job(id=i, arena_id=i, next_run_at=_NOW - timedelta(minutes=60 - i)) for i in range(1, 6)]
    store = InMemoryParserJobStore(jobs)
    registry = ParserRegistry()
    registry.register(parser)
    sched = IceIngestScheduler(
        store=store,
        recorder=InMemoryScrapeRunRecorder(),
        registry=registry,
        tick_budget_s=300.0,
        clock=lambda: clock[0],
    )

    outcomes = await sched.run_due(_NOW)

    # 0 → 120 → 240 (< 300, третий стартует) → 360: стоп.
    assert [o.job_id for o in outcomes] == [1, 2, 3]
    assert parser.calls == 3
    assert sched.last_due_count == 5
    deferred = [store.get(i) for i in (4, 5)]
    assert all(j.last_run_at is None and j.next_run_at < _NOW for j in deferred)

    second = await sched.run_due(_NOW)
    assert [o.job_id for o in second] == [4, 5]


@pytest.mark.asyncio
async def test_tick_budget_always_runs_at_least_one_job() -> None:
    clock = [0.0]
    parser = _ClockParser(clock, step=10.0)
    store = InMemoryParserJobStore([_job()])
    registry = ParserRegistry()
    registry.register(parser)
    sched = IceIngestScheduler(
        store=store,
        recorder=InMemoryScrapeRunRecorder(),
        registry=registry,
        tick_budget_s=0.0,
        clock=lambda: clock[0],
    )

    assert len(await sched.run_due(_NOW)) == 1


def test_default_tick_budget_is_five_minutes() -> None:
    from src.ingestion.scheduler import TICK_BUDGET_S

    assert TICK_BUDGET_S == 300.0
