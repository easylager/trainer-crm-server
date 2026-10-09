"""Public Ice Discovery read-only routes (TASK-051). New module — do not grow webapp.py."""
from __future__ import annotations

import logging
import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.public_list_cache import set_public_json_list_cache
from src.api.routes.public import _enrich_trainer_photo_urls
from src.application.arena_public_use_cases import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    IcePublicQueryError,
    find_nearest_ice_now,
    get_public_arena_card,
    list_ice_discovery_cities,
    list_public_arena_sessions,
    list_public_arena_trainers,
    list_public_ice_arenas,
    record_ice_city_interest,
    search_public_ice,
)
from src.application.client_delight_metrics import record_client_share
from src.application.client_share_message import share_body_for_native_share_dialog
from src.application.ice_city_day import (
    compose_ice_city_day_share_message,
    get_city_ice_day,
    ice_city_day_page_url,
    resolve_city_by_ref,
    summary_line,
)
from src.application.place_links import place_image_url, place_page_url
from src.application.place_page import load_place_view, share_payload
from src.infrastructure.db.models import (
    CLIENT_SHARE_KIND_ICE_CITY_DAY,
    CLIENT_SHARE_KIND_PLACE,
    CLIENT_SHARE_KIND_SELECTION,
)
from src.shared.config import Settings
from src.shared.ice_discovery_scope import public_city_scope_sql, public_scope_params

logger = logging.getLogger(__name__)
_MAP_CONFIG_EMPTY_WARN_SEC = 600.0
_map_config_empty_warned_at = 0.0

router = APIRouter(prefix="/api/public", tags=["public-ice"])


def _query_error(exc: IcePublicQueryError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def _slug_city_id(
    session: AsyncSession, arena_ref: str, city_id: int | None, city: str | None
) -> int | None:
    """Город для поиска по slug. Числовой id арены город не требует.

    Без города — ``None``: голый slug разрешается, только если он один среди публично
    видимых арен (``_load_arena_by_ref``), иначе 404. Явно указанный, но неизвестный
    город — сразу 404.
    """
    if str(arena_ref).strip().isdigit():
        return None
    resolved = int(city_id) if city_id is not None else None
    raw = (city or "").strip()
    if resolved is None and raw:
        found = await resolve_city_by_ref(session, raw)
        if found is None:
            raise HTTPException(status_code=404, detail="Arena not found")
        resolved = int(found["id"])
    return resolved


@router.get("/ice/map-config")
async def get_ice_map_config(response: Response) -> dict[str, str | None]:
    """Browser Yandex Maps JS API key. Empty → Ice tab shows a map empty state (no OSM)."""
    response.headers["Cache-Control"] = "no-store"
    key = (Settings().yandex_maps_js_api_key or "").strip() or None
    if not key:
        _warn_map_config_key_empty()
    return {"yandex_maps_js_api_key": key}


def _warn_map_config_key_empty() -> None:
    """The endpoint is not rate-limited, so an empty key must not warn on every hit."""
    global _map_config_empty_warned_at
    now = time.monotonic()
    if now - _map_config_empty_warned_at < _MAP_CONFIG_EMPTY_WARN_SEC:
        return
    _map_config_empty_warned_at = now
    logger.warning("ice map-config requested but YANDEX_MAPS_JS_API_KEY is empty")


@router.get("/ice/cities")
async def get_ice_discovery_cities(
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Cities for the Ice picker: only those with MK sessions and/or catalog trainers."""
    set_public_json_list_cache(response)
    items = await list_ice_discovery_cities(session)
    return {"items": items}


@router.get("/ice/arenas")
async def get_public_ice_arenas(
    response: Response,
    city_id: int | None = None,
    bbox: str | None = Query(None, description="min_lat,min_lon,max_lat,max_lon"),
    near: str | None = Query(None, description="lat,lon"),
    intent: str = Query("skate", description="skate | coach | group | ohm"),
    venue_type: str | None = Query(
        None,
        description="ice|gym|choreo|pool|outdoor|other, можно через запятую. Пусто — все типы.",
    ),
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    cursor: str | None = None,
    when: str | None = Query(
        None,
        description="Окно времени: auto | today_evening | today | tomorrow | weekend | any. auto — умный дефолт.",
    ),
    day: str | None = Query(
        None,
        description="Конкретный календарный день YYYY-MM-DD (Минск); приоритет над when, кроме совпадения с «завтра».",
    ),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Ice tab list. intent=skate only includes arenas with a future public_skate|open_ice slot.

    ``venue_type`` фильтрует площадки по типу (лёд/зал/хореография/…). Ответ всегда
    несёт ``venue_type_facets`` — типы, реально представленные в городе, чтобы
    клиент не рисовал чип, за которым пусто.
    """
    set_public_json_list_cache(response)
    try:
        return await list_public_ice_arenas(
            session,
            city_id=city_id,
            bbox=bbox,
            near=near,
            intent=intent,
            venue_type=venue_type,
            limit=limit,
            cursor=cursor,
            when=when,
            day=day,
        )
    except IcePublicQueryError as exc:
        raise _query_error(exc) from exc


@router.get("/ice/nearest")
async def get_nearest_ice_now(
    response: Response,
    near: str = Query(..., description="lat,lon"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """«Лёд рядом сейчас»: ближайший каток с сеансом сегодня, иначе — в ближайший день со льдом."""
    response.headers["Cache-Control"] = "no-store"
    try:
        found = await find_nearest_ice_now(session, near=near)
    except IcePublicQueryError as exc:
        raise _query_error(exc) from exc
    return {"item": found}


@router.get("/ice/share/{city_id}")
async def get_ice_city_day_share(
    city_id: int,
    response: Response,
    share_context: str | None = Query(
        None, description="Где нажали «Поделиться»: ice_tab (вкладка «Лёд»)."
    ),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Готовое сообщение для Telegram share: ссылка на публичную страницу «Лёд сегодня».

    Контракт тот же, что у ``/api/webapp/client/share-trainer``
    (``share_url``/``share_body``/``share_text``), поэтому фронт переиспользует
    ``openTelegramShareUrlFromMiniApp`` без правок.

    Ручка публичная и по этой причине **не знает, кто поделился**: у события шеринга
    города остаётся ``actor_hash = NULL``. Это осознанный размен — доля шеринга по
    людям здесь не считается, зато вкладка «Лёд» работает и до авторизации, как и вся
    остальная публичная витрина Ice Discovery.
    """
    response.headers["Cache-Control"] = "no-store"
    row = (
        await session.execute(
            text(f"SELECT id, name FROM cities WHERE id = :cid AND {public_city_scope_sql('cities')}"),
            {"cid": int(city_id), **public_scope_params()},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="City not found")
    city_name = str(row[1])

    day = await get_city_ice_day(session, city_id=int(city_id))
    page_url = ice_city_day_page_url(
        base_url=Settings().webapp_base_url, city_name=city_name
    )
    share_text = compose_ice_city_day_share_message(
        city_name=city_name, day=day, page_url=page_url
    )
    share_body = share_body_for_native_share_dialog(share_text, page_url)

    ctx = (share_context or "").strip().lower() or "ice_tab"
    await record_client_share(
        session,
        kind=CLIENT_SHARE_KIND_ICE_CITY_DAY,
        share_context=ctx,
        city_id=int(city_id),
        payload={
            "local_date": day.get("local_date"),
            "arena_count": day.get("arena_count"),
            "session_count": day.get("session_count"),
        },
    )

    return {
        "share_url": page_url,
        "share_body": share_body,
        "share_text": share_text,
        "city_name": city_name,
        "local_date": day.get("local_date"),
        "day_label": day.get("day_label"),
        "arena_count": day.get("arena_count"),
        "session_count": day.get("session_count"),
        "summary": summary_line(day, city_name=city_name, absolute=True),
        "share_context": ctx,
    }


class IceCityInterestBody(BaseModel):
    city_id: int
    intent: str = "skate"
    source: str = Field(default="coming_soon_cta", max_length=32)


@router.post("/ice/interest")
async def post_ice_interest(
    body: IceCityInterestBody,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Record that a client asked for skating in a city that has trainers but no map rinks."""
    response.headers["Cache-Control"] = "no-store"
    try:
        payload = await record_ice_city_interest(
            session, city_id=body.city_id, intent=body.intent, source=body.source
        )
    except IcePublicQueryError as exc:
        raise _query_error(exc) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="City not found")
    return payload


@router.get("/search")
async def get_public_search(
    response: Response,
    q: str = Query(..., min_length=1),
    limit: int = Query(8, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """One search, three result groups: arena, trainer, city (tsvector + optional pg_trgm)."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return await search_public_ice(session, q, limit=limit)
    except IcePublicQueryError as exc:
        raise _query_error(exc) from exc


@router.get("/arenas/{arena_ref}/sessions")
async def get_public_arena_sessions(
    arena_ref: str,
    response: Response,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    city_id: int | None = Query(None),
    city: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Canonical ice_sessions feed grouped by local_date. Expired slots are omitted."""
    scoped = await _slug_city_id(session, arena_ref, city_id, city)
    payload = await list_public_arena_sessions(
        session, arena_ref, date_from=date_from, date_to=date_to, city_id=scoped
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Arena not found")
    set_public_json_list_cache(response)
    return payload


@router.get("/arenas/{arena_ref}/trainers")
async def get_public_arena_trainers(
    arena_ref: str,
    response: Response,
    city_id: int | None = Query(None),
    city: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Trainers on an arena with can_book from get_trainer_booking_availability."""
    scoped = await _slug_city_id(session, arena_ref, city_id, city)
    payload = await list_public_arena_trainers(session, arena_ref, city_id=scoped)
    if payload is None:
        raise HTTPException(status_code=404, detail="Arena not found")
    for trainer in payload["items"]:
        _enrich_trainer_photo_urls(trainer)
    set_public_json_list_cache(response)
    return payload


_SHARE_CHANNELS = (
    "telegram",
    "copy",
    "story",
    "story_tg",
    "story_os",
    "story_fallback",
    "system",
    "viber",
    "whatsapp",
    "image_tg",
    "image_os",
    "image_fallback",
)


@router.get("/ice/selection/share")
async def get_public_selection_share(
    response: Response,
    city_id: int = Query(...),
    venue_type: str | None = Query(None),
    when: str | None = Query(None),
    record: bool = Query(True),
    channel: str | None = Query(None),
    share_context: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    «Поделиться подборкой» из каталога (TASK-146): ссылка на /c/{город}?t=&w= — ровно
    та выборка, что на экране (город, тип места, окно времени). Тот же контракт, что у
    шеринга места; превью — og.png подборки.
    """
    from src.application.selection_page import (
        clean_venue,
        clean_when,
        compose_selection_share,
        load_selection_view,
        selection_image_path,
        selection_image_version,
        selection_path,
    )

    response.headers["Cache-Control"] = "no-store"
    row = (
        await session.execute(text(f"SELECT id, name FROM cities WHERE id = :cid AND {public_city_scope_sql('cities')}"),
            {"cid": int(city_id), **public_scope_params()},)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="City not found")
    city = {"id": int(row[0]), "name": str(row[1])}
    venue, window_key = clean_venue(venue_type), clean_when(when)
    if window_key is None and (when or "").strip().lower() == "auto":
        from src.application.ice_time_windows import resolve_window

        resolved = resolve_window("auto")
        window_key = resolved.key if resolved else None
    view = await load_selection_view(session, city=city, venue=venue, when=window_key)
    base = (Settings().webapp_base_url or "").rstrip("/")
    page_url = base + selection_path(city_name=city["name"], venue=venue, when=window_key)
    payload = compose_selection_share(view, page_url=page_url)
    if record:
        ch = (channel or "").strip().lower()
        await record_client_share(
            session,
            kind=CLIENT_SHARE_KIND_SELECTION,
            share_context=(share_context or "ice_list").strip().lower()[:40],
            city_id=city["id"],
            payload={"venue_type": venue, "when": window_key, "channel": ch if ch in _SHARE_CHANNELS else None},
        )
    # ?v= — хэш данных превью (число мест, сеансов и день): Telegram кэширует og-картинку по URL.
    image = base + selection_image_path(
        city_name=city["name"], venue=venue, when=window_key, version=selection_image_version(view)
    )
    story = image.replace("/og.png", "/story.png")
    return {**payload, "og_image_url": image, "story_image_url": story, "venue_type": venue, "when": window_key}


@router.get("/arenas/{arena_ref}/share")
async def get_public_place_share(
    arena_ref: str,
    response: Response,
    session_id: int | None = Query(None, description="Сеанс, которым делятся (ссылка ведёт прямо на него)."),
    invite: bool = Query(False, description="Тон «Позвать с собой» вместо «Расписание»."),
    share_context: str | None = Query(None, description="Где нажали: arena_card, ice_list, hub."),
    record: bool = Query(True, description="false — предпросмотр в шите: показать, но не считать шерингом."),
    channel: str | None = Query(None, description="Канал: telegram | copy | story | system."),
    city_id: int | None = Query(None),
    city: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Готовое сообщение для шеринга места (TASK-146): ссылка на публичную страницу
    ``/p/{city}/{slug}``, а не на бота — у страницы своё превью, и она открывается
    в любом мессенджере без Telegram.

    Контракт тот же, что у ``/ice/share`` и ``share-trainer``. Плюс ``story_image_url``
    для «Сохранить картинку» (истории Instagram/VK) и ``invite_*`` — тот же текст в тоне
    «погнали?», чтобы переключатель в шит-оверлее не ходил на сервер второй раз.

    Публичная ручка: кто поделился, не знает (``actor_hash = NULL``), как и ``/ice/share``.

    Шит «Поделиться» сначала показывает превью (``record=false`` — переключатели и выбор
    сеанса не должны раздувать счётчик), а событие пишет по нажатию канала: одна строка ==
    одно намерение отправить, с каналом в ``payload.channel`` (Q-007: что реально шерят и куда).
    """
    response.headers["Cache-Control"] = "no-store"
    scoped = await _slug_city_id(session, arena_ref, city_id, city)
    view = await load_place_view(session, arena_ref, session_id=session_id, city_id=scoped)
    if view is None or not view["card"].get("slug"):
        raise HTTPException(status_code=404, detail="Arena not found")
    card = view["card"]
    base = Settings().webapp_base_url
    city_name = str(card.get("city_name") or "")
    focus_id = int(view["focus"]["id"]) if view.get("focus") is not None else None
    url_kwargs = {"base_url": base, "city_name": city_name, "slug": str(card["slug"]), "session_id": focus_id}
    plain = share_payload(view, page_url=place_page_url(**url_kwargs), invite=False)
    invited = share_payload(view, page_url=place_page_url(**url_kwargs, invite=True), invite=True)
    chosen = invited if invite else plain

    ctx = (share_context or "").strip().lower()[:40] or "arena_card"
    if record:
        ch = (channel or "").strip().lower()
        await record_client_share(
            session,
            kind=CLIENT_SHARE_KIND_PLACE,
            share_context=ctx,
            city_id=int(card["city_id"]),
            arena_id=int(card["id"]),
            payload={
                "venue_type": card.get("venue_type"),
                "session_id": focus_id,
                "invite": bool(invite),
                "channel": ch if ch in _SHARE_CHANNELS else None,
            },
        )
    return {
        **chosen,
        "invite_share_url": invited["share_url"],
        "invite_share_body": invited["share_body"],
        "invite_share_text": invited["share_text"],
        "place_share_url": plain["share_url"],
        "place_share_body": plain["share_body"],
        "place_share_text": plain["share_text"],
        "og_image_url": place_image_url(**url_kwargs, invite=invite),
        "story_image_url": place_image_url(**url_kwargs, invite=invite, story=True),
        "venue_type": card.get("venue_type"),
        "session_id": focus_id,
        "share_context": ctx,
    }


@router.get("/arenas/{arena_ref}")
async def get_public_arena_card_route(
    arena_ref: str,
    response: Response,
    city_id: int | None = Query(None, description="Город, если arena_ref — slug, а не id."),
    city: str | None = Query(None, description="Slug или id города. Вместе со slug арены."),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Arena card: profile, media, tier on read, honest freshness/source."""
    response.headers["Cache-Control"] = "no-store"
    scoped = await _slug_city_id(session, arena_ref, city_id, city)
    payload = await get_public_arena_card(session, arena_ref, city_id=scoped)
    if payload is None:
        raise HTTPException(status_code=404, detail="Arena not found")
    return payload
