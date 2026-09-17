"""TASK-118: Junost (Каток ХК «Юность», arena_id=8) parser adapter.

junost.by 403s any non-BY egress; even a BY-egress Globalping probe comes back
truncated (~10 KB) before the schedule grid. No confirmed BY-egress fetch has ever
reached the real weekend grid — this is the terminal V1 state documented in
``.ai/parsers/minsk-junost.md``: sessions=[] + blocked_without_by_egress=true. The
adapter's whole job for V1 is to recognize the known blocked shapes and never
fabricate a schedule.
"""
from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.ingestion.adapters import JunostHtmlParser, is_junost_blocked_snapshot
from src.ingestion.jobs import InMemoryParserJobStore
from src.ingestion.parsers import ParserRegistry, default_registry
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import InMemoryScrapeRunRecorder
from src.ingestion.types import RUN_STATUS_BLOCKED, RUN_STATUS_EMPTY, ParserJob

ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = ROOT / ".ai/data/fixtures/minsk-junost"
_NOW = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)


def _junost_job(**overrides) -> ParserJob:
    base = ParserJob(
        id=8,
        arena_id=8,
        parser_key=JunostHtmlParser.parser_key,
        is_enabled=False,
        cadence="weekly",
        next_run_at=_NOW - timedelta(minutes=5),
        last_run_at=None,
        config={
            "url": "https://junost.by/seansy_massovogo_kataniya_na_vyhodnyh/",
            "timezone": "Europe/Minsk",
            "kind": "public_skate",
            "requires_by_egress": True,
            "use_fallback_if_schedule_blocked": False,
            "blocked_http_statuses": [403],
            "egress": "by_ip_required",
            "fixture_dir": str(_FIXTURES),
        },
    )
    return replace(base, **overrides) if overrides else base


def test_junost_adapter_registered_in_default_registry() -> None:
    """AC-001: registered under the spec's parser_key."""
    parser = default_registry().get("junost_origin_html_v1")
    assert isinstance(parser, JunostHtmlParser)


@pytest.mark.asyncio
async def test_junost_403_fixture_matches_expected_empty_golden() -> None:
    """AC-001: the non-BY 403 fixture extracts to the fixture's empty golden."""
    expected = json.loads((_FIXTURES / "expected.json").read_text(encoding="utf-8"))
    job = _junost_job()
    extraction = await JunostHtmlParser().extract(job)

    assert extraction.slots == []
    assert expected["sessions"] == []
    assert expected["blocked_without_by_egress"] is True
    assert extraction.snapshot["blocked_without_by_egress"] is True


def test_junost_403_body_detected_as_blocked() -> None:
    html = (_FIXTURES / "junost-origin.html").read_text(encoding="utf-8")
    assert is_junost_blocked_snapshot(html) is True


def test_junost_truncated_globalping_snapshot_detected_as_blocked() -> None:
    """BY-egress Globalping probe is HTTP 200 but cut off before the schedule grid."""
    html = (_FIXTURES / "globalping-by-truncated.html").read_text(encoding="utf-8")
    assert "</html>" not in html.lower()
    assert is_junost_blocked_snapshot(html) is True


def test_junost_adapter_never_reads_the_hockey_by_price_mirror() -> None:
    """Spec: junost.hockey.by is a human price hint, never a schedule fallback."""
    source = inspect.getsource(JunostHtmlParser.extract)
    assert "hockey-skating" not in source
    assert "hockey.by" not in source
    assert "junost.hockey" not in source


def test_junost_adapter_never_persists_to_ice_sessions() -> None:
    """Extract-only contract: no direct writes to ice_sessions."""
    source = inspect.getsource(JunostHtmlParser)
    assert "INSERT" not in source
    assert "ice_sessions" not in source


@pytest.mark.asyncio
async def test_junost_job_still_blocked_without_by_egress_configured() -> None:
    """AC-003: same scheduler guarantee as ledlife (TASK-083) — the parser is never
    even invoked while the worker has no BY egress, regardless of is_enabled.
    """
    parser = JunostHtmlParser()
    job = _junost_job(is_enabled=True)
    store = InMemoryParserJobStore([job])
    recorder = InMemoryScrapeRunRecorder()
    registry = ParserRegistry()
    registry.register(parser)
    sched = IceIngestScheduler(store=store, recorder=recorder, registry=registry, by_egress_configured=False)

    await sched.run_due(_NOW)

    assert recorder.runs[0].status == RUN_STATUS_BLOCKED
    assert recorder.runs[0].error_code == "requires_by_egress"


@pytest.mark.asyncio
async def test_junost_job_extracts_empty_when_by_egress_is_configured() -> None:
    """Once a worker has real BY egress, the adapter runs but still yields no
    sessions against the 403 fixture — it must never fabricate a grid.
    """
    parser = JunostHtmlParser()
    job = _junost_job(is_enabled=True)
    store = InMemoryParserJobStore([job])
    recorder = InMemoryScrapeRunRecorder()
    registry = ParserRegistry()
    registry.register(parser)
    sched = IceIngestScheduler(store=store, recorder=recorder, registry=registry, by_egress_configured=True)

    await sched.run_due(_NOW)

    assert recorder.runs[0].status == RUN_STATUS_EMPTY
    assert recorder.runs[0].slot_count == 0
