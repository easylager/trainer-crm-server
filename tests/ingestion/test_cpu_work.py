"""TASK-188: CPU-bound parser work must not block the event loop."""
from __future__ import annotations

import asyncio
import time

import pytest

from src.ingestion.cpu_work import IngestTimeoutError, run_cpu_bound


def _slow_ocr_stub(_image_bytes: bytes) -> str:
    time.sleep(0.35)
    return "ok"


@pytest.mark.asyncio
async def test_cpu_bound_work_does_not_block_event_loop() -> None:
    ping_delays: list[float] = []

    async def pinger() -> None:
        for _ in range(5):
            t0 = time.monotonic()
            await asyncio.sleep(0.05)
            ping_delays.append(time.monotonic() - t0)

    ocr_task = asyncio.create_task(run_cpu_bound(_slow_ocr_stub, b"img"))
    ping_task = asyncio.create_task(pinger())
    assert await ocr_task == "ok"
    await ping_task
    assert max(ping_delays) < 0.1


@pytest.mark.asyncio
async def test_cpu_bound_times_out_on_stuck_work() -> None:
    def _hang() -> None:
        time.sleep(5)

    with pytest.raises(IngestTimeoutError):
        await run_cpu_bound(_hang, timeout_s=0.2)
