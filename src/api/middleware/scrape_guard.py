"""Детектор автоматического обхода публичного сайта.

Человек за сессию открывает несколько страниц; скрипт, собирающий весь каталог, — десятки разных
за считаные минуты. Считаем уникальные HTML-страницы (200, ``text/html``) на «посетителя»
(IP + отпечаток User-Agent) в скользящем окне.

Поисковые боты и превью мессенджеров не учитываются и не блокируются никогда: от них зависят индексация
и ссылки. Режимы (``SCRAPE_GUARD_MODE``): ``off`` | ``log`` (по умолчанию: только строка в логе) |
``block`` (ответ 429 после порога). Счётчик в памяти процесса, без обращений к БД, на скорость не влияет.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import deque

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.api.middleware.http_limits import _mask_client_ip, client_ip_from_request
from src.shared.config import Settings
from src.shared.ua_class import UA_PREVIEW, UA_SEARCH, classify_user_agent

logger = logging.getLogger(__name__)

# Не страницы сайта: API, Mini App, статика и картинки.
_SKIP_PREFIXES = ("/api/", "/webapp/", "/static/", "/logos/", "/assets/", "/health")
_MAX_ACTORS = 5000
_MAX_PER_ACTOR = 400
_RETRY_AFTER_SEC = 600


class _Tracker:
    def __init__(self) -> None:
        self._seen: dict[str, deque[tuple[float, str]]] = {}
        self._flagged: dict[str, float] = {}

    def reset(self) -> None:
        self._seen.clear()
        self._flagged.clear()

    def distinct(self, key: str, now: float, window: float) -> int:
        entries = self._seen.get(key)
        if not entries:
            return 0
        while entries and entries[0][0] < now - window:
            entries.popleft()
        return len({path for _, path in entries})

    def record(self, key: str, path: str, now: float, window: float) -> int:
        if key not in self._seen and len(self._seen) >= _MAX_ACTORS:
            for stale in list(self._seen)[: _MAX_ACTORS // 2]:
                self._seen.pop(stale, None)
                self._flagged.pop(stale, None)
        entries = self._seen.setdefault(key, deque(maxlen=_MAX_PER_ACTOR))
        entries.append((now, path))
        return self.distinct(key, now, window)

    def first_flag(self, key: str, now: float, window: float) -> bool:
        """True once per actor per window — keeps the log from filling up."""
        if now - self._flagged.get(key, float("-inf")) < window:
            return False
        self._flagged[key] = now
        return True


_tracker = _Tracker()


def reset_scrape_guard_for_tests() -> None:
    _tracker.reset()


class ScrapeGuardMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "GET":
            await self.app(scope, receive, send)
            return
        settings = Settings()
        mode = (settings.scrape_guard_mode or "log").lower()
        path = str(scope.get("path") or "")
        if mode == "off" or path.startswith(_SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers") or []}
        user_agent = headers.get(b"user-agent", b"").decode("latin-1")
        if classify_user_agent(user_agent) in (UA_SEARCH, UA_PREVIEW):
            await self.app(scope, receive, send)
            return

        ip = client_ip_from_request(Request(scope))
        key = f"{ip}|{hashlib.sha1(user_agent.encode('latin-1', 'ignore')).hexdigest()[:8]}"
        window = float(settings.scrape_guard_window_sec)
        threshold = int(settings.scrape_guard_distinct_pages)

        if mode == "block" and _tracker.distinct(key, time.monotonic(), window) >= threshold:
            response = JSONResponse(
                {"detail": "Too many pages requested. Try again later."},
                status_code=429,
                headers={"Retry-After": str(_RETRY_AFTER_SEC)},
            )
            await response(scope, receive, send)
            return

        async def send_counting(message: Message) -> None:
            if message["type"] == "http.response.start" and message.get("status") == 200:
                content_type = next((v for k, v in message.get("headers") or [] if k.lower() == b"content-type"), b"")
                if content_type.startswith(b"text/html"):
                    now = time.monotonic()
                    distinct = _tracker.record(key, path, now, window)
                    if distinct >= threshold and _tracker.first_flag(key, now, window):
                        logger.warning(
                            "scrape_suspect mode=%s ip=%s ua=%r distinct_pages=%d window_sec=%d last=%s",
                            mode, _mask_client_ip(ip), user_agent[:80], distinct, int(window), path,
                        )
            await send(message)

        await self.app(scope, receive, send_counting)
