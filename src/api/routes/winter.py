"""Зимние точки (TASK-343): публичный список / карточка / отметка с сайта и Mini App."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.middleware.http_limits import client_ip_from_request
from src.api.middleware.scrape_guard import _allowed_hosts, request_comes_from_site
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform
from src.application import winter_asks, winter_marks, winter_photos, winter_public, winter_subscriptions
from src.shared import winter_status as ws
from src.shared.config import Settings
from src.shared.ua_class import UA_HUMAN, classify_user_agent

NO_STORE = {"Cache-Control": "no-store"}
PAGE_CACHE = {"Cache-Control": "public, max-age=120"}  # <= 5 мин (O5)

public_router = APIRouter(prefix="/api/public/winter", tags=["winter"])
webapp_router = APIRouter(tags=["winter-webapp"])


def _enabled() -> None:
    if not Settings().seasonal_rinks_enabled:
        raise HTTPException(status_code=404, detail="Not found")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Companion(BaseModel):
    kind: str = Field(max_length=8)
    value: str = Field(max_length=16)


class MarkBody(BaseModel):
    kind: str = Field(max_length=8)
    value: str = Field(max_length=16)
    token: str | None = Field(default=None, max_length=80)
    idem_key: str | None = Field(default=None, max_length=40)
    # Попутные отметки шторки «Как там сейчас?» (людей, хоккей): главная — про лёд, лимит считается один раз.
    companions: list[Companion] = Field(default_factory=list, max_length=2)
    website: str | None = Field(default=None, max_length=100)  # honeypot


def _mark_http(exc: winter_marks.MarkError) -> HTTPException:
    status = {"not_found": 404, "rate_limited": 429, "bad_value": 422, "bad_source": 422}.get(exc.code, 400)
    headers = {"Retry-After": str(exc.retry_after_sec)} if exc.retry_after_sec else None
    return HTTPException(status_code=status, detail=exc.code, headers=headers)


async def _record_companions(session, body: MarkBody, *, arena_id: int, source: str, actor: str, telegram_id: int | None, now) -> None:
    """Людей / хоккей из той же шторки. Лёд сюда не попадает: он главная отметка."""
    seen: set[str] = set()
    for c in body.companions:
        if c.kind not in (ws.KIND_CROWD, ws.KIND_HOCKEY) or c.kind in seen:
            raise HTTPException(status_code=422, detail="bad_value")
        seen.add(c.kind)
        try:
            await winter_marks.record_mark(
                session, arena_id=arena_id, kind=c.kind, value=c.value, source=source, actor=actor,
                telegram_id=telegram_id, idem_key=f"{body.idem_key}:{c.kind}" if body.idem_key else None,
                now=now, skip_site_limits=True,
            )
        except winter_marks.MarkError as exc:
            raise _mark_http(exc) from exc


def _result(res: winter_marks.MarkResult) -> dict:
    return {"ok": True, "state": res.state, "changed": res.state_changed, "quality": res.quality, "duplicate": res.duplicate}


@public_router.get("/cities/{city_id}/points")
async def list_city_points(
    city_id: int,
    lat: float | None = Query(default=None, ge=-90, le=90),
    lon: float | None = Query(default=None, ge=-180, le=180),
    kind: str | None = Query(default=None, pattern="^(rink|hockey_box)$"),
    flooded: bool = False,
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    data = await winter_public.list_points(session, city_id, now=_now(), lat=lat, lon=lon, kind=kind, only_flooded=flooded)
    from fastapi.responses import JSONResponse

    return JSONResponse(content=data, headers=PAGE_CACHE if lat is None else NO_STORE)


@public_router.get("/points/{ident}")
async def get_point(
    ident: str,
    lat: float | None = Query(default=None, ge=-90, le=90),
    lon: float | None = Query(default=None, ge=-180, le=180),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    data = await winter_public.get_point(session, ident, now=_now(), lat=lat, lon=lon)
    if data is None:
        raise HTTPException(status_code=404, detail="Not found")
    from fastapi.responses import JSONResponse

    return JSONResponse(content=data, headers=NO_STORE)  # токен отметки и «сейчас» не кэшируем


@public_router.post("/points/{arena_id}/marks")
async def post_site_mark(arena_id: int, body: MarkBody, request: Request, session: AsyncSession = Depends(get_session)):
    """Отметка с сайта без входа: POST + токен страницы + same-site + человек по UA + лимиты."""
    _enabled()
    if body.website and body.website.strip():
        raise HTTPException(status_code=400, detail="Invalid request")
    ua = request.headers.get("user-agent")
    if classify_user_agent(ua) != UA_HUMAN:
        raise HTTPException(status_code=403, detail="forbidden")
    if request_comes_from_site(dict(request.headers.raw), _allowed_hosts(Settings())) is not True:
        raise HTTPException(status_code=403, detail="forbidden")
    now = _now()
    if not winter_public.check_page_token(arena_id, body.token, now):
        raise HTTPException(status_code=403, detail="token")
    ip = client_ip_from_request(request)
    actor = winter_public.site_actor(None if ip == "unknown" else ip, ua)
    if actor is None:
        raise HTTPException(status_code=503, detail="unavailable")
    try:
        res = await winter_marks.record_mark(
            session, arena_id=arena_id, kind=body.kind, value=body.value, source=ws.SOURCE_SITE, actor=actor,
            idem_key=body.idem_key, now=now,
        )
    except winter_marks.MarkError as exc:
        raise _mark_http(exc) from exc
    await _record_companions(session, body, arena_id=arena_id, source=ws.SOURCE_SITE, actor=actor, telegram_id=None, now=now)
    await session.commit()
    return _result(res)


@public_router.post("/photos/{photo_id}/report")
async def report_photo(photo_id: int, request: Request, session: AsyncSession = Depends(get_session)):
    _enabled()
    ip = client_ip_from_request(request)
    actor = winter_public.site_actor(None if ip == "unknown" else ip, request.headers.get("user-agent"))
    if actor is None:
        raise HTTPException(status_code=503, detail="unavailable")
    await winter_photos.report_photo(session, photo_id, actor)
    await session.commit()
    return {"ok": True}


# --- Mini App --------------------------------------------------------------------
def _tg(principal: MiniAppPrincipal) -> int:
    return int(client_catalog_telegram_key(principal))


@webapp_router.post("/winter/points/{arena_id}/marks")
async def post_miniapp_mark(
    arena_id: int, body: MarkBody, session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    _enabled()
    tg = _tg(principal)
    try:
        res = await winter_marks.record_mark(
            session, arena_id=arena_id, kind=body.kind, value=body.value, source=ws.SOURCE_MINIAPP,
            actor=f"tg:{tg}", telegram_id=tg, idem_key=body.idem_key, now=_now(),
        )
    except winter_marks.MarkError as exc:
        raise _mark_http(exc) from exc
    await _record_companions(
        session, body, arena_id=arena_id, source=ws.SOURCE_MINIAPP, actor=f"tg:{tg}", telegram_id=tg, now=_now()
    )
    await session.commit()
    return _result(res)


@webapp_router.post("/winter/points/{arena_id}/gone")
async def post_gone(
    arena_id: int, session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    _enabled()
    try:
        res = await winter_marks.signal_gone(session, arena_id=arena_id, telegram_id=_tg(principal), now=_now())
    except winter_marks.MarkError as exc:
        raise _mark_http(exc) from exc
    await session.commit()
    return {"ok": True, "counted": res.counted, "reason": res.reason}


@webapp_router.post("/winter/points/{arena_id}/route-click")
async def post_route_click(
    arena_id: int, session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Клик «Маршрут»: через сутки бот спросит «Были? Как лёд?» (только после «Маршрут»)."""
    _enabled()
    scheduled = False
    if principal.platform == MiniAppPlatform.TELEGRAM:
        scheduled = await winter_asks.schedule_ask(session, _tg(principal), arena_id, _now())
        await session.commit()
    return {"ok": True, "scheduled": scheduled}


class NearBody(BaseModel):
    lat: float | None = None
    lon: float | None = None
    radius_m: int | None = None


class PointSubBody(BaseModel):
    arena_id: int


def _tg_only(principal: MiniAppPrincipal) -> int:
    if principal.platform != MiniAppPlatform.TELEGRAM:
        raise HTTPException(status_code=409, detail="channel_unsupported")
    return _tg(principal)


@webapp_router.post("/winter/subscriptions/near")
async def post_sub_near(
    body: NearBody, session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    _enabled()
    try:
        out = await winter_subscriptions.subscribe_near(session, _tg_only(principal), body.lat, body.lon, body.radius_m)
    except winter_subscriptions.SubscriptionError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    await session.commit()
    return {"ok": True, **out}


@webapp_router.post("/winter/subscriptions/point")
async def post_sub_point(
    body: PointSubBody, session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    _enabled()
    try:
        out = await winter_subscriptions.subscribe_point(session, _tg_only(principal), body.arena_id)
    except winter_subscriptions.SubscriptionError as exc:
        raise HTTPException(status_code=404, detail=exc.code) from exc
    await session.commit()
    return {"ok": True, **out}


@webapp_router.get("/winter/subscriptions")
async def get_subs(
    session: AsyncSession = Depends(get_session), principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    _enabled()
    return {"items": await winter_subscriptions.list_subscriptions(session, _tg(principal))}


@webapp_router.delete("/winter/subscriptions")
async def delete_subs(
    sub_id: int | None = None, session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    _enabled()
    n = await winter_subscriptions.unsubscribe(session, _tg(principal), sub_id=sub_id)
    await session.commit()
    return {"ok": True, "removed": n}
