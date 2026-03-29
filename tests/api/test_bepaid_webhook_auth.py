"""POST /api/webhooks/bepaid: HTTP Basic when BEPAID_* credentials are set (SEC-F1)."""
import base64

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


def _basic(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


@pytest.mark.asyncio
async def test_bepaid_webhook_401_when_credentials_configured_but_no_auth(
    app_use_test_db,
    monkeypatch,
) -> None:
    class _Cfg:
        bepaid_shop_id = "shop_1"
        bepaid_secret_key = "secret_1"

    monkeypatch.setattr("src.api.routes.webhooks.Settings", _Cfg)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/webhooks/bepaid",
            json={"transaction": {"status": "successful", "tracking_id": "x"}},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bepaid_webhook_401_when_wrong_password(
    app_use_test_db,
    monkeypatch,
) -> None:
    class _Cfg:
        bepaid_shop_id = "shop_1"
        bepaid_secret_key = "secret_1"

    monkeypatch.setattr("src.api.routes.webhooks.Settings", _Cfg)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/webhooks/bepaid",
            json={"transaction": {"status": "successful", "tracking_id": "x"}},
            headers={"Authorization": _basic("shop_1", "wrong")},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bepaid_webhook_200_without_auth_when_credentials_not_configured(
    app_use_test_db,
    monkeypatch,
) -> None:
    class _Cfg:
        bepaid_shop_id = None
        bepaid_secret_key = None

    monkeypatch.setattr("src.api.routes.webhooks.Settings", _Cfg)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/webhooks/bepaid",
            json={"transaction": {"status": "successful", "tracking_id": "unknown"}},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_bepaid_webhook_200_with_valid_basic_when_configured(
    app_use_test_db,
    monkeypatch,
) -> None:
    class _Cfg:
        bepaid_shop_id = "shop_1"
        bepaid_secret_key = "secret_1"

    monkeypatch.setattr("src.api.routes.webhooks.Settings", _Cfg)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/webhooks/bepaid",
            json={"transaction": {"status": "successful", "tracking_id": "unknown"}},
            headers={"Authorization": _basic("shop_1", "secret_1")},
        )
    assert resp.status_code == 200
