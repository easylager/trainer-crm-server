"""Публичная подборка и админские закрепы."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.deps import get_admin_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.city_hub_page import load_city_hub_view
from src.application.city_picks import clear_for_you_cache
from tests.application.test_city_picks import _city, _place


@pytest.fixture(autouse=True)
def _reset_for_you_cache():
    clear_for_you_cache()
    yield
    clear_for_you_cache()


@contextmanager
def patch_admin_principal(user_id: int = 4242) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_id)
    app.dependency_overrides[get_admin_miniapp_principal] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_admin_miniapp_principal, None)


def _enable(monkeypatch, city_id: int) -> None:
    monkeypatch.setenv("FOR_YOU_CITY_IDS", str(city_id))
    clear_for_you_cache()


@pytest.mark.asyncio
async def test_public_for_you_matches_city_page_and_search(app_use_test_db, db_session, monkeypatch) -> None:
    city_id, name = await _city(db_session)
    _enable(monkeypatch, city_id)
    arena_id = await _place(db_session, city_id, name="Альфа", photo=True)
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        direct = await client.get(f"/api/public/cities/{city_id}/for-you")
        search = await client.get("/api/public/ice/arenas", params={"city_id": city_id})
    assert direct.status_code == 200, direct.text
    assert search.status_code == 200, search.text
    item = direct.json()["items"][0]
    assert item["arena_id"] == arena_id
    assert item["name"] == "Альфа"
    assert item["kind_label"] == "Магазин"
    assert item["path"].startswith("/p/")
    assert item["pinned"] is False
    assert search.json()["for_you"] == direct.json()["items"]

    view = await load_city_hub_view(db_session, city={"id": city_id, "name": name, "country": "BY"})
    assert view["for_you"] == direct.json()["items"]


@pytest.mark.asyncio
async def test_admin_pin_move_and_unpin(app_use_test_db, db_session, monkeypatch) -> None:
    city_id, _name = await _city(db_session)
    _enable(monkeypatch, city_id)
    arena_id = await _place(db_session, city_id, name=f"Лезвие {uuid.uuid4().hex[:4]}", photo=True)
    other = await _place(db_session, city_id, name="Другой", venue_type="gym", photo=True)
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.get(f"/api/webapp/admin/cities/{city_id}/for-you")
        assert denied.status_code in (401, 403)

        with patch_admin_principal():
            pinned = await client.post(
                f"/api/webapp/admin/cities/{city_id}/for-you",
                json={"position": 1, "arena_id": arena_id},
            )
            assert pinned.status_code == 200, pinned.text
            assert pinned.json()["positions"][0]["pin"]["arena_id"] == arena_id
            assert pinned.json()["positions"][0]["line"].startswith("Закреп:")

            moved = await client.post(
                f"/api/webapp/admin/cities/{city_id}/for-you",
                json={"position": 2, "arena_id": arena_id},
            )
            assert moved.status_code == 200, moved.text
            rows = (
                await db_session.execute(
                    text("SELECT position, arena_id FROM city_picks WHERE city_id = :city_id ORDER BY position"),
                    {"city_id": city_id},
                )
            ).all()
            assert [(int(row[0]), int(row[1])) for row in rows] == [(2, arena_id)]

            replaced = await client.post(
                f"/api/webapp/admin/cities/{city_id}/for-you",
                json={"position": 2, "arena_id": other},
            )
            assert replaced.status_code == 200, replaced.text
            found = await client.get(
                f"/api/webapp/admin/cities/{city_id}/for-you/places",
                params={"q": "Лезвие"},
            )
            assert found.status_code == 200
            assert arena_id in [item["arena_id"] for item in found.json()["items"]]

            cleared = await client.delete(f"/api/webapp/admin/cities/{city_id}/for-you/2")
            assert cleared.status_code == 200, cleared.text
            left = (
                await db_session.execute(
                    text("SELECT COUNT(*) FROM city_picks WHERE city_id = :city_id"),
                    {"city_id": city_id},
                )
            ).scalar_one()
            assert int(left) == 0
