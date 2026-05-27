"""Tests for public catalog-scenarios endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


@pytest.mark.asyncio
async def test_public_catalog_scenarios_returns_ice_defaults() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/public/catalog-scenarios")
    assert resp.status_code == 200
    items = resp.json().get("items") or []
    assert len(items) >= 2
    keys = {it.get("key") for it in items}
    assert "skating" in keys
    assert "from-zero" in keys
