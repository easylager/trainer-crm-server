"""Страница создания приглашения ``/zovi`` (TASK-234).

Посадочная из Threads: её можно индексировать. Картинку og сделает TASK-238,
поэтому ``og:image`` здесь нет.
"""

from __future__ import annotations

import html as html_lib
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.shared.config import Settings
from src.shared.html_template import fill_placeholders

router = APIRouter(tags=["zovi-create"])

_TEMPLATE_PATH = Path(__file__).resolve().parents[3] / "static" / "share" / "zovi-create.html"
_PAGE_CACHE = {"Cache-Control": "private, no-store"}

_OG_TITLE = "Позови на каток"
_OG_DESCRIPTION = "Открытка-приглашение на настоящий сеанс. Кнопка «Нет» не работает."


def _esc(value: str) -> str:
    return html_lib.escape(value, quote=True)


def render_zovi_create_page(*, canonical_url: str) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return fill_placeholders(
        template,
        {
            "__LANG__": "ru-BY",
            "__OG_LOCALE__": "ru_BY",
            "__OG_TITLE__": _esc(_OG_TITLE),
            "__OG_DESCRIPTION__": _esc(_OG_DESCRIPTION),
            "__CANONICAL__": _esc(canonical_url),
            "__ROBOTS__": "index, follow",
            "__ASSET_V__": "10",
        },
    )


def _canonical(request: Request) -> str:
    base = (Settings().webapp_base_url or "").strip().rstrip("/")
    if base:
        return f"{base}/zovi"
    return str(request.base_url).rstrip("/") + "/zovi"


@router.get("/zovi", response_class=HTMLResponse)
async def zovi_create_page(request: Request) -> HTMLResponse:
    html = render_zovi_create_page(canonical_url=_canonical(request))
    return HTMLResponse(content=html, media_type="text/html", headers=_PAGE_CACHE)
