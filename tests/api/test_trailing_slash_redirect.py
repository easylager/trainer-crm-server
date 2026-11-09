"""Завершающий слэш → 301 на https-канон без «/»."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


async def _get(path: str, headers: dict[str, str] | None = None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, headers=headers or {}, follow_redirects=False)


@pytest.mark.asyncio
async def test_trailing_slash_redirects_301_to_https_without_slash(monkeypatch) -> None:
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glideclub.by")
    r = await _get("/c/minsk/trenery/", {"x-forwarded-proto": "http"})
    assert r.status_code == 301
    assert r.headers["location"] == "https://glideclub.by/c/minsk/trenery"


@pytest.mark.asyncio
async def test_trailing_slash_keeps_query(monkeypatch) -> None:
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glideclub.by")
    r = await _get("/p/minsk/arena/?s=3&utm=x", {"host": "glideclub.by", "x-forwarded-proto": "https"})
    assert r.status_code == 301
    assert r.headers["location"] == "https://glideclub.by/p/minsk/arena?s=3&utm=x"


@pytest.mark.asyncio
async def test_cyrillic_city_path_trailing_slash_301(monkeypatch) -> None:
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glideclub.by")
    r = await _get("/c/%D0%BC%D0%B8%D0%BD%D1%81%D0%BA/", {"x-forwarded-proto": "https", "host": "glideclub.by"})
    assert r.status_code == 301
    assert r.headers["location"] == "https://glideclub.by/c/%D0%BC%D0%B8%D0%BD%D1%81%D0%BA"


@pytest.mark.asyncio
async def test_root_and_api_are_not_stripped() -> None:
    root = await _get("/")
    api = await _get("/health/live/")
    assert root.status_code != 301
    assert api.status_code != 301
