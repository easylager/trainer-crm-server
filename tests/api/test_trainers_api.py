"""
API tests for trainer list endpoints. Use test DB (same DATABASE_URL as pytest).
"""
import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


@pytest.mark.asyncio
async def test_list_trainers_returns_200_and_items(app_use_test_db) -> None:
    """GET /api/trainers returns 200 and body has 'items' list."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/trainers")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_list_public_trainers_returns_200_and_items_total(app_use_test_db) -> None:
    """GET /api/public/trainers returns 200 and body has 'items' and 'total'."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/public/trainers")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    assert isinstance(data["total"], int)
