"""TASK-072 AC-001…004: persist scrape runs, keep future slots, success %, TTL."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from src.ingestion.jobs import InMemoryParserJobStore, SqlAlchemyParserJobStore
from src.ingestion.parsers import ParserRegistry
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import (
    IceScrapeRunRequired,
    SqlAlchemyScrapeRunRecorder,
    assert_can_replace_ice_sessions,
)
from src.ingestion.success_rates import job_success_rates, list_arenas_with_no_result
from src.ingestion.ttl import purge_ice_scrape_ttl
from src.ingestion.types import (
    RUN_STATUS_BLOCKED,
    RUN_STATUS_EMPTY,
    RUN_STATUS_ERROR,
    RUN_STATUS_OK,
    ParserJob,
    ScrapeRunRecord,
)
from tests.ingestion.fakes import RecordingParser

_NOW = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]


def _job(**overrides) -> ParserJob:
    base = ParserJob(
        id=1,
        arena_id=100,
        parser_key=RecordingParser.parser_key,
        is_enabled=True,
        cadence="daily",
        next_run_at=_NOW - timedelta(minutes=5),
        last_run_at=None,
        config={"url": "https://example.test/ice"},
    )
    return replace(base, **overrides) if overrides else base


def _run(**overrides) -> ScrapeRunRecord:
    base = ScrapeRunRecord(
        job_id=1,
        arena_id=100,
        parser_key="recording_v1",
        status=RUN_STATUS_OK,
        slot_count=2,
        slots_dropped=0,
        error_message=None,
        started_at=_NOW,
        finished_at=_NOW,
    )
    return replace(base, **overrides) if overrides else base


async def _arena(db_session, name: str) -> int:
    city = (await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))).scalar()
    if city is None:
        pytest.skip("need seed cities")
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


async def _job_row(db_session, arena_id: int, parser_key: str, *, past: datetime | None = None) -> int:
    due = past or (_NOW - timedelta(hours=1))
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_parser_jobs
                        (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                    VALUES
                        (:aid, :pkey, true, 'daily', :next_run, '{}'::jsonb)
                    RETURNING id
                    """
                ),
                {"aid": arena_id, "pkey": parser_key, "next_run": due},
            )
        ).scalar_one()
    )


async def _insert_session(
    db_session,
    arena_id: int,
    *,
    starts_at: datetime,
    ends_at: datetime,
    kind: str = "public_skate",
) -> int:
    local_date = starts_at.astimezone(timezone.utc).date()
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_sessions (
                        arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                        starts_at_local, ends_at_local, currency_code, status
                    ) VALUES (
                        :aid, :kind, :starts, :ends, :ldate,
                        :stime, :etime, 'BYN', 'active'
                    )
                    RETURNING id
                    """
                ),
                {
                    "aid": arena_id,
                    "kind": kind,
                    "starts": starts_at,
                    "ends": ends_at,
                    "ldate": local_date,
                    "stime": starts_at.timetz().replace(tzinfo=None),
                    "etime": ends_at.timetz().replace(tzinfo=None),
                },
            )
        ).scalar_one()
    )


async def _insert_run(
    db_session,
    job_id: int,
    arena_id: int,
    *,
    status: str,
    finished_at: datetime,
    slots_found: int = 0,
) -> int:
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_scrape_runs (
                        job_id, arena_id, started_at, finished_at, status, slots_found
                    ) VALUES (
                        :job_id, :arena_id, :started, :finished, :status, :slots
                    )
                    RETURNING id
                    """
                ),
                {
                    "job_id": job_id,
                    "arena_id": arena_id,
                    "started": finished_at - timedelta(seconds=5),
                    "finished": finished_at,
                    "status": status,
                    "slots": slots_found,
                },
            )
        ).scalar_one()
    )


def test_slots_cannot_be_replaced_without_recorded_ok_run() -> None:
    """AC-001: no silent ice_sessions write without a persisted ok run."""
    with pytest.raises(IceScrapeRunRequired):
        assert_can_replace_ice_sessions(None, run_id=None)
    with pytest.raises(IceScrapeRunRequired):
        assert_can_replace_ice_sessions(_run(status=RUN_STATUS_OK), run_id=None)
    with pytest.raises(IceScrapeRunRequired):
        assert_can_replace_ice_sessions(_run(status=RUN_STATUS_EMPTY), run_id=9)
    with pytest.raises(IceScrapeRunRequired):
        assert_can_replace_ice_sessions(_run(status=RUN_STATUS_ERROR), run_id=9)
    with pytest.raises(IceScrapeRunRequired):
        assert_can_replace_ice_sessions(_run(status=RUN_STATUS_BLOCKED), run_id=9)
    assert_can_replace_ice_sessions(_run(status=RUN_STATUS_OK), run_id=42)


def test_scheduler_source_still_does_not_insert_sessions() -> None:
    """Publication stays on TASK-061; a run row is the only write this TASK owns."""
    sched = (ROOT / "src/ingestion/scheduler.py").read_text(encoding="utf-8")
    recorder = (ROOT / "src/ingestion/scrape_runs.py").read_text(encoding="utf-8")
    assert "INSERT INTO ice_sessions" not in sched
    assert "INSERT INTO ice_sessions" not in recorder
    assert "DELETE FROM ice_sessions" not in recorder


@pytest.mark.asyncio
async def test_due_job_persists_scrape_run_row(db_session) -> None:
    """AC-001: every strategy attempt leaves ice_scrape_runs.status."""
    arena_id = await _arena(db_session, "Лёд-072-run")
    recording = RecordingParser()
    job_id = await _job_row(db_session, arena_id, recording.parser_key)
    await db_session.flush()

    registry = ParserRegistry()
    registry.register(recording)
    sched = IceIngestScheduler(
        store=SqlAlchemyParserJobStore(db_session),
        recorder=SqlAlchemyScrapeRunRecorder(db_session),
        registry=registry,
    )
    outcomes = await sched.run_due(_NOW)
    await db_session.flush()

    assert len(outcomes) == 1
    row = (
        await db_session.execute(
            text(
                """
                SELECT id, job_id, arena_id, status, slots_found, error_summary
                FROM ice_scrape_runs WHERE job_id = :jid
                """
            ),
            {"jid": job_id},
        )
    ).one()
    assert row.job_id == job_id
    assert row.arena_id == arena_id
    assert row.status in {RUN_STATUS_EMPTY, RUN_STATUS_OK, RUN_STATUS_ERROR, RUN_STATUS_BLOCKED}
    assert outcomes[0].persisted_id == row.id


@pytest.mark.asyncio
async def test_empty_run_leaves_future_sessions(db_session) -> None:
    """AC-002: empty does not delete future ice_sessions."""
    arena_id = await _arena(db_session, "Лёд-072-keep")
    job_id = await _job_row(db_session, arena_id, RecordingParser.parser_key)
    future_start = _NOW + timedelta(days=2)
    session_id = await _insert_session(
        db_session,
        arena_id,
        starts_at=future_start,
        ends_at=future_start + timedelta(minutes=45),
    )
    await db_session.flush()

    recorder = SqlAlchemyScrapeRunRecorder(db_session)
    persisted = await recorder.record(
        _run(
            job_id=job_id,
            arena_id=arena_id,
            status=RUN_STATUS_EMPTY,
            slot_count=0,
        )
    )
    await db_session.flush()
    assert persisted > 0

    remaining = (
        await db_session.execute(
            text("SELECT id FROM ice_sessions WHERE id = :id"),
            {"id": session_id},
        )
    ).scalar_one()
    assert remaining == session_id


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RUN_STATUS_ERROR, RUN_STATUS_BLOCKED])
async def test_error_and_blocked_leave_future_sessions(db_session, status: str) -> None:
    arena_id = await _arena(db_session, f"Лёд-072-{status}")
    job_id = await _job_row(db_session, arena_id, RecordingParser.parser_key)
    future_start = _NOW + timedelta(days=1)
    session_id = await _insert_session(
        db_session,
        arena_id,
        starts_at=future_start,
        ends_at=future_start + timedelta(minutes=60),
    )
    await db_session.flush()

    await SqlAlchemyScrapeRunRecorder(db_session).record(
        _run(job_id=job_id, arena_id=arena_id, status=status, slot_count=0, error_message=status)
    )
    await db_session.flush()
    assert (
        await db_session.execute(text("SELECT id FROM ice_sessions WHERE id = :id"), {"id": session_id})
    ).scalar_one() == session_id


@pytest.mark.asyncio
async def test_success_rate_30d_is_ok_over_all_finished(db_session) -> None:
    """AC-003: ok / all_finished per job for 30d (and 7d)."""
    arena_id = await _arena(db_session, "Лёд-072-rate")
    job_id = await _job_row(db_session, arena_id, "rate_v1")
    other_arena = await _arena(db_session, "Лёд-072-rate-b")
    other_job = await _job_row(db_session, other_arena, "rate_other_v1")
    await db_session.flush()

    await _insert_run(db_session, job_id, arena_id, status=RUN_STATUS_OK, finished_at=_NOW - timedelta(days=1))
    await _insert_run(db_session, job_id, arena_id, status=RUN_STATUS_EMPTY, finished_at=_NOW - timedelta(days=2))
    await _insert_run(db_session, job_id, arena_id, status=RUN_STATUS_ERROR, finished_at=_NOW - timedelta(days=3))
    await _insert_run(db_session, job_id, arena_id, status=RUN_STATUS_BLOCKED, finished_at=_NOW - timedelta(days=4))
    await _insert_run(
        db_session,
        job_id,
        arena_id,
        status=RUN_STATUS_OK,
        finished_at=_NOW - timedelta(days=10),
    )
    await _insert_run(
        db_session,
        other_job,
        other_arena,
        status=RUN_STATUS_OK,
        finished_at=_NOW - timedelta(days=1),
    )
    await db_session.flush()

    rates = await job_success_rates(db_session, now=_NOW, window_days=(7, 30))
    by_job = {row.job_id: row for row in rates}
    target = by_job[job_id]
    assert target.finished_7d == 4
    assert target.ok_7d == 1
    assert target.success_rate_7d == 1 / 4
    assert target.finished_30d == 5
    assert target.ok_30d == 2
    assert target.success_rate_30d == 2 / 5
    assert by_job[other_job].success_rate_30d == 1.0


@pytest.mark.asyncio
async def test_no_result_when_last_run_not_ok_and_no_future_slots(db_session) -> None:
    """Admin SQL: «результата нет» if last finished run is not ok and no future MK/open ice."""
    dark = await _arena(db_session, "Лёд-072-dark")
    dark_job = await _job_row(db_session, dark, "dark_v1")
    lit = await _arena(db_session, "Лёд-072-lit")
    lit_job = await _job_row(db_session, lit, "lit_v1")
    await db_session.flush()

    await _insert_run(db_session, dark_job, dark, status=RUN_STATUS_EMPTY, finished_at=_NOW)
    await _insert_run(db_session, lit_job, lit, status=RUN_STATUS_EMPTY, finished_at=_NOW)
    future = _NOW + timedelta(days=3)
    await _insert_session(db_session, lit, starts_at=future, ends_at=future + timedelta(minutes=45))
    await db_session.flush()

    flagged = {row.arena_id for row in await list_arenas_with_no_result(db_session, now=_NOW)}
    assert dark in flagged
    assert lit not in flagged


@pytest.mark.asyncio
async def test_ttl_keeps_last_ok_even_if_older_than_90_days(db_session) -> None:
    """AC-004: TTL must not delete the last ok run, even past 90 days."""
    arena_id = await _arena(db_session, "Лёд-072-ttl")
    job_id = await _job_row(db_session, arena_id, "ttl_v1")
    await db_session.flush()

    last_ok = await _insert_run(
        db_session,
        job_id,
        arena_id,
        status=RUN_STATUS_OK,
        finished_at=_NOW - timedelta(days=120),
        slots_found=3,
    )
    stale = await _insert_run(
        db_session,
        job_id,
        arena_id,
        status=RUN_STATUS_EMPTY,
        finished_at=_NOW - timedelta(days=110),
    )
    last_any = await _insert_run(
        db_session,
        job_id,
        arena_id,
        status=RUN_STATUS_ERROR,
        finished_at=_NOW - timedelta(days=100),
    )

    old_start = _NOW - timedelta(days=20)
    stale_session = await _insert_session(
        db_session,
        arena_id,
        starts_at=old_start,
        ends_at=old_start + timedelta(minutes=45),
    )
    future_start = _NOW + timedelta(days=2)
    live_session = await _insert_session(
        db_session,
        arena_id,
        starts_at=future_start,
        ends_at=future_start + timedelta(minutes=45),
    )
    await db_session.flush()

    stats = await purge_ice_scrape_ttl(db_session, now=_NOW)
    await db_session.flush()

    remaining_runs = {
        int(row)
        for row in (
            await db_session.execute(
                text("SELECT id FROM ice_scrape_runs WHERE job_id = :jid"),
                {"jid": job_id},
            )
        ).scalars()
    }
    assert last_ok in remaining_runs
    assert last_any in remaining_runs
    assert stale not in remaining_runs
    assert stats.runs_deleted >= 1
    assert (
        await db_session.execute(text("SELECT id FROM ice_sessions WHERE id = :id"), {"id": stale_session})
    ).scalar() is None
    assert (
        await db_session.execute(text("SELECT id FROM ice_sessions WHERE id = :id"), {"id": live_session})
    ).scalar_one() == live_session


@pytest.mark.asyncio
async def test_in_memory_scheduler_still_records_without_sql() -> None:
    from src.ingestion.scrape_runs import InMemoryScrapeRunRecorder

    store = InMemoryParserJobStore([_job()])
    recorder = InMemoryScrapeRunRecorder()
    registry = ParserRegistry()
    registry.register(RecordingParser())
    sched = IceIngestScheduler(store=store, recorder=recorder, registry=registry)
    await sched.run_due(_NOW)
    assert recorder.runs
    assert recorder.runs[0].status in {
        RUN_STATUS_EMPTY,
        RUN_STATUS_OK,
        RUN_STATUS_ERROR,
        RUN_STATUS_BLOCKED,
    }
