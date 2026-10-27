"""Admin ice inbox: schedule screenshots from the phone, review and publish. New module — do not grow webapp.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth.deps import get_admin_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPrincipal
from src.application import admin_ice_inbox as inbox
from src.application.manual_schedule_publish import PublishBusyError

router = APIRouter(tags=["webapp-admin-ice-inbox"])

_STATUS_BY_CODE = {
    "not_found": 404, "arena_not_found": 404, "too_large": 413, "closed": 409,
    "not_parsed": 409, "publish_failed": 502,
}


def _http(exc: inbox.InboxError) -> HTTPException:
    return HTTPException(status_code=_STATUS_BY_CODE.get(exc.code, 400), detail=str(exc))


class RejectBody(BaseModel):
    note: str | None = Field(None, max_length=500)


@router.get("/admin/ice-inbox")
async def get_admin_ice_inbox(
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    return await inbox.list_inbox(session)


@router.post("/admin/ice-inbox")
async def post_admin_ice_inbox(
    arena_id: int = Form(...),
    file: UploadFile = File(...),
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    try:
        new_id = await inbox.add_upload(
            session,
            arena_id=arena_id,
            body=await file.read(),
            content_type=file.content_type or "image/jpeg",
            admin_telegram_id=int(principal.user_id),
        )
    except inbox.InboxError as exc:
        raise _http(exc) from exc
    return {"ok": True, "id": new_id}


@router.get("/admin/ice-inbox/{inbox_id:int}/image")
async def get_admin_ice_inbox_image(
    inbox_id: int,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    found = await inbox.get_image(session, inbox_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Not found")
    body, content_type = found
    return Response(content=body, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"})


@router.post("/admin/ice-inbox/{inbox_id:int}/publish")
async def post_admin_ice_inbox_publish(
    inbox_id: int,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    try:
        count = await inbox.publish(session, inbox_id)
    except inbox.InboxError as exc:
        raise _http(exc) from exc
    except PublishBusyError as exc:
        raise HTTPException(status_code=503, detail="Планировщик занят, повторите через минуту") from exc
    return {"ok": True, "published": count}


@router.post("/admin/ice-inbox/{inbox_id:int}/reject")
async def post_admin_ice_inbox_reject(
    inbox_id: int,
    body: RejectBody,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    del principal
    if not await inbox.reject(session, inbox_id, body.note):
        raise HTTPException(status_code=409, detail="Запись уже закрыта или не найдена")
    return {"ok": True}
