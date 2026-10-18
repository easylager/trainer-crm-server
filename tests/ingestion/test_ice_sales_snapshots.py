"""TASK-295: Korona sales snapshots for Zamok."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from src.ingestion.ice_sales_snapshots import (
    SqlAlchemyKoronaSalesSnapshotStore,
    record_korona_sales_if_changed,
)
from src.ingestion.jobs import SqlAlchemyParserJobStore
from src.ingestion.koronaticket_rink import KoronaRinkSession, parse_rink_nuxt_html
from src.ingestion.parsers import ParserRegistry, ZamokHtmlParser
from src.ingestion.publish import SqlAlchemyIceSessionPublisher
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import SqlAlchemyScrapeRunRecorder
from src.ingestion.types import RUN_STATUS_OK

ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = ROOT / "data/fixtures/minsk-zamok"
_KORONA_HTML = (_FIXTURES / "korona-rink.html").read_text(encoding="utf-8")
_NOW = datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)


def _zamok_job_config() -> dict:
    return {
        "url": "https://tczamok.by/entertainments/ice-rink",
        "timezone": "Europe/Minsk",
        "horizon_days": 1,
        "slot_start_suffix": ":15",
        "duration_minutes": 45,
        "run_date": "2026-10-04",
        "prices_already_minor": True,
        "fixture_dir": str(_FIXTURES),
        "requires_by_egress": False,
    }


async def _insert_zamok_job(db_session, arena_id: int) -> None:
    await db_session.execute(
        text("""
            INSERT INTO ice_parser_jobs
                (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
            VALUES (:aid, 'zamok_html_v1', true, 'daily', :next_run, CAST(:cfg AS jsonb))
            """),
        {
            "aid": arena_id,
            "next_run": _NOW - timedelta(minutes=1),
            "cfg": json.dumps(_zamok_job_config(), ensure_ascii=False),
        },
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_record_korona_sales_dedupes_and_tracks_bought_change(db_session, seed_city_id) -> None:
    arena_id = int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                    VALUES (:cid, 'Замок-295', 'пр-т Победителей, 65', true, true)
                    RETURNING id
                    """),
                {"cid": int(seed_city_id)},
            )
        ).scalar_one()
    )
    sessions = parse_rink_nuxt_html(_KORONA_HTML)
    assert sessions
    observed = _NOW

    first = await record_korona_sales_if_changed(
        db_session,
        arena_id=arena_id,
        korona_sessions=sessions,
        observed_at=observed,
    )
    await db_session.flush()
    assert first > 0

    second = await record_korona_sales_if_changed(
        db_session,
        arena_id=arena_id,
        korona_sessions=sessions,
        observed_at=observed + timedelta(minutes=15),
    )
    await db_session.flush()
    assert second == 0

    sample = next(s for s in sessions if s.starts_at_local == "13:15")
    bumped = KoronaRinkSession(
        local_date=sample.local_date,
        starts_at_local=sample.starts_at_local,
        ends_at_local=sample.ends_at_local,
        count=sample.count,
        bought=sample.bought + 1,
        locked=sample.locked,
        ordered=sample.ordered,
        remaining=max(0, sample.remaining - 1),
        is_available=sample.is_available,
    )
    patched = [bumped if s.starts_at_local == "13:15" else s for s in sessions]
    third = await record_korona_sales_if_changed(
        db_session,
        arena_id=arena_id,
        korona_sessions=patched,
        observed_at=observed + timedelta(minutes=30),
    )
    await db_session.flush()
    assert third == 1

    rows_for_slot = (
        await db_session.execute(
            text("""
                SELECT count(*) FROM ice_sales_snapshots
                WHERE arena_id = :aid AND local_date = :d AND starts_at_local = '13:15:00'
                """),
            {"aid": arena_id, "d": date(2026, 10, 4)},
        )
    ).scalar_one()
    assert rows_for_slot == 2


@pytest.mark.asyncio
async def test_zamok_scheduler_writes_snapshots_on_ok_run(db_session, seed_city_id) -> None:
    arena_id = int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                    VALUES (:cid, 'Замок-295-sched', 'пр-т Победителей, 65', true, true)
                    RETURNING id
                    """),
                {"cid": int(seed_city_id)},
            )
        ).scalar_one()
    )
    await _insert_zamok_job(db_session, arena_id)

    registry = ParserRegistry()
    registry.register(ZamokHtmlParser())
    sched = IceIngestScheduler(
        store=SqlAlchemyParserJobStore(db_session),
        recorder=SqlAlchemyScrapeRunRecorder(db_session),
        registry=registry,
        publisher=SqlAlchemyIceSessionPublisher(db_session),
        korona_sales_store=SqlAlchemyKoronaSalesSnapshotStore(db_session),
    )
    outcomes = await sched.run_due(_NOW)
    await db_session.flush()
    assert outcomes[0].status == RUN_STATUS_OK
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM ice_sales_snapshots WHERE arena_id = :aid"),
            {"aid": arena_id},
        )
    ).scalar_one()
    assert count > 0


class _FlakyKoronaStore(SqlAlchemyKoronaSalesSnapshotStore):
    async def record_korona_sales(self, *args, **kwargs) -> int:  # type: ignore[no-untyped-def]
        raise RuntimeError("snapshot db down")


@pytest.mark.asyncio
async def test_snapshot_write_failure_does_not_block_publish(db_session, seed_city_id) -> None:
    arena_id = int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                    VALUES (:cid, 'Замок-295-fail', 'пр-т Победителей, 65', true, true)
                    RETURNING id
                    """),
                {"cid": int(seed_city_id)},
            )
        ).scalar_one()
    )
    await _insert_zamok_job(db_session, arena_id)
    registry = ParserRegistry()
    registry.register(ZamokHtmlParser())
    sched = IceIngestScheduler(
        store=SqlAlchemyParserJobStore(db_session),
        recorder=SqlAlchemyScrapeRunRecorder(db_session),
        registry=registry,
        publisher=SqlAlchemyIceSessionPublisher(db_session),
        korona_sales_store=_FlakyKoronaStore(db_session),
    )
    outcomes = await sched.run_due(_NOW)
    await db_session.flush()
    assert outcomes[0].status == RUN_STATUS_OK
    sessions = (
        await db_session.execute(
            text("SELECT count(*) FROM ice_sessions WHERE arena_id = :aid"),
            {"aid": arena_id},
        )
    ).scalar_one()
    assert sessions > 0


@pytest.mark.asyncio
async def test_db_error_in_snapshot_keeps_session_usable(db_session, seed_city_id) -> None:
    """Ошибка БД при записи снимка откатывает только точку сохранения, сессия прогона жива."""
    from src.ingestion.ice_sales_snapshots import try_record_korona_sales

    bad = KoronaRinkSession(
        local_date=date(2099, 1, 1),
        starts_at_local="12:00",
        ends_at_local="13:00",
        count=-1,  # нарушает CHECK capacity >= 0
        bought=0,
        locked=0,
        ordered=0,
        remaining=0,
        is_available=False,
    )
    arena_id = int((await db_session.execute(text("SELECT id FROM arenas ORDER BY id LIMIT 1"))).scalar_one())
    await try_record_korona_sales(
        SqlAlchemyKoronaSalesSnapshotStore(db_session),
        arena_id=arena_id,
        korona_sessions=[bad],
        observed_at=_NOW,
        timezone_name="Europe/Minsk",
    )
    assert (await db_session.execute(text("SELECT 1"))).scalar_one() == 1
