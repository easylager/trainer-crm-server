"""Admin moderation of user-suggested places (PDEC-028). New module — do not grow webapp.py."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth.deps import get_admin_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPrincipal
from src.application import place_suggestion_use_cases as uc
from src.shared.config import Settings

router = APIRouter(tags=["webapp-admin-place-suggestions"])

_PREFIX = "/admin/place-suggestions"
_STATUS_BY_CODE = {"not_found": 404, "arena_not_found": 404, "closed": 409, "invalid": 400}


def _http(exc: uc.PlaceSuggestionAdminError) -> HTTPException:
    return HTTPException(status_code=_STATUS_BY_CODE.get(exc.code, 400), detail=str(exc))


class RejectBody(BaseModel):
    reason: str = Field(..., max_length=32)


class DuplicateBody(BaseModel):
    target_arena_id: int
    copy_fields: list[str] = Field(default_factory=list)


class MessageBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)


@router.get(_PREFIX)
async def get_admin_place_suggestions(
    tab: str = Query("new"),
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        return {"items": await uc.list_place_suggestions(session, tab=tab)}
    except uc.PlaceSuggestionAdminError as exc:
        raise _http(exc) from exc


@router.get(_PREFIX + "/{sid:int}")
async def get_admin_place_suggestion(
    sid: int,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        return await uc.get_place_suggestion(session, sid)
    except uc.PlaceSuggestionAdminError as exc:
        raise _http(exc) from exc


@router.patch(_PREFIX + "/{sid:int}")
async def patch_admin_place_suggestion(
    sid: int,
    fields: dict[str, Any] = Body(...),
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        return await uc.patch_place_suggestion(session, sid, fields)
    except uc.PlaceSuggestionAdminError as exc:
        raise _http(exc) from exc


@router.post(_PREFIX + "/{sid:int}/approve")
async def post_admin_place_suggestion_approve(
    sid: int,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await uc.approve_place_suggestion(session, sid, admin_id=int(principal.user_id))
    except uc.PlaceSuggestionAdminError as exc:
        raise _http(exc) from exc
    # Админский Mini App может жить не на хосте сайта — даём и полную ссылку на карточку.
    base = (Settings().webapp_base_url or "").strip().rstrip("/")
    result["public_url"] = f"{base}{result['url']}" if result.get("url") else None
    return result


@router.post(_PREFIX + "/{sid:int}/reject")
async def post_admin_place_suggestion_reject(
    sid: int,
    body: RejectBody,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        await uc.reject_place_suggestion(session, sid, body.reason)
    except uc.PlaceSuggestionAdminError as exc:
        raise _http(exc) from exc
    return {"ok": True}


@router.post(_PREFIX + "/{sid:int}/duplicate")
async def post_admin_place_suggestion_duplicate(
    sid: int,
    body: DuplicateBody,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        await uc.mark_duplicate(session, sid, body.target_arena_id, body.copy_fields)
    except uc.PlaceSuggestionAdminError as exc:
        raise _http(exc) from exc
    return {"ok": True}


@router.post(_PREFIX + "/{sid:int}/messages")
async def post_admin_place_suggestion_message(
    sid: int,
    body: MessageBody,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        return await uc.send_message_to_author(session, sid, body.body)
    except uc.PlaceSuggestionAdminError as exc:
        raise _http(exc) from exc
