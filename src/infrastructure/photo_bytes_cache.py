"""Память процесса для публичных фото.

Ключи в хранилище содержат uuid, новый кадр — новый ключ. Повторный заход не ходит
в объектное хранилище: первый байт ответа — это уже байты из процесса.
"""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock

_MAX_BYTES = 48 * 1024 * 1024
_MAX_ITEM_BYTES = 1_500_000


class PhotoBytesCache:
    def __init__(self, max_bytes: int = _MAX_BYTES, max_item_bytes: int = _MAX_ITEM_BYTES) -> None:
        self._max_bytes = max_bytes
        self._max_item_bytes = max_item_bytes
        self._items: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._size = 0
        self._lock = Lock()

    def get(self, key: str) -> tuple[bytes, str] | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            self._items.move_to_end(key)
            return item

    def put(self, key: str, body: bytes, content_type: str) -> None:
        if not key or len(body) > self._max_item_bytes:
            return
        with self._lock:
            previous = self._items.pop(key, None)
            if previous is not None:
                self._size -= len(previous[0])
            self._items[key] = (body, content_type)
            self._size += len(body)
            while self._items and self._size > self._max_bytes:
                _, evicted = self._items.popitem(last=False)
                self._size -= len(evicted[0])

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._size = 0


photo_bytes_cache = PhotoBytesCache()
