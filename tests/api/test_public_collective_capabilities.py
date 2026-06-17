"""Public collective landing contract — O0.3 capability fields for client catalog."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from tests.api.collective_api_helpers import seed_active_collective_owner
from tests.api.test_webapp_client_miniapp_integration import _require_seed_ids

pytestmark = pytest.mark.collective

PUBLIC_CAPABILITY_KEYS = frozenset(
    {
        "organization_format",
        "catalog_mode",
        "hero_variant",
        "show_coaches_catalog_tab",
    }
)


@pytest.mark.asyncio
async def test_public_collective_studio_capabilities(app_use_test_db, db_session) -> None:
    sid, cid, _ = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_tr = await client.post(
            "/api/trainers",
            json={
                "profile": {"first_name": "Pub", "last_name": "Studio", "age": 30, "city_id": cid},
                "service_ids": [sid],
            },
        )
        assert r_tr.status_code == 200
        tid = r_tr.json()["id"]
    await seed_active_collective_owner(
        db_session,
        tid,
        slug="pub-studio-roster",
        organization_format="studio",
        schedule_mode="member_autonomous",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/public/collectives/pub-studio-roster")
    assert resp.status_code == 200
    body = resp.json()
    assert PUBLIC_CAPABILITY_KEYS <= set(body.keys())
    assert body["organization_format"] == "studio"
    assert body["catalog_mode"] == "studio_roster"
    assert body["hero_variant"] == "studio"
    assert body["show_coaches_catalog_tab"] is False
    assert body["slug"] == "pub-studio-roster"
    assert body["schedule_mode"] == "member_autonomous"


@pytest.mark.asyncio
async def test_public_collective_center_capabilities(app_use_test_db, db_session) -> None:
    sid, cid, _ = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_tr = await client.post(
            "/api/trainers",
            json={
                "profile": {"first_name": "Pub", "last_name": "Center", "age": 30, "city_id": cid},
                "service_ids": [sid],
            },
        )
        assert r_tr.status_code == 200
        tid = r_tr.json()["id"]
    await seed_active_collective_owner(
        db_session,
        tid,
        slug="pub-center-grid",
        organization_format="center",
        schedule_mode="studio_central",
        owner_studio_access_mode="studio_admin_only",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/public/collectives/pub-center-grid")
    assert resp.status_code == 200
    body = resp.json()
    assert body["organization_format"] == "center"
    assert body["catalog_mode"] == "center_grid"
    assert body["hero_variant"] == "center"
    assert body["show_coaches_catalog_tab"] is False


@pytest.mark.asyncio
async def test_public_collective_center_hybrid_coaches_tab(app_use_test_db, db_session) -> None:
    sid, cid, _ = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_tr = await client.post(
            "/api/trainers",
            json={
                "profile": {"first_name": "Pub", "last_name": "Hybrid", "age": 30, "city_id": cid},
                "service_ids": [sid],
            },
        )
        assert r_tr.status_code == 200
        tid = r_tr.json()["id"]
    await seed_active_collective_owner(
        db_session,
        tid,
        slug="pub-center-hybrid",
        organization_format="center_hybrid",
        schedule_mode="studio_central",
        owner_studio_access_mode="full_trainer",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/public/collectives/pub-center-hybrid")
    assert resp.status_code == 200
    body = resp.json()
    assert body["organization_format"] == "center_hybrid"
    assert body["catalog_mode"] == "center_grid"
    assert body["show_coaches_catalog_tab"] is True


@pytest.mark.asyncio
async def test_public_collective_404_when_inactive(app_use_test_db, db_session) -> None:
    sid, cid, _ = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_tr = await client.post(
            "/api/trainers",
            json={
                "profile": {"first_name": "Draft", "last_name": "Only", "age": 30, "city_id": cid},
                "service_ids": [sid],
            },
        )
        assert r_tr.status_code == 200
        tid = r_tr.json()["id"]
    await db_session.execute(
        text(
            """
            INSERT INTO collectives (
                slug, display_name, status, seat_limit, owner_trainer_id,
                schedule_mode, organization_format, created_at, updated_at
            )
            VALUES (
                'pub-draft-only', 'Draft', 'draft', 5, :tid,
                'member_autonomous', 'studio', NOW(), NOW()
            )
            """
        ),
        {"tid": tid},
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/public/collectives/pub-draft-only")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_public_collective_404_when_suspended(app_use_test_db, db_session) -> None:
    sid, cid, _ = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_tr = await client.post(
            "/api/trainers",
            json={
                "profile": {"first_name": "Susp", "last_name": "Ended", "age": 30, "city_id": cid},
                "service_ids": [sid],
            },
        )
        assert r_tr.status_code == 200
        tid = r_tr.json()["id"]
    await db_session.execute(
        text(
            """
            INSERT INTO collectives (
                slug, display_name, status, seat_limit, owner_trainer_id,
                schedule_mode, organization_format, created_at, updated_at
            )
            VALUES (
                'pub-suspended', 'Suspended Brand', 'suspended', 5, :tid,
                'member_autonomous', 'studio', NOW(), NOW()
            )
            """
        ),
        {"tid": tid},
    )
    await db_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/public/collectives/pub-suspended")
    assert resp.status_code == 404
