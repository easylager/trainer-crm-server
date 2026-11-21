"""Защитные заголовки публичного сайта.

Всем ответам — HSTS (только https), nosniff и Referrer-Policy. HTML вне
``/webapp/`` — ещё и ``frame-ancestors``: чужой сайт не встроит страницу во
фрейм, а Telegram Web (страница места открывается и как Mini App) — встроит.
Яндекс Метрика тоже в списке: Вебвизор и карта кликов открывают страницу
в своём фрейме (иначе «Невозможно воспроизвести посещение»). Домены —
из справки Яндекса (install-counter-csp, frame-ancestors) плюс ``*.webvisor.com``.
``/webapp/`` не трогаем: у Mini App свои правила (SEC-G2), фрейм Telegram там
обязателен, а полный CSP требует постраничной политики.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

HSTS = "max-age=31536000"
# Сайт не просит камеру, микрофон, оплату и USB; геолокацию не трогаем (ближайший каток).
PERMISSIONS_POLICY = "camera=(), microphone=(), payment=(), usb=()"
# Telegram + Яндекс Метрика (Вебвизор / карта кликов). Список Метрики:
# https://yandex.ru/support/metrica/ru/code/install-counter-csp
FRAME_ANCESTORS = (
    "frame-ancestors 'self' "
    "https://web.telegram.org https://*.telegram.org "
    "https://metrika.yandex.ru https://metrika.yandex.by https://metrika.yandex.com "
    "https://metrika.yandex.com.tr https://metrika.yandex.kz https://metrika.yandex.uz "
    "https://metrika.yandex https://metrika.ya.ru "
    "https://metrica.yandex.ru https://metrica.yandex.by https://metrica.yandex.com "
    "https://metrica.yandex.com.tr https://metrica.yandex.kz https://metrica.yandex "
    "https://metrica.ya.ru "
    "https://metr.yandex.ru https://metr.yandex.by https://metr.yandex.com "
    "https://metr.yandex.com.tr https://metr.yandex.kz "
    "https://analytics.yandex.ru https://analytics.yandex.by https://analytics.yandex.com "
    "https://analytics.yandex.com.tr https://analytics.yandex.kz "
    "https://*.webvisor.com"
)

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
                if not is_webapp and b"permissions-policy" not in present:
                    headers.append((b"permissions-policy", PERMISSIONS_POLICY.encode()))
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
