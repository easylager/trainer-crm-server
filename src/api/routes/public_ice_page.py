"""
Старый адрес «Лёд сегодня в городе» (TASK-096, DEC-004) и его og-картинка.

С TASK-266 страница — постоянная переадресация на список ``/c/{город}?t=ice&w=today``:
ссылки из чатов живут, в поиске один адрес. Роутер без префикса ``/api`` и без авторизации:
его открывает человек по ссылке из чата.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.application.ice_city_day import (
    aliased_city_slug,
    get_city_ice_day,
    ice_city_day_page_url,
    list_public_cities,
    render_unknown_city_html,
    resolve_city_by_ref,
)
from src.application.ice_city_day_og import render_ice_city_day_og
from src.application.png_render_cache import render_png_cached
from src.shared.config import Settings
router = APIRouter(tags=["public-ice-share"])

_OG_CACHE = {"Cache-Control": "public, max-age=900"}


def _public_base() -> str:
    return (Settings().webapp_base_url or "").strip().rstrip("/")


async def _load(session: AsyncSession, city_ref: str):
    city = await resolve_city_by_ref(session, city_ref)
    if city is None:
        return None, None
    day = await get_city_ice_day(session, city_id=int(city["id"]))
    return city, day


@router.get("/ice/{city_ref}/today", response_class=HTMLResponse)
async def ice_city_day_page(
    city_ref: str,
    session: AsyncSession = Depends(get_session),
):
    """Старый адрес «Лёд сегодня» (TASK-266): навсегда на список «Покататься → Сегодня».

    Одна ссылка на одну вещь: поиск переносит вес на список, старые ссылки из чатов не ломаются.
    По id, по старому slug и по канону — один переход сразу на канонический список.
    """
    city = await resolve_city_by_ref(session, city_ref)
    if city is not None:
        return RedirectResponse(url=ice_city_day_page_url(base_url="", city_name=str(city["name"])), status_code=301)
    alias = await aliased_city_slug(session, city_ref)
    if alias:
        return RedirectResponse(url=f"/c/{alias}?t=ice&w=today", status_code=301)
    base = _public_base()
    home = f"{base}/" if base else "/"
    cities = await list_public_cities(session)
    return HTMLResponse(render_unknown_city_html(cities, home=home), status_code=404)


@router.api_route("/ice/{city_ref}/today/og.png", methods=["GET", "HEAD"])
async def ice_city_day_og(
    city_ref: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """og:image для страницы выше. Рисуется на лету из той же выборки — кэша на диске нет."""
    city, day = await _load(session, city_ref)
    if city is None or day is None:
        return Response(status_code=404)
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
