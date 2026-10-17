"""Лимитер исходящих вызовов Bot API внутри одного процесса.

Общий лимит на все процессы (API, бот, notification_service) без общего хранилища
не держится. [ВОПРОС] нужен ли Redis, или достаточно лимита на процесс.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable


class OutboundLimiter:
    def __init__(
        self,
        *,
        global_per_sec: float = 30,
        chat_per_sec: float = 1,
        group_per_min: int = 20,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.global_per_sec = global_per_sec
        self.chat_interval = 1.0 / chat_per_sec if chat_per_sec else 0
        self.group_per_min = group_per_min
        self._clock = clock or time.monotonic
        self._sleep = sleep
        self._global: deque[float] = deque()
        self._chat: dict[int, float] = {}
        self._group: dict[int, deque[float]] = {}
        self.retry_after_waits = 0

    def _trim(self, now: float) -> None:
        window = 1.0
        while self._global and now - self._global[0] >= window:
            self._global.popleft()

    def delay(self, chat_id: int | None, *, is_group: bool, now: float | None = None) -> float:
        now = self._clock() if now is None else now
        self._trim(now)
        wait = 0.0
        if len(self._global) >= self.global_per_sec:
            wait = max(wait, 1.0 - (now - self._global[0]))
        if chat_id is not None and chat_id in self._chat:
            wait = max(wait, self.chat_interval - (now - self._chat[chat_id]))
        if is_group and chat_id is not None:
            bucket = self._group.setdefault(chat_id, deque())
            while bucket and now - bucket[0] >= 60:
                bucket.popleft()
            if len(bucket) >= self.group_per_min:
                wait = max(wait, 60 - (now - bucket[0]))
        return max(0.0, wait)

    def mark(self, chat_id: int | None, *, is_group: bool, now: float | None = None) -> None:
        now = self._clock() if now is None else now
        self._global.append(now)
        if chat_id is not None:
            self._chat[chat_id] = now
            if is_group:
                self._group.setdefault(chat_id, deque()).append(now)

    async def acquire(self, chat_id: int | None, *, is_group: bool) -> None:
        if self._sleep is None:
            self.mark(chat_id, is_group=is_group)
            return
        while True:
            wait = self.delay(chat_id, is_group=is_group)
            if wait <= 0:
                self.mark(chat_id, is_group=is_group)
                return
            await self._sleep(wait)

    def note_retry_after(self) -> None:
        self.retry_after_waits += 1
