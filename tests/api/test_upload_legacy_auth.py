"""Legacy /api/upload/* without initData: disabled unless INTERNAL_UPLOAD_API_KEY is set."""
import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app


@pytest.mark.asyncio
async def test_upload_photo_403_when_internal_key_not_configured(
    app_use_test_db,
    monkeypatch,
) -> None:
    class _NoKey:
        internal_upload_api_key = None

    monkeypatch.setattr("src.api.routes.upload.Settings", _NoKey)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/upload/photo",
            data={"trainer_id": "1"},
            files={"file": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")},
        )
    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_photo_presign_403_when_internal_key_not_configured(
    app_use_test_db,
    monkeypatch,
) -> None:
    class _NoKey:
        internal_upload_api_key = None

    monkeypatch.setattr("src.api.routes.upload.Settings", _NoKey)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/upload/photo/presign",
            json={"trainer_id": 1, "content_type": "image/jpeg"},
        )
    assert resp.status_code == 403
