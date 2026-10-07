"""POST/DELETE /api/webapp/client/arena-follows — подписка из Mini App (initData)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.application.arena_follows import SOURCE_MINIAPP, follow_arena, unfollow_arena

router = APIRouter(tags=["webapp"])


class ArenaFollowBody(BaseModel):
    arena_id: int = Field(gt=0)


@router.post("/client/arena-follows")
async def post_client_arena_follow(
    body: ArenaFollowBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> dict:
    """Тот же эффект, что deep link ``follow_<id>``. Повтор — без второй строки."""
    reply = await follow_arena(
        session,
        telegram_id=client_catalog_telegram_key(principal),
        arena_id=body.arena_id,
        source=SOURCE_MINIAPP,
    )
    if not reply.found:
        raise HTTPException(status_code=404, detail=reply.text)
    return {
        "following": True,
        "created": reply.created,
        "arena_id": reply.arena_id,
        "arena_name": reply.arena_name,
    }


@router.delete("/client/arena-follows/{arena_id}")
async def delete_client_arena_follow(
    arena_id: int,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> dict:
    """«Отписаться» со страницы места внутри Telegram. Кнопку рисует TASK-211."""
    if arena_id <= 0:
        raise HTTPException(status_code=404, detail="Не нашли такой каток.")
    await unfollow_arena(
        session,
        telegram_id=client_catalog_telegram_key(principal),
        arena_id=arena_id,
        via="miniapp",
    )
    return {"following": False, "arena_id": arena_id}
