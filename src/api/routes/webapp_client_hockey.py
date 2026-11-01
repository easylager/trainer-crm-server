"""Клиентское API игры «Кто кого»: матчи с ходом, ход, общая таблица."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.application.hockey_game import (
    DoubleUnavailable,
    Pick,
    PicksClosed,
    Standing,
    live_points,
    make_pick,
    my_double,
    my_doubles,
    player_matches,
    set_double,
)
from src.application.hockey_hub import hub_card, mark_result_seen
from src.application.hockey_races import (
    leader_line,
    mark_race_seen,
    race_by_id,
    race_result,
    race_summary,
)
from src.application.hockey_slices import (
    club_scope,
    crown_totals,
    parse_period,
    peaks,
    slice_rows,
    stakes,
    table_view,
)
from src.application.hockey_leagues import friends_moves, friends_picks
from src.application.hockey_teams import team_card
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


def _pick_out(
    side: str, home_score: int | None, away_score: int | None, points: int | None, doubled: bool = False
) -> dict:
    """``points`` — базовые очки хода (0…50), ``doubled`` — стоит ли на нём ×2 (TASK-335)."""
    return {
        "side": side,
        "home_score": home_score,
        "away_score": away_score,
        "points": points,
        "doubled": bool(doubled),
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
    if not isinstance(first, str) or not first.strip():
        return ""
    # «Андрей К.»: в общей таблице одних Андреев десятки, полная фамилия там не нужна.
    last = user.get("last_name")
    initial = last.strip()[:1].upper() if isinstance(last, str) and last.strip() else ""
    return f"{first.strip()} {initial}." if initial else first.strip()


def _live_out(row: dict) -> dict | None:
    """Текущий счёт идущего матча: отдельно от итога; очки игрока — «если так закончится»."""
    if row["status"] == "final" or row.get("live_home_score") is None or row.get("live_away_score") is None:
        return None
    pick_points = None
    if row["pick_side"] is not None:
        pick_points = live_points(
            side=row["pick_side"],
            home_score=row["pick_home_score"],
            away_score=row["pick_away_score"],
            live_home=row["live_home_score"],
            live_away=row["live_away_score"],
            doubled=bool(row["pick_doubled"]),
        )
    return {
        "home_score": row["live_home_score"],
        "away_score": row["live_away_score"],
        "updated_at": None if row.get("live_at") is None else _aware(row["live_at"]).isoformat(),
        "pick_points_if_ends_now": pick_points,
    }


def _match_out(
    row: dict,
    *,
    now: datetime,
    friends: dict[str, list[str]],
    final_id: int | None = None,
    moves: list[dict] | None = None,
) -> dict:
    starts_at = _aware(row["starts_at"])
    played = row["status"] == "final"
    my_pick = None
    if row["pick_side"] is not None:
        my_pick = _pick_out(
            row["pick_side"], row["pick_home_score"], row["pick_away_score"], row["pick_points"], row["pick_doubled"]
        )
    return {
        "id": row["id"],
        "home_team": row["home_team"],
        "away_team": row["away_team"],
        "home": team_card(row["home_team"]),
        "away": team_card(row["away_team"]),
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
        "friends": friends,
        "race_final": row["id"] == final_id,
        "league": row.get("league"),
        "live": _live_out(row),
        # Со стартом матча — счета друзей из моих лиг (TASK-335); до старта сервер их не отдаёт.
        "friend_moves": moves or [],
    }


@router.get("/client/hockey/matches")
async def get_client_hockey_matches(
    club: str | None = Query(None, description="только матчи клуба, дома и в гостях"),
    league: str = Query("khl", pattern="^(khl|extraliga|all)$", description="khl — Динамо (по умолчанию)"),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    rows = await player_matches(
        session,
        player_key,
        since=now - _MATCH_WINDOW,
        limit=_LIST_LIMIT,
        club=club,
        league=None if league == "all" else league,
    )
    ids = [int(row["id"]) for row in rows]
    friends = await friends_picks(session, player_key=player_key, match_ids=ids)
    moves = await friends_moves(session, player_key=player_key, match_ids=ids, now=now)
    race = await race_summary(session, now=now)
    final_id = race["final_match_id"]
    final_open = any(row["id"] == final_id and row["status"] == "scheduled" for row in rows)
    return {
        "items": [
            _match_out(row, now=now, friends=friends[int(row["id"])], final_id=final_id, moves=moves[int(row["id"])])
            for row in rows
        ],
        "me": _standing_me(await _my_season_row(session, player_key, now)),
        "race": race,
        "double": await my_double(session, player_key=player_key, now=now),
        "doubles": await my_doubles(session, player_key=player_key, now=now),
        "leader": await leader_line(session, player_key=player_key, now=now) if final_open else None,
    }


@router.get("/client/hockey/hub")
async def get_client_hockey_hub(
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await hub_card(session, client_catalog_telegram_key(principal), now=datetime.now(timezone.utc))


@router.post("/client/hockey/matches/{match_id}/seen", status_code=204)
async def post_client_hockey_result_seen(
    match_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await mark_result_seen(
        session,
        player_key=client_catalog_telegram_key(principal),
        match_id=match_id,
        now=datetime.now(timezone.utc),
    )
    await session.commit()
    return Response(status_code=204)


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
    return {"my_pick": _pick_out(pick.side, pick.home_score, pick.away_score, pick.points, pick.doubled)}


async def _my_season_row(session: AsyncSession, player_key: int, now: datetime):
    rows = await slice_rows(session, scope=club_scope(None), period=parse_period(None, now))
    return next((r for r in rows if r.player_key == player_key), None)


@router.get("/client/hockey/standings")
async def get_client_hockey_standings(
    club: str | None = Query(None, description="клуб — только его матчи; пусто — «Все»"),
    period: str = Query("season", description="season | month | 2026-11"),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Таблица среза «команда × период»: по умолчанию «Все · Сезон».

    ``me`` — ``null``, если игрок в этом срезе не ходил (новичок видит плашку, а не строку с нулём).
    """
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        chosen = parse_period(period, now)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неизвестный период") from None
    rows = await slice_rows(session, scope=club_scope(club), period=chosen)
    crowns = await crown_totals(session, league_id=None)
    view = table_view(
        rows, player_key=player_key, crowns=crowns, limit=_TABLE_LIMIT, crown_possible=chosen.kind == "month"
    )
    return {
        "club": club,
        "period": {"key": chosen.key, "kind": chosen.kind, "title": chosen.title, "ends_at": chosen.until.isoformat()},
        "race": await race_summary(session, now=now),
        **view,
    }


@router.get("/client/hockey/peaks")
async def get_client_hockey_peaks(
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """«Твои вершины»: три среза, где у игрока лучшее место. Пусто, пока нет среза с тремя игроками и тремя ходами."""
    return {"items": await peaks(session, player_key=client_catalog_telegram_key(principal), now=datetime.now(timezone.utc))}


@router.get("/client/hockey/matches/{match_id}/stakes")
async def get_client_hockey_stakes(
    match_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """«Если угадаешь» (в коде stakes): места в срезах и лигах, если угадан победитель. Оценка по текущим таблицам."""
    out = await stakes(
        session, player_key=client_catalog_telegram_key(principal), match_id=match_id, now=datetime.now(timezone.utc)
    )
    if out is None:
        raise HTTPException(status_code=404, detail="Матч не найден")
    return out


@router.get("/client/hockey/races/{race_id}/result")
async def get_client_hockey_race_result(
    race_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Итоги месяца (TASK-334): лучшая лига игрока или общая таблица, подиум, чемпионы."""
    race = await race_by_id(session, race_id)
    if race is None or race.closed_at is None:
        raise HTTPException(status_code=404, detail="race_not_closed")
    return await race_result(session, player_key=client_catalog_telegram_key(principal), race=race)


@router.post("/client/hockey/races/{race_id}/seen", status_code=204)
async def post_client_hockey_race_seen(
    race_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if await race_by_id(session, race_id) is None:
        raise HTTPException(status_code=404, detail="race_not_found")
    await mark_race_seen(
        session, player_key=client_catalog_telegram_key(principal), race_id=race_id, now=datetime.now(timezone.utc)
    )
    await session.commit()
    return Response(status_code=204)


class DoubleBody(BaseModel):
    on: bool


@router.put("/client/hockey/matches/{match_id}/double")
async def put_client_hockey_double(
    match_id: int,
    body: DoubleBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Козырь недели ×2: поставить, перенести на другой матч недели или снять до начала матча."""
    now = datetime.now(timezone.utc)
    player_key = client_catalog_telegram_key(principal)
    try:
        await set_double(session, player_key=player_key, match_id=match_id, on=body.on, now=now)
    except LookupError:
        raise HTTPException(status_code=404, detail="Матч не найден") from None
    except PicksClosed:
        raise HTTPException(status_code=409, detail="Матч уже начался") from None
    except DoubleUnavailable as exc:
        detail = {
            "no_pick": "Сначала тапни за команду",
            "used": "Козырь этой недели уже на начавшемся матче",
        }[exc.reason]
        raise HTTPException(status_code=409, detail=detail) from None
    await session.commit()
    return {
        "double": await my_double(session, player_key=player_key, now=now),
        "doubles": await my_doubles(session, player_key=player_key, now=now),
    }


class RemindBody(BaseModel):
    on: bool
    display_name: str | None = None


@router.get("/client/hockey/remind")
async def get_client_hockey_remind(
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from src.application.hockey_notices import remind_on

    return {"on": await remind_on(session, client_catalog_telegram_key(principal))}


@router.put("/client/hockey/remind")
async def put_client_hockey_remind(
    body: RemindBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
) -> dict:
    """Напоминать за час до матча и присылать итог (TASK-335). Включает только сам игрок."""
    from src.application.hockey_notices import set_remind

    name = _player_name(body.display_name, x_telegram_init_data or "")
    on = await set_remind(session, client_catalog_telegram_key(principal), body.on, display_name=name)
    await session.commit()
    return {"on": on}
