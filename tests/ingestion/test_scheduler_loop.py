"""TASK-176: цикл планировщика льда не умирает молча и пишет heartbeat на каждый тик."""
from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path

import pytest

from src.ingestion.loop import IceIngestTickResult, run_ice_ingest_scheduler_loop

ROOT = Path(__file__).resolve().parents[2]
_LOGGER = "src.ingestion.loop"


async def _wait_for(predicate, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.005)


def _heartbeats(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == _LOGGER and r.levelno == logging.INFO and r.getMessage().startswith("ice ingest tick ")
    ]


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


@pytest.mark.asyncio
async def test_stray_cancelled_error_inside_tick_does_not_end_loop(caplog) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    calls: list[int] = []

    async def tick() -> IceIngestTickResult:
        calls.append(1)
        if len(calls) == 1:
            # Чужой CancelledError изнутри тика (драйвер, закрытое соединение) — не остановка сервиса.
            raise asyncio.CancelledError()
        return IceIngestTickResult(acquired=True, due=3, ran=3, ok=2)

    task = asyncio.create_task(run_ice_ingest_scheduler_loop(tick=tick, interval_sec=0))
    await _wait_for(lambda: len(calls) >= 3)
    assert not task.done(), "loop exited after a stray CancelledError"
    await _stop(task)

    errors = [r for r in caplog.records if r.levelno == logging.ERROR and r.name == _LOGGER]
    assert any("CancelledError" in r.getMessage() for r in errors)
    beats = _heartbeats(caplog)
    assert "ice ingest tick failed error=CancelledError" in beats[0]
    assert any("acquired=yes due=3 ran=3 ok=2" in b for b in beats[1:])


@pytest.mark.asyncio
async def test_service_shutdown_during_tick_stops_loop() -> None:
    entered = asyncio.Event()

    async def hanging_tick() -> IceIngestTickResult:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    task = asyncio.create_task(run_ice_ingest_scheduler_loop(tick=hanging_tick, interval_sec=0))
    await asyncio.wait_for(entered.wait(), 2)
    await _stop(task)


@pytest.mark.asyncio
async def test_service_shutdown_during_sleep_stops_loop() -> None:
    task = asyncio.create_task(run_ice_ingest_scheduler_loop(tick=None, interval_sec=3600))
    await asyncio.sleep(0)
    await _stop(task)


@pytest.mark.asyncio
async def test_failing_tick_is_logged_and_loop_continues(caplog) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    calls: list[int] = []

    async def tick() -> IceIngestTickResult:
        calls.append(1)
        if len(calls) == 1:
            # Так выглядел прод: SyntaxError при импорте scheduler_lock на Python 3.11.
            raise SyntaxError("expected '('")
        return IceIngestTickResult(acquired=True)

    task = asyncio.create_task(run_ice_ingest_scheduler_loop(tick=tick, interval_sec=0))
    await _wait_for(lambda: len(calls) >= 2)
    assert not task.done()
    await _stop(task)

    assert any(r.levelno == logging.ERROR and r.exc_info for r in caplog.records if r.name == _LOGGER)
    assert "error=SyntaxError" in _heartbeats(caplog)[0]


@pytest.mark.asyncio
async def test_heartbeat_on_every_tick_including_empty_and_skipped(caplog) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    results = [
        IceIngestTickResult(acquired=True, due=0, ran=0, ok=0),
        IceIngestTickResult(acquired=False),
        IceIngestTickResult(acquired=True, due=35, ran=20, ok=18),
    ]
    calls: list[int] = []

    async def tick() -> IceIngestTickResult:
        calls.append(1)
        return results[min(len(calls), len(results)) - 1]

    task = asyncio.create_task(run_ice_ingest_scheduler_loop(tick=tick, interval_sec=0))
    await _wait_for(lambda: len(calls) >= 3 and len(_heartbeats(caplog)) >= 3)
    await _stop(task)

    beats = _heartbeats(caplog)
    assert beats[0].startswith("ice ingest tick acquired=yes due=0 ran=0 ok=0 duration=")
    assert beats[1].startswith("ice ingest tick acquired=no")
    assert beats[2].startswith("ice ingest tick acquired=yes due=35 ran=20 ok=18 duration=")
    started = [r.getMessage() for r in caplog.records if r.name == _LOGGER]
    assert started[0].startswith("ice ingest scheduler loop started")


def _runtime_python() -> tuple[int, int]:
    raw = (ROOT / "runtime.txt").read_text(encoding="utf-8").strip().removeprefix("python-")
    major, minor = raw.split(".")[:2]
    return int(major), int(minor)


def test_code_parses_on_production_python_version() -> None:
    """Прод (Railway/Nixpacks) берёт версию из runtime.txt; CI гоняет 3.12.

    PEP 695 (``def f[T]()``) в scheduler_lock.py на 3.11 — SyntaxError при импорте внутри
    цикла, и планировщик сутки молчал. Ловим такой синтаксис до деплоя.
    """
    version = _runtime_python()
    bad: list[str] = []
    for folder in ("src", "scripts", "migrations"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=version)
            except SyntaxError as exc:
                bad.append(f"{path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")
    assert not bad, f"not valid on Python {version}: {bad}"


def test_feature_version_guard_catches_pep695() -> None:
    with pytest.raises(SyntaxError):
        ast.parse("async def f[T](x: T) -> T:\n    return x\n", feature_version=(3, 11))
