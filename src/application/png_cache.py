"""Кэш картинок для чата и превью (открытки матча, карточки компаний, лиги, итоги).

Pillow рисует 70–200 мс процессора. Без кэша каждый запрос рисует заново, а адрес с любой
«версией» (``/kk/m/11/любое.png``) — новый запрос. Поэтому:

- ключ — данные, из которых рисуется картинка, а не адрес: чужая версия попадает в тот же кэш;
- рисование уходит в поток (``run_in_threadpool``), чтобы не держать цикл событий сервера;
- кэш ограничен по числу и объёму, вытесняется самое давнее.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from collections.abc import Callable, Hashable

from starlette.concurrency import run_in_threadpool

_MAX_ITEMS = 256
_MAX_BYTES = 48 * 1024 * 1024

_items: OrderedDict[Hashable, bytes] = OrderedDict()
_size = 0
_inflight: dict[Hashable, asyncio.Future[bytes]] = {}


def bytes_key(*parts: bytes | None) -> str:
    """Короткий отпечаток аватаров и прочих байтов для ключа кэша."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(b"\x00" if part is None else hashlib.sha256(part).digest())
    return digest.hexdigest()[:16]


def _put(key: Hashable, png: bytes) -> None:
    global _size
    if key in _items:
        _size -= len(_items.pop(key))
    _items[key] = png
    _size += len(png)
    while _items and (len(_items) > _MAX_ITEMS or _size > _MAX_BYTES):
        _, old = _items.popitem(last=False)
        _size -= len(old)


async def cached_png(key: Hashable, render: Callable[[], bytes]) -> bytes:
    """Готовая картинка по ключу; нет — рисуем в потоке. Одинаковые запросы ждут один рендер."""
    hit = _items.get(key)
    if hit is not None:
        _items.move_to_end(key)
        return hit
    pending = _inflight.get(key)
    if pending is not None:
        return await asyncio.shield(pending)
    future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
    _inflight[key] = future
    try:
        png = await run_in_threadpool(render)
    except BaseException as exc:
        future.set_exception(exc)
        future.exception()  # ошибку забрали: без ждущих не будет «never retrieved»
        raise
    finally:
        _inflight.pop(key, None)
    _put(key, png)
    future.set_result(png)
    return png


def reset_png_cache() -> None:
    """Для тестов."""
    global _size
    _items.clear()
    _inflight.clear()
    _size = 0
