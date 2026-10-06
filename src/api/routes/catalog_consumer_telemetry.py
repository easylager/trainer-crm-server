"""Публичная телеметрия каталога: CTA-редирект и (опционально) health для метрик."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.middleware.http_limits import client_ip_from_request
from src.application.catalog_consumer_events import (
    KIND_PUBLIC_TELEGRAM_CTA,
    classify_user_agent,
    public_actor_hash,
    record_catalog_consumer_event,
    resolve_entry_scope,
)
from src.application.place_links import is_valid_start_param, telegram_open_link
from src.shared.config import Settings

router = APIRouter(prefix="/api/public/catalog", tags=["catalog-telemetry"])

_ALLOWED_SURFACES = frozenset(
    {
        "place_page",
        "selection_page",
        "ice_city_day",
    }
)


@router.get("/open-telegram")
async def open_telegram_from_public_page(
    request: Request,
    startapp: str = Query(..., min_length=1, max_length=64),
    surface: str = Query(..., min_length=1, max_length=40),
    city_id: int | None = Query(None),
    arena_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Клик «Открыть в Telegram» с /p/, /c/, «Лёд сегодня» → учёт → редирект в Telegram."""
    settings = Settings()
    base = (settings.webapp_base_url or "").rstrip("/") or ""
    if not is_valid_start_param(startapp):
        return RedirectResponse(url=f"{base}/webapp/ice", status_code=302, headers={"Cache-Control": "no-store"})
    surf = surface.strip().lower()
    if surf not in _ALLOWED_SURFACES:
        surf = "place_page"
    user_agent = request.headers.get("user-agent")
    # city_id/arena_id из query ничем не подписаны: считаем, что сказал startapp (его же откроет
    # Telegram). Несовпадающие значения не пишем в метрики, а только помечаем.
    scope_city, scope_arena = await resolve_entry_scope(
        session, start_param=startapp, city_id=None, arena_id=None
    )
    mismatch = (city_id is not None and city_id != scope_city) or (
        arena_id is not None and arena_id != scope_arena
    )
    actor = public_actor_hash(
        client_ip=client_ip_from_request(request),
        user_agent=user_agent,
    )
    await record_catalog_consumer_event(
        session,
        kind=KIND_PUBLIC_TELEGRAM_CTA,
        surface=surf,
        actor_hash=actor,
        city_id=scope_city,
        arena_id=scope_arena,
        start_param=startapp,
        payload={"ingress": "public_cta", "ua_class": classify_user_agent(user_agent), "scope_mismatch": mismatch},
    )
    link = telegram_open_link(
        client_bot_username=settings.client_bot_username,
        mini_app_short_name=settings.client_mini_app_short_name,
        main_mini_app=settings.client_bot_main_mini_app,
        start_param=startapp,
    )
    if not link:
        base = (settings.webapp_base_url or "").rstrip("/")
        return RedirectResponse(url=f"{base}/webapp/ice", status_code=302, headers={"Cache-Control": "no-store"})
    return RedirectResponse(url=link, status_code=302, headers={"Cache-Control": "no-store"})
