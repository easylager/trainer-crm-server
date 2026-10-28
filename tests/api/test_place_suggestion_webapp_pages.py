"""Страницы Mini App для «мест от людей» (PDEC-028): форма клиента и модерация."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "marker"),
    [
        ("/webapp/suggest", "PlaceSuggestForm.mount"),
        ("/webapp/admin-place-suggestions", "/admin/place-suggestions"),
    ],
)
async def test_place_suggestion_webapp_pages_are_served(path, marker):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(path)
    assert r.status_code == 200
    assert marker in r.text
