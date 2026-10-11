"""Public invite card API (TASK-231). Routes stay thin; rules live in ice_invites."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.catalog_share_actor import catalog_share_actor
from src.api.deps import get_session
from src.api.miniapp_auth.deps import get_optional_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPrincipal
from src.application.ice_invites import InviteRejected, answer_invite, create_invite, get_invite, get_invite_status

router = APIRouter(prefix="/api/public", tags=["public-invites"])


class CreateInviteBody(BaseModel):
    session_id: int
    to_name: str | None = None
    from_name: str
    show_price: bool = False
    parent_code: str | None = None


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


@router.post("/invites", status_code=201)
async def post_public_invite(
    body: CreateInviteBody,
    request: Request,
    response: Response,
    principal: MiniAppPrincipal | None = Depends(get_optional_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    _no_store(response)
    _, actor_hash = catalog_share_actor(principal, request)
    try:
        return await create_invite(
            session,
            session_id=body.session_id,
            to_name=body.to_name,
            from_name=body.from_name,
            show_price=body.show_price,
            parent_code=body.parent_code,
            creator_actor_hash=actor_hash,
        )
    except InviteRejected as exc:
        raise _http(exc) from exc


@router.get("/invites/{code}")
async def get_public_invite(
    code: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
    x_zovi_device: str | None = Header(None, alias="X-Zovi-Device"),
) -> dict:
    _no_store(response)
    try:
        return await get_invite(session, code, device_token=x_zovi_device)
    except InviteRejected as exc:
        raise _http(exc) from exc


@router.post("/invites/{code}/answer")
async def post_public_invite_answer(
    code: str,
    body: AnswerInviteBody,
    request: Request,
    response: Response,
    principal: MiniAppPrincipal | None = Depends(get_optional_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _no_store(response)
    _, actor_hash = catalog_share_actor(principal, request)
    try:
        return await answer_invite(
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
