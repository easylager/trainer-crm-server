"""
Публичная страница «Лёд сегодня в городе» — шеринг-артефакт №1 эпика (TASK-096, DEC-004).

Отдельный модуль и отдельный роутер без префикса ``/api``: это не API, а страница,
которую открывает человек по ссылке из чата. Авторизации нет **осознанно** — требовать
Telegram у получателя пересланной ссылки значит убить пересылку на первом же шаге.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.application.ice_city_day import (
    city_slug,
    get_city_ice_day,
    resolve_city_by_ref,
)
from src.application.ice_city_day_og import render_ice_city_day_og
from src.application.ice_city_day_page import ice_city_day_paths, render_ice_city_day_page
from src.application.catalog_consumer_events import record_public_page_view
from src.application.png_render_cache import render_png_cached
from src.application.place_links import catalog_start_param, public_telegram_cta_url
from src.shared.config import Settings

router = APIRouter(tags=["public-ice-share"])

# Страница живая: её открывают спустя часы после пересылки, и к этому моменту утренние
# сеансы уже прошли. Короткий кэш достаточен, чтобы пережить всплеск от одного репоста,
# и слишком короткий, чтобы показать вчерашнее расписание.
_PAGE_CACHE = {"Cache-Control": "public, max-age=300"}
_OG_CACHE = {"Cache-Control": "public, max-age=900"}


def _public_base() -> str:
    return (Settings().webapp_base_url or "").strip().rstrip("/")


def _cta_url(city_id: int) -> str | None:
    """В каталог этого города на сегодня, с теми же фильтрами, что у страницы."""
    base = _public_base()
    return public_telegram_cta_url(
        base,
        start_param=catalog_start_param(int(city_id), "skate", "today"),
        surface="ice_city_day",
        city_id=int(city_id),
    )


async def _load(session: AsyncSession, city_ref: str):
    city = await resolve_city_by_ref(session, city_ref)
    if city is None:
        raise HTTPException(status_code=404, detail="City not found")
    day = await get_city_ice_day(session, city_id=int(city["id"]))
    return city, day


@router.get("/ice/{city_ref}/today", response_class=HTMLResponse)
async def ice_city_day_page(
    city_ref: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Расписание массовых катаний города на день + og-теги для превью в Telegram."""
    city, day = await _load(session, city_ref)
    city_name = str(city["name"])

    canonical_path, og_path = ice_city_day_paths(city_name)
    if city_ref.strip().lower() != city_slug(city_name):
        # Пришли по id (`/ice/12/today`) — уводим на канонический slug, чтобы в чатах
        # ходила одна ссылка, а не две на одно и то же.
        return RedirectResponse(url=canonical_path, status_code=301)

    base = _public_base()
    html = render_ice_city_day_page(
        city_name=city_name,
        day=day,
        canonical_url=f"{base}{canonical_path}" if base else canonical_path,
        og_image_url=f"{base}{og_path}" if base else og_path,
        cta_url=_cta_url(int(city["id"])),
    )
    await record_public_page_view(
        session,
        request,
        surface="ice_city_day",
        city_id=int(city["id"]),
    )
    return HTMLResponse(content=html, media_type="text/html", headers=_PAGE_CACHE)


@router.get("/ice/{city_ref}/today/og.png")
async def ice_city_day_og(
    city_ref: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """og:image для страницы выше. Рисуется на лету из той же выборки — кэша на диске нет."""
    city, day = await _load(session, city_ref)
    # Рендер PIL — в threadpool и через LRU: параметры запроса картинку не меняют (query не читаем),
    # ключ — город + сама выборка, так что обновление расписания сбрасывает кэш само.
    png = await render_png_cached(
        "ice_og",
        {"city_id": int(city["id"]), "city": str(city["name"])},
        day,
        render_ice_city_day_og,
        city_name=str(city["name"]),
        day=day,
    )
    return Response(content=png, media_type="image/png", headers=_OG_CACHE)
