"""TASK-329 AC2/AC6: волна пишется после коммита публикации, её сбой не ломает прогон."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.ingestion.jobs import InMemoryParserJobStore
from src.ingestion.parsers import ParserRegistry
from src.ingestion.publish import IceSessionPublisher
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import InMemoryScrapeRunRecorder
from src.ingestion.types import RUN_STATUS_EMPTY, RUN_STATUS_ERROR, RUN_STATUS_OK, ParserJob
from tests.ingestion.fakes import FakeJsonWidgetParser

_NOW = datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc)
_EVENT = {"date": "2026-09-23", "start": "09:00", "end": "10:00", "adult": 4000, "id": "evt-1"}


def _job(events: list[dict]) -> ParserJob:
    return ParserJob(
        id=7,
        arena_id=321,
        parser_key=FakeJsonWidgetParser.parser_key,
        is_enabled=True,
        cadence="daily",
        next_run_at=_NOW - timedelta(minutes=5),
        last_run_at=None,
        config={"payload": {"events": events}, "currency_code": "BYN", "prices_already_minor": True},
    )


class _FailingPublisher(IceSessionPublisher):
    async def publish(self, run, drafts, *, run_id):
        raise RuntimeError("publish exploded")


def _scheduler(job, *, calls, recorder_fn, publisher=None, with_checkpoint=True):
    registry = ParserRegistry()
    registry.register(FakeJsonWidgetParser())

    async def checkpoint() -> None:
        calls.append("checkpoint")

    store = InMemoryParserJobStore([job])
    sched = IceIngestScheduler(
        store=store,
        recorder=InMemoryScrapeRunRecorder(),
        registry=registry,
        publisher=publisher if publisher is not None else IceSessionPublisher(),
        checkpoint=checkpoint if with_checkpoint else None,
        schedule_wave_recorder=recorder_fn,
    )
    return sched, store


@pytest.mark.asyncio
async def test_wave_recorded_after_checkpoint_with_arena_id() -> None:
    calls: list = []

    async def recorder(arena_id: int) -> str:
        calls.append(("wave", arena_id))
        return "seed"

    sched, _store = _scheduler(_job([_EVENT]), calls=calls, recorder_fn=recorder)
    outcomes = await sched.run_due(_NOW)
    assert outcomes[0].status == RUN_STATUS_OK
    assert calls == ["checkpoint", ("wave", 321)]


@pytest.mark.asyncio
async def test_wave_failure_does_not_break_publish_or_job() -> None:
    calls: list = []

    async def recorder(arena_id: int) -> str:
        calls.append("wave")
        raise RuntimeError("waves table is gone")

    sched, store = _scheduler(_job([_EVENT]), calls=calls, recorder_fn=recorder)
    outcomes = await sched.run_due(_NOW)  # не бросает
    assert outcomes[0].status == RUN_STATUS_OK
    assert calls == ["checkpoint", "wave"]
    assert (await store.list_due(_NOW)) == []  # задание сдвинуто, не застряло


@pytest.mark.asyncio
async def test_no_wave_without_checkpoint() -> None:
    calls: list = []

    async def recorder(arena_id: int) -> None:
        calls.append("wave")

    sched, _ = _scheduler(_job([_EVENT]), calls=calls, recorder_fn=recorder, with_checkpoint=False)
    await sched.run_due(_NOW)
    assert calls == []


@pytest.mark.asyncio
async def test_no_wave_on_empty_run() -> None:
    calls: list = []

    async def recorder(arena_id: int) -> None:
        calls.append("wave")

    sched, _ = _scheduler(_job([]), calls=calls, recorder_fn=recorder)
    outcomes = await sched.run_due(_NOW)
    assert outcomes[0].status == RUN_STATUS_EMPTY
    assert calls == ["checkpoint"]


@pytest.mark.asyncio
async def test_no_wave_when_publish_failed() -> None:
    calls: list = []

    async def recorder(arena_id: int) -> None:
        calls.append("wave")

    sched, _ = _scheduler(
        _job([_EVENT]), calls=calls, recorder_fn=recorder, publisher=_FailingPublisher()
    )
    outcomes = await sched.run_due(_NOW)
    assert outcomes[0].status == RUN_STATUS_ERROR
    assert calls == ["checkpoint"]
