"""Короткий процессный кэш агрегатов «Кто кого»: TTL, single-flight, лимиты, сброс."""

from __future__ import annotations

import asyncio

import pytest

from src.application.hockey_cache import AggregateCache


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.asyncio
async def test_value_is_reused_until_ttl_expires() -> None:
    clock = Clock()
    cache = AggregateCache(ttl=30, clock=clock)
    calls = 0

    async def compute() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert await cache.get_or_compute("k", compute) == 1
    clock.now = 29
    assert await cache.get_or_compute("k", compute) == 1
    clock.now = 31
    assert await cache.get_or_compute("k", compute) == 2


@pytest.mark.asyncio
async def test_concurrent_requests_compute_once() -> None:
    cache = AggregateCache()
    calls = 0

    async def compute() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return 7

    results = await asyncio.gather(*(cache.get_or_compute("k", compute) for _ in range(20)))
    assert results == [7] * 20
    assert calls == 1
    assert cache._locks == {}  # замки не копятся


@pytest.mark.asyncio
async def test_failed_compute_is_not_cached_and_followers_retry() -> None:
    cache = AggregateCache()
    attempts = 0

    async def compute() -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("db down")
        return 5

    with pytest.raises(RuntimeError):
        await cache.get_or_compute("k", compute)
    assert await cache.get_or_compute("k", compute) == 5


@pytest.mark.asyncio
async def test_clear_during_compute_drops_stale_result() -> None:
    cache = AggregateCache()
    release = asyncio.Event()
    seen = []

    async def slow() -> str:
        await release.wait()
        return "old"

    task = asyncio.create_task(cache.get_or_compute("k", slow))
    await asyncio.sleep(0)
    cache.clear()  # очки пересчитаны, пока шёл расчёт
    release.set()
    assert await task == "old"  # тому, кто считал, отдаём как есть
    assert len(cache) == 0  # но в кэш устаревшее не кладём

    async def fresh() -> str:
        seen.append(1)
        return "new"

    assert await cache.get_or_compute("k", fresh) == "new"


@pytest.mark.asyncio
async def test_size_limits_evict_least_recently_used() -> None:
    cache = AggregateCache(max_entries=2, max_weight=10)

    async def make(v):
        return v

    await cache.get_or_compute("a", lambda: make("a"))
    await cache.get_or_compute("b", lambda: make("b"))
    await cache.get_or_compute("a", lambda: make("a"))  # a свежее b
    await cache.get_or_compute("c", lambda: make("c"))
    assert set(cache._items) == {"a", "c"}
    # одна запись тяжелее всего бюджета не кэшируется и не вытесняет остальное
    await cache.get_or_compute("big", lambda: make("big"), weight=lambda v: 11)
    assert set(cache._items) == {"a", "c"}


@pytest.mark.asyncio
async def test_not_cacheable_key_always_computes() -> None:
    cache = AggregateCache()
    calls = 0

    async def compute() -> int:
        nonlocal calls
        calls += 1
        return calls

    await cache.get_or_compute("k", compute, cacheable=False)
    await cache.get_or_compute("k", compute, cacheable=False)
    assert calls == 2 and len(cache) == 0
