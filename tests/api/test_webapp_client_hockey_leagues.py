"""Клиентское и публичное API лиг друзей «Кто кого»."""

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
from src.application import hockey_leagues

ME = 880_298_001
OTHER = 880_298_002
STRANGER = 880_298_003


@contextmanager
def patch_client_principal(user_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_id)
    app.dependency_overrides[get_client_miniapp_principal] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_client_miniapp_principal, None)


def _code(invite_url: str) -> str:
    return invite_url.split("kk_", 1)[1].split("&", 1)[0].split("?", 1)[0]


def _mine(items: list[dict]) -> dict:
    flagged = [row for row in items if row["is_me"]]
    assert len(flagged) == 1
    return flagged[0]


async def _insert_match(db_session, *, starts_at: datetime) -> int:
    return int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO hockey_matches (
                        source, source_match_id, home_team, away_team, starts_at, status
                    )
                    VALUES ('hcdinamo', :mid, 'Динамо-Минск', 'Барыс', :starts_at, 'scheduled')
                    RETURNING id
                    """),
                {"mid": uuid.uuid4().hex, "starts_at": starts_at},
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_create_list_join_and_table_hides_player_key(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            created = await client.post(
                "/api/webapp/client/hockey/leagues",
                json={"name": "  Двор   на  льду  ", "display_name": "Саша"},
            )
            assert created.status_code == 200, created.text
            league = created.json()
            assert league["name"] == "Двор на льду"
            assert league["members"] == 1
            assert league["is_owner"] is True
            assert league["my_rank"] == 1
            assert league["my_points"] == 0
            assert league["invite_url"]
            assert "player_key" not in created.text
            code = _code(league["invite_url"])

            listed = await client.get("/api/webapp/client/hockey/leagues")
            assert listed.status_code == 200, listed.text
            assert listed.json()["items"] == [league]

        with patch_client_principal(OTHER):
            joined = await client.post(
                "/api/webapp/client/hockey/leagues/join",
                json={"code": code.lower(), "display_name": "Катя"},
            )
            assert joined.status_code == 200, joined.text
            assert joined.json()["id"] == league["id"]
            assert joined.json()["members"] == 2
            assert joined.json()["is_owner"] is False
            again = await client.post(
                "/api/webapp/client/hockey/leagues/join",
                json={"code": code, "display_name": "Катя"},
            )
            assert again.status_code == 200, again.text
            assert again.json()["id"] == league["id"]
            assert again.json()["members"] == 2

            table = await client.get(f"/api/webapp/client/hockey/leagues/{league['id']}")
            assert table.status_code == 200, table.text
            body = table.json()
            assert body["name"] == "Двор на льду"
            assert body["is_owner"] is False
            assert "player_key" not in table.text
            assert {row["display_name"] for row in body["items"]} == {"Саша", "Катя"}
            assert _mine(body["items"])["display_name"] == "Катя"

        with patch_client_principal(ME):
            owner_table = await client.get(f"/api/webapp/client/hockey/leagues/{league['id']}")
            assert owner_table.status_code == 200, owner_table.text
            assert "player_key" not in owner_table.text
            assert _mine(owner_table.json()["items"])["display_name"] == "Саша"
            assert owner_table.json()["is_owner"] is True


@pytest.mark.asyncio
async def test_stranger_cannot_read_and_owner_leave_moves_then_deletes(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            created = await client.post(
                "/api/webapp/client/hockey/leagues", json={"name": "Двор", "display_name": "Саша"}
            )
            assert created.status_code == 200, created.text
            league_id = created.json()["id"]
            code = _code(created.json()["invite_url"])

        with patch_client_principal(OTHER):
            joined = await client.post(
                "/api/webapp/client/hockey/leagues/join", json={"code": code, "display_name": "Катя"}
            )
            assert joined.status_code == 200, joined.text
            denied = await client.patch(f"/api/webapp/client/hockey/leagues/{league_id}", json={"name": "Чужая"})
            assert denied.status_code == 403

        with patch_client_principal(STRANGER):
            hidden = await client.get(f"/api/webapp/client/hockey/leagues/{league_id}")
            assert hidden.status_code == 403

        with patch_client_principal(ME):
            renamed = await client.patch(f"/api/webapp/client/hockey/leagues/{league_id}", json={"name": "Наш двор"})
            assert renamed.status_code == 200, renamed.text
            assert renamed.json()["name"] == "Наш двор"
            left = await client.delete(f"/api/webapp/client/hockey/leagues/{league_id}/membership")
            assert left.status_code == 200, left.text
            assert left.json() == {"result": "owner_moved"}

        with patch_client_principal(OTHER):
            owned = await client.get(f"/api/webapp/client/hockey/leagues/{league_id}")
            assert owned.status_code == 200, owned.text
            assert owned.json()["is_owner"] is True
            assert owned.json()["name"] == "Наш двор"
            gone = await client.delete(f"/api/webapp/client/hockey/leagues/{league_id}/membership")
            assert gone.status_code == 200, gone.text
            assert gone.json() == {"result": "deleted"}
            missing = await client.get(f"/api/webapp/client/hockey/leagues/{league_id}")
            assert missing.status_code == 404
            assert missing.json()["detail"] == "Лига не найдена"


@pytest.mark.asyncio
async def test_league_errors_and_limits(app_use_test_db, monkeypatch: pytest.MonkeyPatch) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            empty = await client.post("/api/webapp/client/hockey/leagues", json={"name": "   "})
            assert empty.status_code == 400
            assert empty.json()["detail"] == "Назовите лигу"
            bad = await client.post("/api/webapp/client/hockey/leagues/join", json={"code": "неттакого"})
            assert bad.status_code == 404
            assert bad.json()["detail"] == "Лига не найдена"

            monkeypatch.setattr(hockey_leagues, "MAX_LEAGUES_PER_PLAYER", 1)
            first = await client.post("/api/webapp/client/hockey/leagues", json={"name": "Одна"})
            assert first.status_code == 200, first.text
            second = await client.post("/api/webapp/client/hockey/leagues", json={"name": "Вторая"})
            assert second.status_code == 409
            assert second.json()["detail"] == "Можно состоять максимум в 20 лигах"

        monkeypatch.setattr(hockey_leagues, "MAX_MEMBERS", 1)
        with patch_client_principal(OTHER):
            full = await client.post(
                "/api/webapp/client/hockey/leagues/join",
                json={"code": _code(first.json()["invite_url"])},
            )
            assert full.status_code == 409
            assert full.json()["detail"] == "В лиге уже 100 человек"


@pytest.mark.asyncio
async def test_public_preview_without_auth(app_use_test_db, monkeypatch: pytest.MonkeyPatch) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            created = await client.post(
                "/api/webapp/client/hockey/leagues", json={"name": "Двор", "display_name": "Саша"}
            )
            assert created.status_code == 200, created.text
        code = _code(created.json()["invite_url"])

        preview = await client.get(f"/api/public/hockey/leagues/{code.lower()}")
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["name"] == "Двор"
        assert body["members"] == 1
        assert body["names"] == ["Саша"]
        assert body["invite_code"] == code
        assert "player_key" not in preview.text
        assert body["invite_url"] and f"kk_{code}" in body["invite_url"]

        monkeypatch.setenv("CLIENT_BOT_USERNAME", "")
        silent = await client.get(f"/api/public/hockey/leagues/{code}")
        assert silent.status_code == 200, silent.text
        assert silent.json()["invite_url"] is None

        missing = await client.get("/api/public/hockey/leagues/ZZZZZZZZ")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "Лига не найдена"


@pytest.mark.asyncio
async def test_match_list_shows_league_friends_only(app_use_test_db, db_session) -> None:
    match_id = await _insert_match(db_session, starts_at=datetime.now(timezone.utc) + timedelta(days=1))
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            created = await client.post(
                "/api/webapp/client/hockey/leagues", json={"name": "Двор", "display_name": "Саша"}
            )
            assert created.status_code == 200, created.text
            code = _code(created.json()["invite_url"])
            mine = await client.put(
                f"/api/webapp/client/hockey/matches/{match_id}/pick",
                json={"side": "home", "display_name": "Саша"},
            )
            assert mine.status_code == 200, mine.text

        with patch_client_principal(OTHER):
            joined = await client.post(
                "/api/webapp/client/hockey/leagues/join", json={"code": code, "display_name": "Катя"}
            )
            assert joined.status_code == 200, joined.text
            theirs = await client.put(
                f"/api/webapp/client/hockey/matches/{match_id}/pick",
                json={"side": "away", "display_name": "Катя"},
            )
            assert theirs.status_code == 200, theirs.text

        with patch_client_principal(STRANGER):
            foreign = await client.put(
                f"/api/webapp/client/hockey/matches/{match_id}/pick",
                json={"side": "home", "display_name": "Чужой"},
            )
            assert foreign.status_code == 200, foreign.text
            alone = await client.get("/api/webapp/client/hockey/matches")
            assert alone.status_code == 200, alone.text
            alone_friends = next(item for item in alone.json()["items"] if item["id"] == match_id)["friends"]
            assert alone_friends == {"home": [], "away": []}

        with patch_client_principal(ME):
            listed = await client.get("/api/webapp/client/hockey/matches")
        assert listed.status_code == 200, listed.text
        friends = next(item for item in listed.json()["items"] if item["id"] == match_id)["friends"]
        assert friends == {"home": [], "away": ["Катя"]}
