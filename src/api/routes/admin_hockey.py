"""Админка матчей Динамо-Минск: список и ручной ввод итога."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth.deps import get_admin_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPrincipal
from src.application.hockey_game import score_finished_matches
from src.application.hockey_matches import STATUS_REVIEW, MatchRow, list_matches, set_manual_result

router = APIRouter(tags=["webapp-admin-hockey"])


class ResultBody(BaseModel):
    home_score: int
    away_score: int
    decided_in: str


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _match_out(row: MatchRow) -> dict:
    return {
        "id": row.id,
        "home_team": row.home_team,
        "away_team": row.away_team,
        "starts_at": _iso(row.starts_at),
        "status": row.status,
        "home_score": row.home_score,
        "away_score": row.away_score,
        "decided_in": row.decided_in,
        "result_source": row.result_source,
        "review_reason": row.review_reason,
    }


@router.get("/admin/hockey/matches")
async def get_admin_hockey_matches(
    status: str = Query("all"),
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    del principal
    if status not in ("review", "all"):
        raise HTTPException(status_code=400, detail="status: review или all")
    statuses = (STATUS_REVIEW,) if status == "review" else None
    rows = await list_matches(session, statuses=statuses, limit=50)
    return {"items": [_match_out(row) for row in rows]}


@router.post("/admin/hockey/matches/{match_id}/result")
async def post_admin_hockey_result(
    match_id: int,
    body: ResultBody,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    del principal
    try:
        row = await set_manual_result(
            session,
            match_id,
            home_score=body.home_score,
            away_score=body.away_score,
            decided_in=body.decided_in,
            now=datetime.now(timezone.utc),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Матч не найден") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Очки игроков — сразу, а не на следующем тике цикла.
    await score_finished_matches(session, now=datetime.now(timezone.utc))
    await session.commit()
    return _match_out(row)


@router.get("/admin/hockey/extraliga/subscriptions")
async def get_admin_extraliga_subscriptions(
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Сводка «Позвать» по клубам Экстралиги: где подписок больше, там «Кто кого» запускаем первым."""
    del principal
    from src.application.hockey_event import kk_subscription_counts

    return {"items": await kk_subscription_counts(session)}
