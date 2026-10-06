"""Маленький in-process LRU готовых PNG (TASK-190).

Ключ — всё, что влияет на картинку: нормализованные параметры + данные, из которых она рисуется
(хэш выборки). Лишние/случайные query-параметры в ключ не попадают, поэтому ``?x=1,2,3…`` не
заставляет рендерить заново, а смена расписания меняет хэш данных и сбрасывает кэш сама.
Рендер идёт в threadpool: PIL держит event loop иначе.
"""
from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from typing import Any

from starlette.concurrency import run_in_threadpool

MAX_ENTRIES = 128
MAX_BYTES = 48 * 1024 * 1024

_lock = Lock()
_cache: OrderedDict[str, bytes] = OrderedDict()
_total_bytes = 0
_stats = {"hits": 0, "renders": 0}


def cache_key(kind: str, params: dict[str, Any], data: Any) -> str:
    raw = json.dumps([kind, params, data], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def reset_png_cache_for_tests() -> None:
    global _total_bytes
    with _lock:
        _cache.clear()
        _total_bytes = 0
        _stats["hits"] = 0
        _stats["renders"] = 0


def png_cache_stats() -> dict[str, int]:
    with _lock:
        return {**_stats, "entries": len(_cache), "bytes": _total_bytes}


def _get(key: str) -> bytes | None:
    with _lock:
        value = _cache.get(key)
        if value is not None:
            _cache.move_to_end(key)
            _stats["hits"] += 1
        return value


def _put(key: str, value: bytes) -> None:
    global _total_bytes
    if len(value) > MAX_BYTES // 4:
        return
    with _lock:
        old = _cache.pop(key, None)
        if old is not None:
            _total_bytes -= len(old)
        _cache[key] = value
        _total_bytes += len(value)
        while _cache and (len(_cache) > MAX_ENTRIES or _total_bytes > MAX_BYTES):
            _, evicted = _cache.popitem(last=False)
            _total_bytes -= len(evicted)


async def render_png_cached(
    kind: str,
    params: dict[str, Any],
    data: Any,
    render: Callable[..., bytes],
    *args: Any,
    **kwargs: Any,
) -> bytes:
    key = cache_key(kind, params, data)
    hit = _get(key)
    if hit is not None:
        return hit
    png = await run_in_threadpool(render, *args, **kwargs)
    with _lock:
        _stats["renders"] += 1
    _put(key, png)
    return png
