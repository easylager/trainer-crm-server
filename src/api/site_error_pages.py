"""Страницы ошибок для людей: браузеру — оформленная 404, API и скриптам — прежний JSON.

Код ответа остаётся настоящим 404/405: «мягкая 404» (страница с кодом 200) портит индексацию.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_PAGE_PATH = Path(__file__).resolve().parent.parent.parent / "static" / "landing" / "404.html"
_NO_HTML_PREFIXES = ("/api/", "/webapp/", "/static/")
# Старые адреса городов без префикса: /mozyr -> /c/mozyr (в поиске они ещё лежат с прошлых обходов).
_LEGACY_CITY_PATH = re.compile(r"^/([a-z][a-z0-9-]*)/?$")
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


async def _legacy_city_redirect(request: Request) -> RedirectResponse | None:
    """301 со старого ``/{город}`` на ``/c/{город}``, если такой публичный город есть."""
    match = _LEGACY_CITY_PATH.match(request.url.path)
    if match is None or request.method not in ("GET", "HEAD"):
        return None
    try:
        from src.application.ice_city_day import city_slug, resolve_city_by_ref
        from src.infrastructure.db import async_session_factory

        async with async_session_factory() as session:
            city = await resolve_city_by_ref(session, match.group(1))
    except Exception:  # noqa: BLE001 — любая сбойная проверка = обычная 404, не 500
        return None
    if city is None:
        return None
    query = request.url.query
    return RedirectResponse(url=f"/c/{city_slug(str(city['name']))}" + (f"?{query}" if query else ""), status_code=301)


async def site_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        redirect = await _legacy_city_redirect(request)
        if redirect is not None:
            return redirect
    if exc.status_code in (404, 405) and _wants_html_page(request):
        return HTMLResponse(_page(), status_code=exc.status_code, headers=exc.headers)
    return await http_exception_handler(request, exc)
