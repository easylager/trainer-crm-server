"""TASK-428 (слой A): API предложения подписки — один раз на актёра и каток, подписанным нет, воронка в событиях."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.catalog_consumer_events import telegram_actor_hash
from src.application.place_page import watch_offer_site_html
from tests.api.test_client_ice_watches import _fresh_client_telegram_id, _insert_city, _insert_client
from tests.api.test_webapp_client_miniapp_integration import _client_auth_headers, patch_client_init_auth

SECRET = "o" * 40
UA = {"user-agent": "Mozilla/5.0 (iPhone) Safari"}


@pytest.fixture(autouse=True)
def _secret(monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", SECRET)


async def _arena(db_session) -> int:
    city_id = await _insert_city(db_session)
    arena = (
        await db_session.execute(
            text("""
                INSERT INTO arenas (city_id, name, latitude, longitude, is_active, is_confirmed, venue_type)
                VALUES (:cid, 'Offer Rink', 53.9, 27.5, true, true, 'ice') RETURNING id
                """),
            {"cid": city_id},
        )
    ).scalar_one()
    await db_session.commit()
    return int(arena)


async def _events(db_session, arena_id: int) -> list[tuple]:
    rows = await db_session.execute(
        text("SELECT kind, surface, actor_hash FROM catalog_consumer_events WHERE arena_id = :a ORDER BY id"),
        {"a": arena_id},
    )
    return [tuple(r) for r in rows.all()]


@pytest.mark.asyncio
async def test_miniapp_offer_once_then_never(app_use_test_db, db_session) -> None:
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid)
    arena = await _arena(db_session)
    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            h = _client_auth_headers()
            first = await client.get(f"/api/webapp/client/watch-offer?arena_id={arena}", headers=h)
            assert first.json() == {"show": True} and first.headers["cache-control"] == "no-store"
            for action in ("shown", "shown", "closed"):
                r = await client.post(
                    "/api/webapp/client/watch-offer", headers=h, json={"arena_id": arena, "action": action}
                )
                assert r.status_code == 200
            again = await client.get(f"/api/webapp/client/watch-offer?arena_id={arena}", headers=h)
            assert again.json() == {"show": False}
            bad = await client.post(
                "/api/webapp/client/watch-offer", headers=h, json={"arena_id": arena, "action": "spam"}
            )
            assert bad.status_code == 400
    actor = telegram_actor_hash(tid)
    assert await _events(db_session, arena) == [
        ("watch_offer_shown", "miniapp_arena", actor),  # повтор показа не пишется
        ("watch_offer_closed", "miniapp_arena", actor),
    ]


@pytest.mark.asyncio
async def test_miniapp_offer_hidden_for_subscriber_and_subscription_recorded(app_use_test_db, db_session) -> None:
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid)
    arena = await _arena(db_session)
    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            h = _client_auth_headers()
            sub = await client.post(
                "/api/webapp/client/ice-watches",
                headers=h,
                json={"arena_id": arena, "watch_kind": "sessions", "when": "any", "origin": "offer"},
            )
            assert sub.status_code == 200, sub.text
            state = await client.get(f"/api/webapp/client/watch-offer?arena_id={arena}", headers=h)
            assert state.json()["show"] is False
    assert await _events(db_session, arena) == [("watch_offer_subscribed", "miniapp_arena", telegram_actor_hash(tid))]


@pytest.mark.asyncio
async def test_plain_bell_subscription_is_not_offer_funnel(app_use_test_db, db_session) -> None:
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid)
    arena = await _arena(db_session)
    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/webapp/client/ice-watches",
                headers=_client_auth_headers(),
                json={"arena_id": arena, "watch_kind": "sessions", "when": "any"},
            )
    assert await _events(db_session, arena) == []


@pytest.mark.asyncio
async def test_unknown_arena_never_shows(app_use_test_db, db_session) -> None:
    tid = _fresh_client_telegram_id()
    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/webapp/client/watch-offer?arena_id=999999999", headers=_client_auth_headers())
            assert r.json() == {"show": False}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/public/catalog/watch-offer?arena_id=999999999", headers=UA)
        assert r.json() == {"show": False}


@pytest.mark.asyncio
async def test_site_offer_once_per_actor(app_use_test_db, db_session) -> None:
    arena = await _arena(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(f"/api/public/catalog/watch-offer?arena_id={arena}", headers=UA)).json() == {
            "show": True
        }
        for action in ("shown", "click"):
            r = await client.post(f"/api/public/catalog/watch-offer?arena_id={arena}&action={action}", headers=UA)
            assert r.status_code == 204
        assert (await client.get(f"/api/public/catalog/watch-offer?arena_id={arena}", headers=UA)).json() == {
            "show": False
        }
        other = {"user-agent": "Mozilla/5.0 (Android) Chrome"}
        assert (await client.get(f"/api/public/catalog/watch-offer?arena_id={arena}", headers=other)).json() == {
            "show": True
        }
        bad = await client.post(f"/api/public/catalog/watch-offer?arena_id={arena}&action=x", headers=UA)
        assert bad.status_code == 400
    kinds = [k for k, _, _ in await _events(db_session, arena)]
    assert kinds == ["watch_offer_shown", "watch_offer_click"]


def test_site_script_tag_points_to_offer_start() -> None:
    html = watch_offer_site_html(42, "/api/public/catalog/open-telegram?startapp=watch_42_o&amp;x=1")
    assert 'data-surface="site"' in html and 'data-arena-id="42"' in html and "watch_42_o" in html
    assert "/static/webapp/watch-offer.js?v=" in html and "/static/webapp/watch-offer.css?v=" in html
