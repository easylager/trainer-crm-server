"""Static Mini App routes for trainer profile: canonical URL, legacy redirects (Part 4)."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


@pytest.mark.asyncio
async def test_trainer_profile_readiness_redirects_to_moderation_anchor() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        resp = await client.get("/webapp/trainer-profile-readiness")
    assert resp.status_code == 302
    assert resp.headers.get("location") == "/webapp/trainer-profile#moderation"


@pytest.mark.asyncio
async def test_trainer_profile_html_alias_redirects_to_canonical() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        resp = await client.get("/webapp/trainer-profile.html")
    assert resp.status_code == 302
    assert resp.headers.get("location") == "/webapp/trainer-profile"


@pytest.mark.asyncio
async def test_trainer_profile_page_returns_html() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/webapp/trainer-profile")
    assert resp.status_code == 200
    assert "text/html" in (resp.headers.get("content-type") or "")
    assert len(resp.text) > 100
