"""Матчи как события сайта (TASK-347): список ``/hockey``, страница ``/m/{id}-{home}-{away}``, ``.ics``.

За флагом ``SITE_MATCHES_ENABLED``: пока он выключен, все адреса отвечают 404, как будто их нет.
Адрес матча не содержит даты — перенос его не меняет; несовпавший хвост получает 301 на канонический.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.application import site_matches
from src.application.ice_city_day import city_slug, resolve_city_by_ref
from src.application.site_matches_page import cache_header, render_match_page, render_matches_list
from src.shared.config import Settings

router = APIRouter(tags=["public-matches"])

_NOT_FOUND = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" />
<title>Матч не найден — Glideclub</title>
__PUBLIC_FONTS_HEAD__
<style>body{font-family:'Golos Text',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f4f6f7;color:#0d1b26;
margin:0;padding:48px 20px;text-align:center}h1{font-weight:600;letter-spacing:-.01em}a{color:#0B6E70;font-weight:600}</style></head>
<body><h1>Такого матча нет</h1>
<p>Возможно, он ещё не в расписании или клуб пока не подключён.</p>
<p><a href="/hockey">Все матчи</a></p></body></html>"""


def _base() -> str:
    return (Settings().webapp_base_url or "").strip().rstrip("/")  # type: ignore[call-arg]


def _not_found() -> HTMLResponse:
    from src.application.style_b import public_fonts_head_html

    return HTMLResponse(_NOT_FOUND.replace("__PUBLIC_FONTS_HEAD__", public_fonts_head_html()), status_code=404)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.api_route("/hockey", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def hockey_list(
    request: Request,
    city: str | None = Query(None, max_length=80, description="Город (slug): его матчи первыми"),
    club: str | None = Query(None, max_length=60, description="Клуб (slug): только его матчи"),
    session: AsyncSession = Depends(get_session),
):
    if not site_matches.site_enabled():
        return _not_found()
    if request.method == "HEAD":
        return Response(status_code=200, headers={"Cache-Control": "public, max-age=60"})
    ref = (city or request.cookies.get("glide_city", "")).strip().lower()
    found = await resolve_city_by_ref(session, ref) if ref else None
    city_name = str(found["name"]) if found else None
    data = await site_matches.matches_list(
        session, now=_now(), city=city_name, club=(club or "").strip().lower() or None
    )
    html = render_matches_list(
        data,
        base_url=_base(),
        city_name=city_name,
        city_id=int(found["id"]) if found else None,
        noindex=bool(club or city),
    )
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=60, stale-while-revalidate=300", "Vary": "Cookie"})


async def _load(session: AsyncSession, ref: str):
    match_id = site_matches.parse_match_ref(ref)
    if match_id is None or not site_matches.site_enabled():
        return None
    return await site_matches.match_page_data(session, match_id, now=_now())


@router.api_route("/m/{ref}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def match_page(ref: str, request: Request, session: AsyncSession = Depends(get_session)):
    data = await _load(session, ref)
    if data is None:
        return _not_found()
    canonical = data["match"]["path"]
    if request.url.path != canonical:
        query = request.url.query
        return RedirectResponse(url=canonical + (f"?{query}" if query else ""), status_code=301)
    headers = cache_header(data["match"]["phase"])
    if request.method == "HEAD":
        return Response(status_code=200, headers=headers)
    city_href = None
    city_id = None
    if data.get("city"):
        found = await resolve_city_by_ref(session, city_slug(str(data["city"])))
        if found:
            city_href = f"/c/{city_slug(str(found['name']))}"
            city_id = int(found["id"])
    html = render_match_page(data, base_url=_base(), now=_now(), city_href=city_href, city_id=city_id)
    return HTMLResponse(html, headers=headers)


@router.get("/m/{ref}/calendar.ics")
async def match_ics(ref: str, session: AsyncSession = Depends(get_session)):
    data = await _load(session, ref)
    if data is None or data["gone"]:
        return Response(status_code=404)
    match = data["match"]
    body = site_matches.build_ics(
        row=data["row"],
        url=f"{_base()}{match['path']}",
        arena_name=str(data["arena_name"]),
        address=data["arena"].get("address"),
        now=_now(),
    )
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="glide-match-{match["id"]}.ics"',
            "Cache-Control": "public, max-age=300",
        },
    )
