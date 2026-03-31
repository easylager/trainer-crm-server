"""
HTTP rate limiting (per client IP) and Content-Length body caps for /api (Epic D).
Webhooks are excluded from rate limit; multipart uploads use a larger cap when Content-Length is present.
"""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.shared.config import Settings
from src.shared.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

_limiters: dict[str, RateLimiter] | None = None


def reset_http_limiters_for_tests() -> None:
    """Clear cached limiters so the next request rebuilds from current env (tests only)."""
    global _limiters
    _limiters = None


def client_ip_from_request(request: Request) -> str:
    """Client IP: first X-Forwarded-For hop when behind a proxy, else request.client."""
    forwarded = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if forwarded:
        part = forwarded.split(",")[0].strip()
        if part:
            return part
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit_bucket_for_path(path: str) -> str:
    """
    Bucket for sliding-window limiter, or 'skip' when no API rate limit applies.
    """
    if not path.startswith("/api/"):
        return "skip"
    if path.startswith("/api/webhooks"):
        return "skip"
    if path.startswith("/api/public"):
        return "public"
    if path.startswith("/api/webapp"):
        return "webapp"
    if path.startswith("/api/upload") or "/upload/" in path:
        return "upload"
    return "default"


def _get_limiters() -> dict[str, RateLimiter]:
    global _limiters
    if _limiters is None:
        s = Settings()
        _limiters = {
            "public": RateLimiter(s.api_rate_limit_public_max_requests, s.api_rate_limit_public_window_sec),
            "webapp": RateLimiter(s.api_rate_limit_webapp_max_requests, s.api_rate_limit_webapp_window_sec),
            "upload": RateLimiter(s.api_rate_limit_upload_max_requests, s.api_rate_limit_upload_window_sec),
            "default": RateLimiter(s.api_rate_limit_default_max_requests, s.api_rate_limit_default_window_sec),
        }
    return _limiters


class ApiRateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limit per IP for /api/* (except /api/webhooks)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)
        settings = Settings()
        if not settings.api_rate_limit_enabled:
            return await call_next(request)
        path = request.url.path
        bucket = rate_limit_bucket_for_path(path)
        if bucket == "skip":
            return await call_next(request)
        ip = client_ip_from_request(request)
        limiter = _get_limiters()[bucket]
        if not limiter.check_and_consume(ip):
            retry = max(1, int(limiter.window_sec))
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(retry)},
            )
        return await call_next(request)


def max_body_bytes_for_path(path: str) -> int:
    """Upper bound when Content-Length is set; larger routes for uploads and webhooks."""
    s = Settings()
    if path.startswith("/api/webhooks"):
        return s.api_max_body_bytes_webhook
    if path.startswith("/api/upload") or path.rstrip("/").endswith("/trainer/photos"):
        return s.api_max_body_bytes_upload
    return s.api_max_body_bytes_default


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """Reject oversized bodies early when Content-Length is present (413)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        cl = request.headers.get("content-length")
        if not cl:
            # Chunked or missing length: cannot pre-check; rely on reverse proxy / server limits in prod.
            return await call_next(request)
        try:
            n = int(cl)
        except ValueError:
            return await call_next(request)
        max_bytes = max_body_bytes_for_path(path)
        if n > max_bytes:
            return JSONResponse(status_code=413, content={"detail": "Payload too large"})
        return await call_next(request)
