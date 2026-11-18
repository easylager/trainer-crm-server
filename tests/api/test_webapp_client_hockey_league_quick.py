"""«Своя лига в один тап» (TASK-431): экран «Лига готова» и «Позвать друзей»."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.deps import get_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application import hockey_leagues
from src.application.hockey_leagues import NAME_MAX, quick_name

ME, BUSY = 880_431_301, 880_431_302
URL = "/api/webapp/client/hockey/leagues/quick"


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


def test_quick_name_is_league_of_the_player_cut_to_the_limit() -> None:
    assert quick_name("Макс") == "Лига Макс"
    assert quick_name("  Андрей   К. ") == "Лига Андрей К."
    assert quick_name("") == "Лига игрока"
    long = quick_name("Константин Константинопольский")
    assert len(long) <= NAME_MAX and long.startswith("Лига Константин")


@pytest.mark.asyncio
async def test_ready_screen_then_one_tap_league_then_reopen(app_use_test_db, db_session) -> None:
    await db_session.execute(
        text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, 'Макс')"), {"k": ME}
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with as_player(ME):
            ready = await client.get(URL)
            assert ready.status_code == 200, ready.text
            assert ready.json() == {"league_id": None, "name": "Лига Макс"}
            # Открыть экран — не значит создать лигу.
            count = await db_session.execute(
                text("SELECT COUNT(*) FROM hockey_leagues WHERE owner_key = :k"), {"k": ME}
            )
            assert count.scalar_one() == 0

            bad = await client.post(URL, json={"scope": "clubs", "clubs": []})
            assert bad.status_code == 400

            made = await client.post(
                URL, json={"scope": "clubs", "clubs": ["Неман"], "stake_text": "  на пиво ", "src": "lg2"}
            )
            assert made.status_code == 200, made.text
            league = made.json()
            assert league["created"] is True and league["name"] == "Лига Макс"
            assert (league["scope"], league["clubs"], league["term"]) == ("clubs", ["Неман"], "season")
            assert league["stake_text"] == "на пиво" and league["members"] == 1 and league["invite_url"]
            row = (
                await db_session.execute(text("SELECT src FROM hockey_leagues WHERE id = :id"), {"id": league["id"]})
            ).one()
            assert row.src == "lg2"  # лига из еженедельного приглашения различима

            again = await client.post(URL, json={"scope": "all"})
            assert again.json()["id"] == league["id"] and again.json()["created"] is False
            assert (await client.get(URL)).json() == {"league_id": league["id"], "name": "Лига Макс"}


@pytest.mark.asyncio
async def test_quick_league_respects_the_quota_and_ignores_bad_src(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setattr(hockey_leagues, "MAX_LEAGUES_PER_PLAYER", 0)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with as_player(BUSY):
            r = await client.post(URL, json={"scope": "all", "display_name": "Оля"})
            assert r.status_code == 409
    monkeypatch.setattr(hockey_leagues, "MAX_LEAGUES_PER_PLAYER", 20)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with as_player(BUSY):
            r = await client.post(URL, json={"scope": "dinamo", "display_name": "Оля", "src": "<script>"})
            assert r.status_code == 200, r.text
            assert r.json()["name"] == "Лига Оля" and r.json()["scope"] == "dinamo"
            src = await db_session.execute(
                text("SELECT src FROM hockey_leagues WHERE id = :id"), {"id": r.json()["id"]}
            )
            assert src.scalar_one() is None
