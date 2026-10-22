"""
TASK-313: вкладка «Профиль» (trainer-account) и экран «Услуги и цены» (trainer-prices).

/webapp/ отдаёт только явно перечисленные файлы. Страница или скрипт без своего маршрута
получают 404 (JSON) — вкладка бара открывала бы пустой экран.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app

WEBAPP = Path(__file__).resolve().parents[2] / "static" / "webapp"


@pytest.mark.asyncio
@pytest.mark.parametrize("page", ["trainer-account", "trainer-prices", "trainer-arenas"])
async def test_page_and_its_assets_are_served(page: str) -> None:
    html = (WEBAPP / f"{page}.html").read_text(encoding="utf-8")
    own = re.findall(r'(?:src|href)="((?:trainer-(?:account|prices|arenas)|mini-app-trainer-account)[^"?]*)', html)
    assert own, "страница не подключила свои файлы"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/webapp/{page}")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        for name in own:
            r = await client.get(f"/webapp/{name}?v=1")
            assert r.status_code == 200, name
            expected = "javascript" if name.endswith(".js") else "text/css"
            assert expected in r.headers["content-type"], name
