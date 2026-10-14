"""Защитные заголовки публичного сайта.

Всем ответам — HSTS (только https), nosniff и Referrer-Policy. HTML вне
``/webapp/`` — ещё и ``frame-ancestors``: чужой сайт не встроит страницу во
фрейм, а Telegram Web (страница места открывается и как Mini App) — встроит.
``/webapp/`` не трогаем: у Mini App свои правила (SEC-G2), фрейм Telegram там
обязателен, а полный CSP требует постраничной политики.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

HSTS = "max-age=31536000"
FRAME_ANCESTORS = "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"

_ALL: tuple[tuple[bytes, bytes], ...] = (
    (b"strict-transport-security", HSTS.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_webapp = str(scope.get("path") or "").startswith("/webapp/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {name.lower() for name, _ in headers}
                for name, value in _ALL:
                    if name not in present:
                        headers.append((name, value))
                content_type = next((v for k, v in headers if k.lower() == b"content-type"), b"")
                if (
                    not is_webapp
                    and content_type.startswith(b"text/html")
                    and b"content-security-policy" not in present
                ):
                    headers.append((b"content-security-policy", FRAME_ANCESTORS.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
