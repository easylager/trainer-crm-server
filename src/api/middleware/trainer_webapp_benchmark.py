"""
Trainer Mini App + Web App shell (FastAPI): wall-clock timing for:

- ``kind=api`` — ``/api/webapp/trainer/*`` (JSON from hub, schedule, profile, …)
- ``kind=page`` — GET ``/webapp/...`` HTML entry points (trainer-home, schedule-editor, …)
- ``kind=asset`` — GET static ``/webapp/*`` and ``/static/webapp/*`` (.js, .css, fonts, images, …)

Grep logs for ``BENCH trainer_webapp`` (logger name is this module, e.g. ``src.api.middleware.trainer_webapp_benchmark``).
Env (on the **API** process only): ``TRAINER_WEBAPP_BENCHMARK_LOG``, ``TRAINER_WEBAPP_BENCHMARK_SLOW_MS``.
"""
from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.shared.config import Settings

# Use module logger so Uvicorn/root config shows the same lines as other app code (not a custom dot-logger).
bench_log = logging.getLogger(__name__)
bench_log.setLevel(logging.INFO)

# File extensions served as static Mini App assets (not HTML shells).
_STATIC_EXT = frozenset({
    "css",
    "js",
    "mjs",
    "svg",
    "woff2",
    "woff",
    "ttf",
    "ico",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "map",
})


def _filename_ext(path: str) -> str | None:
    base = path.rstrip("/").rsplit("/", 1)[-1]
    if "." not in base:
        return None
    return base.rsplit(".", 1)[-1].lower()


def _is_webapp_static_asset_path(path: str) -> bool:
    ext = _filename_ext(path)
    if ext is None or ext not in _STATIC_EXT:
        return False
    return path.startswith("/webapp/") or path.startswith("/static/webapp/")


def _bench_kind(request: Request) -> str | None:
    if request.method == "OPTIONS":
        return None
    path = request.url.path
    if path.startswith("/api/webapp/trainer"):
        return "api"
    if request.method != "GET":
        return None
    if _is_webapp_static_asset_path(path):
        return "asset"
    if path.startswith("/webapp/"):
        return "page"
    return None


class TrainerWebappBenchmarkMiddleware(BaseHTTPMiddleware):
    """Log duration for trainer API + Mini App HTML pages + shared static assets."""

    async def dispatch(self, request: Request, call_next) -> Response:
        kind = _bench_kind(request)
        if kind is None:
            return await call_next(request)
        s = Settings()
        full = s.trainer_webapp_benchmark_log
        slow_ms = s.trainer_webapp_benchmark_slow_ms
        if not full and slow_ms is None:
            return await call_next(request)

        t0 = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            slow = slow_ms is not None and elapsed_ms >= float(slow_ms)
            if full or slow:
                msg = (
                    f"BENCH trainer_webapp kind={kind} method={request.method} path={request.url.path} "
                    f"status={status_code} duration_ms={elapsed_ms:.1f} slow={1 if slow else 0}"
                )
                if slow and not full:
                    bench_log.warning(msg)
                else:
                    bench_log.info(msg)
