"""
Маркетинговый вход в каталог: ``/go``, ``/go/<источник>``, ``/go/<источник>/<город>`` (TASK-146).

Ссылка для постов, сторис, листовок и QR. Человек переходит → попадает в Telegram:
с коротким именем мини-аппа — сразу в каталог (``startapp``), без него — в бота, который
отвечает одной кнопкой «Каталог». Город в ссылке — каталог этого города; без города
каталог сам спросит геолокацию и покажет то, что рядом.

Ссылка на нашем домене, а не на ``t.me`` напрямую, ради двух вещей:
* **учёт** — каждый переход пишется в ``catalog_entry_clicks`` с меткой источника,
  поэтому видно, какой канал реально приводит людей (а не «кажется, инста работает»);
* **устойчивость** — сменится бот или имя мини-аппа, напечатанные QR останутся живыми.

Кто перешёл, не храним: источник, город, куда увели, хост реферера.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.application.ice_city_day import resolve_city_by_ref
from src.application.place_links import CATALOG_START_ANY, catalog_start_param, telegram_open_link
from src.shared.config import Settings

router = APIRouter(tags=["catalog-entry"])

_SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def normalize_source(raw: str | None) -> str:
    """«Insta» → «insta»; мусор и пустое — «other» и «direct», а не ошибка: ссылка обязана открыться."""
    value = (raw or "").strip().lower()
    if not value:
        return "direct"
    return value if _SOURCE_RE.match(value) else "other"


async def _record(session: AsyncSession, *, source: str, city_id: int | None, target: str, referer: str | None) -> None:
    host = (urlparse(referer).hostname or "")[:120] if referer else None
    try:
        await session.execute(
            text("INSERT INTO catalog_entry_clicks (source, city_id, target, referer_host) " "VALUES (:s, :c, :t, :h)"),
            {"s": source, "c": city_id, "t": target, "h": host or None},
        )
        await session.commit()
    except Exception:  # noqa: BLE001 — сбой учёта не должен ломать сам переход
        await session.rollback()


async def _go(request: Request, session: AsyncSession, source: str | None, city_ref: str | None):
    settings = Settings()
    src = normalize_source(source)
    city_id: int | None = None
    if city_ref:
        city = await resolve_city_by_ref(session, city_ref)
        city_id = int(city["id"]) if city else None
    start = catalog_start_param(city_id) if city_id else CATALOG_START_ANY
    link = telegram_open_link(
        client_bot_username=settings.client_bot_username,
        mini_app_short_name=settings.client_mini_app_short_name,
        main_mini_app=settings.client_bot_main_mini_app,
        start_param=start,
    )
    if link:
        target = "startapp" if "startapp=" in link else "bot"
    else:
        # Бот не настроен — не тупик: веб-каталог открывается и так.
        base = (settings.webapp_base_url or "").rstrip("/")
        link = f"{base}/webapp/ice" + (f"?city_id={city_id}" if city_id else "")
        target = "web"
    await _record(session, source=src, city_id=city_id, target=target, referer=request.headers.get("referer"))
    # 302, а не 301: каждый переход должен дойти до сервера и попасть в учёт.
    return RedirectResponse(url=link, status_code=302, headers={"Cache-Control": "no-store"})


@router.get("/go")
async def go_catalog(request: Request, session: AsyncSession = Depends(get_session)):
    return await _go(request, session, None, None)


@router.get("/go/{source}")
async def go_catalog_source(source: str, request: Request, session: AsyncSession = Depends(get_session)):
    return await _go(request, session, source, None)


@router.get("/go/{source}/{city_ref}")
async def go_catalog_city(source: str, city_ref: str, request: Request, session: AsyncSession = Depends(get_session)):
    return await _go(request, session, source, city_ref)
