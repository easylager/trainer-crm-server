"""Публичное API и страница компании. Организатор — только с проверенным initData."""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from src.api.deps import get_session
from src.application import hockey_event
from src.application.hockey_matches import DINAMO
from src.application.ice_company.avatars import cache_telegram_avatar_with_token, going_avatar_bytes, read_avatar_bytes
from src.application.ice_company.codes import tg_participant_key, web_participant_key
from src.application.hockey_cards import render_match_company_card
from src.application.png_cache import bytes_key, cached_png
from src.application.ice_company.copy import MATCH_KIND, closed_headline, match_nickname
from src.application.ice_company.keyboard import inline_button_json
from src.application.ice_company.lifecycle import button_rows, buttons_for, calendar_url_for, render_hash
from src.application.ice_company.og import company_photo, render_company_card
from src.application.ice_company.page import render_company_page
from src.application.ice_company.safety import strip_emoji_for_poster
from src.application.ice_company.service import (
    CompanyRejected,
    actor_for_telegram,
    cancel_company,
    create_company,
    create_match_company,
    delete_own,
    preview_snap,
    read_company,
    resolve_participant,
    respond,
    snap_from,
    _home_match_row,
    _load,
    _match_id,
    _responses,
)
from src.shared.client_ip import trusted_client_ip
from src.shared.config import Settings
from src.shared.telegram_webapp import (
    InitDataAuthError,
    display_name_from_telegram_user,
    parse_user_json_from_init_data,
    require_telegram_user_id,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ice-company"])

_hits: dict[str, deque[float]] = {}


class CreateBody(BaseModel):
    # Ровно одно из двух: сеанс льда или домашний матч Динамо (TASK-304).
    session_id: int | None = None
    match_id: int | None = None
    display_name: str = ""
    name: str = ""
    surface: str = "miniapp"


class RespondBody(BaseModel):
    status: str
    display_name: str = ""
    participant_token: str = ""
    consent: bool = False
    source: str = "web"
    website: str = ""


class TokenBody(BaseModel):
    participant_token: str = ""


def reset_company_rate_limits() -> None:
    _hits.clear()


def _allow(key: str, limit: int) -> bool:
    now = time.monotonic()
    bucket = _hits.setdefault(key, deque())
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


def _http(exc: CompanyRejected) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _init_user(raw: str | None) -> int | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return require_telegram_user_id(str(raw).strip(), Settings().telegram_bot_token_client)
    except InitDataAuthError:
        raise HTTPException(status_code=401, detail="Сессия Telegram устарела. Откройте мини-приложение снова.") from None


def _client_ip(request: Request) -> str | None:
    peer = request.client.host if request.client else None
    return trusted_client_ip(request.headers, peer)


def _ics(view: dict) -> str:
    event = view["event"]
    start = datetime.fromisoformat(event["starts_at"]).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    end = datetime.fromisoformat(event["ends_at"]).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = (view.get("name") or "Компания на лёд").replace("\n", " ")
    place = str(event.get("venue_label") or "").replace("\n", " ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Glide//ice-company//RU",
        "BEGIN:VEVENT",
        f"DTSTART:{start}",
        f"DTEND:{end}",
        f"SUMMARY:{summary}",
        f"LOCATION:{place}",
        f"URL:{view.get('page_url') or ''}",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
    return "\r\n".join(lines)


@router.post("/api/public/ice-companies", status_code=201)
async def post_company(
    body: CreateBody,
    request: Request,
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    init_raw = x_telegram_init_data or request.query_params.get("init_data") or ""
    user_id = _init_user(init_raw)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Собрать компанию можно из Telegram.")
    if (body.session_id is None) == (body.match_id is None):
        raise HTTPException(status_code=422, detail="Нужен ровно один из session_id и match_id.")
    if body.match_id is not None and not hockey_event.enabled():
        raise HTTPException(status_code=404, detail="Не найдено")
    organizer_name = (body.display_name or "").strip()
    if not organizer_name:
        organizer_name = display_name_from_telegram_user(parse_user_json_from_init_data(init_raw)) or ""
    if not organizer_name:
        raise HTTPException(status_code=422, detail="Не удалось подставить имя из Telegram.")
    try:
        if body.match_id is not None:
            view = await create_match_company(
                session,
                telegram_user_id=user_id,
                match_id=body.match_id,
                home_team=DINAMO,
                display_name=organizer_name,
                name=body.name,
            )
        else:
            assert body.session_id is not None
            view = await create_company(
                session,
                telegram_user_id=user_id,
                session_id=body.session_id,
                display_name=organizer_name,
                name=body.name,
                surface=(body.surface or "miniapp")[:16],
            )
    except CompanyRejected as exc:
        raise _http(exc) from None
    company = await _load(session, str(view["public_code"]))
    if company is not None:
        await cache_telegram_avatar_with_token(
            session,
            Settings(),
            company_id=int(company["id"]),
            participant_key=tg_participant_key(user_id),
            telegram_user_id=user_id,
        )
    return view


@router.get("/api/public/ice-companies/preview.png")
async def company_preview_png(
    session_id: int | None = None,
    match_id: int | None = None,
    name: str = "",
    you: str = "",
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Превью картинки компании до создания: тот же рисунок, что уйдёт в чат (лист шаринга, вкладка «Компания»)."""
    if match_id is not None:
        match = await _home_match(session, match_id)
        if match is None or not Settings().hockey_matches_enabled:
            raise HTTPException(status_code=404, detail="Матч не найден.")
        who = strip_emoji_for_poster((you or "").strip()[:24]) or "Ты"
        title = strip_emoji_for_poster((name or "").strip()[:40])
        png = await cached_png(
            (
                "preview-match",
                match_id,
                str(match["home_team"]),
                str(match["away_team"]),
                match["starts_at"].isoformat(),
                who,
                title,
            ),
            lambda: render_match_company_card(
                home=str(match["home_team"]),
                away=str(match["away_team"]),
                starts_at=match["starts_at"],
                going=[(who, None)],
                watching=[],
                name=title,
            ),
        )
        return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})
    snap = await preview_snap(session, session_id=session_id or 0, display_name=you[:64], name=name[:64])
    if snap is None:
        raise HTTPException(status_code=404, detail="Сеанс не найден.")
    return Response(
        content=await cached_png(("preview-ice", snap), lambda: render_company_card(snap)),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/api/public/ice-companies/{code}")
async def get_company(code: str, session: AsyncSession = Depends(get_session)) -> dict:
    view = await read_company(session, code)
    if view is None:
        raise HTTPException(status_code=404, detail="Компания не найдена.")
    return view


@router.post("/api/public/ice-companies/{code}/responses")
async def post_response(
    code: str,
    body: RespondBody,
    request: Request,
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if (body.website or "").strip():
        view = await read_company(session, code)
        if view is None:
            raise HTTPException(status_code=404, detail="Компания не найдена.")
        return {**view, "participant_token": None}
    user_id = _init_user(x_telegram_init_data or request.query_params.get("init_data"))
    source = "tg" if user_id is not None else ("viber" if body.source == "viber" else "web")
    ip = _client_ip(request)
    limit = Settings().ice_company_web_rate_per_minute
    if user_id is None:
        token = (body.participant_token or "").strip()
        if not _allow(f"ip:{ip}", limit) or (token and not _allow(f"tok:{token[:16]}", limit)):
            raise HTTPException(status_code=429, detail="Слишком часто. Подождите минуту.")
    try:
        key, issued = resolve_participant(
            telegram_user_id=user_id,
            raw_token=(body.participant_token or "").strip() or None,
            source=source,
        )
        view = await respond(
            session,
            code=code,
            status=body.status,
            display_name=body.display_name,
            participant_key=key,
            source=source,
            consent=bool(body.consent) or user_id is not None,
            actor_hash=actor_for_telegram(user_id, ip, request.headers.get("user-agent")),
        )
    except CompanyRejected as exc:
        raise _http(exc) from None
    if issued:
        view = {**view, "participant_token": issued}
    if user_id is not None and body.status == "going":
        company = await _load(session, code)
        if company is not None:
            await cache_telegram_avatar_with_token(
                session,
                Settings(),
                company_id=int(company["id"]),
                participant_key=tg_participant_key(user_id),
                telegram_user_id=user_id,
            )
    return view


@router.post("/api/public/ice-companies/{code}/cancel")
async def post_cancel(
    code: str,
    request: Request,
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = _init_user(x_telegram_init_data or request.query_params.get("init_data"))
    if user_id is None:
        raise HTTPException(status_code=401, detail="Отменить может тот, кто собирал компанию.")
    try:
        return await cancel_company(session, code=code, telegram_user_id=user_id)
    except CompanyRejected as exc:
        raise _http(exc) from None


@router.delete("/api/public/ice-companies/{code}/me", status_code=204)
async def delete_me(
    code: str,
    body: TokenBody,
    request: Request,
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    user_id = _init_user(x_telegram_init_data or request.query_params.get("init_data"))
    if user_id is not None:
        from src.application.ice_company.codes import tg_participant_key

        key = tg_participant_key(user_id)
    elif (body.participant_token or "").strip():
        key = web_participant_key(body.participant_token.strip())
    else:
        raise HTTPException(status_code=401, detail="Не видно, чьи данные удалять.")
    try:
        await delete_own(session, code=code, participant_key=key)
    except CompanyRejected as exc:
        raise _http(exc) from None
    return Response(status_code=204)


@router.get("/k/{code}", response_class=HTMLResponse)
async def company_page(code: str, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    view = await read_company(session, code)
    # Компания на матч живёт в чате и Mini App; публичной страницы «на лёд» у неё нет.
    if view is None or view["event"]["kind"] == MATCH_KIND:
        return HTMLResponse("Компания не найдена.", status_code=404, headers={"X-Robots-Tag": "noindex, nofollow"})
    return HTMLResponse(
        render_company_page(view),
        headers={"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "private, no-store"},
    )


@router.get("/k/{code}/event.ics")
async def company_ics(code: str, session: AsyncSession = Depends(get_session)) -> Response:
    view = await read_company(session, code)
    if view is None:
        raise HTTPException(status_code=404, detail="Компания не найдена.")
    return Response(
        content=_ics(view),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="glide-company.ics"'},
    )


async def _home_match(session: AsyncSession, match_id: int | None) -> dict | None:
    return await _home_match_row(session, match_id, DINAMO) if match_id else None


def _people(responses: list[dict], status: str) -> list[tuple[str, bytes | None]]:
    # Эмодзи в имени шрифт карточки не рисует (квадратик) — на картинке без них, в подписи остаются.
    return [
        (strip_emoji_for_poster(str(row["display_name"])) or "·", read_avatar_bytes(row.get("avatar_file_key")))
        for row in responses
        if row["status"] == status
    ]


async def _card_png(session: AsyncSession, code: str) -> bytes:
    company = await _load(session, code)
    if company is None:
        raise HTTPException(status_code=404, detail="Компания не найдена.")
    responses = await _responses(session, int(company["id"]))
    snap = snap_from(company, responses)
    if company["event_kind"] != MATCH_KIND:
        avatars = going_avatar_bytes(responses)
        return await cached_png(
            ("ice-card", snap, bytes_key(*avatars)), lambda: render_company_card(snap, avatar_bytes=avatars)
        )
    # Матч: «Трибуна против дивана» — «Иду» на трибуне, «Смотрю дома» на диване.
    match = await _home_match(session, _match_id(str(company["source_ref"])))
    if match is None:
        raise HTTPException(status_code=404, detail="Компания не найдена.")
    going, watching = _people(responses, "going"), _people(responses, "maybe")
    closed = closed_headline(snap)
    title = strip_emoji_for_poster(match_nickname(str(company.get("name") or "")))
    key = (
        "match-card",
        str(match["home_team"]),
        str(match["away_team"]),
        match["starts_at"].isoformat(),
        tuple(name for name, _ in going),
        tuple(name for name, _ in watching),
        bytes_key(*(face for _, face in going + watching)),
        closed,
        title,
    )
    return await cached_png(
        key,
        lambda: render_match_company_card(
            home=str(match["home_team"]),
            away=str(match["away_team"]),
            starts_at=match["starts_at"],
            going=going,
            watching=watching,
            closed=closed,
            name=title,
        ),
    )


@router.get("/k/{code}/og.png")
async def company_og(code: str, session: AsyncSession = Depends(get_session)) -> Response:
    png = await _card_png(session, code)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=120"})


@router.get("/k/{code}/card.png")
async def company_card(code: str, session: AsyncSession = Depends(get_session)) -> Response:
    png = await _card_png(session, code)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.post("/api/public/ice-companies/{code}/telegram-prepare")
async def prepare_telegram_share(
    code: str,
    request: Request,
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """savePreparedInlineMessage. Если inline выключен, клиент зовёт switchInlineQuery."""
    user_id = _init_user(x_telegram_init_data or request.query_params.get("init_data"))
    if user_id is None:
        raise HTTPException(status_code=401, detail="Поделиться можно из Telegram.")
    company = await _load(session, code)
    if company is None:
        raise HTTPException(status_code=404, detail="Компания не найдена.")
    responses = await _responses(session, int(company["id"]))
    snap = snap_from(company, responses)
    from src.application.ice_company.copy import card_text
    from src.application.ice_company.service import ice_slot_url

    settings = Settings()
    page = ice_slot_url(company, settings)
    text = card_text(snap)
    markup = buttons_for(company, snap, page, calendar_url=calendar_url_for(settings, code))
    is_match = snap.kind == MATCH_KIND
    photo, size = company_photo(settings.webapp_base_url, company, code, render_hash(text, markup))
    prepared = await _save_prepared(
        settings.telegram_bot_token_client,
        user_id,
        code,
        text,
        markup,
        photo,
        size=size,
        title="Звать на матч" if is_match else "Компания на лёд",
    )
    from src.application.ice_company.service import _track

    await _track(
        session,
        kind="card_shared",
        city_id=int(company["city_id"]),
        arena_id=None,
        payload={"surface": "telegram", "prepared": prepared is not None},
        actor_hash=actor_for_telegram(user_id, None, None),
    )
    await session.commit()
    return {
        "prepared_message_id": prepared,
        "inline_query": f"k:{code}",
        "fallback": "switchInlineQuery",
    }


async def _save_prepared(
    token: str,
    user_id: int,
    code: str,
    text: str,
    buttons: list[dict[str, str]],
    photo_url: str | None = None,
    title: str = "Компания на лёд",
    size: tuple[int, int] = (1080, 1080),
) -> str | None:
    import aiohttp

    if not (token or "").strip():
        return None
    keyboard = []
    for group in button_rows(buttons):
        row = []
        for button in group:
            row.append(inline_button_json(button))
        if row:
            keyboard.append(row)
    payload = {
        "user_id": user_id,
        "allow_user_chats": True,
        "allow_group_chats": True,
        "allow_channel_chats": False,
        "allow_bot_chats": False,
        "result": (
            {
                "type": "photo",
                "id": code,
                "photo_url": photo_url,
                "thumbnail_url": photo_url,
                "photo_width": size[0],
                "photo_height": size[1],
                "caption": text,
                "reply_markup": {"inline_keyboard": keyboard},
            }
            if photo_url
            else {
                "type": "article",
                "id": code,
                "title": title,
                "input_message_content": {"message_text": text},
                "reply_markup": {"inline_keyboard": keyboard},
            }
        ),
    }
    url = f"https://api.telegram.org/bot{token}/savePreparedInlineMessage"
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.post(url, json=payload) as resp:
                data = await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001 — в тексте aiohttp бывает токен
        logger.info("savePreparedInlineMessage failed: %s", type(exc).__name__)
        return None
    if not isinstance(data, dict) or data.get("ok") is not True:
        return None
    result = data.get("result") or {}
    return str(result.get("id") or "") or None

