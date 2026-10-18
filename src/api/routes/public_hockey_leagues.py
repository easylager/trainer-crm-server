"""Публичное превью лиги друзей: по ссылке-приглашению, без входа."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.routes.webapp_client_hockey_leagues import invite_url_for_code
from src.application.hockey_leagues import league_preview

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/hockey/leagues/{code}")
async def get_public_hockey_league(code: str, session: AsyncSession = Depends(get_session)) -> dict:
    preview = await league_preview(session, code)
    if preview is None:
        raise HTTPException(status_code=404, detail="Лига не найдена")
    return {**preview, "invite_url": invite_url_for_code(preview["invite_code"])}
