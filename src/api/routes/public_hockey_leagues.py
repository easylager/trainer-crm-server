"""Публичное превью лиги друзей и картинки карточек «Кто кого»: по ссылке, без входа."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.routes.webapp_client_hockey_leagues import invite_url_for_code
from src.application.hockey_cards import check_result_card_sig, render_league_card, render_result_card, result_verdict
from src.application.hockey_leagues import league_preview
from src.application.hockey_matches import STATUS_FINAL, get_match
from src.application.hockey_share import league_card
from src.shared.config import Settings

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/hockey/leagues/{code}")
async def get_public_hockey_league(code: str, session: AsyncSession = Depends(get_session)) -> dict:
    preview = await league_preview(session, code)
    if preview is None:
        raise HTTPException(status_code=404, detail="Лига не найдена")
    return {**preview, "invite_url": invite_url_for_code(preview["invite_code"])}


# Картинки карточек для чата (TASK-300): Telegram забирает их по адресу без initData.
card_router = APIRouter(tags=["public"])

_IMMUTABLE = {"Cache-Control": "public, max-age=604800, immutable"}


@card_router.get("/kk/r/{match_id}/{points}/{sig}.png")
async def get_result_card_png(
    match_id: int, points: int, sig: str, session: AsyncSession = Depends(get_session)
) -> Response:
    """Итог «в точку!»: адрес подписан, счёт берём из базы, а не из адреса."""
    if not check_result_card_sig(Settings().telegram_bot_token_client, match_id, points, sig):  # type: ignore[call-arg]
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    match = await get_match(session, match_id)
    if match is None or match.status != STATUS_FINAL or result_verdict(points) is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    assert match.home_score is not None and match.away_score is not None
    png = render_result_card(
        home=match.home_team,
        away=match.away_team,
        home_score=match.home_score,
        away_score=match.away_score,
        points=points,
    )
    return Response(content=png, media_type="image/png", headers=_IMMUTABLE)


@card_router.get("/kk/l/{code}.png")
async def get_league_card_png(code: str, session: AsyncSession = Depends(get_session)) -> Response:
    """Приглашение в лигу. Адрес несёт ?v= от содержимого — новая версия, новый адрес."""
    card = await league_card(session, code, now=datetime.now(timezone.utc))
    if card is None:
        raise HTTPException(status_code=404, detail="Лига не найдена")
    png = render_league_card(name=card.name, members=card.members, names=card.names, next_match=card.next_match)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})
