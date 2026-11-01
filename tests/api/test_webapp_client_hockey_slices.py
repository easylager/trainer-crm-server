"""TASK-334: API срезов — таблица клуб × период, вершины, «Если угадаешь», лиги на набор команд, «Продлить»."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.hockey_game import make_pick, score_finished_matches
from src.application.hockey_matches import set_manual_result
from tests.api.test_webapp_client_hockey import patch_client_principal

ME, B, C = 880_334_001, 880_334_002, 880_334_003


async def _match(db, starts_at, *, home="Юность", away="Неман", extraliga=True) -> int:
    return int(
        (
            await db.execute(
                text("""
                    INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at)
                    VALUES (:s, :l, :mid, :h, :a, :t) RETURNING id
                    """),
                {
                    "s": "hockeyby" if extraliga else "hcdinamo",
                    "l": "extraliga" if extraliga else "khl",
                    "mid": uuid.uuid4().hex,
                    "h": home,
                    "a": away,
                    "t": starts_at,
                },
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_standings_peaks_stakes_and_matches_filter(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=3)
    played = await _match(db_session, start)
    for who, score in ((ME, (3, 1)), (B, (2, 0)), (C, None)):
        await make_pick(
            db_session,
            player_key=who,
            display_name=f"И{who % 10}",
            match_id=played,
            home_score=None if score is None else score[0],
            away_score=None if score is None else score[1],
            side="home" if score is None else None,
            now=start - timedelta(days=1),
        )
    await set_manual_result(
        db_session, played, home_score=3, away_score=1, decided_in="regulation", now=start + timedelta(hours=3)
    )
    await score_finished_matches(db_session, now=start + timedelta(hours=3))
    upcoming = await _match(db_session, now + timedelta(days=2))
    dinamo_game = await _match(db_session, now + timedelta(days=3), home="Динамо-Минск", away="Барыс", extraliga=False)
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            default = (await client.get("/api/webapp/client/hockey/standings")).json()
            assert default["period"]["kind"] == "season" and default["club"] is None
            assert default["me"]["rank"] == 1 and default["me"]["correct_percent"] == 100
            club = (
                await client.get("/api/webapp/client/hockey/standings", params={"club": "Юность", "period": "season"})
            ).json()
            assert club["players"] == 3 and club["to_crown"] == 0
            empty = (await client.get("/api/webapp/client/hockey/standings", params={"club": "Лида"})).json()
            assert empty["items"] == [] and empty["me"] is None
            bad = await client.get("/api/webapp/client/hockey/standings", params={"period": "когда-нибудь"})
            assert bad.status_code == 400

            # Матчи: по умолчанию Динамо; клуб Экстралиги — отдельным фильтром.
            ids_default = {i["id"] for i in (await client.get("/api/webapp/client/hockey/matches")).json()["items"]}
            ids_club = {
                i["id"]
                for i in (
                    await client.get("/api/webapp/client/hockey/matches", params={"club": "Юность", "league": "all"})
                ).json()["items"]
            }
            assert dinamo_game in ids_default and upcoming not in ids_default
            assert upcoming in ids_club and dinamo_game not in ids_club

            # Ход на матч Экстралиги и козырь недели.
            put = await client.put(
                f"/api/webapp/client/hockey/matches/{upcoming}/pick", json={"side": "home", "display_name": "Я"}
            )
            assert put.status_code == 200, put.text
            dbl = await client.put(f"/api/webapp/client/hockey/matches/{upcoming}/double", json={"on": True})
            assert dbl.status_code == 200 and dbl.json()["double"]["match_id"] == upcoming
            st = (await client.get(f"/api/webapp/client/hockey/matches/{upcoming}/stakes")).json()
            assert st["points_if_winner"] == 40 and st["doubled"] is True
            assert (await client.get("/api/webapp/client/hockey/matches/99999999/stakes")).status_code == 404
            peaks = await client.get("/api/webapp/client/hockey/peaks")
            assert peaks.status_code == 200 and peaks.json() == {"items": []}  # мало ходов: вершин ещё нет


@pytest.mark.asyncio
async def test_league_with_clubs_term_preview_and_extend(app_use_test_db, db_session) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            body = {"scope": "clubs", "clubs": ["Юность", "Динамо-Минск"], "term": "weeks4"}
            preview = await client.post("/api/webapp/client/hockey/leagues/terms-preview", json=body)
            assert preview.status_code == 200 and preview.json()["few_matches"] is True
            created = await client.post(
                "/api/webapp/client/hockey/leagues", json={"name": "Две команды", "display_name": "Я", "terms": body}
            )
            assert created.status_code == 200, created.text
            league = created.json()
            assert (league["scope"], league["clubs"], league["term"]) == ("clubs", ["Юность", "Динамо-Минск"], "weeks4")
            bad = await client.post(
                "/api/webapp/client/hockey/leagues",
                json={"name": "X", "terms": {"scope": "clubs", "clubs": [], "term": "season"}},
            )
            assert bad.status_code == 400
            ext = await client.post(f"/api/webapp/client/hockey/leagues/{league['id']}/extend", json={})
            assert ext.status_code == 200 and ext.json()["created"] is True and ext.json()["id"] != league["id"]
            again = await client.post(f"/api/webapp/client/hockey/leagues/{league['id']}/extend", json={})
            assert again.json()["id"] == ext.json()["id"] and again.json()["created"] is False
        with patch_client_principal(B):
            denied = await client.post(f"/api/webapp/client/hockey/leagues/{league['id']}/extend", json={})
            assert denied.status_code == 403
