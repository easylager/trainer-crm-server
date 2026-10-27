"""Защита публичного расписания от массового выкачивания.

Три слоя, все на счётчиках в памяти процесса (без БД, на скорость не влияет):

1. Бюджет страниц. Человек за сессию открывает несколько страниц, а скрипт по sitemap — десятки.
   Считаем уникальные HTML-страницы за короткое окно и уникальные арены за сутки на посетителя
   (IP + отпечаток User-Agent). Суточное окно ловит и «медленный» обход.
2. JSON расписания (``/api/public/arenas/{ref}/sessions``) нужен нашим страницам и Mini App.
   Запрос без признаков того, что он пришёл со страницы сайта (``Sec-Fetch-Site``/``Origin``/``Referer``),
   считается внешним.
3. Ловушка: путь ``/export/…`` закрыт в ``robots.txt``, и ссылок на него нет. Заглянул — значит читает
   robots.txt, чтобы найти, что закрыто, и в блок-режиме закрывается на сутки.

Поисковые боты и превью мессенджеров не учитываются и не блокируются никогда: от них зависят индексация
и ссылки. Режимы ``SCRAPE_GUARD_MODE`` (бюджеты и ловушка) и ``SCRAPE_GUARD_JSON_MODE`` (проверка JSON):
``off`` | ``log`` (по умолчанию: только строка в логе) | ``block`` (429 / 403).
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import deque
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.api.middleware.http_limits import _mask_client_ip, client_ip_from_request
from src.shared.config import Settings
from src.shared.ua_class import UA_PREVIEW, UA_SEARCH, classify_user_agent

logger = logging.getLogger(__name__)

# Не страницы сайта: API (кроме JSON расписания ниже), Mini App, статика и картинки.
_SKIP_PREFIXES = ("/api/", "/webapp/", "/static/", "/logos/", "/assets/", "/health")
_ARENA_PAGE_RE = re.compile(r"^/p/[^/]+/[^/]+/?$")
_ARENA_JSON_RE = re.compile(r"^/api/public/arenas/([^/]+)/sessions/?$")
TRAP_PREFIX = "/export/"
_DAY_SEC = 86400.0
_TRAP_BAN_SEC = 86400.0
_RETRY_AFTER_SEC = 600
_MAX_ACTORS = 5000
_MAX_PER_ACTOR = 400
_MAX_ARENAS_PER_ACTOR = 64  # дальше порога хранить незачем: посетитель уже над бюджетом


class _Tracker:
    def __init__(self) -> None:
        self._pages: dict[str, deque[tuple[float, str]]] = {}
        self._arenas: dict[str, dict[tuple[str, str], float]] = {}
        self._flagged: dict[tuple[str, str], float] = {}
        self._trapped: dict[str, float] = {}

    def reset(self) -> None:
        self._pages.clear()
        self._arenas.clear()
        self._flagged.clear()
        self._trapped.clear()

    def _evict(self, store: dict) -> None:
        if len(store) >= _MAX_ACTORS:
            for stale in list(store)[: _MAX_ACTORS // 2]:
                store.pop(stale, None)

    # — страницы в коротком окне
    def pages_distinct(self, key: str, now: float, window: float) -> int:
        entries = self._pages.get(key)
        if not entries:
            return 0
        while entries and entries[0][0] < now - window:
            entries.popleft()
        return len({path for _, path in entries})

    def record_page(self, key: str, path: str, now: float, window: float) -> int:
        if key not in self._pages:
            self._evict(self._pages)
        self._pages.setdefault(key, deque(maxlen=_MAX_PER_ACTOR)).append((now, path))
        return self.pages_distinct(key, now, window)

    # — арены за сутки (страницы и JSON считаются отдельно: ref арены в них разный)
    def arenas_distinct(self, key: str, now: float) -> int:
        seen = self._arenas.get(key)
        if not seen:
            return 0
        for item in [i for i, ts in seen.items() if ts < now - _DAY_SEC]:
            del seen[item]
        counts: dict[str, int] = {}
        for ns, _ in seen:
            counts[ns] = counts.get(ns, 0) + 1
        return max(counts.values(), default=0)

    def record_arena(self, key: str, ns: str, ref: str, now: float) -> int:
        if key not in self._arenas:
            self._evict(self._arenas)
        seen = self._arenas.setdefault(key, {})
        if (ns, ref) in seen or len(seen) < _MAX_ARENAS_PER_ACTOR:
            seen[(ns, ref)] = now
        return self.arenas_distinct(key, now)

    # — ловушка и «один раз на окно» для логов
    def trap(self, key: str, now: float) -> None:
        if key not in self._trapped:
            self._evict(self._trapped)
        self._trapped[key] = now

    def is_trapped(self, key: str, now: float) -> bool:
        ts = self._trapped.get(key)
        if ts is None:
            return False
        if now - ts >= _TRAP_BAN_SEC:
            del self._trapped[key]
            return False
        return True

    def first_flag(self, key: str, reason: str, now: float, window: float) -> bool:
        """True один раз на посетителя и причину за окно — лог не засоряется."""
        if len(self._flagged) >= _MAX_ACTORS * 2:
            self._flagged.clear()
        if now - self._flagged.get((key, reason), float("-inf")) < window:
            return False
        self._flagged[(key, reason)] = now
        return True


_tracker = _Tracker()


def reset_scrape_guard_for_tests() -> None:
    _tracker.reset()


def _allowed_hosts(settings: object) -> set[str]:
    hosts = {h.strip().lower() for h in str(getattr(settings, "scrape_guard_allowed_hosts", "")).split(",") if h.strip()}
    base = urlparse(str(getattr(settings, "webapp_base_url", "") or "")).hostname
    if base:
        hosts.add(base.lower())
    return hosts


def request_comes_from_site(headers: dict[bytes, bytes], allowed: set[str]) -> bool | None:
    """True/False — по заголовкам браузера; None — их нет вовсе (curl, скрипт, старый клиент)."""
    fetch_site = headers.get(b"sec-fetch-site", b"").decode("latin-1").lower()
    if fetch_site:
        return fetch_site in ("same-origin", "same-site", "none")
    for name in (b"origin", b"referer"):
        value = headers.get(name, b"").decode("latin-1")
        if value:
            return (urlparse(value).hostname or "").lower() in allowed
    return None


def _forbid(status: int, detail: str, retry_after: bool) -> JSONResponse:
    return JSONResponse(
        {"detail": detail},
        status_code=status,
        headers={"Retry-After": str(_RETRY_AFTER_SEC)} if retry_after else None,
    )


class ScrapeGuardMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in ("GET", "HEAD"):
            await self.app(scope, receive, send)
            return
        settings = Settings()
        mode = (settings.scrape_guard_mode or "log").lower()
        json_mode = (settings.scrape_guard_json_mode or "log").lower()
        path = str(scope.get("path") or "")
        json_match = _ARENA_JSON_RE.match(path)
        is_trap = path.startswith(TRAP_PREFIX)
        is_page = bool(_ARENA_PAGE_RE.match(path)) or (
            not json_match and not is_trap and not path.startswith(_SKIP_PREFIXES)
        )
        if (mode == "off" and json_mode == "off") or not (json_match or is_trap or is_page):
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers") or []}
        user_agent = headers.get(b"user-agent", b"").decode("latin-1")
        if classify_user_agent(user_agent) in (UA_SEARCH, UA_PREVIEW):
            await self.app(scope, receive, send)
            return

        ip = client_ip_from_request(Request(scope))
        key = f"{ip}|{hashlib.sha1(user_agent.encode('latin-1', 'ignore')).hexdigest()[:8]}"
        now = time.monotonic()
        window = float(settings.scrape_guard_window_sec)
        page_limit = int(settings.scrape_guard_distinct_pages)
        arena_limit = int(settings.scrape_guard_daily_arenas)

        def flag(reason: str, window_sec: float, **details: object) -> None:
            if _tracker.first_flag(key, reason, now, window_sec):
                logger.warning(
                    "scrape_suspect reason=%s mode=%s ip=%s ua=%r path=%s %s",
                    reason, json_mode if reason == "external_json" else mode, _mask_client_ip(ip),
                    user_agent[:80], path, " ".join(f"{k}={v}" for k, v in details.items()),
                )

        if is_trap and mode != "off":
            _tracker.trap(key, now)
            flag("trap", _DAY_SEC)
            await _forbid(404, "Not Found", False)(scope, receive, send)
            return

        if mode == "block" and _tracker.is_trapped(key, now):
            await _forbid(429, "Too many requests. Try again later.", True)(scope, receive, send)
            return

        if json_match and json_mode != "off":
            from_site = request_comes_from_site(headers, _allowed_hosts(settings))
            if from_site is not True:
                flag("external_json", window, sec_fetch_site=headers.get(b"sec-fetch-site", b"-").decode("latin-1"))
                if json_mode == "block":
                    await _forbid(403, "Forbidden", False)(scope, receive, send)
                    return

        if mode == "block" and (
            _tracker.pages_distinct(key, now, window) >= page_limit
            or _tracker.arenas_distinct(key, now) >= arena_limit
        ):
            await _forbid(429, "Too many pages requested. Try again later.", True)(scope, receive, send)
            return

        async def send_counting(message: Message) -> None:
            if mode != "off" and message["type"] == "http.response.start" and message.get("status") == 200:
                content_type = next((v for k, v in message.get("headers") or [] if k.lower() == b"content-type"), b"")
                t = time.monotonic()
                if content_type.startswith(b"text/html") and is_page:
                    distinct = _tracker.record_page(key, path, t, window)
                    if distinct >= page_limit:
                        flag("pages_burst", window, distinct_pages=distinct, window_s=int(window))
                    if _ARENA_PAGE_RE.match(path):
                        arenas = _tracker.record_arena(key, "page", path, t)
                        if arenas >= arena_limit:
                            flag("arenas_daily", _DAY_SEC, distinct_arenas=arenas)
                elif json_match and content_type.startswith(b"application/json"):
                    arenas = _tracker.record_arena(key, "json", json_match.group(1), t)
                    if arenas >= arena_limit:
                        flag("arenas_daily", _DAY_SEC, distinct_arenas=arenas)
            await send(message)

        await self.app(scope, receive, send_counting)
