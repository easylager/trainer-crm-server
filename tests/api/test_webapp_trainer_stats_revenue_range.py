"""Trainer stats revenue-range API (Mini App «Бухгалтерия»)."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


@pytest.mark.asyncio
async def test_trainer_revenue_range_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/trainer/stats/revenue-range?from=2026-01-01&to=2026-01-31")
    assert resp.status_code == 401
