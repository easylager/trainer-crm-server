"""Сайт: «Зимой в <городе>» ``/c/{city}/zimoy`` и страница зимней точки ``/p/{city}/{slug}`` (TASK-343, волна 2).

Всё за ``SEASONAL_RINKS_ENABLED``: флаг выключен — страницы 404, как будто их нет. Страница точки
отдаётся из общего ``/p/{city}/{slug}`` (``maybe_winter_point_response``), чтобы у точки не было двух адресов.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.application import winter_public
from src.application.catalog_home_page import catalog_home_og_image_url
from src.application.ice_city_day import city_slug, resolve_city_by_ref
from src.application.place_links import place_path
from src.application.public_site_footer import render_site_footer_html
from src.application.public_web_cta import public_page_view_beacon_script
from src.application.winter_page import render_city_page, render_gone_page, render_point_page, winter_city_path
from src.shared.config import Settings
from src.shared.glide_city_cookie import apply_glide_city_cookie, glide_city_pin_script

router = APIRouter(tags=["winter-pages"])

# Статус на странице живёт минуты, не недели (O5): приватный кэш на 30 с, как у остальных публичных страниц.
PAGE_CACHE = {"Cache-Control": "private, max-age=30, stale-while-revalidate=120"}
NO_STORE = {"Cache-Control": "no-store"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _base() -> str:
    return (Settings().webapp_base_url or "").strip().rstrip("/")


def _enabled() -> bool:
    return bool(Settings().seasonal_rinks_enabled)


def _not_found() -> HTMLResponse:
    html = render_gone_page(city=None, name=None, list_href=None, home_href="/")
    return HTMLResponse(html.replace("Этой точки больше нет в зимнем каталоге", "Такой страницы нет"), status_code=404)


@router.api_route("/c/{city_ref}/zimoy", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def winter_city_page(city_ref: str, request: Request, session: AsyncSession = Depends(get_session)):
    if not _enabled():
        return _not_found()
    city = await resolve_city_by_ref(session, city_ref)
    if city is None:
        return _not_found()
    name = str(city["name"])
    if city_ref != city_slug(name):
        return RedirectResponse(url=winter_city_path(name), status_code=301)
    if request.method == "HEAD":
        return Response(status_code=200, headers=PAGE_CACHE)
    settings = Settings()
    data = await winter_public.list_points(session, int(city["id"]), now=_now())
    base = _base()
    html = render_city_page(
        city=city,
        data=data,
        base_url=base,
        ymaps_key=settings.yandex_maps_js_api_key,
        suggest_href=f"/suggest?city={int(city['id'])}",
        city_href=f"/c/{city_slug(name)}",
        beacon=public_page_view_beacon_script(surface="selection_page", city_id=int(city["id"])),
        city_pin=glide_city_pin_script(city_slug(name)),
        og_image=catalog_home_og_image_url(base),
    )
    response = HTMLResponse(content=html, headers=PAGE_CACHE)
    apply_glide_city_cookie(response, slug=city_slug(name))
    return response


async def maybe_winter_point_response(
    session: AsyncSession, request: Request, city: dict, arena_id: int, *, city_ref: str, slug: str
) -> Response | None:
    """Ответ для зимней точки или ``None`` — тогда ``/p/…`` отдаёт обычную страницу места."""
    if not _enabled():
        return None
    known = await winter_public.lookup_any(session, arena_id)
    if known is None or not known["own_page"]:
        return None
    name = str(city["name"])
    list_href = winter_city_path(name)
    if known["hidden"]:
        # 410, а не 404: адрес был, точку убрали. Человек видит объяснение и выход к соседним точкам.
        html = render_gone_page(city=city, name=known["name"], list_href=list_href, home_href=(_base() or "") + "/")
        return HTMLResponse(html, status_code=410, headers=NO_STORE)
    item = await winter_public.get_point(session, arena_id, now=_now())
    if item is None:
        return None
    if city_ref != city_slug(name) or slug != item["slug"]:
        q = request.url.query
        return RedirectResponse(url=place_path(city_name=name, slug=str(item["slug"])) + (f"?{q}" if q else ""), status_code=301)
    base = _base()
    # Токен отметки в HTML не кладём (страница кэшируется) — скрипт берёт его из no-store API.
    item.pop("mark_token", None)
    html = render_point_page(
        city=city,
        item=item,
        base_url=base,
        indexable=winter_public.is_indexable(item),
        list_href=list_href,
        suggest_href=f"/suggest?city={int(city['id'])}",
        beacon=public_page_view_beacon_script(surface="place_page", city_id=int(city["id"]), arena_id=int(item["id"])),
        city_pin=glide_city_pin_script(city_slug(name)),
        og_image=catalog_home_og_image_url(base),
    )
    response = HTMLResponse(content=html, headers=PAGE_CACHE)
    apply_glide_city_cookie(response, slug=city_slug(name))
    return response
