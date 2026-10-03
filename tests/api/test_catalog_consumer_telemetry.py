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
