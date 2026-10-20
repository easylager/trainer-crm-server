"""Защитные заголовки, robots для ресурсов страниц, HEAD у превью, Secure у cookie."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from tests.api.test_public_place_page import _place


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_every_response_gets_hsts_nosniff_and_referrer_policy() -> None:
    async with _client() as client:
        resp = await client.get("/robots.txt")
    assert resp.headers["strict-transport-security"] == "max-age=31536000"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    # Не HTML — встраивать во фрейм нечего, CSP не нужен.
    assert "content-security-policy" not in resp.headers


@pytest.mark.asyncio
async def test_robots_lets_google_load_page_photos_and_styles() -> None:
    async with _client() as client:
        text = (await client.get("/robots.txt")).text
    for line in ("Allow: /api/public/photos/", "Allow: /webapp/*.css", "Allow: /webapp/*.js", "Disallow: /api/"):
        assert line in text.splitlines()


@pytest.mark.asyncio
async def test_robots_and_sitemap_support_head() -> None:
    async with _client() as client:
        robots_head = await client.head("/robots.txt")
        sitemap_head = await client.head("/sitemap.xml")
    assert robots_head.status_code == 200
    assert sitemap_head.status_code == 200
    assert robots_head.content == b""
    assert sitemap_head.content == b""


@pytest.mark.asyncio
async def test_place_page_frames_only_in_telegram_and_cookie_is_secure(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    await db_session.commit()
    async with _client() as client:
        page = await client.get(place["path"])
        head = await client.head(place["path"] + "/og.png")
    assert page.status_code == 200
    csp = page.headers["content-security-policy"]
    assert csp.startswith("frame-ancestors 'self'") and "https://web.telegram.org" in csp
    assert "secure" in page.headers.get("set-cookie", "").lower()
    # Сервисы превью ссылок иногда сначала спрашивают HEAD.
    assert head.status_code == 200
    assert head.headers["content-type"] == "image/png"


@pytest.mark.asyncio
async def test_mini_app_html_keeps_its_own_frame_rules() -> None:
    async with _client() as client:
        resp = await client.get("/webapp/ice")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/html")
    assert "content-security-policy" not in resp.headers
    assert resp.headers["x-content-type-options"] == "nosniff"
