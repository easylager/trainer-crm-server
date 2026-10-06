"""Публичный CTA-редирект и presence мини-аппа."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth import MiniAppPlatform, MiniAppPrincipal


@pytest.mark.asyncio
async def test_open_telegram_cta_records_and_redirects(app_use_test_db, db_session) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        r = await client.get(
            "/api/public/catalog/open-telegram",
            params={"startapp": "catalog", "surface": "selection_page"},
            follow_redirects=False,
        )
    assert r.status_code == 302
    assert "t.me" in r.headers.get("location", "") or "webapp" in r.headers.get("location", "")
    count = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM catalog_consumer_events WHERE kind = 'public_telegram_cta'")
        )
    ).scalar_one()
    assert int(count) >= 1


@pytest.mark.asyncio
async def test_catalog_presence_requires_init_data(app_use_test_db) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        r = await client.post(
            "/api/webapp/client/catalog/presence",
            json={"surface": "miniapp_ice", "city_id": 1},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_catalog_presence_records(app_use_test_db, db_session) -> None:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=9001)
    transport = ASGITransport(app=app)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            r = await client.post(
                "/api/webapp/client/catalog/presence",
                json={"surface": "miniapp_shell", "start_param": "catalog"},
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert body.get("recorded") is True
    count = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM catalog_consumer_events WHERE kind = 'miniapp_catalog_entry'"
            )
        )
    ).scalar_one()
    assert int(count) >= 1


@pytest.mark.asyncio
async def test_catalog_presence_marks_share_open_and_derives_city(app_use_test_db, db_session, monkeypatch) -> None:
    """TASK-189: признак share-open считается из подписанной initData и пишется в payload;
    город берётся из арены диплинка, даже если клиент прислал только start_param."""
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "test-catalog-actor-secret-0123456789abcdef")
    city_id = (
        await db_session.execute(
            text(
                "INSERT INTO cities (name, country, price_group, is_active, sort_order) "
                "VALUES ('Тест-189-api', 'BY', 'default', true, 0) RETURNING id"
            )
        )
    ).scalar_one()
    arena_id = (
        await db_session.execute(
            text(
                "INSERT INTO arenas (city_id, name, address, is_active, is_confirmed) "
                "VALUES (:c, 'Арена-189-api', 'ул. 1', true, true) RETURNING id"
            ),
            {"c": city_id},
        )
    ).scalar_one()
    await db_session.flush()
    transport = ASGITransport(app=app)
    calls = [
        (9101, f"chat_type=group&start_param=arena_{arena_id}&hash=x", True),
        (9102, f"start_param=arena_{arena_id}&hash=x", False),  # CTA публички: из браузера, без чата
        (9103, "chat_type=private&start_param=catalog&hash=x", False),  # /go
    ]
    for uid, init_data, _ in calls:
        fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=uid)
        with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
            async with AsyncClient(transport=transport, base_url="https://test") as client:
                r = await client.post(
                    "/api/webapp/client/catalog/presence",
                    json={"surface": "miniapp_shell", "start_param": None},
                    headers={"X-Telegram-Init-Data": init_data},
                )
        assert r.status_code == 200, r.text
    rows = (
        await db_session.execute(
            text(
                "SELECT city_id, arena_id, start_param, (payload->>'share_deeplink')::boolean AS share "
                "FROM catalog_consumer_events WHERE kind = 'miniapp_catalog_entry' ORDER BY id"
            )
        )
    ).all()
    tail = rows[-3:]
    assert [r.share for r in tail] == [expected for _, _, expected in calls]
    assert tail[0].city_id == city_id and tail[0].arena_id == arena_id
    assert tail[2].start_param == "catalog" and tail[2].city_id is None
