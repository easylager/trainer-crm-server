"""TASK-234: посадочная /zovi индексируется и отдаёт экран создания."""

from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _meta(html: str, prop: str) -> str:
    match = re.search(rf'<meta (?:property|name)="{re.escape(prop)}" content="([^"]*)"', html)
    assert match, f"no meta {prop}"
    return match.group(1)


@pytest.mark.asyncio
async def test_zovi_page_is_indexable(app_use_test_db) -> None:
    async with _client() as client:
        page = await client.get("/zovi")
        script = await client.get("/static/shared/zovi-create.js")
    assert page.status_code == 200, page.text
    html = page.text
    assert _meta(html, "og:title") == "Позови на каток"
    assert _meta(html, "og:description") == ("Открытка-приглашение на настоящий сеанс. Кнопка «Нет» не работает.")
    assert _meta(html, "robots") == "index, follow"
    assert "noindex" not in html
    assert "og:image" not in html
    assert "/static/shared/zovi-create.js?v=5" in html
    assert 'id="back"' in html
    assert "К расписанию" in html
    assert script.status_code == 200
    assert "previewQuestion" in script.text
