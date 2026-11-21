"""TASK-436 AC-3: просмотр «Зимой» не съедается дедупом просмотра хаба того же города."""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.catalog_consumer_events import KIND_PUBLIC_PAGE_VIEW
from src.application.ice_city_day import city_slug
from tests.api.test_public_arenas import _insert_city


async def _views(db_session, city_id: int) -> list[str]:
    rows = await db_session.execute(
        text(
            "SELECT payload->>'path' FROM catalog_consumer_events "
            "WHERE kind = :k AND city_id = :c AND surface = 'selection_page' ORDER BY id"
        ),
        {"k": KIND_PUBLIC_PAGE_VIEW, "c": city_id},
    )
    return [r[0] for r in rows]


@pytest.mark.asyncio
async def test_hub_then_zimoy_same_day_both_counted(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "test-catalog-actor-secret-0123456789abcdef")
    name = f"Зима {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    await db_session.commit()
    hub = f"/c/{city_slug(name)}"
    headers = {"User-Agent": f"Mozilla/5.0 (iPhone) Zimoy {uuid.uuid4().hex[:8]}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in (hub, f"{hub}/zimoy", f"{hub}/zimoy", hub):
            resp = await client.post(
                "/api/public/catalog/page-view",
                params={"surface": "selection_page", "city_id": city_id, "path": path},
                headers=headers,
            )
            assert resp.status_code == 204

    # Хаб и зима — по одному просмотру за сутки; повторы того же актёра схлопнуты, как раньше.
    assert await _views(db_session, city_id) == [hub, f"{hub}/zimoy"]
