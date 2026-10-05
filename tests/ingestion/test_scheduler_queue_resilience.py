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
