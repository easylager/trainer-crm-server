"""www.glideclub.by → glideclub.by: 301, путь и query сохраняются; остальные хосты не трогаем."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


async def _request(method: str, url: str, headers: dict[str, str]):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, url, headers=headers, follow_redirects=False)


@pytest.mark.asyncio
async def test_www_get_redirects_301_keeping_path_and_query():
    r = await _request("GET", "/c/minsk?utm=x&a=1", {"host": "www.glideclub.by"})
    assert r.status_code == 301
    assert r.headers["location"] == "https://glideclub.by/c/minsk?utm=x&a=1"
    assert "strict-transport-security" in r.headers


@pytest.mark.asyncio
async def test_www_root_and_forwarded_host():
    r = await _request("GET", "/", {"host": "internal.railway", "x-forwarded-host": "WWW.glideclub.by:443"})
    assert r.status_code == 301
    assert r.headers["location"] == "https://glideclub.by/"


@pytest.mark.asyncio
async def test_www_post_uses_308_to_keep_method():
    r = await _request("POST", "/api/anything", {"host": "www.glideclub.by"})
    assert r.status_code == 308
    assert r.headers["location"] == "https://glideclub.by/api/anything"


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["glideclub.by", "test", "www.example.com", "notwww.glideclub.by"])
async def test_other_hosts_are_not_redirected(host: str):
    r = await _request("GET", "/health", {"host": host})
    assert r.status_code != 301
    assert "location" not in r.headers
