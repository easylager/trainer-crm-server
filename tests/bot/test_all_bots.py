"""all_bots: супервизор перезапускает упавший бот, остальные живут; остановка общая; режим простоя."""

from __future__ import annotations

import asyncio
import logging

import pytest

from src.bot import all_bots


@pytest.mark.asyncio
async def test_crashed_bot_is_restarted_and_backoff_grows(caplog):
    stop = asyncio.Event()
    runs = 0

    async def flaky() -> None:
        nonlocal runs
        runs += 1
        if runs < 4:
            raise RuntimeError("telegram hiccup")
        await asyncio.Event().wait()  # дальше работает

    with caplog.at_level(logging.WARNING, logger="src.bot.all_bots"):
        task = asyncio.create_task(
            all_bots.supervise("trainer", flaky, stop, start_backoff=0.01, max_backoff=0.04, min_stable=999)
        )
        await asyncio.sleep(0.3)
        assert runs == 4  # три падения, четвёртый запуск держится
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    delays = [r.message.rsplit(" ", 1)[-1] for r in caplog.records if "restart in" in r.message]
    assert delays == ["0.01s", "0.02s", "0.04s"]  # пауза удваивается до потолка


@pytest.mark.asyncio
async def test_one_bot_crashing_does_not_stop_the_others():
    stop = asyncio.Event()
    alive = {"admin": 0, "client": 0}

    async def admin() -> None:
        alive["admin"] += 1
        await asyncio.Event().wait()

    async def client() -> None:
        alive["client"] += 1
        await asyncio.Event().wait()

    async def broken() -> None:
        raise RuntimeError("bad token")

    runner = asyncio.create_task(
        all_bots.run_all(
            {"admin": admin, "trainer": broken, "client": client}, stop,
            start_backoff=0.01, max_backoff=0.02, min_stable=999,
        )
    )
    await asyncio.sleep(0.15)
    assert alive == {"admin": 1, "client": 1}  # живые не перезапускались
    stop.set()
    await asyncio.wait_for(runner, timeout=2)


@pytest.mark.asyncio
async def test_stop_cancels_every_bot_and_returns():
    stop = asyncio.Event()
    cancelled: list[str] = []

    def make(name: str):
        async def run() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(name)
                raise

        return run

    runner = asyncio.create_task(all_bots.run_all({n: make(n) for n in ("admin", "trainer", "client")}, stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(runner, timeout=2)
    assert sorted(cancelled) == ["admin", "client", "trainer"]


@pytest.mark.asyncio
async def test_backoff_resets_after_a_stable_run(caplog):
    stop = asyncio.Event()
    runs = 0

    async def run() -> None:
        nonlocal runs
        runs += 1
        if runs == 1:
            raise RuntimeError("early crash")
        await asyncio.sleep(0.05)  # работал «долго» (min_stable=0.02) — потом упал
        raise RuntimeError("late crash")

    with caplog.at_level(logging.WARNING, logger="src.bot.all_bots"):
        task = asyncio.create_task(
            all_bots.supervise("client", run, stop, start_backoff=0.01, max_backoff=0.08, min_stable=0.02)
        )
        await asyncio.sleep(0.25)
        stop.set()
        await asyncio.gather(task, return_exceptions=True)
    delays = [r.message.rsplit(" ", 1)[-1] for r in caplog.records if "restart in" in r.message]
    assert delays[0] == "0.01s" and delays[1] == "0.01s"  # после стабильного запуска пауза снова начальная


def test_is_active_reads_the_switch(monkeypatch):
    monkeypatch.delenv(all_bots.ACTIVE_ENV, raising=False)
    assert all_bots.is_active() is False
    for value, expected in (("1", True), ("true", True), ("0", False), ("", False)):
        monkeypatch.setenv(all_bots.ACTIVE_ENV, value)
        assert all_bots.is_active() is expected


@pytest.mark.asyncio
async def test_inactive_process_idles_without_polling(monkeypatch):
    monkeypatch.delenv(all_bots.ACTIVE_ENV, raising=False)
    with pytest.raises(asyncio.TimeoutError):  # простаивает, не возвращается и не падает
        await asyncio.wait_for(all_bots.main(), timeout=0.2)


def test_bot_mains_accept_embedded_mode():
    import inspect

    from src.bot import admin_app, client_app, trainer_app

    for module in (admin_app, client_app, trainer_app):
        assert "embedded" in inspect.signature(module.main).parameters
