"""
HTTP rate limiting (per client IP) and Content-Length body caps for /api (Epic D).
The public per-IP bucket also covers the marketing redirect at /go. TASK-190: public HTML pages
(/p/ /c/ /ice/ /r/) and PNG renders (og.png/story.png) have their own buckets.
Webhooks are excluded from rate limit; multipart uploads use a larger cap when Content-Length is present.
"""
from __future__ import annotations

import ipaddress
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.shared.client_ip import trusted_client_ip
from src.shared.config import Settings
from src.shared.ua_class import UA_HUMAN, classify_user_agent
from src.shared.rate_limit import RateLimiter

logger = logging.getLogger(__name__)


def _mask_client_ip(ip: str) -> str:
    """Log-safe IP: IPv4 /16, IPv6 /48. Short forms (2a02::1) are not returned raw."""
    if not ip or ip == "unknown":
        return ip
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return "?"
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    prefix = 16 if addr.version == 4 else 48
    net = ipaddress.ip_network(f"{addr}/{prefix}", strict=False)
    return f"{net.network_address}/{net.prefixlen}"


_limiters: dict[str, RateLimiter] | None = None
_rate_limit_warn_at: dict[tuple[str, str], float] = {}
_WARN_CACHE_MAX = 256
_WARN_STALE_SEC = 600.0


def reset_http_limiters_for_tests() -> None:
    """Clear cached limiters so the next request rebuilds from current env (tests only)."""
    global _limiters
    _limiters = None
    _rate_limit_warn_at.clear()


def client_ip_from_request(request: Request) -> str:
    """Client IP (see :mod:`src.shared.client_ip`): leftmost public XFF entry (Railway strips client XFF), X-Real-IP, socket."""
    ip = trusted_client_ip(
        request.headers,
        request.client.host if request.client else None,
        strategy=Settings().client_ip_strategy,
        hops=Settings().trusted_proxy_hops,
    )
    return ip or "unknown"


_PAGE_PREFIXES = ("/p/", "/c/", "/ice/", "/r/")


def rate_limit_bucket_for_path(path: str) -> str:
    """
    Bucket for sliding-window limiter, or 'skip' when no API rate limit applies.
    """
    if path.startswith(_PAGE_PREFIXES):
        # og.png / story.png: PIL-рендер дороже HTML — свой, более узкий бакет.
        return "image" if path.endswith((".png", "/og.png", "/story.png")) else "page"
    if path == "/go" or path.startswith("/go/"):
        return "public"
    if not path.startswith("/api/"):
        return "skip"
    if path.startswith("/api/webhooks"):
        return "skip"
    if path == "/api/public/ice/map-config":
        return "skip"
    if path.startswith("/api/public/photos/"):
        return "photo"
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
            "photo": RateLimiter(s.api_rate_limit_photo_max_requests, s.api_rate_limit_photo_window_sec),
            "webapp": RateLimiter(s.api_rate_limit_webapp_max_requests, s.api_rate_limit_webapp_window_sec),
            "upload": RateLimiter(s.api_rate_limit_upload_max_requests, s.api_rate_limit_upload_window_sec),
            "default": RateLimiter(s.api_rate_limit_default_max_requests, s.api_rate_limit_default_window_sec),
            "page": RateLimiter(s.api_rate_limit_page_max_requests, s.api_rate_limit_page_window_sec),
            "image": RateLimiter(s.api_rate_limit_image_max_requests, s.api_rate_limit_image_window_sec),
            # Превью-боты и краулеры: общие IP (Telegram), поэтому лимит широкий — но не бесконечный,
            # иначе подделка UA снимала бы лимит целиком.
            "bot": RateLimiter(s.api_rate_limit_bot_max_requests, s.api_rate_limit_bot_window_sec),
        }
    return _limiters


def _prune_rate_limit_warns(now: float) -> None:
    cutoff = now - _WARN_STALE_SEC
    stale = [key for key, ts in _rate_limit_warn_at.items() if ts < cutoff]
    for key in stale:
        del _rate_limit_warn_at[key]
    overflow = len(_rate_limit_warn_at) - _WARN_CACHE_MAX
    if overflow > 0:
        oldest = sorted(_rate_limit_warn_at, key=_rate_limit_warn_at.get)[:overflow]
        for key in oldest:
            del _rate_limit_warn_at[key]


def _log_rate_limit_once(bucket: str, path: str, ip: str, window_sec: float) -> None:
    """One warning per (bucket, masked IP) per limiter window — a burst of 429s must not flood logs."""
    masked = _mask_client_ip(ip)
    key = (bucket, masked)
    now = time.monotonic()
    _prune_rate_limit_warns(now)
    last = _rate_limit_warn_at.get(key)
    if last is not None and now - last < max(window_sec, 1.0):
        return
    _rate_limit_warn_at[key] = now
    logger.warning("rate limit exceeded bucket=%s path=%s ip=%s", bucket, path, masked)


class ApiRateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limit per IP for /api/* and /go (except /api/webhooks)."""

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
        if bucket in ("page", "image") and classify_user_agent(request.headers.get("user-agent")) != UA_HUMAN:
            bucket = "bot"
        limiter = _get_limiters()[bucket]
        if not limiter.check_and_consume(ip):
            _log_rate_limit_once(bucket, path, ip, float(limiter.window_sec))
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
    normalized = path.rstrip("/")
    if (
        path.startswith("/api/upload")
        or normalized.endswith("/trainer/photos")
        or ("/admin/arenas/" in path and normalized.endswith("/photos"))
    ):
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
