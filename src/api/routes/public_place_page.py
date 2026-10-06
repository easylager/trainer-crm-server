"""
Публичная страница места ``/p/{city}/{slug}`` и её картинки (TASK-146).

Как и «Лёд сегодня» (``public_ice_page``) — не API, а страница для человека по
ссылке из чата и для поисковика, поэтому без префикса ``/api`` и без авторизации.

* ``?s=<session_id>`` — ссылка на конкретный сеанс: он первым на странице и на картинке.
* ``?i=1`` — тон «Позвать с собой»: заголовок-вопрос вместо объявления.

Обе формы не индексируются (``noindex``): в поиск идёт только каноническая страница.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.application.ice_city_day import city_slug, ice_city_day_page_url, resolve_city_by_ref
from src.application.place_card_image import render_place_card, share_display_path
from src.application.arena_public_use_cases import resolve_merged_arena_id
from src.application.catalog_consumer_events import record_public_page_view
from src.application.png_render_cache import render_png_cached
from src.application.place_links import (
    place_image_url,
    place_page_url,
    place_path,
    place_start_param,
    public_telegram_cta_url,
)
from src.application.place_page import load_place_view, render_place_page, share_payload
from src.shared.config import Settings
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params

router = APIRouter(tags=["public-place"])

# Страница живая (расписание), но переживает всплеск от одного репоста: 5 минут.
# Картинка дороже в рендере и меняется реже — 15 минут, как у «Лёд сегодня».
_PAGE_CACHE = {"Cache-Control": "public, max-age=300"}
_IMAGE_CACHE = {"Cache-Control": "public, max-age=900"}
_IMAGE_CACHE_SESSION = {"Cache-Control": "private, no-store, must-revalidate"}


def _base() -> str:
    return (Settings().webapp_base_url or "").strip().rstrip("/")


def _int_or_none(raw: str | None) -> int | None:
    value = (raw or "").strip()
    return int(value) if value.isdigit() and 0 < int(value) < 2**31 else None


def _flag(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes")


async def _arena_id_in_city(session: AsyncSession, city_id: int, slug: str) -> int | None:
    row = (
        await session.execute(
            text("""
                SELECT p.arena_id FROM arena_profiles p
                WHERE p.city_id = :cid AND p.slug = :slug
                LIMIT 1
                """),
            {"cid": int(city_id), "slug": slug.strip().lower()},
        )
    ).first()
    return int(row[0]) if row else None


_NOT_FOUND_HTML = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" />
<title>Место не найдено — Glide</title>
<meta property="og:title" content="Glide — карта льда" />
<meta property="og:description" content="Где покататься сегодня: катки, расписание и цены." />
<style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f4f6f7;color:#0d1b26;
margin:0;padding:48px 20px;text-align:center}a{color:#0f8f8a;font-weight:600}</style></head>
<body><h1>Этого места больше нет в каталоге</h1>
<p>Возможно, оно закрылось или переехало. Посмотрите, где покататься сегодня:</p>
<p><a href="__HOME__">Открыть карту льда</a></p></body></html>"""


def _not_found(home: str) -> HTMLResponse:
    # 404, а не 200: поисковик должен забыть адрес. Человеку — понятная страница с выходом.
    return HTMLResponse(_NOT_FOUND_HTML.replace("__HOME__", home), status_code=404)


async def _merged_redirect(session: AsyncSession, arena_id: int, request: Request) -> RedirectResponse | None:
    """301 from a retired duplicate (``arenas.merged_into_arena_id``) to the canonical page.

    TASK-177: duplicates are retired into one canonical id; links to the old card that
    already live in chats and search indexes keep working and pass their weight on.
    """
    target_id = await resolve_merged_arena_id(session, int(arena_id))
    if target_id is None:
        return None
    view = await load_place_view(session, str(target_id))
    if view is None or not view["card"].get("slug"):
        return None
    card = view["card"]
    target = place_path(city_name=str(card.get("city_name") or ""), slug=str(card["slug"]))
    q = request.url.query
    return RedirectResponse(url=target + (f"?{q}" if q else ""), status_code=301)


async def _resolve(session: AsyncSession, city_ref: str, slug: str):
    city = await resolve_city_by_ref(session, city_ref)
    if city is None:
        return None, None
    arena_id = await _arena_id_in_city(session, int(city["id"]), slug)
    return city, arena_id


@router.get("/p/{arena_id:int}")
async def place_by_id(arena_id: int, request: Request, session: AsyncSession = Depends(get_session)):
    """Короткая форма по id (бот, админка) → 301 на каноническую ``/p/{city}/{slug}``."""
    view = await load_place_view(session, str(arena_id))
    if view is None or not view["card"].get("slug"):
        merged = await _merged_redirect(session, arena_id, request)
        return merged or _not_found(_base() + "/webapp/ice")
    card = view["card"]
    target = place_path(city_name=str(card.get("city_name") or ""), slug=str(card["slug"]))
    q = request.url.query
    return RedirectResponse(url=target + (f"?{q}" if q else ""), status_code=301)


@router.get("/p/{city_ref}/{slug}", response_class=HTMLResponse)
async def place_page(
    city_ref: str,
    slug: str,
    request: Request,
    s: str | None = Query(None, description="id сеанса, на который ведёт ссылка"),
    i: str | None = Query(None, description="1 — тон «Позвать с собой»"),
    session: AsyncSession = Depends(get_session),
):
    base = _base()
    city, arena_id = await _resolve(session, city_ref, slug)
    if city is None or arena_id is None:
        return _not_found(base + "/webapp/ice")
    session_id = _int_or_none(s)
    invite = _flag(i)
    view = await load_place_view(session, str(arena_id), session_id=session_id)
    if view is None:
        merged = await _merged_redirect(session, arena_id, request)
        return merged or _not_found(base + "/webapp/ice")
    card = view["card"]
    city_name = str(card.get("city_name") or city["name"])
    if city_ref != city_slug(city_name) or slug != card.get("slug"):
        q = request.url.query
        target = place_path(city_name=city_name, slug=str(card["slug"]))
        return RedirectResponse(url=target + (f"?{q}" if q else ""), status_code=301)

    canonical = place_page_url(base_url=base, city_name=city_name, slug=str(card["slug"]))
    # Пересылаем то, что открыто: выбранный сеанс сохраняется, «позвать» — нет
    # (получатель, пересылая дальше, сам решит, зовёт он или нет).
    share_url = place_page_url(
        base_url=base,
        city_name=city_name,
        slug=str(card["slug"]),
        session_id=session_id if view.get("focus") is not None else None,
    )
    image_kwargs = {
        "base_url": base,
        "city_name": city_name,
        "slug": str(card["slug"]),
        "session_id": session_id if view.get("focus") is not None else None,
        "invite": invite,
    }
    settings = Settings()
    html = render_place_page(
        view,
        canonical_url=canonical,
        base_path=place_path(city_name=city_name, slug=str(card["slug"])),
        og_image_url=place_image_url(**image_kwargs),
        story_image_url=place_image_url(**image_kwargs, story=True),
        cta_url=public_telegram_cta_url(
            base,
            start_param=place_start_param(
                int(card["id"]),
                int(view["focus"]["id"]) if view.get("focus") is not None else None,
            ),
            surface="place_page",
            city_id=int(city["id"]),
            arena_id=int(card["id"]),
        ),
        city_page_url=ice_city_day_page_url(base_url=base, city_name=city_name),
        share=share_payload(view, page_url=share_url, invite=False),
        invite=invite,
    )
    await record_public_page_view(
        session,
        request,
        surface="place_page",
        city_id=int(city["id"]),
        arena_id=int(card["id"]),
    )
    return HTMLResponse(content=html, media_type="text/html", headers=_PAGE_CACHE)


async def _image(
    session: AsyncSession, city_ref: str, slug: str, s: str | None, i: str | None, *, story: bool
) -> Response:
    city, arena_id = await _resolve(session, city_ref, slug)
    if city is None or arena_id is None:
        return Response(status_code=404)
    focus_id = _int_or_none(s)
    view = await load_place_view(session, str(arena_id), session_id=focus_id)
    if view is None:
        return Response(status_code=404)
    card = view["card"]
    invite = _flag(i)
    page = place_page_url(
        base_url=_base(),
        city_name=str(card.get("city_name") or ""),
        slug=str(card.get("slug") or ""),
        session_id=focus_id,
        invite=invite,
    )
    kwargs = {"invite": invite, "story": story}
    if story:
        kwargs["share_url"] = page
        kwargs["display_path"] = share_display_path(page)
    png = await render_png_cached(
        "place_story" if story else "place_og",
        {"arena_id": arena_id, "session": focus_id, "invite": invite, "page": page},
        view,
        render_place_card,
        view,
        **kwargs,
    )
    cache = _IMAGE_CACHE_SESSION if focus_id is not None else _IMAGE_CACHE
    return Response(content=png, media_type="image/png", headers=cache)


@router.get("/p/{city_ref}/{slug}/og.png")
@router.get("/p/{city_ref}/{slug}/session/{session_id}/og.png")
async def place_og_image(
    city_ref: str,
    slug: str,
    session_id: int | None = None,
    s: str | None = None,
    i: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """og:image 1200×630 — превью ссылки в Telegram/Viber/VK."""
    sid = str(session_id) if session_id is not None else s
    return await _image(session, city_ref, slug, sid, i, story=False)


@router.get("/p/{city_ref}/{slug}/story.png")
@router.get("/p/{city_ref}/{slug}/session/{session_id}/story.png")
async def place_story_image(
    city_ref: str,
    slug: str,
    session_id: int | None = None,
    s: str | None = None,
    i: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """9:16 для историй Instagram/VK — у них нет API «опубликовать», только «сохранить и выложить»."""
    sid = str(session_id) if session_id is not None else s
    return await _image(session, city_ref, slug, sid, i, story=True)


# ---------------------------------------------------------------------------
# Поиск: sitemap и robots (Q-004). Каталог «вся страна» растёт органикой из
# поиска — «массовое катание <город> расписание», «заточка коньков <район>».
# ---------------------------------------------------------------------------

_SITEMAP_SQL = text(f"""
    SELECT c.name AS city_name, p.slug, a.venue_type
    FROM arenas a
    JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    WHERE {PUBLIC_ARENA_VISIBLE_SQL}
      AND p.status = 'published' AND p.slug IS NOT NULL
    ORDER BY c.sort_order, c.id, a.id
    """)


@router.get("/sitemap.xml")
async def sitemap(session: AsyncSession = Depends(get_session)) -> Response:
    from xml.sax.saxutils import escape

    base = _base()
    rows = (await session.execute(_SITEMAP_SQL, public_scope_params())).mappings().all()
    urls: list[tuple[str, str]] = [(base + "/", "weekly")]
    seen_cities: set[str] = set()
    shop_cities: set[str] = set()
    for row in rows:
        city_name = str(row["city_name"])
        if city_name not in seen_cities:
            seen_cities.add(city_name)
            urls.append((ice_city_day_page_url(base_url=base, city_name=city_name), "daily"))
            # Подборка города — ответ на «где покататься в <город>» (TASK-146).
            urls.append((f"{base}/c/{city_slug(city_name)}", "daily"))
        if row["venue_type"] == "shop" and city_name not in shop_cities:
            shop_cities.add(city_name)
            urls.append((f"{base}/c/{city_slug(city_name)}?t=shop", "weekly"))
        freq = "daily" if row["venue_type"] == "ice" else "weekly"
        urls.append((place_page_url(base_url=base, city_name=city_name, slug=str(row["slug"])), freq))
    body = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, freq in urls:
        body.append(f"<url><loc>{escape(loc)}</loc><changefreq>{freq}</changefreq></url>")
    body.append("</urlset>")
    return Response(
        content="\n".join(body),
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/robots.txt")
async def robots() -> Response:
    # /webapp — оболочки мини-аппа без серверного контента; индексировать нечего.
    content = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "Disallow: /api/",
            "Disallow: /webapp/",
            f"Sitemap: {_base()}/sitemap.xml",
            "",
        ]
    )
    return Response(content=content, media_type="text/plain", headers={"Cache-Control": "public, max-age=86400"})


# ---------------------------------------------------------------------------
# Подборка /c/{город}?t=<тип>&w=<окно> — то, чем делятся прямо из каталога.
# ---------------------------------------------------------------------------


@router.get("/c/{city_ref}", response_class=HTMLResponse)
async def selection_page(
    city_ref: str,
    request: Request,
    t: str | None = Query(None, description="Тип места: ice|shop|gym|…"),
    w: str | None = Query(None, description="Окно: today_evening|today|tomorrow|weekend"),
    session: AsyncSession = Depends(get_session),
):
    from src.application.selection_page import (
        clean_venue,
        clean_when,
        compose_selection_share,
        load_selection_view,
        render_selection_page,
        selection_image_path,
        selection_path,
        selection_start_param,
    )

    base = _base()
    city = await resolve_city_by_ref(session, city_ref)
    if city is None:
        return _not_found(base + "/webapp/ice")
    venue, when = clean_venue(t), clean_when(w)
    city_name = str(city["name"])
    path = selection_path(city_name=city_name, venue=venue, when=when)
    if city_ref != city_slug(city_name):
        return RedirectResponse(url=path, status_code=301)
    view = await load_selection_view(session, city=city, venue=venue, when=when)
    html = render_selection_page(
        view,
        canonical_url=base + path,
        og_image_url=base + selection_image_path(city_name=city_name, venue=venue, when=when),
        cta_url=public_telegram_cta_url(
            base,
            start_param=selection_start_param(city_id=int(city["id"]), venue=venue, when=when),
            surface="selection_page",
            city_id=int(city["id"]),
        ),
        share=compose_selection_share(view, page_url=base + path),
        city_page_url=ice_city_day_page_url(base_url=base, city_name=city_name),
        story_image_url=base
        + selection_image_path(city_name=city_name, venue=venue, when=when).replace("/og.png", "/story.png"),
    )
    await record_public_page_view(
        session,
        request,
        surface="selection_page",
        city_id=int(city["id"]),
    )
    return HTMLResponse(content=html, media_type="text/html", headers=_PAGE_CACHE)


async def _selection_image(session: AsyncSession, city_ref: str, t: str | None, w: str | None, *, story: bool):
    from src.application.place_card_image import render_selection_card
    from src.application.selection_page import clean_venue, clean_when, load_selection_view, selection_path

    city = await resolve_city_by_ref(session, city_ref)
    if city is None:
        return Response(status_code=404)
    venue, when = clean_venue(t), clean_when(w)
    view = await load_selection_view(session, city=city, venue=venue, when=when)
    page = _base() + selection_path(city_name=str(city["name"]), venue=venue, when=when)
    view["share_url"] = page
    view["display_path"] = share_display_path(page)
    png = await render_png_cached(
        "selection_story" if story else "selection_og",
        {"venue": venue, "when": when, "page": page},
        view,
        render_selection_card,
        view,
        story=story,
    )
    return Response(content=png, media_type="image/png", headers=_IMAGE_CACHE)


@router.get("/c/{city_ref}/og.png")
async def selection_og_image(
    city_ref: str, t: str | None = None, w: str | None = None, session: AsyncSession = Depends(get_session)
) -> Response:
    return await _selection_image(session, city_ref, t, w, story=False)


@router.get("/c/{city_ref}/story.png")
async def selection_story_image(
    city_ref: str, t: str | None = None, w: str | None = None, session: AsyncSession = Depends(get_session)
) -> Response:
    return await _selection_image(session, city_ref, t, w, story=True)
