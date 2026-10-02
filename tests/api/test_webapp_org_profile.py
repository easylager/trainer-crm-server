"""TASK-141 (S3): GET/PATCH /api/webapp/org/profile — checklist onboarding.
TASK-143: площадка (primary_arena_id) — PATCH validation + GET /profile/arenas;
POST /profile/assets — logo/cover/gallery upload.
"""
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from typing import Iterator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.arena_profile import backfill_arena_profiles
from src.application.collective_use_cases import (
    OPERATOR_ROLE_ADMIN,
    OPERATOR_STATUS_ACTIVE,
    consume_collective_claim_token_for_operator,
    create_collective_draft,
    issue_collective_claim_token,
)

pytestmark = pytest.mark.collective


def _jpeg_bytes(color: tuple[int, int, int] = (30, 90, 150)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (64, 48), color=color).save(buf, "JPEG", quality=80)
    return buf.getvalue()


async def _add_admin_operator(db_session, *, collective_id: int, telegram_id: int) -> None:
    now = datetime.now(timezone.utc)
    await db_session.execute(
        text(
            """
            INSERT INTO collective_operators (
                collective_id, telegram_id, role, status, created_at, updated_at
            )
            VALUES (:cid, :tgid, :role, :status, :now, :now)
            """
        ),
        {
            "cid": collective_id,
            "tgid": telegram_id,
            "role": OPERATOR_ROLE_ADMIN,
            "status": OPERATOR_STATUS_ACTIVE,
            "now": now,
        },
    )
    await db_session.commit()


async def _insert_public_arena(db_session, *, city_id: int | None = None, name: str | None = None) -> tuple[int, int]:
    """Confirmed + published arena — the "public catalog" площадка picker draws from."""
    if city_id is None:
        r = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
        city_id = r.scalar()
        if city_id is None:
            pytest.skip("need seed cities")
    ins = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
            VALUES (:cid, :name, 'пр-т Победителей, 1', true, true)
            RETURNING id
            """
        ),
        {"cid": city_id, "name": name or f"Каток {uuid.uuid4().hex[:8]}"},
    )
    arena_id = int(ins.scalar_one())
    await backfill_arena_profiles(db_session)
    await db_session.flush()
    return int(city_id), arena_id


async def _insert_unconfirmed_arena(db_session, *, city_id: int) -> int:
    ins = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, is_active, is_confirmed)
            VALUES (:cid, :name, true, false)
            RETURNING id
            """
        ),
        {"cid": city_id, "name": f"Неподтверждённый {uuid.uuid4().hex[:8]}"},
    )
    arena_id = int(ins.scalar_one())
    await db_session.flush()
    return arena_id


@contextmanager
def patch_org_webapp_init(telegram_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=telegram_id)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        yield


async def _claim_school(db_session, *, slug: str, telegram_id: int) -> int:
    created = await create_collective_draft(db_session, slug=slug, display_name=slug)
    claim = await issue_collective_claim_token(db_session, int(created["id"]))
    outcome = await consume_collective_claim_token_for_operator(db_session, claim["token"], telegram_id)
    assert outcome.error is None
    return int(created["id"])


@pytest.mark.asyncio
async def test_profile_get_shows_missing_required_fields(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_200_001
    await _claim_school(db_session, slug="org-profile-fresh", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/org/profile", headers={"X-Telegram-Init-Data": "mock"}
            )
    assert resp.status_code == 200
    body = resp.json()
    # display_name was set at draft creation, about/contact are not.
    assert body["readiness"]["ready"] is False
    assert "about" in body["readiness"]["missing"]
    assert "contact" in body["readiness"]["missing"]
    assert "display_name" not in body["readiness"]["missing"]


@pytest.mark.asyncio
async def test_profile_patch_fills_required_fields_and_becomes_ready(
    app_use_test_db, db_session
) -> None:
    telegram_id = 8_555_200_002
    await _claim_school(db_session, slug="org-profile-fill", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/webapp/org/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "about": "Небольшая школа фигурного катания для детей 4-12 лет.",
                    "contacts": {"phone": "+375291234567"},
                },
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["readiness"]["ready"] is True
    assert body["readiness"]["missing"] == []
    assert body["about"] == "Небольшая школа фигурного катания для детей 4-12 лет."
    assert body["contacts"]["phone"] == "+375291234567"


@pytest.mark.asyncio
async def test_profile_patch_rejects_empty_display_name(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_200_003
    await _claim_school(db_session, slug="org-profile-badname", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/webapp/org/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"display_name": "   "},
            )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_profile_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/org/profile")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_profile_get_includes_cities_refs(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_200_010
    await _claim_school(db_session, slug="org-profile-refs", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/org/profile", headers={"X-Telegram-Init-Data": "mock"}
            )
    assert resp.status_code == 200
    body = resp.json()
    assert "refs" in body
    assert isinstance(body["refs"]["cities"]["items"], list)
    assert body["primary_arena_id"] is None


@pytest.mark.asyncio
async def test_profile_patch_sets_and_echoes_primary_arena(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_200_011
    await _claim_school(db_session, slug="org-profile-arena-set", telegram_id=telegram_id)
    city_id, arena_id = await _insert_public_arena(db_session, name="Ледовый дворец Тест")

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/webapp/org/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"primary_arena_id": arena_id},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["primary_arena_id"] == arena_id
            assert body["primary_arena_name"] == "Ледовый дворец Тест"
            assert body["primary_arena_address"] == "пр-т Победителей, 1"

            get_resp = await client.get(
                "/api/webapp/org/profile", headers={"X-Telegram-Init-Data": "mock"}
            )
    assert get_resp.status_code == 200
    assert get_resp.json()["primary_arena_id"] == arena_id


@pytest.mark.asyncio
async def test_profile_patch_rejects_unconfirmed_arena(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_200_012
    await _claim_school(db_session, slug="org-profile-arena-bad", telegram_id=telegram_id)
    city_id, _confirmed_arena_id = await _insert_public_arena(db_session)
    unconfirmed_id = await _insert_unconfirmed_arena(db_session, city_id=city_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/webapp/org/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"primary_arena_id": unconfirmed_id},
            )
    assert resp.status_code == 400

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/webapp/org/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"primary_arena_id": 9_999_999},
            )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_profile_patch_clears_primary_arena(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_200_013
    await _claim_school(db_session, slug="org-profile-arena-clear", telegram_id=telegram_id)
    _city_id, arena_id = await _insert_public_arena(db_session)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            set_resp = await client.patch(
                "/api/webapp/org/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"primary_arena_id": arena_id},
            )
            assert set_resp.status_code == 200
            assert set_resp.json()["primary_arena_id"] == arena_id

            clear_resp = await client.patch(
                "/api/webapp/org/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"primary_arena_id": None},
            )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["primary_arena_id"] is None


@pytest.mark.asyncio
async def test_profile_arenas_endpoint_lists_public_catalog_only(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_200_014
    await _claim_school(db_session, slug="org-profile-arena-list", telegram_id=telegram_id)
    city_id, confirmed_id = await _insert_public_arena(db_session, name="Публичная арена")
    unconfirmed_id = await _insert_unconfirmed_arena(db_session, city_id=city_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/org/profile/arenas",
                params={"city_id": city_id},
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["items"]]
    assert confirmed_id in ids
    assert unconfirmed_id not in ids


@pytest.mark.asyncio
async def test_profile_asset_upload_logo_owner(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_200_020
    await _claim_school(db_session, slug="org-profile-logo", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/org/profile/assets",
                params={"kind": "logo"},
                headers={"X-Telegram-Init-Data": "mock"},
                files={"file": ("logo.jpg", _jpeg_bytes(), "image/jpeg")},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["asset"]["kind"] == "logo"
    assert body["asset"]["url"]
    assert body["profile"]["logo_url"] == body["asset"]["url"]


@pytest.mark.asyncio
async def test_profile_asset_upload_cover_and_gallery(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_200_021
    await _claim_school(db_session, slug="org-profile-cover-gallery", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            cover_resp = await client.post(
                "/api/webapp/org/profile/assets",
                params={"kind": "cover"},
                headers={"X-Telegram-Init-Data": "mock"},
                files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
            )
            gallery_resp = await client.post(
                "/api/webapp/org/profile/assets",
                params={"kind": "gallery"},
                headers={"X-Telegram-Init-Data": "mock"},
                files={"file": ("g1.jpg", _jpeg_bytes((10, 20, 30)), "image/jpeg")},
            )
    assert cover_resp.status_code == 200
    assert cover_resp.json()["profile"]["cover_url"] == cover_resp.json()["asset"]["url"]
    assert gallery_resp.status_code == 200
    gallery = gallery_resp.json()["profile"]["gallery"]
    assert len(gallery) == 1
    assert gallery[0]["url"] == gallery_resp.json()["asset"]["url"]


@pytest.mark.asyncio
async def test_profile_asset_upload_rejects_too_large(app_use_test_db, db_session) -> None:
    from src.application.trainer_use_cases import MAX_TRAINER_PHOTO_BYTES

    telegram_id = 8_555_200_022
    await _claim_school(db_session, slug="org-profile-toolarge", telegram_id=telegram_id)
    oversized = b"\xff\xd8\xff" + b"0" * (MAX_TRAINER_PHOTO_BYTES + 1)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/org/profile/assets",
                params={"kind": "logo"},
                headers={"X-Telegram-Init-Data": "mock"},
                files={"file": ("big.jpg", oversized, "image/jpeg")},
            )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_profile_asset_upload_rejects_non_image(app_use_test_db, db_session) -> None:
    telegram_id = 8_555_200_023
    await _claim_school(db_session, slug="org-profile-notimage", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/org/profile/assets",
                params={"kind": "logo"},
                headers={"X-Telegram-Init-Data": "mock"},
                files={"file": ("note.txt", b"not an image", "text/plain")},
            )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_profile_asset_upload_gallery_full(app_use_test_db, db_session) -> None:
    from src.application.brand_presentation import MAX_COLLECTIVE_GALLERY_ITEMS

    telegram_id = 8_555_200_024
    await _claim_school(db_session, slug="org-profile-galleryfull", telegram_id=telegram_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for i in range(MAX_COLLECTIVE_GALLERY_ITEMS):
                r = await client.post(
                    "/api/webapp/org/profile/assets",
                    params={"kind": "gallery"},
                    headers={"X-Telegram-Init-Data": "mock"},
                    files={"file": (f"g{i}.jpg", _jpeg_bytes((i, i, i)), "image/jpeg")},
                )
                assert r.status_code == 200
            over_limit = await client.post(
                "/api/webapp/org/profile/assets",
                params={"kind": "gallery"},
                headers={"X-Telegram-Init-Data": "mock"},
                files={"file": ("over.jpg", _jpeg_bytes(), "image/jpeg")},
            )
    assert over_limit.status_code == 409


@pytest.mark.asyncio
async def test_profile_asset_upload_admin_operator_forbidden(app_use_test_db, db_session) -> None:
    owner_telegram_id = 8_555_200_025
    admin_telegram_id = 8_555_200_026
    collective_id = await _claim_school(db_session, slug="org-profile-admin-upload", telegram_id=owner_telegram_id)
    await _add_admin_operator(db_session, collective_id=collective_id, telegram_id=admin_telegram_id)

    with patch_org_webapp_init(admin_telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/org/profile/assets",
                params={"kind": "logo"},
                headers={"X-Telegram-Init-Data": "mock"},
                files={"file": ("logo.jpg", _jpeg_bytes(), "image/jpeg")},
            )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_profile_patch_admin_operator_cannot_set_arena(app_use_test_db, db_session) -> None:
    owner_telegram_id = 8_555_200_027
    admin_telegram_id = 8_555_200_028
    collective_id = await _claim_school(db_session, slug="org-profile-admin-patch", telegram_id=owner_telegram_id)
    await _add_admin_operator(db_session, collective_id=collective_id, telegram_id=admin_telegram_id)
    _city_id, arena_id = await _insert_public_arena(db_session)

    with patch_org_webapp_init(admin_telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/webapp/org/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"primary_arena_id": arena_id},
            )
    assert resp.status_code == 403
