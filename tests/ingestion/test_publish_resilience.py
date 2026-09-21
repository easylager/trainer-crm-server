"""Regression: a publish() failure for one job must not sink the whole tick.

Prod incident (2026-09-21): an oversized source_id crashed the publish INSERT
for one arena; because that exception escaped run_due() uncaught, the caller
(loop.py) never reached session.commit(), so *every* job in that tick lost
its work and the failing job's next_run_at never advanced — it kept jamming
the front of the due queue forever. This asserts two independent jobs in the
same tick: one whose publish fails, one that succeeds, and that neither the
failure blocks the sibling nor leaves the failing job stuck.

The failure is forced via a deliberately-flaky publisher subclass rather than
an oversized field, because normalize.py now caps every adapter-supplied text
field before it reaches publish() (see test_normalize_source_id.py) — this
test is about the scheduler/savepoint contract itself, not any one column.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.ingestion.jobs import SqlAlchemyParserJobStore
from src.ingestion.parsers import ParserRegistry
from src.ingestion.publish import SqlAlchemyIceSessionPublisher
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import SqlAlchemyScrapeRunRecorder
from src.ingestion.types import CanonicalSlotDraft, RUN_STATUS_ERROR
from tests.ingestion.fakes import FakeJsonWidgetParser, RecordingParser

_NOW = datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc)


class _FlakyPublisher(SqlAlchemyIceSessionPublisher):
    """Raises mid-transaction for one arena, to prove the savepoint isolates it."""

    def __init__(self, session, *, fail_arena_id: int) -> None:
        super().__init__(session)
        self._fail_arena_id = fail_arena_id

    async def _insert(self, draft: CanonicalSlotDraft, *, scrape_run_id: int | None) -> None:
        if draft.arena_id == self._fail_arena_id:
            raise RuntimeError("simulated publish failure")
        await super()._insert(draft, scrape_run_id=scrape_run_id)


@pytest.mark.asyncio
async def test_bad_publish_does_not_block_sibling_job_or_stall_the_queue(db_session) -> None:
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

    bad_arena = await _arena("Лёд-публикация-bad")
    ok_arena = await _arena("Лёд-публикация-ok")
    await db_session.flush()

    past = _NOW - timedelta(minutes=5)
    bad_widget = FakeJsonWidgetParser()
    recording = RecordingParser()
    for aid, pkey, cfg in (
        (
            bad_arena,
            bad_widget.parser_key,
            {
                "payload": {
                    "events": [
                        {
                            "date": "2026-09-23",
                            "start": "09:00",
                            "end": "10:00",
                            "adult": 4000,
                            "id": "evt-1",
                        }
                    ]
                },
                "currency_code": "RUB",
                "prices_already_minor": True,
            },
        ),
        (ok_arena, recording.parser_key, {"url": "https://example.test"}),
    ):
        await db_session.execute(
            text(
                """
                INSERT INTO ice_parser_jobs
                    (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                VALUES
                    (:aid, :pkey, true, 'daily', :next_run, CAST(:cfg AS jsonb))
                """
            ),
            {"aid": aid, "pkey": pkey, "next_run": past, "cfg": json.dumps(cfg)},
        )
    await db_session.flush()

    registry = ParserRegistry()
    registry.register(bad_widget)
    registry.register(recording)
    recorder = SqlAlchemyScrapeRunRecorder(db_session)
    sched = IceIngestScheduler(
        store=SqlAlchemyParserJobStore(db_session),
        recorder=recorder,
        registry=registry,
        publisher=_FlakyPublisher(db_session, fail_arena_id=bad_arena),
    )

    outcomes = await sched.run_due(_NOW)  # must not raise
    await db_session.flush()

    by_arena = {o.arena_id: o for o in outcomes}
    assert by_arena[bad_arena].status == RUN_STATUS_ERROR
    assert by_arena[bad_arena].error_code == "publish_error"
    assert recording.seen_configs  # sibling job still ran

    rows = (
        await db_session.execute(
            text("SELECT arena_id, next_run_at FROM ice_parser_jobs WHERE arena_id IN (:a, :b)"),
            {"a": bad_arena, "b": ok_arena},
        )
    ).all()
    for row in rows:
        assert row.next_run_at > _NOW  # neither job is stuck re-due forever

    persisted_status = (
        await db_session.execute(
            text("SELECT status FROM ice_scrape_runs WHERE arena_id = :a ORDER BY id DESC LIMIT 1"),
            {"a": bad_arena},
        )
    ).scalar_one()
    assert persisted_status == RUN_STATUS_ERROR  # not left showing a false "ok"

    leftover = (
        await db_session.execute(
            text("SELECT count(*) FROM ice_sessions WHERE arena_id = :a"), {"a": bad_arena}
        )
    ).scalar_one()
    assert leftover == 0  # savepoint rolled the bad insert back cleanly
