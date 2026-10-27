"""Страницы ошибок для людей: браузеру — оформленная 404, API и скриптам — прежний JSON.

Код ответа остаётся настоящим 404/405: «мягкая 404» (страница с кодом 200) портит индексацию.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_PAGE_PATH = Path(__file__).resolve().parent.parent.parent / "static" / "landing" / "404.html"
_NO_HTML_PREFIXES = ("/api/", "/webapp/", "/static/")
_page_cache: str | None = None


def _page() -> str:
    global _page_cache
    if _page_cache is None:
        _page_cache = _PAGE_PATH.read_text(encoding="utf-8")
    return _page_cache


def _wants_html_page(request: Request) -> bool:
    if request.url.path.startswith(_NO_HTML_PREFIXES):
        return False
    return "text/html" in request.headers.get("accept", "").lower()


async def site_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code in (404, 405) and _wants_html_page(request):
        return HTMLResponse(_page(), status_code=exc.status_code, headers=exc.headers)
    return await http_exception_handler(request, exc)
