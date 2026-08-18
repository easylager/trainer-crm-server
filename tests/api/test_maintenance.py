"""Planned MAINTENANCE_MODE: API 503, Mini App HTML still served."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.shared.outage import SERVICE_UNAVAILABLE_CODE


@pytest.mark.asyncio
async def test_maintenance_mode_blocks_api_and_keeps_webapp_html(monkeypatch, app_use_test_db) -> None:
    monkeypatch.setenv("MAINTENANCE_MODE", "1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        api = await client.get("/api/public/cities")
        page = await client.get("/webapp/client-home")
        live = await client.get("/health/live")
        ready = await client.get("/health")
    assert api.status_code == 503
    body = api.json()
    assert body.get("code") == SERVICE_UNAVAILABLE_CODE
    assert api.headers.get("retry-after") == "60"
    assert api.headers.get("x-ice-studio-outage") == SERVICE_UNAVAILABLE_CODE
    assert page.status_code == 200
    assert "text/html" in (page.headers.get("content-type") or "")
    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json().get("status") == "maintenance"
