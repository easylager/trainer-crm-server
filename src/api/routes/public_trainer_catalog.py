"""Каталог тренеров ``/c/{city}/trenery[/{направление}]`` (TASK-355). Логика — ``site_trainer_catalog``.

Неизвестный город или направление → 404; город не каноническим slug (id, алиас) → 301 с тем же query.
Фильтр катка ``?arena=`` — та же страница, canonical без него.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.application import site_trainer_catalog as catalog
from src.application.ice_city_day import city_slug, resolve_city_by_ref
from src.shared.config import Settings

router = APIRouter(tags=["public-trainer-catalog"])

_CACHE = {"Cache-Control": "public, max-age=60, stale-while-revalidate=300"}

_NOT_FOUND = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" />
<title>Такой страницы нет — Glideclub</title>
__PUBLIC_FONTS_HEAD__
<style>body{font-family:'Golos Text',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f4f6f7;color:#0d1b26;
margin:0;padding:48px 20px;text-align:center}h1{font-weight:600;letter-spacing:-.01em}a{color:#0B6E70;font-weight:600}</style></head>
<body><h1>Такой страницы нет</h1>
<p>Возможно, ссылка устарела.</p>
<p><a href="/">Катки и тренеры</a></p></body></html>"""


def _not_found() -> HTMLResponse:
    from src.application.style_b import public_fonts_head_html

    return HTMLResponse(_NOT_FOUND.replace("__PUBLIC_FONTS_HEAD__", public_fonts_head_html()), status_code=404)


async def _page(city_ref: str, direction_slug: str | None, request: Request, session: AsyncSession) -> Response:
    direction = catalog.direction_by_slug(direction_slug)
    if direction is None:
        return _not_found()
    city = await resolve_city_by_ref(session, city_ref)
    if city is None:
        return _not_found()
    name = str(city["name"])
    if city_ref != city_slug(name):
        query = request.url.query
        return RedirectResponse(url=catalog.catalog_path(name, direction) + (f"?{query}" if query else ""), status_code=301)
    if request.method == "HEAD":
        return Response(status_code=200, headers=_CACHE)
    data = await catalog.load_city_catalog(session, city)
    html = catalog.render_catalog_page(
        data,
        direction,
        base_url=(Settings().webapp_base_url or "").strip().rstrip("/"),  # type: ignore[call-arg]
        arena_id=catalog.parse_arena_param(request.query_params.get("arena")),
    )
    return HTMLResponse(html, headers=_CACHE)


@router.api_route(f"/c/{{city_ref}}/{catalog.CATALOG_SEGMENT}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def trainer_catalog_all(city_ref: str, request: Request, session: AsyncSession = Depends(get_session)):
    return await _page(city_ref, None, request, session)


@router.api_route(
    f"/c/{{city_ref}}/{catalog.CATALOG_SEGMENT}/{{direction}}", methods=["GET", "HEAD"], response_class=HTMLResponse
)
async def trainer_catalog_direction(
    city_ref: str, direction: str, request: Request, session: AsyncSession = Depends(get_session)
):
    return await _page(city_ref, direction, request, session)
