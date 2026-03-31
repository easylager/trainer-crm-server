#!/usr/bin/env python3
"""
Lightweight HTTP load generator for public API (httpx async).
Use on staging/local with API_RATE_LIMIT_ENABLED=false to avoid 429 from a single IP.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
import time
from collections import Counter

import httpx


def _percentile(sorted_ms: list[float], p: float) -> float:
    if not sorted_ms:
        return float("nan")
    k = (len(sorted_ms) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(sorted_ms) - 1)
    if f == c:
        return sorted_ms[f]
    return sorted_ms[f] + (sorted_ms[c] - sorted_ms[f]) * (k - f)


async def _one(client: httpx.AsyncClient, url: str) -> tuple[int, float]:
    t0 = time.perf_counter()
    try:
        r = await client.get(url)
        dt = (time.perf_counter() - t0) * 1000.0
        return r.status_code, dt
    except Exception:
        return 0, (time.perf_counter() - t0) * 1000.0


async def _worker(
    url: str,
    duration_sec: float,
    q: asyncio.Queue[tuple[int, float]],
) -> None:
    timeout = httpx.Timeout(120.0)
    limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        end = time.monotonic() + duration_sec
        while time.monotonic() < end:
            status, ms = await _one(client, url)
            await q.put((status, ms))


async def _run_mixed(
    base: str,
    duration_sec: float,
    concurrency: int,
) -> None:
    paths = [
        ("/health", 1),
        ("/api/public/cities", 1),
        ("/api/public/trainers?limit=15", 3),
    ]
    q: asyncio.Queue[tuple[int, float]] = asyncio.Queue()

    async def mixed_worker() -> None:
        timeout = httpx.Timeout(120.0)
        limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            end = time.monotonic() + duration_sec
            while time.monotonic() < end:
                total_w = sum(w for _, w in paths)
                roll = random.randint(1, total_w)
                acc = 0
                path = paths[0][0]
                for p, w in paths:
                    acc += w
                    if roll <= acc:
                        path = p
                        break
                status, ms = await _one(client, base.rstrip("/") + path)
                await q.put((status, ms))

    tasks = [asyncio.create_task(mixed_worker()) for _ in range(concurrency)]
    await asyncio.gather(*tasks)
    await _report(q, duration_sec, concurrency, "mixed")


async def _report(
    q: asyncio.Queue[tuple[int, float]],
    duration_sec: float,
    concurrency: int,
    label: str,
) -> None:
    rows: list[tuple[int, float]] = []
    while not q.empty():
        rows.append(q.get_nowait())
    if not rows:
        print("No samples.", file=sys.stderr)
        return
    codes = Counter(s for s, _ in rows)
    ok_ms = [ms for s, ms in rows if 200 <= s < 300]
    ok_ms.sort()
    err = len(rows) - len(ok_ms)
    print(f"\n=== {label} ===")
    print(f"concurrency={concurrency} duration≈{duration_sec:.0f}s total_requests={len(rows)} req/s={len(rows)/duration_sec:.1f}")
    print(f"status_codes: {dict(codes)}")
    if ok_ms:
        print(
            f"latency_ms (2xx): min={min(ok_ms):.1f} p50={_percentile(ok_ms, 50):.1f} "
            f"p95={_percentile(ok_ms, 95):.1f} p99={_percentile(ok_ms, 99):.1f} max={max(ok_ms):.1f}"
        )
    if err:
        print(f"non-2xx: {err}")


async def main() -> None:
    p = argparse.ArgumentParser(description="Public API load test (async httpx)")
    p.add_argument("--base", default=os.environ.get("LOADTEST_BASE", "http://127.0.0.1:8000"), help="API base URL")
    p.add_argument("--duration", type=float, default=30.0, help="Seconds per worker group")
    p.add_argument("--concurrency", type=int, default=20, help="Parallel clients")
    p.add_argument(
        "--endpoint",
        choices=("trainers", "cities", "health", "mixed", "photo"),
        default="trainers",
    )
    p.add_argument("--photo-key", default="", help="For endpoint=photo, e.g. trainers/1/abc.jpg")
    args = p.parse_args()
    base = args.base.rstrip("/")

    if args.endpoint == "mixed":
        await _run_mixed(base, args.duration, args.concurrency)
        return

    if args.endpoint == "photo":
        if not args.photo_key:
            print("Use --photo-key trainers/... for photo endpoint", file=sys.stderr)
            sys.exit(2)
        path = f"/api/public/photos/{args.photo_key}"
    else:
        path = {
            "trainers": "/api/public/trainers?limit=15",
            "cities": "/api/public/cities",
            "health": "/health",
        }[args.endpoint]

    url = base + path
    q: asyncio.Queue[tuple[int, float]] = asyncio.Queue()
    tasks = [
        asyncio.create_task(_worker(url, args.duration, q))
        for _ in range(args.concurrency)
    ]
    await asyncio.gather(*tasks)
    await _report(q, args.duration, args.concurrency, args.endpoint)


if __name__ == "__main__":
    asyncio.run(main())
