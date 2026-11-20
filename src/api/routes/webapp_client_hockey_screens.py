"""Клиентское API экранов игры «Кто кого»: клубы, один матч, «куда сдвинулась», карточка болельщика (TASK-334, S5)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.api.routes.webapp_client_hockey import _match_out
from src.application.hockey_leagues import MAX_CLUBS, friends_moves, friends_picks
from src.application.hockey_screens import clubs_catalog, fan_profile, match_movement, player_stand

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webapp"])

# Один матч, в том числе отменённый и давний: в списке /matches их нет, а экрану нужны.
_ONE_MATCH = text("""
    SELECT m.id, m.home_team, m.away_team, m.starts_at, m.status, m.league, m.arena, m.city,
           m.home_score, m.away_score, m.decided_in,
           m.live_home_score, m.live_away_score, m.live_at,
           m.previous_starts_at,
           p.side AS pick_side, p.home_score AS pick_home_score, p.away_score AS pick_away_score,
           p.points AS pick_points, COALESCE(p.doubled, false) AS pick_doubled,
           (SELECT COUNT(*) FROM hockey_picks x WHERE x.match_id = m.id AND x.side = 'home')::int AS home_picks,
           (SELECT COUNT(*) FROM hockey_picks x WHERE x.match_id = m.id AND x.side = 'away')::int AS away_picks,
           (SELECT COUNT(*) FROM hockey_picks x
            WHERE x.match_id = m.id AND x.player_key <> :player_key
              AND x.home_score = p.home_score AND x.away_score = p.away_score)::int AS same_exact
    FROM game_matches AS m
    LEFT JOIN hockey_picks AS p ON p.match_id = m.id AND p.player_key = :player_key
    WHERE m.id = :match_id
    """)


@router.get("/client/hockey/clubs")
async def get_client_hockey_clubs(
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> dict:
    """Клубы для фильтра таблицы и новой лиги: Динамо-Минск и вся Экстралига."""
    return {"items": clubs_catalog(), "max_clubs": MAX_CLUBS}


@router.get("/client/hockey/matches/{match_id}")
async def get_client_hockey_match(
    match_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    row = (await session.execute(_ONE_MATCH, {"player_key": player_key, "match_id": match_id})).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Матч не найден")
    data = dict(row._mapping)
    friends = await friends_picks(session, player_key=player_key, match_ids=[match_id])
    moves = await friends_moves(session, player_key=player_key, match_ids=[match_id], now=now)
    out = _match_out(data, now=now, friends=friends[match_id], moves=moves[match_id])
    return out


@router.get("/client/hockey/matches/{match_id}/preview")
async def get_client_hockey_match_preview(
    match_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """«Перед матчем» в игре: место, последние пять, личные встречи. Чего нет — того нет в ответе."""
    from src.application.extraliga_preview import game_preview

    return await game_preview(session, match_id)


@router.get("/client/hockey/matches/{match_id}/movement")
async def get_client_hockey_movement(
    match_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """«Куда сдвинулась»: место до и после итога в срезах матча и лигах игрока."""
    out = await match_movement(
        session, player_key=client_catalog_telegram_key(principal), match_id=match_id, now=datetime.now(timezone.utc)
    )
    if out is None:
        raise HTTPException(status_code=404, detail="Матч не найден")
    return out


@router.get("/client/hockey/players/{public_id}/stand")
async def get_client_hockey_player_stand(
    public_id: str,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Стенд другого игрока: только короны и имя. Открывается по ``pid`` из строки таблицы (TASK-430)."""
    if not 6 <= len(public_id) <= 16 or not public_id.isalnum():
        raise HTTPException(status_code=404, detail="Игрок не найден")
    out = await player_stand(session, public_id=public_id, viewer_key=client_catalog_telegram_key(principal))
    if out is None:
        raise HTTPException(status_code=404, detail="Игрок не найден")
    key = (await session.execute(_KEY_BY_PID, {"pid": public_id})).scalar_one_or_none()
    return {**out, "outfit": await _outfit_of(session, key)}


_KEY_BY_PID = text("SELECT player_key FROM hockey_players WHERE public_id = :pid")


async def _outfit_of(session: AsyncSession, player_key: int | None) -> dict | None:
    """Экипировка от капитанов лиг на стенде (TASK-432). Сбой подсчёта не роняет стенд."""
    from src.application.hockey_league_captain import outside_outfits

    if player_key is None:
        return None
    try:
        async with session.begin_nested():
            found = await outside_outfits(session, [player_key], now=datetime.now(timezone.utc))
    except Exception:  # noqa: BLE001
        logger.warning("kk stand outfit failed", exc_info=True)
        return None
    return found.get(player_key)


@router.get("/client/hockey/profile")
async def get_client_hockey_profile(
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Карточка болельщика: серия, короны, звания сезона, дуэли с людьми из общих лиг."""
    key = client_catalog_telegram_key(principal)
    out = await fan_profile(session, player_key=key, now=datetime.now(timezone.utc))
    return {**out, "outfit": await _outfit_of(session, key)}
