"""TASK-359: GET /client/hockey/matches — фаза матча, очки с козырем, окно на сезон, режимы и подгрузка."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.deps import get_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.hockey_slices import week_start

ME = 880_359_001
OTHER = 880_359_002
URL = "/api/webapp/client/hockey/matches"


@contextmanager
def as_player(user_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_id)
    app.dependency_overrides[get_client_miniapp_principal] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_client_miniapp_principal, None)


async def _match(
    db,
    starts_at: datetime,
    *,
    status: str = "scheduled",
    league: str = "khl",
    probe: bool = False,
    previous: datetime | None = None,
) -> int:
    final = status == "final"
    return int(
        (
            await db.execute(
                text("""
                    INSERT INTO hockey_matches (
                        source, league, source_match_id, home_team, away_team, starts_at, status,
                        home_score, away_score, decided_in, result_source, finalized_at, result_probe,
                        previous_starts_at
                    ) VALUES (
                        :source, :league, :mid, 'Динамо-Минск', 'Барыс', :starts_at, :status,
                        :hs, :as_, :decided, :rsrc, :fin, CAST(:probe AS jsonb), :previous
                    ) RETURNING id
                    """),
                {
                    "source": "hockeyby" if league == "extraliga" else "hcdinamo",
                    "league": league,
                    "mid": uuid.uuid4().hex,
                    "starts_at": starts_at,
                    "status": status,
                    "hs": 3 if final else None,
                    "as_": 2 if final else None,
                    "decided": "regulation" if final else None,
                    "rsrc": "manual" if final else None,
                    "fin": starts_at + timedelta(hours=3) if final else None,
                    "probe": '{"home": 3, "away": 2, "decided_in": "regulation"}' if probe else None,
                    "previous": previous,
                },
            )
        ).scalar_one()
    )


async def _pick(db, match_id: int, who: int = ME, *, points: int | None = None, doubled: bool = False) -> None:
    await db.execute(
        text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, 'Игрок') ON CONFLICT DO NOTHING"),
        {"k": who},
    )
    starts_at = (
        await db.execute(text("SELECT starts_at FROM hockey_matches WHERE id = :m"), {"m": match_id})
    ).scalar_one()
    await db.execute(
        text("""
            INSERT INTO hockey_picks (match_id, player_key, side, points, doubled, trump_week)
            VALUES (:m, :k, 'home', :p, :d, :week)
            """),
        {"m": match_id, "k": who, "p": points, "d": doubled, "week": week_start(starts_at) if doubled else None},
    )


async def _get(db, params: str = "?league=all", who: int = ME) -> dict:
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with as_player(who):
            r = await client.get(URL + params)
    assert r.status_code == 200, r.text
    return r.json()


def _by_id(body: dict) -> dict[int, dict]:
    return {item["id"]: item for item in body["items"]}


@pytest.mark.asyncio
async def test_each_match_carries_phase_and_my_points_and_old_fields_stay(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    ahead = await _match(db_session, now + timedelta(days=1))
    live = await _match(db_session, now - timedelta(hours=1))
    waiting = await _match(db_session, now - timedelta(hours=5), league="extraliga", probe=True)
    played = await _match(db_session, now - timedelta(hours=9), status="final")
    stuck = await _match(db_session, now - timedelta(days=4), league="extraliga")
    cancelled = await _match(db_session, now + timedelta(days=2), status="cancelled")
    await _pick(db_session, played, points=50, doubled=True)
    await _pick(db_session, live)
    await _pick(db_session, ahead)
    await _pick(db_session, stuck)
    await _pick(db_session, cancelled)

    body = await _get(db_session)
    items = _by_id(body)
    assert {k: items[k]["phase"] for k in (ahead, live, waiting, played, stuck, cancelled)} == {
        ahead: "upcoming",
        live: "live",
        waiting: "waiting",
        played: "done",
        stuck: "waiting",
        cancelled: "cancelled",
    }
    assert items[stuck]["stale"] is True and items[waiting]["stale"] is False
    # Козырь удваивает итог, а в my_pick остаются базовые очки: по ним слова «в точку».
    assert items[played]["my_points"] == 100
    assert items[played]["my_pick"]["points"] == 50 and items[played]["my_pick"]["doubled"] is True
    assert items[live]["my_points"] is None and items[ahead]["my_points"] is None
    # Прежние поля ответа не тронуты.
    assert {"home", "away", "open", "result", "sides", "friends", "live", "friend_moves", "race_final"} <= set(
        items[ahead]
    )
    assert items[played]["result"] == {"home_score": 3, "away_score": 2, "decided_in": "regulation"}
    assert {"me", "race", "double", "doubles", "leader"} <= set(body)
    assert body["awaiting"] == 2  # идущий матч и матч впереди с моим ходом; «зависший» на четвёртые сутки не считается
    assert body["history"] == {"has_more": False, "next_before": None}


@pytest.mark.asyncio
async def test_checking_marks_a_finished_match_whose_result_is_being_confirmed(app_use_test_db, db_session) -> None:
    """«Матч окончен · сверяем счёт» — только когда итог запомнен или на проверке, а не когда матч идёт дольше трёх часов."""
    now = datetime.now(timezone.utc)
    probed = await _match(db_session, now - timedelta(hours=2), probe=True)
    review = await _match(db_session, now - timedelta(hours=4), status="review")
    long_live = await _match(db_session, now - timedelta(hours=4))
    live = await _match(db_session, now - timedelta(hours=1))
    played = await _match(db_session, now - timedelta(hours=9), status="final")
    ahead = await _match(db_session, now + timedelta(days=1))

    items = _by_id(await _get(db_session))
    assert items[probed]["phase"] == "waiting" and items[long_live]["phase"] == "waiting"
    assert {k: items[k]["checking"] for k in (probed, review, long_live, live, played, ahead)} == {
        probed: True,
        review: True,
        long_live: False,
        live: False,
        played: False,
        ahead: False,
    }


@pytest.mark.asyncio
async def test_more_than_twenty_played_matches_do_not_push_out_the_future(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    played = [await _match(db_session, now - timedelta(hours=4 + i), status="final") for i in range(25)]
    ahead = [await _match(db_session, now + timedelta(hours=2 + i)) for i in range(6)]
    live = await _match(db_session, now - timedelta(minutes=30))

    body = await _get(db_session)
    ids = set(_by_id(body))
    assert set(ahead) <= ids and live in ids
    assert len(ids & set(played)) == 12  # последняя страница истории, остальное — «Показать раньше»
    assert body["history"]["has_more"] is True

    older = await _get(db_session, "?league=all&before=" + body["history"]["next_before"])
    # Страница «раньше» — только матчи, без остального ответа.
    assert set(older) == {"items", "history"}
    assert set(_by_id(older)).isdisjoint(ids)
    assert len(older["items"]) == 12 and older["history"]["has_more"] is True
    last = await _get(db_session, "?league=all&limit=30&before=" + older["history"]["next_before"])
    assert set(_by_id(older)) | set(_by_id(last)) | (ids & set(played)) == set(played)
    assert last["history"] == {"has_more": False, "next_before": None}


@pytest.mark.asyncio
async def test_mode_mine_and_league_filter(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    mine_done = await _match(db_session, now - timedelta(hours=30), status="final")
    other_done = await _match(db_session, now - timedelta(hours=31), status="final")
    future = await _match(db_session, now + timedelta(hours=4), league="extraliga")
    await _pick(db_session, mine_done)
    await _pick(db_session, other_done, OTHER)

    assert set(_by_id(await _get(db_session, "?league=all&mode=mine"))) == {mine_done, future}
    assert set(_by_id(await _get(db_session, "?league=all&mode=all"))) == {mine_done, other_done, future}
    assert set(_by_id(await _get(db_session, "?league=extraliga&mode=all"))) == {future}
    assert set(_by_id(await _get(db_session, "?league=khl&mode=all"))) == {mine_done, other_done}


@pytest.mark.asyncio
async def test_moved_and_cancelled_rows_keep_my_move(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=1)
    moved = await _match(db_session, start, previous=start - timedelta(hours=1))
    gone = await _match(db_session, now + timedelta(days=2), status="cancelled")
    await _pick(db_session, moved)
    await _pick(db_session, gone)
    items = _by_id(await _get(db_session))
    assert items[moved]["moved_from"] is not None and items[moved]["my_pick"]["side"] == "home"
    assert items[gone]["phase"] == "cancelled" and items[gone]["my_pick"]["side"] == "home"


@pytest.mark.asyncio
async def test_bad_cursor_and_unknown_mode_are_rejected(app_use_test_db, db_session) -> None:
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with as_player(ME):
            assert (await client.get(URL + "?before=oops")).status_code == 400
            assert (await client.get(URL + "?mode=everything")).status_code == 422
            assert (await client.get(URL + "?limit=0")).status_code == 422
