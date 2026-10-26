"""Клиентское API «Кто кого»: матчи, ход, таблица."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.deps import get_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.hockey_game import score_finished_matches
from src.application.hockey_matches import set_manual_result

ME = 880_297_001
OTHER = 880_297_002


@contextmanager
def patch_client_principal(user_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_id)
    app.dependency_overrides[get_client_miniapp_principal] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_client_miniapp_principal, None)


async def _insert_match(db_session, *, starts_at: datetime, status: str = "scheduled") -> int:
    mid = uuid.uuid4().hex
    return int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO hockey_matches (
                        source, source_match_id, home_team, away_team, starts_at, status
                    )
                    VALUES ('hcdinamo', :mid, 'Динамо-Минск', 'Барыс', :starts_at, :status)
                    RETURNING id
                    """),
                {"mid": mid, "starts_at": starts_at, "status": status},
            )
        ).scalar_one()
    )


def _by_id(body: dict, match_id: int) -> dict:
    return next(item for item in body["items"] if item["id"] == match_id)


@pytest.mark.asyncio
async def test_matches_show_own_pick_open_result_and_sides(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    future = await _insert_match(db_session, starts_at=now + timedelta(days=1))
    started = await _insert_match(db_session, starts_at=now - timedelta(hours=2))
    played = await _insert_match(db_session, starts_at=now - timedelta(hours=5))
    await set_manual_result(db_session, played, home_score=1, away_score=4, decided_in="regulation", now=now)
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            mine = await client.put(
                f"/api/webapp/client/hockey/matches/{future}/pick",
                json={"side": "home", "display_name": "Саша"},
            )
            assert mine.status_code == 200, mine.text
        with patch_client_principal(OTHER):
            theirs = await client.put(
                f"/api/webapp/client/hockey/matches/{future}/pick",
                json={"side": "away", "display_name": "Катя"},
            )
            assert theirs.status_code == 200, theirs.text

        with patch_client_principal(ME):
            listed = await client.get("/api/webapp/client/hockey/matches")
        assert listed.status_code == 200, listed.text
        body = listed.json()
        own = _by_id(body, future)
        assert own["open"] is True
        assert own["my_pick"] == {"side": "home", "home_score": None, "away_score": None, "points": None}
        assert own["result"] is None
        assert own["sides"] == {"home": 1, "away": 1}
        assert own["home_team"] == "Динамо-Минск"
        assert own["away_team"] == "Барыс"
        assert own["home"]["short"] == "ДМ"
        assert own["home"]["color"].startswith("#")
        assert own["home"]["logo"] == "/static/webapp/hockey-logos/dinamo-minsk.png"
        assert own["away"]["short"] == "БР"
        assert own["away"]["logo"] == "/static/webapp/hockey-logos/barys.png"
        assert _by_id(body, started)["open"] is False
        assert _by_id(body, started)["my_pick"] is None
        finished = _by_id(body, played)
        assert finished["open"] is False
        assert finished["result"] == {"home_score": 1, "away_score": 4, "decided_in": "regulation"}

        with patch_client_principal(OTHER):
            other_list = await client.get("/api/webapp/client/hockey/matches")
        assert other_list.status_code == 200, other_list.text
        foreign = _by_id(other_list.json(), future)
        assert foreign["my_pick"] == {"side": "away", "home_score": None, "away_score": None, "points": None}
        assert foreign["sides"] == {"home": 1, "away": 1}


@pytest.mark.asyncio
async def test_pick_side_exact_replace_and_errors(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    future = await _insert_match(db_session, starts_at=now + timedelta(days=1))
    started = await _insert_match(db_session, starts_at=now - timedelta(minutes=1))
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.put(f"/api/webapp/client/hockey/matches/{future}/pick", json={"side": "home"})
        assert denied.status_code in (401, 403)

        with patch_client_principal(ME):
            side = await client.put(
                f"/api/webapp/client/hockey/matches/{future}/pick",
                json={"side": "home"},
            )
            assert side.status_code == 200, side.text
            assert side.json()["my_pick"]["side"] == "home"

            exact = await client.put(
                f"/api/webapp/client/hockey/matches/{future}/pick",
                json={"home_score": 1, "away_score": 4},
            )
            assert exact.status_code == 200, exact.text
            assert exact.json()["my_pick"] == {
                "side": "away",
                "home_score": 1,
                "away_score": 4,
                "points": None,
            }

            draw = await client.put(
                f"/api/webapp/client/hockey/matches/{future}/pick",
                json={"home_score": 2, "away_score": 2},
            )
            assert draw.status_code == 400
            assert draw.json()["detail"] == "В хоккее ничьих нет"

            closed = await client.put(
                f"/api/webapp/client/hockey/matches/{started}/pick",
                json={"side": "home"},
            )
            assert closed.status_code == 409
            assert closed.json()["detail"] == "Матч уже начался"

            missing = await client.put(
                "/api/webapp/client/hockey/matches/987654321/pick",
                json={"side": "home"},
            )
            assert missing.status_code == 404
            assert missing.json()["detail"] == "Матч не найден"

            named = await client.put(
                f"/api/webapp/client/hockey/matches/{future}/pick",
                headers={"X-Telegram-Init-Data": "user=" + quote(json.dumps({"id": ME, "first_name": "Маша"}))},
                json={"side": "home"},
            )
            assert named.status_code == 200, named.text

    count = (
        await db_session.execute(text("SELECT COUNT(*) FROM hockey_picks WHERE match_id = :m"), {"m": future})
    ).scalar_one()
    assert count == 1
    stored = (
        await db_session.execute(
            text("""
                SELECT side, home_score, away_score, display_name
                FROM hockey_picks p
                JOIN hockey_players pl ON pl.player_key = p.player_key
                WHERE p.match_id = :m AND p.player_key = :p
                """),
            {"m": future, "p": ME},
        )
    ).one()
    assert (stored.side, stored.home_score, stored.away_score, stored.display_name) == ("home", None, None, "Маша")


@pytest.mark.asyncio
async def test_standings_points_rank_and_is_me(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    match_id = await _insert_match(db_session, starts_at=now + timedelta(hours=2))
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            exact = await client.put(
                f"/api/webapp/client/hockey/matches/{match_id}/pick",
                json={"home_score": 3, "away_score": 1, "display_name": "Саша"},
            )
            assert exact.status_code == 200, exact.text
        with patch_client_principal(OTHER):
            winner = await client.put(
                f"/api/webapp/client/hockey/matches/{match_id}/pick",
                json={"side": "home", "display_name": "Катя"},
            )
            assert winner.status_code == 200, winner.text

        await set_manual_result(db_session, match_id, home_score=3, away_score=1, decided_in="regulation", now=now)
        await score_finished_matches(db_session, now=now)
        await db_session.commit()

        with patch_client_principal(ME):
            table = await client.get("/api/webapp/client/hockey/standings")
        assert table.status_code == 200, table.text
        body = table.json()
        assert "player_key" not in table.text
        me_row = next(item for item in body["items"] if item["display_name"] == "Саша" and item["is_me"])
        other_row = next(item for item in body["items"] if item["display_name"] == "Катя")
        assert me_row["points"] == 50
        assert me_row["exact"] == 1
        assert me_row["played"] == 1
        assert other_row["points"] == 20
        assert other_row["is_me"] is False
        assert me_row["rank"] < other_row["rank"]
        assert body["me"] == {"rank": me_row["rank"], "points": 50, "exact": 1, "played": 1}
        assert sum(1 for item in body["items"] if item["is_me"]) == 1


@pytest.mark.asyncio
async def test_seen_without_a_pick_is_204(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    played = await _insert_match(db_session, starts_at=now - timedelta(hours=4))
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            seen = await client.post(f"/api/webapp/client/hockey/matches/{played}/seen")
        assert seen.status_code == 204
        assert seen.content == b""
        still = await db_session.execute(text("SELECT COUNT(*) FROM hockey_picks WHERE match_id = :m"), {"m": played})
        assert still.scalar_one() == 0


def test_player_name_from_init_data_uses_last_initial() -> None:
    import json
    from urllib.parse import urlencode

    from src.api.routes.webapp_client_hockey import _player_name

    def raw(user: dict) -> str:
        return urlencode({"user": json.dumps(user, ensure_ascii=False)})

    assert _player_name(None, raw({"first_name": "Андрей", "last_name": "козлов"})) == "Андрей К."
    assert _player_name(None, raw({"first_name": "Андрей"})) == "Андрей"
    assert _player_name("Саша", raw({"first_name": "Андрей", "last_name": "Козлов"})) == "Саша"
    assert _player_name(None, "") == ""


@pytest.mark.asyncio
async def test_month_race_result_and_seen(app_use_test_db, db_session) -> None:
    """TASK-334: итоги закрытой гонки и отметка «открыл»; незакрытая гонка — 404."""
    from src.application.hockey_game import make_pick
    from src.application.hockey_races import close_due_races, ensure_month_race, fresh_race_result
    from src.ingestion.hockey_sources import MINSK_TZ

    nov = datetime(2026, 11, 10, 12, 0, tzinfo=MINSK_TZ)
    dec = datetime(2026, 12, 1, 12, 0, tzinfo=MINSK_TZ)
    race = await ensure_month_race(db_session, now=nov)
    starts = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    match_id = await _insert_match(db_session, starts_at=starts)
    await make_pick(
        db_session,
        player_key=ME,
        display_name="Саша",
        match_id=match_id,
        home_score=3,
        away_score=1,
        now=starts - timedelta(hours=1),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            await db_session.commit()
            assert (await client.get(f"/api/webapp/client/hockey/races/{race.id}/result")).status_code == 404
    await set_manual_result(db_session, match_id, home_score=3, away_score=1, decided_in="regulation", now=dec)
    await score_finished_matches(db_session, now=dec)
    assert await close_due_races(db_session, now=dec) == [race.id]
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            body = (await client.get(f"/api/webapp/client/hockey/races/{race.id}/result")).json()
            assert (body["title"], body["won"], body["points"], body["league"]) == ("ноябрь", True, 50, None)
            seen = await client.post(f"/api/webapp/client/hockey/races/{race.id}/seen")
            assert seen.status_code == 204
    assert await fresh_race_result(db_session, player_key=ME, now=dec) is None
