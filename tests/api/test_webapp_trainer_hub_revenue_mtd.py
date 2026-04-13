"""Trainer hub MTD revenue (Обзор) — no analytics gate."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


@pytest.mark.asyncio
async def test_trainer_hub_revenue_mtd_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/trainer/hub/revenue-mtd")
    assert resp.status_code == 401
