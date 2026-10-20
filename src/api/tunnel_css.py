"""Вшивает CSS и локальные скрипты мини-приложения в HTML на туннеле.

Телефон в WebView Телеграма часть подресурсов просто не запрашивает: стили
из `/static/…` и скрипты в конце страницы (экран матча остаётся скелетом).
Внешние `https://` ссылки остаются. На обычном домене файлы по-прежнему
отдельные и кэшируются.
"""

from __future__ import annotations

import re
from pathlib import Path

from starlette.types import ASGIApp, Receive, Scope, Send

_ROOT = Path(__file__).resolve().parent.parent.parent
_WEBAPP = _ROOT / "static" / "webapp"
_SHARED = _ROOT / "static" / "shared"

_LINK_RE = re.compile(
    r'<link\s+rel="stylesheet"\s+href="(?P<href>[^"]+)"\s*/?>',
    re.IGNORECASE,
)
_STYLE_CLOSE_RE = re.compile(r"</style", re.IGNORECASE)
_SCRIPT_RE = re.compile(
    r'<script(?P<attrs>[^>]*?)\ssrc="(?P<href>[^"]+)"(?P<after>[^>]*)></script>',
    re.IGNORECASE,
)
_SCRIPT_CLOSE_RE = re.compile(r"</script", re.IGNORECASE)


# Встроенный скрипт не умеет defer, поэтому его код выполняется в DOMContentLoaded. Но defer-скрипты
# сами вешают обработчики на DOMContentLoaded (каталог тренера так запускает загрузку), а подписка,
# сделанная во время этого события, уже не сработает — экран висел на «Загрузка». Пока такой скрипт
# выполняется, его подписки на DOMContentLoaded копятся и запускаются после всех defer-скриптов.
_DEFER_OPEN = (
    "document.addEventListener('DOMContentLoaded',function(){"
    "var __add=document.addEventListener;"
    "document.addEventListener=function(t,f,o){if(t==='DOMContentLoaded'&&typeof f==='function')"
    "{(window.__tunnelDcl=window.__tunnelDcl||[]).push(f);return;}return __add.call(document,t,f,o);};"
    "try{\n"
)
_DEFER_CLOSE = "\n}finally{document.addEventListener=__add;}});"
_DEFER_FLUSH = (
    "document.addEventListener('DOMContentLoaded',function(){"
    "(window.__tunnelDcl||[]).splice(0).forEach(function(f){"
    "try{f.call(document,new Event('DOMContentLoaded'));}catch(e){setTimeout(function(){throw e;});}});});"
)


def tunnel_host(host: str) -> bool:
    name = host.split(":")[0].lower()
    return "ngrok" in name or name.endswith("trycloudflare.com")


def _css_file(href: str) -> Path | None:
    path = href.split("?", 1)[0].strip()
    if path.startswith(("http://", "https://", "//")):
        return None
    if path.startswith("/static/shared/"):
        name, root = path[len("/static/shared/") :], _SHARED
    elif path.startswith("/static/webapp/"):
        name, root = path[len("/static/webapp/") :], _WEBAPP
    elif path.startswith("/webapp/"):
        name, root = path[len("/webapp/") :], _WEBAPP
    elif "/" not in path:
        name, root = path, _WEBAPP
    else:
        return None
    if not name.endswith(".css") or "/" in name or ".." in name:
        return None
    file = root / name
    return file if file.is_file() else None


def _js_file(href: str) -> Path | None:
    path = href.split("?", 1)[0].strip()
    if path.startswith(("http://", "https://", "//")):
        return None
    if path.startswith("/static/webapp/"):
        name, root = path[len("/static/webapp/") :], _WEBAPP
    elif path.startswith("/webapp/"):
        name, root = path[len("/webapp/") :], _WEBAPP
    elif "/" not in path:
        name, root = path, _WEBAPP
    else:
        return None
    if not name.endswith(".js") or "/" in name or ".." in name:
        return None
    file = root / name
    return file if file.is_file() else None


def inline_tunnel_styles(html: str) -> str:
    def repl_css(match: re.Match[str]) -> str:
        file = _css_file(match.group("href"))
        if file is None:
            return match.group(0)
        css = _STYLE_CLOSE_RE.sub(lambda _m: "<\\/style", file.read_text(encoding="utf-8"))
        return f"<style>{css}</style>"

    def repl_js(match: re.Match[str]) -> str:
        file = _js_file(match.group("href"))
        if file is None:
            return match.group(0)
        js = _SCRIPT_CLOSE_RE.sub(lambda _m: "<\\/script", file.read_text(encoding="utf-8"))
        attrs = f"{match.group('attrs')} {match.group('after')}"
        if re.search(r"\bdefer\b", attrs, re.IGNORECASE):
            deferred[0] += 1
            js = _DEFER_OPEN + js + _DEFER_CLOSE
        return f"<script>{js}</script>"

    deferred = [0]
    out = _SCRIPT_RE.sub(repl_js, _LINK_RE.sub(repl_css, html))
    if not deferred[0]:
        return out
    # Сбор подписок — последним обработчиком DOMContentLoaded, как браузер после всех defer-скриптов.
    flush = f"<script>{_DEFER_FLUSH}</script>"
    close = out.lower().rfind("</body>")
    return out[:close] + flush + out[close:] if close >= 0 else out + flush


def _host_header(scope: Scope) -> str:
    for key, value in scope.get("headers") or []:
        if key == b"host":
            return value.decode("latin1")
    return ""


def _content_type(headers: list[tuple[bytes, bytes]]) -> str:
    for key, value in headers:
        if key.lower() == b"content-type":
            return value.decode("latin1")
    return ""


def _is_html_document(path: str) -> bool:
    if not path.startswith("/webapp"):
        return False
    name = path.rsplit("/", 1)[-1]
    if "." in name and not name.endswith(".html"):
        return False
    return True


class TunnelCssMiddleware:
    """Только HTML `/webapp` на хосте ngrok или trycloudflare."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_html_document(scope.get("path") or ""):
            await self.app(scope, receive, send)
            return
        if not tunnel_host(_host_header(scope)):
            await self.app(scope, receive, send)
            return

        start_message: dict | None = None
        chunks: list[bytes] = []

        async def capture(message: dict) -> None:
            nonlocal start_message
            if message["type"] == "http.response.start":
                start_message = message
                return
            if message["type"] == "http.response.body":
                chunks.append(message.get("body") or b"")
                if message.get("more_body"):
                    return

        await self.app(scope, receive, capture)
        if start_message is None:
            return
        headers = list(start_message.get("headers") or [])
        body = b"".join(chunks)
        if start_message.get("status") == 200 and "text/html" in _content_type(headers):
            body = inline_tunnel_styles(body.decode("utf-8")).encode("utf-8")
            headers = [(k, v) for k, v in headers if k.lower() != b"content-length"]
            headers.append((b"content-length", str(len(body)).encode("ascii")))
        await send({**start_message, "headers": headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})
