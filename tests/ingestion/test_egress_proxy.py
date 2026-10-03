"""TASK-146: BY-прокси реально используется — и только заданиями с requires_by_egress."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.ingestion.jobs import InMemoryParserJobStore
from src.ingestion.parsers import IceParser, ParserRegistry
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import InMemoryScrapeRunRecorder
from src.ingestion.source_io import current_egress_proxy, egress_proxy, ssl_context
from src.ingestion.types import RUN_STATUS_BLOCKED, Extraction, ParserJob

_NOW = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
_PROXY = "http://user:secret@by-egress.example:3128"


class _ProxySpy(IceParser):
    parser_key = "proxy_spy_v1"

    def __init__(self) -> None:
        self.seen: dict[int, str | None] = {}

    async def extract(self, job: ParserJob) -> Extraction:
        self.seen[job.id] = current_egress_proxy()
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot="", slots=[])


def _job(job_id: int, *, by: bool) -> ParserJob:
    return ParserJob(
        id=job_id,
        arena_id=100 + job_id,
        parser_key=_ProxySpy.parser_key,
        is_enabled=True,
        cadence="daily",
        next_run_at=_NOW - timedelta(minutes=5),
        last_run_at=None,
        config={"url": "https://example.test", "requires_by_egress": by},
    )


def _scheduler(spy: _ProxySpy, jobs: list[ParserJob], proxy: str | None) -> tuple[IceIngestScheduler, InMemoryScrapeRunRecorder]:
    registry = ParserRegistry()
    registry.register(spy)
    recorder = InMemoryScrapeRunRecorder()
    sched = IceIngestScheduler(
        store=InMemoryParserJobStore(jobs), recorder=recorder, registry=registry, by_egress_proxy_url=proxy
    )
    return sched, recorder


def test_egress_proxy_context_is_scoped() -> None:
    assert current_egress_proxy() is None
    with egress_proxy(_PROXY):
        assert current_egress_proxy() == _PROXY
    assert current_egress_proxy() is None


@pytest.mark.asyncio
async def test_only_by_egress_jobs_go_through_the_proxy() -> None:
    spy = _ProxySpy()
    sched, _ = _scheduler(spy, [_job(1, by=True), _job(2, by=False)], _PROXY)
    await sched.run_due(_NOW)
    assert spy.seen == {1: _PROXY, 2: None}
    assert current_egress_proxy() is None


@pytest.mark.asyncio
async def test_without_proxy_by_egress_jobs_stay_blocked() -> None:
    spy = _ProxySpy()
    sched, recorder = _scheduler(spy, [_job(1, by=True)], None)
    outcomes = await sched.run_due(_NOW)
    assert spy.seen == {}
    assert outcomes[0].status == RUN_STATUS_BLOCKED


def test_ssl_context_verifies_certificates() -> None:
    import ssl

    ctx = ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
