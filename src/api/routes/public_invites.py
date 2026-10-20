"""Public invite card API (TASK-231). Routes stay thin; rules live in ice_invites."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.catalog_share_actor import catalog_share_actor
from src.api.deps import get_session
from src.api.miniapp_auth.deps import get_optional_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application import hockey_event
from src.application.ice_invite_slots import list_invite_slots
from src.application.zovi_answer_push import push_answer_soon
from src.application.ice_invites import (
    InviteRejected,
    answer_invite_result,
    create_invite,
    get_invite,
    get_invite_status,
)
from src.application.zovi_funnel_events import (
    record_invite_answered,
    record_invite_beacon,
    record_invite_created,
    record_invite_opened,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["public-invites"])


class CreateInviteBody(BaseModel):
    # Ровно одно из двух: сеанс льда или домашний матч Динамо (TASK-304).
    session_id: int | None = None
    match_id: int | None = None
    to_name: str | None = None
    from_name: str
    show_price: bool = False
    parent_code: str | None = None
    # TASK-237: воронка. Всё необязательно; src и via сервер сверяет с белым списком.
    device_token: str | None = None
    src: str | None = None
    via: str | None = None


class AnswerInviteBody(BaseModel):
    device_token: str
    tries: int
    resist_ms: int
    falls: int
    tricked: bool


def _http(exc: InviteRejected) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/invites/slots")
async def get_public_invite_slots(
    response: Response,
    city_id: int | None = Query(None),
    day: date | None = Query(None, alias="date"),
    session_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Будущие сеансы города на день по Минску. ``session_id`` без города подставляет день сеанса."""
    _no_store(response)
    try:
        return await list_invite_slots(session, city_id=city_id, day=day, session_id=session_id)
    except InviteRejected as exc:
        raise _http(exc) from exc


@router.post("/invites", status_code=201)
async def post_public_invite(
    body: CreateInviteBody,
    request: Request,
    response: Response,
    principal: MiniAppPrincipal | None = Depends(get_optional_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    _no_store(response)
    if body.match_id is not None and not hockey_event.enabled():
        # Матчи живут под флагом игры: выключен — как будто их нет.
        raise HTTPException(status_code=404, detail="Не найдено")
    _, actor_hash = catalog_share_actor(principal, request)
    try:
        created = await create_invite(
            session,
            session_id=body.session_id,
            match_id=body.match_id,
            to_name=body.to_name,
            from_name=body.from_name,
            show_price=body.show_price,
            parent_code=body.parent_code,
            creator_actor_hash=actor_hash,
            # Ответ придёт пушем, только если открытку собрали в Telegram (не MAX).
            creator_telegram_id=(
                int(principal.user_id)
                if principal is not None and principal.platform == MiniAppPlatform.TELEGRAM
                else None
            ),
        )
    except InviteRejected as exc:
        raise _http(exc) from exc
    await record_invite_created(
        session,
        code=created["code"],
        actor_hash=actor_hash,
        device_token=body.device_token,
        src=body.src,
        via=body.via,
    )
    return created


@router.get("/invites/{code}")
async def get_public_invite(
    code: str,
    response: Response,
    request: Request,
    src: str | None = Query(None, max_length=16),
    session: AsyncSession = Depends(get_session),
    x_zovi_device: str | None = Header(None, alias="X-Zovi-Device"),
) -> dict:
    _no_store(response)
    try:
        card = await get_invite(session, code, device_token=x_zovi_device)
    except InviteRejected as exc:
        raise _http(exc) from exc
    # Этот вызов делает JS страницы, а не превью-бот: здесь «открыто» считается.
    _, actor_hash = catalog_share_actor(None, request)
    await record_invite_opened(session, code=code, actor_hash=actor_hash, device_token=x_zovi_device, src=src)
    return card


@router.post("/invites/{code}/answer")
async def post_public_invite_answer(
    code: str,
    body: AnswerInviteBody,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    principal: MiniAppPrincipal | None = Depends(get_optional_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _no_store(response)
    _, actor_hash = catalog_share_actor(principal, request)
    try:
        answer, inserted, answer_id = await answer_invite_result(
            session,
            code,
            device_token=body.device_token,
            tries=body.tries,
            resist_ms=body.resist_ms,
            falls=body.falls,
            tricked=body.tricked,
            responder_actor_hash=actor_hash,
        )
    except InviteRejected as exc:
        raise _http(exc) from exc
    if inserted:
        await record_invite_answered(
            session,
            code=code,
            actor_hash=actor_hash,
            device_token=body.device_token,
            tries=answer["tries"],
            tricked=answer["tricked"],
        )
        # Создателю — билет от бота, после ответа: получатель не ждёт Telegram.
        background.add_task(push_answer_soon, answer_id)
    return answer


@router.post("/invites/{code}/event", status_code=204)
async def post_public_invite_event(
    code: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Маячок страницы открытки (TASK-237): ``{kind, device_token, act?}``.

    Всегда 204: маячку нечем обработать ошибку, а воронка не должна ломать открытку. Тело читаем
    сами — ``sendBeacon`` шлёт его с любым Content-Type.
    """
    try:
        data: Any = json.loads((await request.body()) or b"{}")
        if isinstance(data, dict):
            _, actor_hash = catalog_share_actor(None, request)
            await record_invite_beacon(
                session,
                code=code,
                kind=data.get("kind"),
                device_token=data.get("device_token"),
                act=data.get("act"),
                actor_hash=actor_hash,
            )
    except Exception:  # noqa: BLE001
        logger.warning("zovi invite event dropped", exc_info=True)
    return Response(status_code=204)


@router.get("/invites/{code}/status")
async def get_public_invite_status(
    code: str,
    response: Response,
    key: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _no_store(response)
    try:
        return await get_invite_status(session, code, key=key)
    except InviteRejected as exc:
        raise _http(exc) from exc
