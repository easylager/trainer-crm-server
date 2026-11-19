"""API «Вечера» лиги (TASK-431): только участнику, без ключей игроков."""

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

ME, ANYA, SASHA, STRANGER = 880_431_201, 880_431_202, 880_431_203, 880_431_204


@contextmanager
def as_player(user_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_id)
    app.dependency_overrides[get_client_miniapp_principal] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_client_miniapp_principal, None)


@pytest.fixture(autouse=True)
def _league_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "GlideTestBot")


async def _match(db, starts_at: datetime, *, status: str = "final", home: str = "Юность-Минск") -> int:
    final = status == "final"
    return int(
        (
            await db.execute(
                text("""INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at, status,
                                                    home_score, away_score, decided_in, result_source)
                        VALUES ('hockeyby', 'extraliga', :mid, :h, 'Неман', :t, :st, :hs, :as_, :din, :rs) RETURNING id"""),
                {
                    "mid": uuid.uuid4().hex,
                    "h": home,
                    "t": starts_at,
                    "st": status,
                    "hs": 3 if final else None,
                    "as_": 1 if final else None,
                    "din": "regulation" if final else None,
                    "rs": "auto" if final else None,
                },
            )
        ).scalar_one()
    )


async def _pick(db, player: int, match_id: int, side: str, points: int | None) -> None:
    await db.execute(
        text("INSERT INTO hockey_picks (player_key, match_id, side, points) VALUES (:p, :m, :s, :pts)"),
        {"p": player, "m": match_id, "s": side, "pts": points},
    )


async def _league(db, members=(ME, ANYA, SASHA)) -> int:
    now = datetime.now(timezone.utc)
    for key, name in zip((ME, ANYA, SASHA, STRANGER), ("Макс", "Аня", "Саша", "Чужой")):
        await db.execute(
            text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, :n) ON CONFLICT DO NOTHING"),
            {"k": key, "n": name},
        )
    league_id = (
        await db.execute(
            text("""INSERT INTO hockey_leagues (name, invite_code, owner_key, scope, term_kind, starts_at, ends_at)
                    VALUES ('Бригада', :code, :o, 'all', 'season', :s, :e) RETURNING id"""),
            {
                "code": uuid.uuid4().hex[:8].upper(),
                "o": ME,
                "s": now - timedelta(days=30),
                "e": now + timedelta(days=60),
            },
        )
    ).scalar_one()
    for key in members:
        await db.execute(
            text("INSERT INTO hockey_league_members (league_id, player_key, joined_at) VALUES (:l, :k, :j)"),
            {"l": league_id, "k": key, "j": now - timedelta(days=20)},
        )
    return int(league_id)


@pytest.mark.asyncio
async def test_evening_for_members_only(app_use_test_db, db_session) -> None:
    db = db_session
    league_id = await _league(db)
    m = await _match(db, datetime.now(timezone.utc) - timedelta(days=3))
    await _pick(db, ME, m, "home", 50)
    await _pick(db, ANYA, m, "away", 0)
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with as_player(ME):
            r = await client.get(f"/api/webapp/client/hockey/leagues/{league_id}/evening")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["day"] and body["complete"] is True
            assert [x["display_name"] for x in body["items"]][0] == "Макс"
            assert all(x["pid"] for x in body["items"])
            assert str(ME) not in r.text and str(ANYA) not in r.text
            bad = await client.get(f"/api/webapp/client/hockey/leagues/{league_id}/evening?day=nope")
            assert bad.status_code == 422
            missing = await client.get("/api/webapp/client/hockey/leagues/999999999/evening")
            assert missing.status_code == 404
        with as_player(STRANGER):
            r = await client.get(f"/api/webapp/client/hockey/leagues/{league_id}/evening")
            assert r.status_code == 403


async def _pid(db, key: int) -> str:
    return (
        await db.execute(text("SELECT public_id FROM hockey_players WHERE player_key = :k"), {"k": key})
    ).scalar_one()


@pytest.mark.asyncio
async def test_gestures_one_per_pair_per_day_change_and_remove(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("KK_GESTURES_ENABLED", "1")
    db = db_session
    league_id = await _league(db)
    played = datetime.now(timezone.utc) - timedelta(days=3)
    m = await _match(db, played)
    for key, pts in ((ME, 50), (ANYA, 20), (SASHA, 0)):
        await _pick(db, key, m, "home", pts)
    await db.commit()
    anya, me, sasha = await _pid(db, ANYA), await _pid(db, ME), await _pid(db, SASHA)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with as_player(ME):
            ev = (await client.get(f"/api/webapp/client/hockey/leagues/{league_id}/evening")).json()
            day = ev["day"]
            url = f"/api/webapp/client/hockey/leagues/{league_id}/evening/{day}/gesture"
            # Кепка у Саши — значит, день сыгран и кепка разыгрывалась.
            assert [r["display_name"] for r in ev["items"] if r["cap"]] == ["Саша"]
            assert all(r["can_gesture"] is (not r["is_me"]) for r in ev["items"])

            r = await client.put(url, json={"to": sasha, "kind": "pen"})
            assert r.status_code == 200, r.text
            row = next(x for x in r.json()["items"] if x["display_name"] == "Саша")
            assert row["my_gesture"] == "pen" and row["gestures"] == [
                {"kind": "pen", "skin": "base", "from": "Макс", "from_me": True}
            ]

            r = await client.put(url, json={"to": sasha, "kind": "stick"})  # сменить: жест один на пару за день
            row = next(x for x in r.json()["items"] if x["display_name"] == "Саша")
            assert row["gestures"] == [{"kind": "stick", "skin": "base", "from": "Макс", "from_me": True}]

            r = await client.put(url, json={"to": sasha, "kind": None})  # снять
            row = next(x for x in r.json()["items"] if x["display_name"] == "Саша")
            assert row["gestures"] == [] and row["my_gesture"] is None

            assert (await client.put(url, json={"to": me, "kind": "stick"})).status_code == 400  # себе нельзя
            assert (await client.put(url, json={"to": "nobody", "kind": "stick"})).status_code == 400
            assert (await client.put(url, json={"to": anya, "kind": "slap"})).status_code == 422
            await client.put(url, json={"to": sasha, "kind": "pen"})
        with as_player(ANYA):
            await client.put(url, json={"to": sasha, "kind": "pen"})
            r = await client.put(url, json={"to": me, "kind": "stick"})
            mine = next(x for x in r.json()["items"] if x["display_name"] == "Макс")
            assert mine["gestures"] == [{"kind": "stick", "skin": "base", "from": "Аня", "from_me": True}]
        with as_player(STRANGER):
            assert (await client.put(url, json={"to": sasha, "kind": "pen"})).status_code == 403
        with as_player(ME):
            table = (await client.get(f"/api/webapp/client/hockey/leagues/{league_id}")).json()
            by_name = {x["display_name"]: x for x in table["items"]}
            assert (by_name["Саша"]["penalty_minutes"], by_name["Саша"]["caps"]) == (4, 1)
            assert by_name["Макс"]["sticks"] == 1 and by_name["Аня"]["penalty_minutes"] == 0


@pytest.mark.asyncio
async def test_gestures_only_after_the_day_is_played(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("KK_GESTURES_ENABLED", "1")
    db = db_session
    league_id = await _league(db)
    now = datetime.now(timezone.utc)
    await _match(db, now - timedelta(minutes=30), status="scheduled")
    await db.commit()
    sasha = await _pid(db, SASHA)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with as_player(ME):
            ev = (await client.get(f"/api/webapp/client/hockey/leagues/{league_id}/evening")).json()
            assert ev["complete"] is False and not any(r["can_gesture"] for r in ev["items"])
            r = await client.put(
                f"/api/webapp/client/hockey/leagues/{league_id}/evening/{ev['day']}/gesture",
                json={"to": sasha, "kind": "pen"},
            )
            assert r.status_code == 409
            r = await client.put(
                f"/api/webapp/client/hockey/leagues/{league_id}/evening/2026-01-01/gesture",
                json={"to": sasha, "kind": "pen"},
            )
            assert r.status_code == 409  # не день лиги


@pytest.mark.asyncio
async def test_gestures_off_by_default_hide_everywhere(app_use_test_db, db_session, monkeypatch) -> None:
    """Владелец убрал жесты из релиза 19.11: без KK_GESTURES_ENABLED их нет ни в вечере, ни в таблице, ни в API."""
    monkeypatch.delenv("KK_GESTURES_ENABLED", raising=False)
    db = db_session
    league_id = await _league(db)
    m = await _match(db, datetime.now(timezone.utc) - timedelta(days=3))
    for key, pts in ((ME, 50), (ANYA, 20), (SASHA, 0)):
        await _pick(db, key, m, "home", pts)
    await db.commit()
    sasha = await _pid(db, SASHA)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with as_player(ME):
            monkeypatch.setenv("KK_GESTURES_ENABLED", "1")
            ev = (await client.get(f"/api/webapp/client/hockey/leagues/{league_id}/evening")).json()
            url = f"/api/webapp/client/hockey/leagues/{league_id}/evening/{ev['day']}/gesture"
            assert (await client.put(url, json={"to": sasha, "kind": "pen"})).status_code == 200
            monkeypatch.delenv("KK_GESTURES_ENABLED")

            ev = (await client.get(f"/api/webapp/client/hockey/leagues/{league_id}/evening")).json()
            assert ev["gestures_on"] is False
            assert not any(r["can_gesture"] or r["gestures"] or r["my_gesture"] for r in ev["items"])
            assert (await client.put(url, json={"to": sasha, "kind": "stick"})).status_code == 404
            table = (await client.get(f"/api/webapp/client/hockey/leagues/{league_id}")).json()
            saved = next(x for x in table["items"] if x["display_name"] == "Саша")
            assert saved["penalty_minutes"] == 0 and saved["caps"] == 1


@pytest.mark.asyncio
async def test_captain_gives_outfit_seen_in_league_table_and_standings(app_use_test_db, db_session) -> None:
    """Право капитана (TASK-432): выдача через API, голова и «C» в таблице лиги, экипировка в общей таблице."""
    db = db_session
    league_id = await _league(db)
    m = await _match(db, datetime.now(timezone.utc) - timedelta(days=3))
    for key, pts in ((ME, 50), (ANYA, 20), (SASHA, 0)):
        await _pick(db, key, m, "home", pts)
    await db.commit()
    anya, sasha = await _pid(db, ANYA), await _pid(db, SASHA)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with as_player(ANYA):
            ev = (await client.get(f"/api/webapp/client/hockey/leagues/{league_id}/evening")).json()
            url = f"/api/webapp/client/hockey/leagues/{league_id}/evening/{ev['day']}/outfit"
            assert ev["captain"]["right"] is False
            assert (await client.put(url, json={"to": sasha, "item": "bag"})).status_code == 403
        with as_player(ME):
            assert (await client.put(url, json={"to": sasha, "item": "crown"})).status_code == 400
            r = await client.put(url, json={"to": sasha, "item": "bucket"})
            assert r.status_code == 200, r.text
            row = next(x for x in r.json()["items"] if x["display_name"] == "Саша")
            assert row["head"]["item"] == "bucket" and r.json()["captain"]["award"]["from_me"] is True
            table = (await client.get(f"/api/webapp/client/hockey/leagues/{league_id}")).json()
            by = {x["display_name"]: x for x in table["items"]}
            assert by["Саша"]["head"]["item"] == "bucket" and by["Макс"]["captain"] is True
            assert by["Аня"]["head"] is None and not by["Аня"]["captain"]
            # Себе — тоже можно; «me» в общей таблице есть всегда, если ходил: там и проверяем экипировку снаружи.
            assert (await client.put(url, json={"to": await _pid(db, ME), "item": "foil"})).status_code == 200
            standings = (await client.get("/api/webapp/client/hockey/standings")).json()
            assert standings["me"]["outfit"]["item"] == "foil"
            assert [(x["item"], x["n"]) for x in standings["me"]["outfit"]["items"]] == [("foil", 1)]
            assert all(x["outfit"] is None for x in standings["items"] if x["pid"] == anya)
        with as_player(STRANGER):
            assert (await client.put(url, json={"to": sasha, "item": "bag"})).status_code == 403


@pytest.mark.asyncio
async def test_outfit_off_switch(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("KK_CAPTAIN_ENABLED", "0")
    db = db_session
    league_id = await _league(db)
    m = await _match(db, datetime.now(timezone.utc) - timedelta(days=3))
    for key, pts in ((ME, 50), (ANYA, 20), (SASHA, 0)):
        await _pick(db, key, m, "home", pts)
    await db.commit()
    sasha = await _pid(db, SASHA)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with as_player(ME):
            ev = (await client.get(f"/api/webapp/client/hockey/leagues/{league_id}/evening")).json()
            assert ev["captain_on"] is False and ev["captain"]["right"] is False
            r = await client.put(
                f"/api/webapp/client/hockey/leagues/{league_id}/evening/{ev['day']}/outfit",
                json={"to": sasha, "item": "bag"},
            )
            assert r.status_code == 404
