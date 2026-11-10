"""og:type на публичных страницах b.html: свой у тренера и катка, ``website`` у остальных, метка не течёт в HTML."""

from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.application.ice_city_day import city_slug
from src.application.site_trainer_page import trainer_path
from tests.api.test_public_place_page import _place
from tests.api.test_site_trainers import _trainer_on


def _og_type(html: str) -> str | None:
    m = re.search(r'<meta property="og:type" content="([^"]*)"', html)
    return m.group(1) if m else None


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.example")


@pytest.mark.asyncio
async def test_og_type_is_filled_everywhere_and_never_a_raw_placeholder(app_use_test_db, db_session) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        place = await _place(db_session)
        tid = await _trainer_on(db_session, client, place, first_name="Ова")
        slug = city_slug(place["city_name"])
        expected = {
            "/": "website",
            f"/c/{slug}": "website",
            f"/c/{slug}?t=ice&w=weekend": "website",
            f"/c/{slug}/trenery": "website",
            "/privacy": "website",
            "/terms": "website",
            "/suggest": "website",
            place["path"]: "place",
            trainer_path(tid, "Ова Тренерова"): "profile",
        }
        seen = 0
        for path, og in expected.items():
            resp = await client.get(path)
            assert resp.status_code == 200, path
            assert "__OG_TYPE__" not in resp.text, path
            found = _og_type(resp.text)
            if found is not None:
                seen += 1
                assert found == og, path
        assert seen >= 5
        hockey = await client.get("/hockey")
        if hockey.status_code == 200:
            assert "__OG_TYPE__" not in hockey.text and _og_type(hockey.text) == "website"
