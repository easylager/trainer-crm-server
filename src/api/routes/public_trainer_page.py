"""Страница тренера на сайте ``/t/{id}-{slug}`` (TASK-350). Логика — ``site_trainer_page``.

Короткая ``/t/{id}`` и неверный хвост → 301 на канонический адрес; нет тренера или он
деактивирован → 404. Внутри Mini App ту же ссылку перехватывает ``glide-deeplink.js`` и
открывает экран тренера приложения, а не эту страницу.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.application import site_trainer_page
from src.shared.config import Settings

router = APIRouter(tags=["public-trainer-page"])

_NOT_FOUND = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" />
<title>Тренер не найден — Glideclub</title>
__PUBLIC_FONTS_HEAD__
<style>body{font-family:'Golos Text',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f4f6f7;color:#0d1b26;
margin:0;padding:48px 20px;text-align:center}h1{font-weight:600;letter-spacing:-.01em}a{color:#0B6E70;font-weight:600}</style></head>
<body><h1>Такого тренера нет</h1>
<p>Возможно, ссылка устарела. Тренеры — на страницах катков.</p>
<p><a href="/">Катки и тренеры</a></p></body></html>"""

_CACHE = {"Cache-Control": "public, max-age=60, stale-while-revalidate=300"}


def _not_found() -> HTMLResponse:
    from src.application.style_b import public_fonts_head_html

    return HTMLResponse(_NOT_FOUND.replace("__PUBLIC_FONTS_HEAD__", public_fonts_head_html()), status_code=404)


@router.api_route("/t/{ref}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def trainer_page(ref: str, request: Request, session: AsyncSession = Depends(get_session)):
    trainer_id = site_trainer_page.parse_trainer_ref(ref)
    if trainer_id is None:
        return _not_found()
    page = await site_trainer_page.load_trainer_page(session, trainer_id)
    if page is None:
        return _not_found()
    if request.url.path != page["path"]:
        query = request.url.query
        return RedirectResponse(url=page["path"] + (f"?{query}" if query else ""), status_code=301)
    if request.method == "HEAD":
        return Response(status_code=200, headers=_CACHE)
    settings = Settings()  # type: ignore[call-arg]
    html = site_trainer_page.render_trainer_page(
        page,
        base_url=(settings.webapp_base_url or "").strip().rstrip("/"),
        client_bot_username=settings.client_bot_username,
    )
    return HTMLResponse(html, headers=_CACHE)
