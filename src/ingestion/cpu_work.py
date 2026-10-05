"""Run CPU-bound parser work off the asyncio event loop."""
from __future__ import annotations

import asyncio
from typing import TypeVar

T = TypeVar("T")

# One schedule image with many OCR boxes (Orsha) can take a few minutes.
CPU_WORK_TIMEOUT_S = 180.0


class IngestTimeoutError(TimeoutError):
    """CPU-bound parse step exceeded its deadline (OCR, PDF rasterize, etc.)."""


async def run_cpu_bound(fn, /, *args, timeout_s: float = CPU_WORK_TIMEOUT_S) -> T:
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=timeout_s)
    except TimeoutError as exc:
        raise IngestTimeoutError(f"timed out after {timeout_s}s") from exc
