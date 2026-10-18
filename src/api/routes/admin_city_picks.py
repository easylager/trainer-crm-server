"""Админка подборки «Для вас»: город и три позиции."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth.deps import get_admin_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPrincipal
from src.application.city_picks import (
    city_enabled,
    compose_slots,
    list_pins,
    pin_place,
    search_city_places,
    unpin_place,
)

router = APIRouter(tags=["webapp-admin-city-picks"])


class PinBody(BaseModel):
    position: int = Field(..., ge=1, le=3)
    arena_id: int = Field(..., ge=1)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail="Место не найдено в этом городе")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.get("/admin/cities/{city_id}/for-you")
async def get_admin_for_you(
    city_id: int,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    del principal
    pins = await list_pins(session, city_id)
    slots = await compose_slots(session, city_id) if city_enabled(city_id) else [None, None, None]
    positions = []
    for index in range(3):
        position = index + 1
        pin = pins.get(position)
        shown = slots[index]
        if pin is not None:
            line = f"Закреп: {pin['name']}"
        elif shown is not None and not shown.get("pinned"):
            line = f"по алгоритму: {shown['name']}"
        else:
            line = "пусто"
        positions.append(
            {
                "position": position,
                "pin": pin,
                "line": line,
                "shown": None
                if shown is None
                else {
                    "arena_id": shown["arena_id"],
                    "name": shown["name"],
                    "kind_label": shown["kind_label"],
                    "pinned": bool(shown["pinned"]),
                },
            }
        )
    return {"city_id": int(city_id), "enabled": city_enabled(city_id), "positions": positions}


@router.get("/admin/cities/{city_id}/for-you/places")
async def get_admin_for_you_places(
    city_id: int,
    q: str = Query(""),
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    del principal
    return {"items": await search_city_places(session, city_id, q)}


@router.post("/admin/cities/{city_id}/for-you")
async def post_admin_for_you_pin(
    city_id: int,
    body: PinBody,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    del principal
    try:
        await pin_place(session, city_id, body.position, body.arena_id)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc
    return await get_admin_for_you(city_id, session=session)


@router.delete("/admin/cities/{city_id}/for-you/{position}")
async def delete_admin_for_you_pin(
    city_id: int,
    position: int,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    del principal
    try:
        await unpin_place(session, city_id, position)
    except ValueError as exc:
        raise _http_error(exc) from exc
    return await get_admin_for_you(city_id, session=session)
