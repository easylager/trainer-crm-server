"""``www.glideclub.by`` → ``glideclub.by``: один адрес сайта для людей и поисковиков.

Railway отдаёт на www тот же сервис, что и на основной домен, и сам не
перенаправляет. Без редиректа в индексе окажутся два одинаковых сайта.
Путь и query сохраняются. GET/HEAD — 301, остальные методы — 308, чтобы не
потерять метод и тело запроса.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

APEX_HOST = "glideclub.by"
WWW_HOST = f"www.{APEX_HOST}"


def _request_host(scope: Scope) -> str:
    """Хост из заголовков: за прокси сначала X-Forwarded-Host, затем Host; без порта."""
    forwarded = host = ""
    for name, value in scope.get("headers") or []:
        if name == b"x-forwarded-host":
            forwarded = value.decode("latin-1")
        elif name == b"host":
            host = value.decode("latin-1")
    raw = (forwarded or host).split(",")[0].strip().lower()
    return raw.rsplit(":", 1)[0] if ":" in raw else raw


class WwwRedirectMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or _request_host(scope) != WWW_HOST:
            await self.app(scope, receive, send)
            return
        path = scope.get("raw_path") or scope.get("path", "/").encode()
        location = f"https://{APEX_HOST}{path.decode('latin-1') or '/'}"
        query = scope.get("query_string") or b""
        if query:
            location += "?" + query.decode("latin-1")
        status = b"301" if scope.get("method") in ("GET", "HEAD") else b"308"
        await send(
            {
                "type": "http.response.start",
                "status": int(status),
                "headers": [(b"location", location.encode("latin-1")), (b"content-length", b"0")],
            }
        )
        await send({"type": "http.response.body", "body": b""})
