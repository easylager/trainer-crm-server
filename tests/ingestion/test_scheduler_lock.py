"""Focused tests for the shared ice-ingest runner lock protocol."""
from __future__ import annotations

import asyncio

import pytest

from src.ingestion.scheduler_lock import run_with_ice_ingest_lock


class _Result:
    def __init__(self, value: bool) -> None:
        self._value = value

    def scalar_one(self) -> bool:
        return self._value


class _Connection:
    def __init__(self, engine: _Engine) -> None:
        self._engine = engine

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_exc_info) -> None:
        pass

    async def execute(self, statement, _params):
        sql = str(statement)
        if "pg_try_advisory_lock" in sql:
            if self._engine.locked:
                return _Result(False)
            self._engine.locked = True
            return _Result(True)
        if "pg_advisory_unlock" in sql:
            self._engine.unlock_calls += 1
            self._engine.locked = False
            return _Result(True)
        raise AssertionError(f"unexpected lock statement: {sql}")

    async def commit(self) -> None:
        if self._engine.fail_commit:
            self._engine.fail_commit = False
            raise RuntimeError("lock connection commit failed")
        pass


class _Engine:
    def __init__(self) -> None:
        self.locked = False
        self.fail_commit = False
        self.unlock_calls = 0

    def connect(self) -> _Connection:
        return _Connection(self)


@pytest.mark.asyncio
async def test_concurrent_ingest_runners_cannot_enter_the_locked_work() -> None:
    engine = _Engine()
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    first_runs: list[str] = []
    second_runs: list[str] = []

    async def first_runner() -> None:
        first_runs.append("started")
        first_started.set()
        await release_first.wait()

    async def second_runner() -> None:
        second_runs.append("started")

    first = asyncio.create_task(run_with_ice_ingest_lock(engine, first_runner))
    await first_started.wait()

    second_acquired, _ = await run_with_ice_ingest_lock(engine, second_runner)

    release_first.set()
    first_acquired, _ = await first

    assert first_acquired is True
    assert second_acquired is False
    assert first_runs == ["started"]
    assert second_runs == []
    assert engine.locked is False

    reacquired, _ = await run_with_ice_ingest_lock(engine, second_runner)
    assert reacquired is True
    assert second_runs == ["started"]


@pytest.mark.asyncio
async def test_ingest_runner_releases_lock_when_work_raises() -> None:
    engine = _Engine()

    async def fail() -> None:
        raise RuntimeError("ingest failed")

    with pytest.raises(RuntimeError, match="ingest failed"):
        await run_with_ice_ingest_lock(engine, fail)

    assert engine.locked is False


@pytest.mark.asyncio
async def test_ingest_runner_unlocks_if_commit_fails_after_lock_acquisition() -> None:
    engine = _Engine()
    engine.fail_commit = True

    async def should_not_run() -> None:
        raise AssertionError("work must not start when lock setup fails")

    with pytest.raises(RuntimeError, match="lock connection commit failed"):
        await run_with_ice_ingest_lock(engine, should_not_run)

    assert engine.unlock_calls == 1
    assert engine.locked is False
