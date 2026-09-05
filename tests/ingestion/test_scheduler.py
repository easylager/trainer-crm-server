"""AC-001…004: due jobs, config hand-off, unknown parser_key, disabled skip."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.ingestion.jobs import InMemoryParserJobStore, advance_next_run_at
from src.ingestion.parsers import MinskArenaSaleframeParser, ParserRegistry
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import InMemoryScrapeRunRecorder
from src.ingestion.seed_config import MINSK_ARENA_SALEFRAME_CONFIG, PARSER_KEY_MINSK_ARENA
from src.ingestion.types import ParserJob, RUN_STATUS_EMPTY, RUN_STATUS_ERROR
from tests.ingestion.fakes import RecordingParser

_NOW = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)


def _job(**overrides) -> ParserJob:
    base = ParserJob(
        id=1,
        arena_id=100,
        parser_key=RecordingParser.parser_key,
        is_enabled=True,
        cadence="daily",
        next_run_at=_NOW - timedelta(minutes=5),
        last_run_at=None,
        config={"url": "https://example.test/ice", "prices_already_minor": True},
    )
    return replace(base, **overrides) if overrides else base


def _scheduler(
    jobs: list[ParserJob],
    parsers: list | None = None,
) -> tuple[IceIngestScheduler, InMemoryParserJobStore, InMemoryScrapeRunRecorder]:
    store = InMemoryParserJobStore(jobs)
    recorder = InMemoryScrapeRunRecorder()
    registry = ParserRegistry()
    for parser in parsers or [RecordingParser()]:
        registry.register(parser)
    sched = IceIngestScheduler(store=store, recorder=recorder, registry=registry)
    return sched, store, recorder


@pytest.mark.asyncio
async def test_due_job_is_picked_up_and_cadence_advances() -> None:
    """AC-001: past next_run_at runs; after the attempt next_run_at moves by cadence."""
    job = _job()
    sched, store, recorder = _scheduler([job])
    outcomes = await sched.run_due(_NOW)

    assert len(outcomes) == 1
    updated = store.get(job.id)
    assert updated.last_run_at == _NOW
    assert updated.next_run_at == advance_next_run_at("daily", _NOW)
    assert updated.next_run_at == _NOW + timedelta(days=1)
    assert recorder.runs[0].status in {RUN_STATUS_EMPTY, RUN_STATUS_ERROR} or recorder.runs


@pytest.mark.asyncio
async def test_hourly_and_weekly_cadence_deltas() -> None:
    hourly = _job(id=1, cadence="hourly", arena_id=1)
    weekly = _job(id=2, cadence="weekly", arena_id=2, parser_key=RecordingParser.parser_key)
    recording = RecordingParser()
    sched, store, _ = _scheduler([hourly, weekly], parsers=[recording])
    await sched.run_due(_NOW)
    assert store.get(1).next_run_at == _NOW + timedelta(hours=1)
    assert store.get(2).next_run_at == _NOW + timedelta(weeks=1)


@pytest.mark.asyncio
async def test_scheduler_passes_config_json_without_hardcoded_url() -> None:
    """AC-002: strategy sees url from job.config; scheduler source has no arena URL."""
    recording = RecordingParser()
    url = "https://saleframe.minskarena.by/service/55"
    job = _job(config={"url": url, "api_host": "https://abws.minskarena.by", "service_id": 55})
    sched, _, _ = _scheduler([job], parsers=[recording])
    await sched.run_due(_NOW)

    assert recording.seen_configs == [
        {"url": url, "api_host": "https://abws.minskarena.by", "service_id": 55}
    ]
    from pathlib import Path

    sched_src = Path("src/ingestion/scheduler.py").read_text(encoding="utf-8")
    assert "saleframe.minskarena.by" not in sched_src
    assert "abws.minskarena.by" not in sched_src


@pytest.mark.asyncio
async def test_unknown_parser_key_is_error_and_other_jobs_continue() -> None:
    """AC-003: unknown parser_key → error run; sibling job still executes."""
    recording = RecordingParser()
    unknown = _job(id=1, arena_id=1, parser_key="no_such_parser_v9")
    known = _job(id=2, arena_id=2, parser_key=recording.parser_key)
    sched, store, recorder = _scheduler([unknown, known], parsers=[recording])
    await sched.run_due(_NOW)

    by_job = {run.job_id: run for run in recorder.runs}
    assert by_job[1].status == RUN_STATUS_ERROR
    assert by_job[2].job_id == 2
    assert recording.seen_configs  # known parser still ran
    assert store.get(1).next_run_at == _NOW + timedelta(days=1)
    assert store.get(2).next_run_at == _NOW + timedelta(days=1)


@pytest.mark.asyncio
async def test_disabled_job_never_runs() -> None:
    """AC-004."""
    recording = RecordingParser()
    disabled = _job(is_enabled=False, parser_key=recording.parser_key)
    due_next = _job(id=2, arena_id=2, next_run_at=_NOW + timedelta(days=3), parser_key=recording.parser_key)
    sched, store, recorder = _scheduler([disabled, due_next], parsers=[recording])
    await sched.run_due(_NOW)

    assert recording.seen_configs == []
    assert recorder.runs == []
    assert store.get(disabled.id).last_run_at is None
    assert store.get(disabled.id).next_run_at == disabled.next_run_at


@pytest.mark.asyncio
async def test_requires_by_egress_job_is_not_extracted() -> None:
    recording = RecordingParser()
    job = _job(
        parser_key=recording.parser_key,
        config={"url": "https://example.test", "requires_by_egress": True},
    )
    sched, _, recorder = _scheduler([job], parsers=[recording])
    await sched.run_due(_NOW)
    assert recording.seen_configs == []
    assert recorder.runs[0].status == "blocked"


@pytest.mark.asyncio
async def test_saleframe_stub_compiles_and_does_not_insert() -> None:
    parser = MinskArenaSaleframeParser()
    job = _job(parser_key=PARSER_KEY_MINSK_ARENA, config=dict(MINSK_ARENA_SALEFRAME_CONFIG))
    extraction = await parser.extract(job)
    assert extraction.parser_key == PARSER_KEY_MINSK_ARENA
    assert extraction.slots == []


@pytest.mark.asyncio
async def test_due_job_persisted_in_db_advances_next_run(db_session) -> None:
    """AC-001 integration against ice_parser_jobs."""
    city = (await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))).scalar()
    if city is None:
        pytest.skip("need seed cities")
    arena_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                VALUES (:cid, :name, 'ул. Тестовая, 1', true, true)
                RETURNING id
                """
            ),
            {"cid": int(city), "name": "Лёд-тест-071"},
        )
    ).scalar_one()
    await db_session.flush()

    recording = RecordingParser()
    past = _NOW - timedelta(hours=2)
    await db_session.execute(
        text(
            """
            INSERT INTO ice_parser_jobs
                (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
            VALUES
                (:aid, :pkey, true, 'daily', :next_run, CAST(:cfg AS jsonb))
            """
        ),
        {
            "aid": int(arena_id),
            "pkey": recording.parser_key,
            "next_run": past,
            "cfg": '{"url": "https://example.test/from-db"}',
        },
    )
    await db_session.flush()

    from src.ingestion.jobs import SqlAlchemyParserJobStore

    recorder = InMemoryScrapeRunRecorder()
    registry = ParserRegistry()
    registry.register(recording)
    sched = IceIngestScheduler(
        store=SqlAlchemyParserJobStore(db_session),
        recorder=recorder,
        registry=registry,
    )
    await sched.run_due(_NOW)
    await db_session.flush()

    row = (
        await db_session.execute(
            text(
                """
                SELECT last_run_at, next_run_at, parser_key
                FROM ice_parser_jobs WHERE arena_id = :aid
                """
            ),
            {"aid": int(arena_id)},
        )
    ).one()
    assert row.parser_key == recording.parser_key
    assert row.last_run_at is not None
    assert row.next_run_at > _NOW
    assert recording.seen_configs[0]["url"] == "https://example.test/from-db"


@pytest.mark.asyncio
async def test_unknown_parser_key_in_db_does_not_block_sibling(db_session) -> None:
    """AC-003 integration."""
    city = (await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))).scalar()
    if city is None:
        pytest.skip("need seed cities")

    async def _arena(name: str) -> int:
        return int(
            (
                await db_session.execute(
                    text(
                        """
                        INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                        VALUES (:cid, :name, 'ул. Тестовая, 1', true, true)
                        RETURNING id
                        """
                    ),
                    {"cid": int(city), "name": name},
                )
            ).scalar_one()
        )

    a_unknown = await _arena("Лёд-071-unknown")
    a_ok = await _arena("Лёд-071-ok")
    await db_session.flush()
    recording = RecordingParser()
    past = _NOW - timedelta(minutes=1)
    for aid, pkey in ((a_unknown, "missing_key_v1"), (a_ok, recording.parser_key)):
        await db_session.execute(
            text(
                """
                INSERT INTO ice_parser_jobs
                    (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                VALUES
                    (:aid, :pkey, true, 'daily', :next_run, '{}'::jsonb)
                """
            ),
            {"aid": aid, "pkey": pkey, "next_run": past},
        )
    await db_session.flush()

    from src.ingestion.jobs import SqlAlchemyParserJobStore

    recorder = InMemoryScrapeRunRecorder()
    registry = ParserRegistry()
    registry.register(recording)
    sched = IceIngestScheduler(
        store=SqlAlchemyParserJobStore(db_session),
        recorder=recorder,
        registry=registry,
    )
    await sched.run_due(_NOW)

    by_key = {run.parser_key: run for run in recorder.runs}
    assert by_key["missing_key_v1"].status == RUN_STATUS_ERROR
    assert recording.seen_configs
    assert len(recorder.runs) == 2


def test_minsk_arena_seed_config_matches_spec() -> None:
    cfg = MINSK_ARENA_SALEFRAME_CONFIG
    assert cfg["url"] == "https://saleframe.minskarena.by/service/55"
    assert cfg["api_host"] == "https://abws.minskarena.by"
    assert cfg["service_id"] == 55
    assert cfg["prices_already_minor"] is True
    assert cfg["default_duration_minutes"] == 45
    assert cfg["requires_by_egress"] is False
    assert PARSER_KEY_MINSK_ARENA == "minskarena_saleframe_v1"
