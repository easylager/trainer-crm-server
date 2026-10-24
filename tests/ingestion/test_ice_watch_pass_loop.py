"""TASK-328 AC2: колокольчик шлёт один отправитель — проход после коммита тика, под локом.

Интеграционный тест гонки идёт на настоящих коммитах (отдельные соединения), как в проде:
в общем откатываемом соединении conftest незакоммиченное видно всем, и гонку не поймать.
Строки за собой тест удаляет сам.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.application.client_ice_watch_use_cases import IceWatchPassStats, deliver_ice_watch_reminders
from src.ingestion import loop as loop_mod
from src.ingestion.jobs import InMemoryParserJobStore
from src.ingestion.loop import WatchPassThrottle, run_ice_ingest_tick, run_ice_watch_pass_after_tick
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import InMemoryScrapeRunRecorder
from src.ingestion.types import RUN_STATUS_OK, ParserJob, ScrapeRunRecord
from src.shared.config import Settings

MINSK = ZoneInfo("Europe/Minsk")


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# --- Троттлинг и порядок ---------------------------------------------------------------


def test_throttle_allows_once_per_minute() -> None:
    clock = _Clock()
    throttle = WatchPassThrottle(60.0, clock=clock)
    assert throttle.try_start() is True
    clock.now += 59.9
    assert throttle.try_start() is False
    clock.now += 0.1
    assert throttle.try_start() is True


@pytest.mark.asyncio
async def test_watch_pass_failure_is_logged_not_raised(caplog) -> None:
    async def boom():
        raise RuntimeError("db down")

    await run_ice_watch_pass_after_tick(watch_pass=boom, throttle=WatchPassThrottle(0.0))
    assert any("ice watch delivery pass failed" in r.getMessage() for r in caplog.records)


class _FakeSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.events.append("session_closed")

    async def commit(self) -> None:
        self.events.append("tick_commit")


class _FakeScheduler:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail
        self.last_due_count = 1

    async def run_due(self, now):
        self.events.append("run_due")
        if self.fail:
            raise RuntimeError("tick blew up")
        return []


async def _no_lock(_engine, operation):
    return True, await operation()


@pytest.mark.asyncio
async def test_watch_pass_runs_after_tick_commit(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr("src.ingestion.scheduler_lock.run_with_ice_ingest_lock", _no_lock)

    async def watch_pass():
        events.append("watch_pass")
        return IceWatchPassStats()

    result = await run_ice_ingest_tick(
        session_factory=lambda: _FakeSession(events),
        engine=object(),
        scheduler_factory=lambda _s: _FakeScheduler(events),
        watch_pass=watch_pass,
        watch_pass_throttle=WatchPassThrottle(0.0),
    )
    assert result.acquired is True
    assert events == ["run_due", "tick_commit", "session_closed", "watch_pass"]


@pytest.mark.asyncio
async def test_watch_pass_still_runs_when_tick_fails(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr("src.ingestion.scheduler_lock.run_with_ice_ingest_lock", _no_lock)

    async def watch_pass():
        events.append("watch_pass")

    with pytest.raises(RuntimeError, match="tick blew up"):
        await run_ice_ingest_tick(
            session_factory=lambda: _FakeSession(events),
            engine=object(),
            scheduler_factory=lambda _s: _FakeScheduler(events, fail=True),
            watch_pass=watch_pass,
            watch_pass_throttle=WatchPassThrottle(0.0),
        )
    assert events[-1] == "watch_pass"


@pytest.mark.asyncio
async def test_no_watch_pass_without_the_ingest_lock(monkeypatch) -> None:
    """Вторая реплика (лок занят) ничего не шлёт."""

    async def busy(_engine, _operation):
        return False, None

    monkeypatch.setattr("src.ingestion.scheduler_lock.run_with_ice_ingest_lock", busy)
    watch_pass = AsyncMock()
    result = await run_ice_ingest_tick(
        session_factory=lambda: _FakeSession([]),
        engine=object(),
        scheduler_factory=lambda _s: _FakeScheduler([]),
        watch_pass=watch_pass,
        watch_pass_throttle=WatchPassThrottle(0.0),
    )
    assert result.acquired is False
    watch_pass.assert_not_awaited()


@pytest.mark.asyncio
async def test_two_ticks_within_a_minute_run_one_pass(monkeypatch) -> None:
    monkeypatch.setattr("src.ingestion.scheduler_lock.run_with_ice_ingest_lock", _no_lock)
    clock = _Clock()
    throttle = WatchPassThrottle(60.0, clock=clock)
    watch_pass = AsyncMock(return_value=IceWatchPassStats())
    kwargs = dict(
        session_factory=lambda: _FakeSession([]),
        engine=object(),
        scheduler_factory=lambda _s: _FakeScheduler([]),
        watch_pass=watch_pass,
        watch_pass_throttle=throttle,
    )
    await run_ice_ingest_tick(**kwargs)
    clock.now += 30
    await run_ice_ingest_tick(**kwargs)
    assert watch_pass.await_count == 1
    clock.now += 31
    await run_ice_ingest_tick(**kwargs)
    assert watch_pass.await_count == 2


# --- Планировщик больше не шлёт сам -------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_publish_does_not_send_reminders(monkeypatch) -> None:
    from src.application import client_ice_watch_use_cases as uc

    now = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
    job = ParserJob(
        id=1,
        arena_id=100,
        parser_key="any_v1",
        is_enabled=True,
        cadence="daily",
        next_run_at=now - timedelta(minutes=5),
        last_run_at=None,
        config={},
    )
    publisher = AsyncMock()
    publisher.publish = AsyncMock(return_value=7)
    sched = IceIngestScheduler(
        store=InMemoryParserJobStore([job]),
        recorder=InMemoryScrapeRunRecorder(),
        publisher=publisher,
    )

    async def fake_run_one(self, job, now):
        record = ScrapeRunRecord(
            job_id=job.id,
            arena_id=job.arena_id,
            parser_key=job.parser_key,
            status=RUN_STATUS_OK,
            slot_count=1,
            slots_dropped=0,
            error_message=None,
            started_at=now,
            finished_at=now,
        )
        return record, [object()], []

    monkeypatch.setattr(IceIngestScheduler, "_run_one", fake_run_one)
    monkeypatch.setattr(IceIngestScheduler, "_maybe_run_season_open_watches", AsyncMock())
    sent = AsyncMock()
    monkeypatch.setattr(uc, "run_ice_watch_delivery_pass", sent)
    monkeypatch.setattr(uc, "deliver_ice_watch_reminders", sent)

    outcomes = await sched.run_due(now)
    assert [o.status for o in outcomes] == [RUN_STATUS_OK]
    publisher.publish.assert_awaited_once()
    sent.assert_not_awaited()
    assert not hasattr(uc, "run_ice_watch_notifications_for_arena")


# --- Гонка коммита на настоящих соединениях -----------------------------------------------


async def _seed(factory) -> dict:
    tid = 7_500_000_000 + (uuid.uuid4().int % 100_000_000)
    tag = uuid.uuid4().hex[:8]
    async with factory() as s:
        city_id = (
            await s.execute(
                text(
                    "INSERT INTO cities (name, country, price_group, is_active, sort_order) "
                    "VALUES (:n, 'BY', 'default', true, 0) RETURNING id"
                ),
                {"n": f"Race City {tag}"},
            )
        ).scalar_one()
        arena_id = (
            await s.execute(
                text(
                    "INSERT INTO arenas (city_id, name, latitude, longitude, is_active, is_confirmed, venue_type) "
                    "VALUES (:cid, 'Юность', 53.9, 27.5, true, true, 'ice') RETURNING id"
                ),
                {"cid": city_id},
            )
        ).scalar_one()
        await s.execute(
            text("INSERT INTO client_sessions (telegram_id, state) VALUES (:tid, 'idle')"),
            {"tid": tid},
        )
        client_id = (
            await s.execute(
                text(
                    "INSERT INTO clients (first_name, telegram_id, is_sandbox) "
                    "VALUES ('Race', :tid, false) RETURNING id"
                ),
                {"tid": tid},
            )
        ).scalar_one()
        await s.execute(
            text(
                """
                INSERT INTO client_ice_watches (client_id, telegram_id, arena_id, city_id, watch_kind, filter_json, active)
                VALUES (:cid, :tid, :aid, :city, 'sessions', '{"when": "any"}'::jsonb, true)
                """
            ),
            {"cid": client_id, "tid": tid, "aid": arena_id, "city": city_id},
        )
        await s.commit()
    return {"tid": tid, "city_id": city_id, "arena_id": arena_id, "client_id": client_id}


async def _cleanup(factory, seed: dict) -> None:
    async with factory() as s:
        await s.execute(text("DELETE FROM client_ice_watches WHERE arena_id = :aid"), {"aid": seed["arena_id"]})
        await s.execute(text("DELETE FROM ice_sessions WHERE arena_id = :aid"), {"aid": seed["arena_id"]})
        await s.execute(text("DELETE FROM clients WHERE id = :cid"), {"cid": seed["client_id"]})
        await s.execute(text("DELETE FROM client_sessions WHERE telegram_id = :tid"), {"tid": seed["tid"]})
        await s.execute(text("DELETE FROM arenas WHERE id = :aid"), {"aid": seed["arena_id"]})
        await s.execute(text("DELETE FROM cities WHERE id = :cid"), {"cid": seed["city_id"]})
        await s.commit()


@pytest.mark.asyncio
async def test_session_inserted_in_tick_is_sent_by_the_same_pass_after_commit() -> None:
    engine = create_async_engine(Settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    seed = await _seed(factory)
    send = AsyncMock()
    seen_inside_tick: list[int] = []

    class _PublishingScheduler:
        """Как настоящий тик: сеанс пишется в savepoint сессии тика, коммит — после run_due."""

        last_due_count = 1

        def __init__(self, session) -> None:
            self.session = session

        async def run_due(self, now):
            local_day = datetime.now(MINSK).date() + timedelta(days=3)
            starts_local = datetime(local_day.year, local_day.month, local_day.day, 17, 0, tzinfo=MINSK)
            async with self.session.begin_nested():
                await self.session.execute(
                    text(
                        """
                        INSERT INTO ice_sessions (
                            arena_id, kind, status, starts_at_utc, ends_at_utc,
                            starts_at_local, ends_at_local, local_date, schedule_basis, currency_code
                        )
                        VALUES (:aid, 'public_skate', 'active', :s, :e, '17:00', '18:00', :ld, 'live', 'BYN')
                        """
                    ),
                    {
                        "aid": seed["arena_id"],
                        "s": starts_local.astimezone(timezone.utc),
                        "e": (starts_local + timedelta(hours=1)).astimezone(timezone.utc),
                        "ld": local_day,
                    },
                )
            # Старое поведение — отправка изнутри тика из своей сессии: сеанса ещё не видно.
            async with factory() as other:
                stats = await deliver_ice_watch_reminders(other, send_fn=send)
                seen_inside_tick.append(stats.due)
            return []

    async def watch_pass():
        async with factory() as s:
            return await deliver_ice_watch_reminders(s, send_fn=send)

    try:
        result = await run_ice_ingest_tick(
            session_factory=factory,
            engine=engine,
            scheduler_factory=_PublishingScheduler,
            watch_pass=watch_pass,
            watch_pass_throttle=WatchPassThrottle(0.0),
        )
        assert result.acquired is True
        assert seen_inside_tick == [0], "inside the tick the new session must be invisible"
        send.assert_awaited_once()
        assert send.await_args.args[0] == seed["tid"]
        assert "новое расписание" in send.await_args.args[1]
        async with factory() as s:
            row = (
                await s.execute(
                    text("SELECT active, last_notified_at FROM client_ice_watches WHERE arena_id = :aid"),
                    {"aid": seed["arena_id"]},
                )
            ).one()
            journal = (
                await s.execute(
                    text(
                        "SELECT ok FROM client_ice_watch_deliveries d JOIN client_ice_watches w ON w.id = d.watch_id "
                        "WHERE w.arena_id = :aid"
                    ),
                    {"aid": seed["arena_id"]},
                )
            ).scalars().all()
        assert row.active is False and row.last_notified_at is not None
        assert journal == [True]
    finally:
        await _cleanup(factory, seed)
        await engine.dispose()
