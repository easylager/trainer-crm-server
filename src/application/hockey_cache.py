"""Короткий процессный кэш тяжёлых агрегатов игры «Кто кого» (пик после рассылки).

Таблица среза «Все · Сезон» — агрегат по всем ходам всех игроков; на каждое открытие главного экрана
считать её заново нельзя. Кэш держит результат ``TTL`` секунд, одновременные запросы одного ключа
считают его один раз (single-flight), размер ограничен: число записей и суммарный «вес» (строк таблиц).

Кэш **процессный**. При нескольких репликах API у каждой свой кэш, и таблицы у разных реплик могут
расходиться не дольше чем на ``TTL``. Сброс (``invalidate``) после начисления очков и закрытия гонок
срабатывает только в том процессе, где это случилось (цикл матчей и админка) — остальные догоняют по TTL.
Фоновые пересчёты (короны, уведомления) кэш не используют: они читают таблицы напрямую.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable

TTL_SEC = 45.0
MAX_ENTRIES = 48
MAX_WEIGHT = 400_000  # суммарно строк таблиц в кэше: ~100 МБ в худшем случае при 50 тыс. игроков в срезе


class AggregateCache[T]:
    def __init__(
        self,
        *,
        ttl: float = TTL_SEC,
        max_entries: int = MAX_ENTRIES,
        max_weight: int = MAX_WEIGHT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self.max_weight = max_weight
        self._clock = clock
        self._items: OrderedDict[Hashable, tuple[float, int, T]] = OrderedDict()
        self._locks: dict[Hashable, tuple[asyncio.Lock, int]] = {}
        self._weight = 0
        # Сброс во время расчёта: результат, начатый до сброса, в кэш не кладём (он может быть устаревшим).
        self._generation = 0

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._generation += 1
        self._items.clear()
        self._weight = 0

    def _fresh(self, key: Hashable) -> tuple[bool, T | None]:
        hit = self._items.get(key)
        if hit is None:
            return False, None
        expires, _, value = hit
        if self._clock() >= expires:
            self._drop(key)
            return False, None
        self._items.move_to_end(key)
        return True, value

    def _drop(self, key: Hashable) -> None:
        _, weight, _ = self._items.pop(key)
        self._weight -= weight

    def _store(self, key: Hashable, value: T, weight: int) -> None:
        if key in self._items:
            self._drop(key)
        if weight > self.max_weight:
            return  # одна запись больше всего бюджета — не кэшируем, чтобы не вытеснить остальное
        self._items[key] = (self._clock() + self.ttl, weight, value)
        self._weight += weight
        while len(self._items) > self.max_entries or self._weight > self.max_weight:
            oldest = next(iter(self._items))
            self._drop(oldest)

    async def get_or_compute(
        self,
        key: Hashable,
        compute: Callable[[], Awaitable[T]],
        *,
        weight: Callable[[T], int] = lambda value: 1,
        cacheable: bool = True,
    ) -> T:
        """Значение из кэша или ``compute()``; одновременные запросы одного ключа ждут первого."""
        if not cacheable:
            return await compute()
        found, value = self._fresh(key)
        if found:
            return value  # type: ignore[return-value]
        lock, users = self._locks.get(key) or (asyncio.Lock(), 0)
        self._locks[key] = (lock, users + 1)
        try:
            async with lock:
                found, value = self._fresh(key)  # пока ждали, первый мог положить результат
                if found:
                    return value  # type: ignore[return-value]
                generation = self._generation
                value = await compute()
                if generation == self._generation:
                    self._store(key, value, max(1, weight(value)))
                return value
        finally:
            lock, users = self._locks[key]
            if users <= 1:
                del self._locks[key]
            else:
                self._locks[key] = (lock, users - 1)


# Один кэш на все тяжёлые агрегаты: ключ начинается с имени агрегата.
aggregates: AggregateCache = AggregateCache()
# Результаты «на игрока» (вершины): записей много, они не должны вытеснять таблицы срезов.
personal_aggregates: AggregateCache = AggregateCache(max_entries=5000, max_weight=20_000)


def invalidate_aggregates() -> None:
    """Сбросить кэш в этом процессе: очки начислены, гонка закрыта."""
    aggregates.clear()
    personal_aggregates.clear()


def invalidate_after_commit(session) -> None:
    """Сбросить сейчас и ещё раз после коммита сессии.

    Сброс до коммита нужен тестам и тем, кто не коммитит сам; сброс после — настоящая граница: запрос,
    успевший посчитать таблицу по старым данным между сбросом и коммитом, не переживёт коммит.
    """
    invalidate_aggregates()
    try:
        from sqlalchemy import event

        target = getattr(session, "sync_session", session)
        event.listen(target, "after_commit", lambda _s: invalidate_aggregates(), once=True)
    except Exception:  # noqa: BLE001 — подмена сессии в тестах: кэш всё равно сброшен выше
        pass


__all__ = ["AggregateCache", "aggregates", "personal_aggregates", "invalidate_after_commit", "invalidate_aggregates"]
