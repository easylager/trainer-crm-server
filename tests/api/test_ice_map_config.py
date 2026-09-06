"""TASK-054: public Ice map config (Yandex JS API key from env)."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


@pytest.mark.asyncio
async def test_ice_map_config_returns_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_MAPS_JS_API_KEY", "unit-test-yandex-js-key")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/public/ice/map-config")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"yandex_maps_js_api_key": "unit-test-yandex-js-key"}
    assert "Cache-Control" in resp.headers


@pytest.mark.asyncio
async def test_ice_map_config_null_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YANDEX_MAPS_JS_API_KEY", "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/public/ice/map-config")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"yandex_maps_js_api_key": None}
