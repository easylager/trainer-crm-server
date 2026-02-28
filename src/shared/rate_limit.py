"""
In-memory sliding-window rate limiter per user. Used by bot middleware to cap requests per window.
"""
import time


class RateLimiter:
    """Sliding window: at most `max_requests` per `window_sec` per key (e.g. user_id)."""

    __slots__ = ("_ticks", "_max_requests", "_window_sec")

    def __init__(self, max_requests: int = 30, window_sec: float = 60.0) -> None:
        self._max_requests = max(1, max_requests)
        self._window_sec = max(0.1, window_sec)
        # key -> list of timestamps (monotonic) within current window
        self._ticks: dict[int, list[float]] = {}

    def _prune(self, key: int, now: float) -> None:
        cutoff = now - self._window_sec
        if key in self._ticks:
            self._ticks[key] = [t for t in self._ticks[key] if t > cutoff]
            if not self._ticks[key]:
                del self._ticks[key]

    def check_and_consume(self, key: int) -> bool:
        """If under limit: record this request and return True. Otherwise return False."""
        now = time.monotonic()
        self._prune(key, now)
        if key not in self._ticks:
            self._ticks[key] = []
        if len(self._ticks[key]) >= self._max_requests:
            return False
        self._ticks[key].append(now)
        return True
