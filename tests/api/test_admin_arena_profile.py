"""TASK-048 AC-003: admin dictionary PATCH/GET round-trip for arena profile fields."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.deps import get_admin_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.arena_profile import backfill_arena_profiles


@contextmanager
def patch_admin_principal(user_id: int = 4242) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_id)
    app.dependency_overrides[get_admin_miniapp_principal] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_admin_miniapp_principal, None)


@pytest.mark.asyncio
async def test_admin_patch_profile_fields_round_trip(app_use_test_db, db_session) -> None:
    r = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r.scalar()
    if cid is None:
        pytest.skip("need seed cities")

    name = f"Админ-профиль {uuid.uuid4().hex[:8]}"
    ins = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
            VALUES (:cid, :name, 'пр-т Победителей, 1', true, true)
            RETURNING id
            """
        ),
        {"cid": cid, "name": name},
    )
    arena_id = int(ins.scalar_one())
    await backfill_arena_profiles(db_session)
    await db_session.flush()

    payload = {
        "phone": "+375291112233",
        "website_url": "https://example-arena.test",
        "short_description": "Крытый каток",
        "district": "Центральный",
        "season_start_month": 9,
        "season_end_month": 4,
        "opening_hours": {"daily": {"open": "07:00", "close": "23:00"}},
        "amenities": {"skate_rental": True, "cafe": True, "parking": False},
    }
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            patch_resp = await client.patch(f"/api/webapp/admin/arenas/{arena_id}", json=payload)
            assert patch_resp.status_code == 200, patch_resp.text
            get_resp = await client.get(
                "/api/webapp/admin/arenas",
                params={"city_id": cid, "include_inactive": True, "q": name},
            )
    assert get_resp.status_code == 200, get_resp.text
    items = get_resp.json()["items"]
    row = next((a for a in items if a["id"] == arena_id), None)
    assert row is not None
    assert row["phone"] == payload["phone"]
    assert row["website_url"] == payload["website_url"]
    assert row["short_description"] == payload["short_description"]
    assert row["district"] == payload["district"]
    assert row["season_start_month"] == 9
    assert row["season_end_month"] == 4
    assert row["opening_hours"]["daily"]["close"] == "23:00"
    assert row["amenities"]["skate_rental"] is True
    assert row["amenities"]["cafe"] is True
    assert row["amenities"].get("parking") is False


@pytest.mark.asyncio
async def test_admin_patch_rejects_unknown_amenity_key(app_use_test_db, db_session) -> None:
    r = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r.scalar()
    if cid is None:
        pytest.skip("need seed cities")
    ins = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, is_active, is_confirmed)
            VALUES (:cid, :name, true, true)
            RETURNING id
            """
        ),
        {"cid": cid, "name": f"Bad amenity {uuid.uuid4().hex[:8]}"},
    )
    arena_id = int(ins.scalar_one())
    await backfill_arena_profiles(db_session)
    await db_session.flush()

    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/api/webapp/admin/arenas/{arena_id}",
                json={"amenities": {"sauna": True}},
            )
    assert resp.status_code == 400
