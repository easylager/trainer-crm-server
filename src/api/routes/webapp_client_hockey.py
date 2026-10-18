"""Клиентское API игры «Кто кого»: матчи с ходом, ход, общая таблица."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.application.hockey_game import (
    Pick,
    PicksClosed,
    Standing,
    make_pick,
    player_matches,
    player_standing,
    standings,
)
from src.shared.telegram_webapp import parse_user_json_from_init_data

router = APIRouter(tags=["webapp"])

_MATCH_WINDOW = timedelta(days=3)
_LIST_LIMIT = 20
_TABLE_LIMIT = 50


class PickBody(BaseModel):
    side: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    display_name: str | None = None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _pick_out(side: str, home_score: int | None, away_score: int | None, points: int | None) -> dict:
    return {
        "side": side,
        "home_score": home_score,
        "away_score": away_score,
        "points": points,
    }


def _standing_me(row: Standing | None) -> dict | None:
    if row is None:
        return None
    return {"rank": row.rank, "points": row.points, "exact": row.exact, "played": row.played}


def _player_name(display_name: str | None, init_raw: str) -> str:
    given = (display_name or "").strip()
    if given:
        return given
    user = parse_user_json_from_init_data(init_raw) or {}
    first = user.get("first_name")
    if isinstance(first, str) and first.strip():
        return first.strip()
    return ""


def _match_out(row: dict, *, now: datetime) -> dict:
    starts_at = _aware(row["starts_at"])
    played = row["status"] == "final"
    my_pick = None
    if row["pick_side"] is not None:
        my_pick = _pick_out(row["pick_side"], row["pick_home_score"], row["pick_away_score"], row["pick_points"])
    return {
        "id": row["id"],
        "home_team": row["home_team"],
        "away_team": row["away_team"],
        "starts_at": starts_at.isoformat(),
        "status": row["status"],
        "open": row["status"] == "scheduled" and now < starts_at,
        "result": (
            {
                "home_score": row["home_score"],
                "away_score": row["away_score"],
                "decided_in": row["decided_in"],
            }
            if played
            else None
        ),
        "my_pick": my_pick,
        "sides": {"home": row["home_picks"], "away": row["away_picks"]},
    }


@router.get("/client/hockey/matches")
async def get_client_hockey_matches(
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    rows = await player_matches(session, player_key, since=now - _MATCH_WINDOW, limit=_LIST_LIMIT)
    me = await player_standing(session, player_key, now=now)
    return {"items": [_match_out(row, now=now) for row in rows], "me": _standing_me(me)}


@router.put("/client/hockey/matches/{match_id}/pick")
async def put_client_hockey_pick(
    match_id: int,
    body: PickBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    now = datetime.now(timezone.utc)
    init_raw = (init_data or x_telegram_init_data or "").strip()
    try:
        pick: Pick = await make_pick(
            session,
            player_key=client_catalog_telegram_key(principal),
            display_name=_player_name(body.display_name, init_raw),
            match_id=match_id,
            side=body.side,
            home_score=body.home_score,
            away_score=body.away_score,
            now=now,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Матч не найден") from exc
    except PicksClosed as exc:
        raise HTTPException(status_code=409, detail="Матч уже начался") from exc
    await session.commit()
    return {"my_pick": _pick_out(pick.side, pick.home_score, pick.away_score, pick.points)}


@router.get("/client/hockey/standings")
async def get_client_hockey_standings(
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    rows = await standings(session, now=now, limit=_TABLE_LIMIT)
    me = await player_standing(session, player_key, now=now)
    return {
        "items": [
            {
                "rank": row.rank,
                "display_name": row.display_name,
                "points": row.points,
                "exact": row.exact,
                "played": row.played,
                "is_me": row.player_key == player_key,
            }
            for row in rows
        ],
        "me": _standing_me(me),
    }
