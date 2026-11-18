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
