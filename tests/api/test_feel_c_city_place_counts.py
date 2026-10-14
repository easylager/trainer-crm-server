"""FEEL-C: 12 катков + 2 магазина + 1 трасса — одни цифры в hero, og, шере и «Все места»."""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from tests.api.test_catalog_shops import _admin_create_shop
from tests.api.test_public_arenas import _add_future_session, _insert_arena, _insert_city


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _og(html: str, prop: str) -> str:
    match = re.search(rf'<meta property="{prop}" content="([^"]*)"', html)
    assert match, prop
    return match.group(1)


@pytest.mark.asyncio
async def test_mixed_city_inventory_counts_match_everywhere(app_use_test_db, db_session) -> None:
    name = f"FeelC {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    for n in range(12):
        arena_id = await _insert_arena(db_session, city_id, name=f"Каток {n:02d}")
        if n < 10:
            await _add_future_session(db_session, arena_id, days_ahead=1 + (n % 2), starts_at_local="12:00")
    track_id = await _insert_arena(db_session, city_id, name="Трасса скорости")
    await db_session.execute(text("UPDATE arenas SET venue_type = 'gym' WHERE id = :id"), {"id": track_id})
    await db_session.commit()
    await _admin_create_shop(city_id, f"ShopA {uuid.uuid4().hex[:4]}")
    await _admin_create_shop(city_id, f"ShopB {uuid.uuid4().hex[:4]}")
    invalidate_public_city_cache()
    slug = city_slug(name)
    expected = "15 мест · 10 сеансов"

    async with _client() as client:
        hub = await client.get(f"/c/{slug}")
        listing = await client.get(f"/c/{slug}", params={"page": "1"})
        share = await client.get(
            "/api/public/ice/selection/share", params={"city_id": city_id, "record": "false"}
        )

    assert hub.status_code == 200 and listing.status_code == 200 and share.status_code == 200
    assert _og(hub.text, "og:description") == expected
    assert expected in share.json()["share_body"]
    assert "v=" in _og(hub.text, "og:image")
    assert "12\u00a0катков" in hub.text or "12 катков" in hub.text.replace("\u00a0", " ")
    assert "Все места города · 15" in hub.text.replace("\u00a0", " ")
    assert "<b>Катки:</b>" in hub.text and "<b>Магазины и сервисы:</b>" in hub.text and "<b>Прочее:</b>" in hub.text
    assert expected in listing.text
