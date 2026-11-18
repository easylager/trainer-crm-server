"""Фавикон отвечает на HEAD (Яндекс), 120×120 в <head>, статичная строка «Актуальное расписание» на главной."""

from __future__ import annotations

from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from src.api.app import app
from src.application.catalog_home_page import HOME_ACTUAL_LINE


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/favicon.ico", "/favicon-120.png"])
async def test_favicon_get_and_head_200(path: str) -> None:
    async with _client() as client:
        head = await client.head(path)
        get = await client.get(path)
    assert head.status_code == 200
    assert head.headers["content-type"] == "image/png"
    assert get.status_code == 200
    assert get.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_favicon_120_is_square_and_has_no_background() -> None:
    async with _client() as client:
        body = (await client.get("/favicon-120.png")).content
    with Image.open(BytesIO(body)) as icon:
        assert icon.size == (120, 120)
        assert icon.convert("RGBA").getpixel((0, 0))[3] == 0


@pytest.mark.asyncio
async def test_logos_head_200() -> None:
    async with _client() as client:
        resp = await client.head("/logos/01-icon/glide-icon-teal-square-light-512.png")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_home_html_has_actual_line_and_icon_120(app_use_test_db) -> None:
    async with _client() as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert f'<p class="b-hero__fresh">{HOME_ACTUAL_LINE}</p>' in html
    assert HOME_ACTUAL_LINE.startswith("Актуальное расписание")
    assert 'sizes="120x120" href="/favicon-120.png?v=2"' in html
