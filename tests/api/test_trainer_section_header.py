"""Шапка разделов «Профиля» тренера: один стиль кнопки назад на всех экранах."""

import re

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app

SECTION_PAGES = (
    "trainer-prices",
    "trainer-arenas",
    "trainer-groups",
    "trainer-pass-products",
    "trainer-stats",
    "trainer-subscription",
    "trainer-referral",
    "trainer-faq",
    "trainer-requests",
)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_section_css_is_served_and_every_section_page_links_it() -> None:
    async with _client() as client:
        css = await client.get("/webapp/mini-app-trainer-section.css")
        assert css.status_code == 200
        assert css.headers["content-type"].startswith("text/css")
        assert ".ts-back__ic" in css.text
        for page in SECTION_PAGES:
            html = (await client.get(f"/webapp/{page}")).text
            assert re.search(r'href="mini-app-trainer-section\.css\?v=\d+"', html), page


@pytest.mark.asyncio
async def test_prices_and_arenas_use_the_shared_back_button() -> None:
    async with _client() as client:
        for page in ("trainer-prices", "trainer-arenas"):
            html = (await client.get(f"/webapp/{page}")).text
            assert 'class="ts-back tp-back" id="tpBack"' in html, page
            assert 'class="ts-back__ic" id="tpBackIc"' in html, page
            assert 'class="ta-body ts-page"' in html, page
