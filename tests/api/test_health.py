"""Health live/ready and degraded JSON when Postgres is unreachable."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from src.api.app import app
from src.shared.outage import SERVICE_UNAVAILABLE_CODE


@pytest.mark.asyncio
async def test_health_returns_200_and_db_ok(app_use_test_db) -> None:
    """GET /health returns 200 and db: ok when DB is reachable."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert data.get("db") == "ok"


@pytest.mark.asyncio
async def test_health_live_is_200_even_if_db_is_down(monkeypatch) -> None:
    class _Boom:
        async def __aenter__(self):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("src.api.app.async_session_factory", lambda: _Boom())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        live = await client.get("/health/live")
        ready = await client.get("/health/ready")
    assert live.status_code == 200
    assert live.json().get("status") == "live"
    assert ready.status_code == 503
    body = ready.json()
    assert body.get("code") == SERVICE_UNAVAILABLE_CODE
    assert body.get("db") == "error"
    assert "техническ" in (body.get("message") or "")


@pytest.mark.asyncio
async def test_health_ready_alias_ok_when_db_up(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json().get("db") == "ok"
