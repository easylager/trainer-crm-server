"""Открытка «Пойдёшь со мной на каток?» для получателя (TASK-232, TASK-233).

* ``/zovi/{code}`` — страница: SSR для превью в Threads/Telegram, механика — в JS.
  SSR не ставит ``first_opened_at``: превью-боты открывают страницу без JS, а «открыто»
  ставит запрос ``GET /api/public/invites/{code}`` из браузера.
* ``og.png`` 1200×630 и ``ticket.png`` 1080×1350 — Pillow + ``render_png_cached``.
* ``event.ics`` — событие календаря на время сеанса.

Ссылки строятся от текущего origin: свой домен — TASK-238.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.application.ice_invites import InviteRejected, get_invite
from src.application.png_render_cache import render_png_cached
from src.application.zovi_card_image import render_zovi_og, render_zovi_ticket
from src.shared.config import Settings
from src.application.zovi_card_page import (
    decline,
    image_version,
    render_not_found,
    render_zovi_page,
)

router = APIRouter(tags=["zovi-card"])

_PAGE_HEADERS = {"Cache-Control": "private, no-store", "X-Robots-Tag": "noindex, nofollow"}
_IMAGE_HEADERS = {"Cache-Control": "public, max-age=900", "X-Robots-Tag": "noindex"}


def _origin(request: Request) -> str:
    """Публичный адрес как у остальных страниц (``webapp_base_url``). Без него — адрес запроса.

    ``X-Forwarded-Host`` не читаем: его может прислать кто угодно, а адрес уходит в og-ссылки.
    """
    base = (Settings().webapp_base_url or "").strip().rstrip("/")
    if base:
        return base
    return f"{request.url.scheme}://{request.url.netloc}"


async def _read(session: AsyncSession, code: str) -> dict[str, Any] | None:
    try:
        return await get_invite(session, code, device_token=None, mark_opened=False)
    except InviteRejected:
        return None


def _clamp(raw: str | None, low: int, high: int) -> int:
    try:
        value = int((raw or "0").strip())
    except ValueError:
        value = 0
    return max(low, min(high, value))


@router.api_route("/zovi/{code}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def zovi_card_page(code: str, request: Request, session: AsyncSession = Depends(get_session)):
    origin = _origin(request)
    invite = await _read(session, code)
    if invite is None:
        return HTMLResponse(render_not_found(f"{origin}/"), status_code=404, headers=_PAGE_HEADERS)
    if request.method == "HEAD":
        return Response(status_code=200, headers=_PAGE_HEADERS, media_type="text/html")
    page_url = f"{origin}/zovi/{invite['code']}"
    html = render_zovi_page(
        invite,
        page_url=page_url,
        og_image_url=f"{page_url}/og.png?v={image_version(invite)}",
        catalog_url=f"{origin}/",
    )
    return HTMLResponse(html, headers=_PAGE_HEADERS)


@router.get("/zovi/{code}/og.png")
async def zovi_og_image(code: str, session: AsyncSession = Depends(get_session)) -> Response:
    invite = await _read(session, code)
    if invite is None:
        return Response(status_code=404)
    png = await render_png_cached("zovi_og", {"code": invite["code"]}, image_version(invite), render_zovi_og, invite)
    return Response(content=png, media_type="image/png", headers=_IMAGE_HEADERS)


@router.get("/zovi/{code}/ticket.png")
async def zovi_ticket_image(
    code: str,
    t: str | None = Query(None, description="попыток «нет», 0–10"),
    s: str | None = Query(None, description="сопротивление, секунд, 0–600"),
    f: str | None = Query(None, description="падений, 0–5"),
    k: str | None = Query(None, description="1 — нажали переодетую «Да»"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Имена и сеанс — из базы; цифры — из query. Подделка цифр безвредна: билет шуточный."""
    invite = await _read(session, code)
    if invite is None:
        return Response(status_code=404)
    stats = {
        "tries": _clamp(t, 0, 10),
        "seconds": _clamp(s, 0, 600),
        "falls": _clamp(f, 0, 5),
        "tricked": (k or "").strip() == "1",
    }
    data = {
        "v": image_version(invite),
        "ticket": [invite["session"]["arena"].get("address"), invite["session"].get("price")],
    }
    png = await render_png_cached(
        "zovi_ticket", {"code": invite["code"], **stats}, data, render_zovi_ticket, invite, **stats
    )
    return Response(content=png, media_type="image/png", headers=_IMAGE_HEADERS)


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_fold(line: str) -> str:
    """RFC 5545: строки не длиннее 75 октетов, продолжение — с пробела."""
    out: list[str] = []
    current = ""
    for ch in line:
        if len((current + ch).encode("utf-8")) > 75:
            out.append(current)
            current = " " + ch
        else:
            current += ch
    out.append(current)
    return "\r\n".join(out)


def _ics_time(iso: str) -> str:
    moment = datetime.fromisoformat(iso).astimezone(timezone.utc)
    return moment.strftime("%Y%m%dT%H%M%SZ")


@router.get("/zovi/{code}/event.ics")
async def zovi_event_ics(code: str, request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    invite = await _read(session, code)
    if invite is None:
        return Response(status_code=404)
    s = invite["session"]
    arena = s["arena"]
    what = "Хоккей" if invite.get("kind") == "hockey_practice" else "Каток"
    summary = f"{what} с {decline(invite.get('from_name'), 'ins')}"
    location = ", ".join(str(p) for p in (arena.get("name"), arena.get("address"), arena.get("city")) if p)
    page_url = f"{_origin(request)}/zovi/{invite['code']}"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Glide//zovi//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:zovi-{invite['code']}@glide",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{_ics_time(s['starts_at_utc'])}",
        f"DTEND:{_ics_time(s['ends_at_utc'])}",
        f"SUMMARY:{_ics_escape(summary)}",
        f"LOCATION:{_ics_escape(location)}",
        f"DESCRIPTION:{_ics_escape(page_url)}",
        f"URL:{page_url}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    body = "\r\n".join(_ics_fold(line) for line in lines) + "\r\n"
    return Response(
        content=body.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'attachment; filename="glide-zovi.ics"',
        },
    )
