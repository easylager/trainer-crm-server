"""
API health endpoint tests. Require running app or TestClient with app (same process).
"""
import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


@pytest.mark.asyncio
async def test_health_returns_200_and_db_ok(app_use_test_db) -> None:
    """GET /health returns 200 and db: ok when DB is reachable."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert data.get("db") == "ok"
