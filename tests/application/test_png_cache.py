"""Кэш картинок: рисуем один раз на данные, в потоке, с ограничением объёма."""

from __future__ import annotations

import asyncio
import threading

import pytest

from src.application import png_cache


@pytest.fixture(autouse=True)
def _clean() -> None:
    png_cache.reset_png_cache()
    yield
    png_cache.reset_png_cache()


@pytest.mark.asyncio
async def test_same_data_renders_once_off_the_event_loop() -> None:
    calls: list[str] = []
    main = threading.get_ident()

    def render() -> bytes:
        calls.append("thread" if threading.get_ident() != main else "loop")
        return b"png"

    first, second = await asyncio.gather(
        png_cache.cached_png(("match", 11), render), png_cache.cached_png(("match", 11), render)
    )
    third = await png_cache.cached_png(("match", 11), render)
    assert first == second == third == b"png"
    assert calls == ["thread"]


@pytest.mark.asyncio
async def test_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(png_cache, "_MAX_ITEMS", 2)
    for i in range(3):
        await png_cache.cached_png(("k", i), lambda i=i: bytes([i]))
    assert list(png_cache._items) == [("k", 1), ("k", 2)]


@pytest.mark.asyncio
async def test_failed_render_is_not_cached() -> None:
    def boom() -> bytes:
        raise RuntimeError("pillow")

    with pytest.raises(RuntimeError):
        await png_cache.cached_png("x", boom)
    assert await png_cache.cached_png("x", lambda: b"ok") == b"ok"
