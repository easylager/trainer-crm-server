"""TASK-049: admin arena photo upload, order, license, public hero/gallery."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.deps import get_admin_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.arena_media import ARENA_MEDIA_MAX
from src.application.arena_profile import backfill_arena_profiles


@contextmanager
def patch_admin_principal(user_id: int = 4242) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_id)
    app.dependency_overrides[get_admin_miniapp_principal] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_admin_miniapp_principal, None)


def _jpeg_bytes(color: tuple[int, int, int] = (20, 80, 160)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (64, 48), color=color).save(buf, "JPEG", quality=80)
    return buf.getvalue()


async def _insert_arena(db_session, name: str | None = None) -> tuple[int, int]:
    r = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r.scalar()
    if cid is None:
        pytest.skip("need seed cities")
    ins = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
            VALUES (:cid, :name, 'пр-т Победителей, 1', true, true)
            RETURNING id
            """
        ),
        {"cid": cid, "name": name or f"Медиа {uuid.uuid4().hex[:8]}"},
    )
    arena_id = int(ins.scalar_one())
    await backfill_arena_profiles(db_session)
    await db_session.flush()
    return int(cid), arena_id


@pytest.mark.asyncio
async def test_public_arena_without_photos_has_null_hero_and_empty_gallery(
    app_use_test_db, db_session
) -> None:
    cid, arena_id = await _insert_arena(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/public/arenas", params={"city_id": cid})
    assert resp.status_code == 200, resp.text
    row = next((a for a in resp.json()["items"] if a["id"] == arena_id), None)
    assert row is not None
    assert row["hero"] is None
    assert row["gallery"] == []


def _patch_arena_upload(monkeypatch) -> None:
    def fake_upload(arena_id: int, _body: bytes, _content_type: str) -> dict:
        token = uuid.uuid4().hex[:8]
        variants = {
            "thumb": f"arenas/{arena_id}/{token}_thumb.jpg",
            "card": f"arenas/{arena_id}/{token}_card.jpg",
            "hero": f"arenas/{arena_id}/{token}_hero.jpg",
        }
        return {"storage_key": variants["hero"], "variants": variants, "width": 64, "height": 48}

    monkeypatch.setattr("src.infrastructure.s3.upload_arena_photo", fake_upload)


@pytest.mark.asyncio
async def test_admin_upload_requires_license(app_use_test_db, db_session, monkeypatch) -> None:
    _patch_arena_upload(monkeypatch)
    _cid, arena_id = await _insert_arena(db_session)
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/photos",
                files={"file": ("ice.jpg", _jpeg_bytes(), "image/jpeg")},
            )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_admin_upload_two_photos_sets_hero_and_gallery_order(
    app_use_test_db, db_session, monkeypatch
) -> None:
    _patch_arena_upload(monkeypatch)
    cid, arena_id = await _insert_arena(db_session)
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/photos",
                files={"file": ("a.jpg", _jpeg_bytes((10, 20, 30)), "image/jpeg")},
                data={"license": "own"},
            )
            second = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/photos",
                files={"file": ("b.jpg", _jpeg_bytes((200, 10, 10)), "image/jpeg")},
                data={
                    "license": "operator",
                    "source_url": "https://arena.example/photo",
                },
            )
            assert first.status_code == 200, first.text
            assert second.status_code == 200, second.text
            id_a = int(first.json()["id"])
            id_b = int(second.json()["id"])
            reorder = await client.patch(
                f"/api/webapp/admin/arenas/{arena_id}/photos",
                json={"ids": [id_b, id_a]},
            )
            assert reorder.status_code == 200, reorder.text
            listed = await client.get(
                "/api/webapp/admin/arenas",
                params={"city_id": cid, "include_inactive": True},
            )
            public = await client.get("/api/public/arenas", params={"city_id": cid})

    assert listed.status_code == 200, listed.text
    admin_row = next((a for a in listed.json()["items"] if a["id"] == arena_id), None)
    assert admin_row is not None
    assert admin_row["hero"]["id"] == id_b
    assert [g["id"] for g in admin_row["gallery"]] == [id_b, id_a]
    for variant in ("thumb", "card", "hero"):
        assert variant in admin_row["hero"]["variants"]
        assert admin_row["hero"]["variants"][variant]

    assert public.status_code == 200, public.text
    pub_row = next((a for a in public.json()["items"] if a["id"] == arena_id), None)
    assert pub_row is not None
    assert pub_row["hero"]["id"] == id_b
    assert [g["id"] for g in pub_row["gallery"]] == [id_b, id_a]
    assert "storage_key" not in pub_row["hero"]


@pytest.mark.asyncio
async def test_admin_upload_rejects_seventh_photo(app_use_test_db, db_session, monkeypatch) -> None:
    _patch_arena_upload(monkeypatch)
    _cid, arena_id = await _insert_arena(db_session)
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for i in range(ARENA_MEDIA_MAX):
                resp = await client.post(
                    f"/api/webapp/admin/arenas/{arena_id}/photos",
                    files={"file": (f"{i}.jpg", _jpeg_bytes(), "image/jpeg")},
                    data={"license": "own"},
                )
                assert resp.status_code == 200, resp.text
            extra = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/photos",
                files={"file": ("overflow.jpg", _jpeg_bytes(), "image/jpeg")},
                data={"license": "own"},
            )
    assert extra.status_code == 400, extra.text
