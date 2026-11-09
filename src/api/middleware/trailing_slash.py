"""Убираем завершающий «/» у публичных URL: один канонический адрес для индекса."""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from src.shared.config import Settings

_SKIP_PREFIXES = ("/api/", "/health/", "/webapp/", "/static/", "/docs", "/redoc", "/openapi.json")


def _strip_port(host: str) -> str:
    return host.rsplit(":", 1)[0] if ":" in host else host


def _request_host(scope: Scope) -> str:
    forwarded = host = ""
    for name, value in scope.get("headers") or []:
        if name == b"x-forwarded-host":
            forwarded = value.decode("latin-1")
        elif name == b"host":
            host = value.decode("latin-1")
    raw = (forwarded or host).split(",")[0].strip().lower()
    return _strip_port(raw)


def _request_proto(scope: Scope) -> str:
    for name, value in scope.get("headers") or []:
        if name == b"x-forwarded-proto":
            return value.decode("latin-1").split(",")[0].strip().lower()
    return str(scope.get("scheme") or "http").lower()


def _redirect_location(scope: Scope, path: str) -> str:
    query = scope.get("query_string") or b""
    suffix = ("?" + query.decode("latin-1")) if query else ""
    base = (Settings().webapp_base_url or "").strip().rstrip("/")
    if base.startswith("http"):
        return f"{base}{path}{suffix}"
    host = _request_host(scope) or "localhost"
    proto = _request_proto(scope)
    if proto != "https" and host.endswith("glideclub.by"):
        proto = "https"
    return f"{proto}://{host}{path}{suffix}"


class TrailingSlashMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in ("GET", "HEAD"):
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or "/"
        if len(path) <= 1 or not path.endswith("/"):
            await self.app(scope, receive, send)
            return
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return
        location = _redirect_location(scope, path.rstrip("/") or "/")
        await send(
            {
                "type": "http.response.start",
                "status": 301,
                "headers": [(b"location", location.encode("latin-1")), (b"content-length", b"0")],
            }
        )
        await send({"type": "http.response.body", "body": b""})
