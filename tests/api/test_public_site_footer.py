"""Публичный футер и legal-страницы (TASK-279)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.application.public_site_footer import INSTAGRAM_URL, SUPPORT_EMAIL, render_site_footer_html


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def test_site_footer_contains_contacts_and_legal_links() -> None:
    html = render_site_footer_html()
    assert "b-site-foot" in html
    assert SUPPORT_EMAIL in html
    assert INSTAGRAM_URL in html
    assert 'href="/privacy"' not in html
    assert 'href="/terms"' not in html
    assert "Расписание может меняться" in html
    assert "уточняйте у катка" in html


@pytest.mark.asyncio
async def test_privacy_and_terms_return_200_with_footer(app_use_test_db) -> None:
    async with _client() as client:
        for path in ("/privacy", "/terms"):
            r = await client.get(path)
            assert r.status_code == 200
            body = r.text
            assert "b-site-foot" in body
            assert SUPPORT_EMAIL in body
            assert "черновик" in body.casefold()


@pytest.mark.asyncio
async def test_catalog_home_includes_site_footer(app_use_test_db) -> None:
    async with _client() as client:
        r = await client.get("/")
        assert r.status_code == 200
        assert "b-site-foot" in r.text
        assert 'href="/privacy"' not in r.text
        assert 'href="/terms"' not in r.text
