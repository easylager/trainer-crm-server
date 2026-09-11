"""Web App trainer profile API: initData auth, aggregate GET, PATCH (Part 1)."""
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.trainer_profile_completeness import (
    MODERATION_CRITERIA_TOTAL,
    MODERATION_SUBMISSION_CRITERIA_TOTAL,
)


def _fresh_trainer_telegram_id() -> int:
    """Avoid ix_trainers_telegram_id collisions when the test DB is reused across runs."""
    return 5_000_000_000 + (uuid.uuid4().int % 4_000_000_000)


@pytest.mark.asyncio
async def test_webapp_trainer_profile_get_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/trainer/profile")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webapp_trainer_profile_get_403_when_telegram_not_linked(app_use_test_db) -> None:
    tg = 880_000_111
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_webapp_trainer_profile_get_returns_trainer_and_readiness(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Мини", "last_name": "Апп", "age": 28}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "trainer" in data
    assert data["trainer"]["id"] == trainer_id
    assert "moderation_readiness" in data
    assert "complete" in data["moderation_readiness"]
    assert data["moderation_readiness"].get("moderation_criteria_total") == MODERATION_SUBMISSION_CRITERIA_TOTAL
    assert "full_profile_complete" in data["moderation_readiness"]
    assert data["moderation_readiness"].get("full_profile_criteria_total") == MODERATION_CRITERIA_TOTAL
    assert "education_entries" in data
    assert isinstance(data["education_entries"], list)
    assert "digest_enabled" in data["trainer"]
    assert "digest_send_time" in data["trainer"]


@pytest.mark.asyncio
async def test_webapp_trainer_profile_patch_digest_settings(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Дайджест", "last_name": "Тест", "age": 30}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg, digest_send_time = '09:15' WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            patch_ok = await client.patch(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"digest_enabled": True, "digest_send_time": "08:00"},
            )
    assert patch_ok.status_code == 200, patch_ok.text

    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            get_r = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert get_r.status_code == 200
    ds = get_r.json()["trainer"].get("digest_send_time")
    assert ds is not None
    assert str(ds).replace(".", ":")[:5] in ("08:00", "8:00")  # time serialization may vary

    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            patch_off = await client.patch(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"digest_enabled": False, "digest_send_time": None},
            )
    assert patch_off.status_code == 200
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            get2 = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    t2 = get2.json()["trainer"]
    assert t2["digest_enabled"] is False
    tstr = str(t2.get("digest_send_time") or "")
    assert "08" in tstr, t2  # time preserved for re-enable


@pytest.mark.asyncio
async def test_webapp_trainer_profile_patch_updates_profile(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Патч", "last_name": "Тест", "age": 33}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            patch_resp = await client.patch(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"profile": {"description": "Краткое описание для модерации достаточной длины."}},
            )
            get_resp = await client.get(f"/api/trainers/{trainer_id}")
    assert patch_resp.status_code == 200
    assert patch_resp.json() == {"ok": True}
    assert get_resp.status_code == 200
    assert "краткое описание" in (get_resp.json().get("profile") or {}).get("description", "").lower()


@pytest.mark.asyncio
async def test_webapp_trainer_profile_patch_422_invalid_phone(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "П", "last_name": "Т", "age": 33, "phone": "+375291112233"}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            patch_resp = await client.patch(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"profile": {"phone": "+37529"}},
            )
    assert patch_resp.status_code == 422
    detail = patch_resp.json().get("detail")
    assert isinstance(detail, list)
    assert any("phone" in item.get("loc", ()) for item in detail)


@pytest.mark.asyncio
async def test_webapp_trainer_education_create_and_patch(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Эду", "last_name": "Тест", "age": 30}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            post_resp = await client.post(
                "/api/webapp/trainer/education",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "education_type": "formal_education",
                    "institution_name": "БГУФК",
                    "program_or_title": "Тренерский факультет",
                },
            )
            assert post_resp.status_code == 201
            eid = post_resp.json()["id"]
            patch_resp = await client.patch(
                f"/api/webapp/trainer/education/{eid}",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"program_or_title": "Тренерский факультет (обновлено)"},
            )
            assert patch_resp.status_code == 200
            assert patch_resp.json().get("revision_created") is False
            get_prof = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert get_prof.status_code == 200
    entries = get_prof.json().get("education_entries") or []
    assert len(entries) >= 1
    assert entries[0]["program_or_title"] == "Тренерский факультет (обновлено)"


@pytest.mark.asyncio
async def test_webapp_trainer_education_supports_uploaded_document_photos(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Док", "last_name": "Фото", "age": 30}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    fake_key = f"trainers/{trainer_id}/edu-proof.jpg"
    fake_key_list = f"trainers/{trainer_id}/edu-proof_list.jpg"
    with (
        patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)),
        patch("src.application.trainer_use_cases.trainer_photo_bytes_look_like_image", return_value=True),
        patch("src.application.trainer_use_cases.s3.upload_photo", return_value=(fake_key, fake_key_list)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            upload_resp = await client.post(
                "/api/webapp/trainer/education/documents",
                headers={"X-Telegram-Init-Data": "mock"},
                files={"file": ("proof.jpg", b"fake image bytes", "image/jpeg")},
            )
            assert upload_resp.status_code == 200
            uploaded = upload_resp.json()
            assert uploaded["file_key"] == fake_key
            assert uploaded["file_key_list"] == fake_key_list

            post_resp = await client.post(
                "/api/webapp/trainer/education",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "education_type": "formal_education",
                    "institution_name": "БГУФК",
                    "program_or_title": "Тренерский факультет",
                    "document_photos": [
                        {
                            "file_key": fake_key,
                            "file_key_list": fake_key_list,
                        }
                    ],
                },
            )
            assert post_resp.status_code == 201
            get_prof = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert get_prof.status_code == 200
    entries = get_prof.json().get("education_entries") or []
    assert len(entries) >= 1
    assert entries[0].get("document_photos")
    assert entries[0]["document_photos"][0]["file_key"] == fake_key


@pytest.mark.asyncio
async def test_webapp_trainer_education_delete(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Удал", "last_name": "Тест", "age": 30}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            post_resp = await client.post(
                "/api/webapp/trainer/education",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "education_type": "formal_education",
                    "institution_name": "БГУФК",
                    "program_or_title": "Тренерский факультет",
                },
            )
            assert post_resp.status_code == 201
            eid = post_resp.json()["id"]
            del_resp = await client.delete(
                f"/api/webapp/trainer/education/{eid}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert del_resp.status_code == 200
            assert del_resp.json() == {"ok": True}
            get_prof = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert get_prof.status_code == 200
    entries = get_prof.json().get("education_entries") or []
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_webapp_trainer_catalog_visibility_patch_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            "/api/webapp/trainer/catalog-visibility",
            json={"is_catalog_visible": False},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webapp_trainer_catalog_visibility_patch_allowed_before_activation(
    app_use_test_db,
    db_session,
) -> None:
    """
    The toggle is the trainer's opt-in, so it must work while they are still deciding.

    It used to 403 for anything but ``status=active`` — which meant a trainer could only say
    «не хочу в каталог» after being published there.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Не", "last_name": "Актив", "age": 29}},
        )
        trainer_id = create_resp.json()["id"]

    # A fresh row defaults to «не в каталоге» — publication is never implicit.
    r = await db_session.execute(
        text("SELECT is_catalog_visible FROM trainers WHERE id = :id"), {"id": trainer_id}
    )
    assert r.scalar() is False

    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/webapp/trainer/catalog-visibility",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"is_catalog_visible": True},
            )
    assert resp.status_code == 200, resp.text
    r = await db_session.execute(
        text("SELECT is_catalog_visible FROM trainers WHERE id = :id"), {"id": trainer_id}
    )
    assert r.scalar() is True


@pytest.mark.asyncio
async def test_webapp_trainer_catalog_visibility_patch_ok_for_active_trainer(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Кат", "last_name": "Алог", "age": 31}},
        )
        trainer_id = create_resp.json()["id"]
        st = await client.patch(f"/api/trainers/{trainer_id}/status", json={"status": "active"})
        assert st.status_code == 200
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            patch_resp = await client.patch(
                "/api/webapp/trainer/catalog-visibility",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"is_catalog_visible": False},
            )
            assert patch_resp.status_code == 200
            assert patch_resp.json() == {"ok": True}
            get_prof = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert get_prof.status_code == 200
    assert get_prof.json()["trainer"]["is_catalog_visible"] is False

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        get_rest = await client.get(f"/api/trainers/{trainer_id}")
    assert get_rest.status_code == 200
    assert get_rest.json().get("is_catalog_visible") is False


# --- TASK-046: trainer self-service arena creation --------------------------------------


async def _trainer_with_city(db_session, *, city_id: int) -> tuple[int, int]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Арена", "last_name": "Тест", "city_id": city_id}},
        )
        assert create_resp.status_code == 200, create_resp.text
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()
    return trainer_id, tg


@pytest.mark.asyncio
async def test_arena_setup_mode_create_creates_real_arena_and_hides_from_public_until_confirmed(
    app_use_test_db,
    db_session,
    monkeypatch,
) -> None:
    r = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r.scalar()
    if cid is None:
        pytest.skip("need seed cities")

    async def _fake_geocode(address, city_name):
        return None

    monkeypatch.setattr(
        "src.application.trainer_arena_create_use_cases._geocode_address",
        _fake_geocode,
    )

    trainer_id, tg = await _trainer_with_city(db_session, city_id=cid)

    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            create_resp = await client.post(
                "/api/webapp/trainer/profile/arena-setup",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"mode": "create", "arena_name": "Новый каток", "address": "ул. Тестовая, 10"},
            )
            assert create_resp.status_code == 200, create_resp.text
            body = create_resp.json()
            assert body["status"] == "created"
            arena_id = body["arena_id"]
            assert arena_id in (body["trainer"].get("arena_ids") or [])

            # AC-004: visible to the trainer's own (authenticated) arena list right away.
            trainer_arenas_resp = await client.get(
                "/api/webapp/trainer/profile/arenas",
                headers={"X-Telegram-Init-Data": "mock"},
                params={"city_id": cid},
            )
            assert trainer_arenas_resp.status_code == 200
            trainer_items = trainer_arenas_resp.json()["items"]
            trainer_ids = [a["id"] for a in trainer_items]
            assert arena_id in trainer_ids
            created_row = next(a for a in trainer_items if a["id"] == arena_id)
            assert created_row.get("address")

        # AC-004: NOT visible in the public client catalog until confirmed.
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            public_resp = await client.get("/api/public/arenas", params={"city_id": cid})
        assert public_resp.status_code == 200
        public_ids = [a["id"] for a in public_resp.json()["items"]]
        assert arena_id not in public_ids


@pytest.mark.asyncio
async def test_arena_setup_mode_create_duplicate_warns_then_confirm_creates(
    app_use_test_db,
    db_session,
    monkeypatch,
) -> None:
    r = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r.scalar()
    if cid is None:
        pytest.skip("need seed cities")

    async def _fake_geocode(address, city_name):
        return None

    monkeypatch.setattr(
        "src.application.trainer_arena_create_use_cases._geocode_address",
        _fake_geocode,
    )

    trainer_id, tg = await _trainer_with_city(db_session, city_id=cid)

    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post(
                "/api/webapp/trainer/profile/arena-setup",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"mode": "create", "arena_name": "Дубль Арена", "address": "ул. Первая, 1"},
            )
            assert first.status_code == 200
            first_arena_id = first.json()["arena_id"]

            dup = await client.post(
                "/api/webapp/trainer/profile/arena-setup",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"mode": "create", "arena_name": "дубль   арена", "address": "ул. Вторая, 2"},
            )
            assert dup.status_code == 200
            dup_body = dup.json()
            assert dup_body["status"] == "duplicate_warning"
            assert dup_body["duplicates"][0]["arena_id"] == first_arena_id

            confirmed = await client.post(
                "/api/webapp/trainer/profile/arena-setup",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "mode": "create",
                    "arena_name": "дубль   арена",
                    "address": "ул. Вторая, 2",
                    "confirm_duplicate": True,
                },
            )
            assert confirmed.status_code == 200
            assert confirmed.json()["status"] == "created"
            assert confirmed.json()["arena_id"] != first_arena_id


@pytest.mark.asyncio
async def test_arena_setup_mode_request_no_longer_supported(
    app_use_test_db,
    db_session,
) -> None:
    r = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r.scalar()
    if cid is None:
        pytest.skip("need seed cities")
    trainer_id, tg = await _trainer_with_city(db_session, city_id=cid)

    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/profile/arena-setup",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"mode": "request", "arena_name": "Старый путь"},
            )
    assert resp.status_code == 422


# --- TASK-068 S1/S2: arena_ids omit vs empty; on-request services ----------------------


@pytest.mark.asyncio
async def test_patch_profile_without_arena_ids_keeps_created_arena(
    app_use_test_db,
    db_session,
    monkeypatch,
) -> None:
    r = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r.scalar()
    if cid is None:
        pytest.skip("need seed cities")

    async def _fake_geocode(address, city_name):
        return None

    monkeypatch.setattr(
        "src.application.trainer_arena_create_use_cases._geocode_address",
        _fake_geocode,
    )

    _trainer_id, tg = await _trainer_with_city(db_session, city_id=cid)

    with patch(
        "src.api.miniapp_auth.deps.verify_telegram_init_data_principal",
        return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            create_resp = await client.post(
                "/api/webapp/trainer/profile/arena-setup",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"mode": "create", "arena_name": "Каток без PATCH арен", "address": "ул. Охраны, 1"},
            )
            assert create_resp.status_code == 200, create_resp.text
            arena_id = create_resp.json()["arena_id"]

            patch_resp = await client.patch(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"profile": {"contacts": "tg @keep-arenas"}},
            )
            assert patch_resp.status_code == 200, patch_resp.text

            get_resp = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert get_resp.status_code == 200
    assert arena_id in (get_resp.json()["trainer"].get("arena_ids") or [])


@pytest.mark.asyncio
async def test_patch_profile_empty_arena_ids_unlinks(
    app_use_test_db,
    db_session,
    monkeypatch,
) -> None:
    r = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r.scalar()
    if cid is None:
        pytest.skip("need seed cities")

    async def _fake_geocode(address, city_name):
        return None

    monkeypatch.setattr(
        "src.application.trainer_arena_create_use_cases._geocode_address",
        _fake_geocode,
    )

    _trainer_id, tg = await _trainer_with_city(db_session, city_id=cid)

    with patch(
        "src.api.miniapp_auth.deps.verify_telegram_init_data_principal",
        return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            create_resp = await client.post(
                "/api/webapp/trainer/profile/arena-setup",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"mode": "create", "arena_name": "Каток на снятие", "address": "ул. Пустая, 2"},
            )
            assert create_resp.status_code == 200, create_resp.text
            arena_id = create_resp.json()["arena_id"]

            patch_resp = await client.patch(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"arena_ids": []},
            )
            assert patch_resp.status_code == 200, patch_resp.text

            get_resp = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert get_resp.status_code == 200
    assert arena_id not in (get_resp.json()["trainer"].get("arena_ids") or [])


@pytest.mark.asyncio
async def test_patch_services_without_prices_keeps_on_request_service(
    app_use_test_db,
    db_session,
) -> None:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    if sid is None:
        pytest.skip("need seed services")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Цена", "last_name": "По запросу"}},
        )
        assert create_resp.status_code == 200, create_resp.text
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch(
        "src.api.miniapp_auth.deps.verify_telegram_init_data_principal",
        return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            patch_resp = await client.patch(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"services": [{"service_id": sid, "price_tiers": []}]},
            )
            assert patch_resp.status_code == 200, patch_resp.text

            get_resp = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert get_resp.status_code == 200
    services = get_resp.json()["trainer"].get("services") or []
    match = next((s for s in services if int(s["service_id"]) == int(sid)), None)
    assert match is not None
    assert match.get("price_byn") is None
    assert not (match.get("price_tiers") or [])


_PROFILE_WEBAPP = Path(__file__).resolve().parents[2] / "static" / "webapp"


def test_profile_arena_picker_markup_and_legacy_flag() -> None:
    """AC-005/006/009: search lives in static HTML; new picker is default; census is ?arena_picker=legacy."""
    html = (_PROFILE_WEBAPP / "trainer-profile.html").read_text(encoding="utf-8")
    js = (_PROFILE_WEBAPP / "trainer-profile-main.js").read_text(encoding="utf-8")
    assert 'id="arenaPicker"' in html
    assert 'id="arenaSearchInput"' in html
    assert 'id="arenaChips"' in html
    assert "getElementById('arenaSearchInput')" in js
    assert "arena_picker" in js
    assert "!== 'legacy'" in js
    assert "function profileArenaPickerEnabled" in js
    assert "updateArenaChips" in js
    assert "appendArenaCreateCta" in js
    assert "setPrimaryArena" in js


def test_profile_workplace_vitrine_ia() -> None:
    """S4: workplace blocks stay open; vitrine is collapsed and not marked required."""
    html = (_PROFILE_WEBAPP / "trainer-profile.html").read_text(encoding="utf-8")
    assert 'id="profileWorkplaceLabel"' in html
    assert 'id="profileVitrineLabel"' in html
    assert html.find('id="profileServicesCollapse"') < html.find('id="profileNavAbout"')
    assert html.find('id="profileNavArenas"') < html.find('id="profileNavAbout"')
    assert 'id="profileNavAbout" open' not in html
    assert 'id="profileNavExp" open' not in html
    assert 'for="description"><span class="required-dot"' not in html
    assert 'for="experience_years"><span class="required-dot"' not in html
    assert 'for="education"><span class="required-dot"' not in html
    assert 'for="first_name"><span class="required-dot"' in html
    assert 'for="city_id"><span class="required-dot"' in html
    assert 'for="phone"><span class="required-dot"' in html


def test_profile_focused_prices_task_contract() -> None:
    """S5 / AC-008: prices overlay is a query task, not a dump into the full form."""
    html_ob = (_PROFILE_WEBAPP / "trainer-onboarding.html").read_text(encoding="utf-8")
    js_ob = (_PROFILE_WEBAPP / "trainer-onboarding-main.js").read_text(encoding="utf-8")
    js = (_PROFILE_WEBAPP / "trainer-profile-main.js").read_text(encoding="utf-8")
    assert "Указать цены" in html_ob
    assert "task=prices" in js_ob
    assert "from=onboarding" in js_ob
    assert "PROFILE_FOCUSED_TASKS" in js
    assert "startFocusedProfileTask" in js
    assert "finishFocusedProfileTask" in js
    assert "get('task')" in js


def test_profile_focused_catalog_task_contract() -> None:
    """Catalog CTA opens one submission-gap carousel (task=catalog), not polish vitrine."""
    js = (_PROFILE_WEBAPP / "trainer-profile-main.js").read_text(encoding="utf-8")
    html = (_PROFILE_WEBAPP / "trainer-profile.html").read_text(encoding="utf-8")
    js_home = (_PROFILE_WEBAPP / "trainer-home-main.js").read_text(encoding="utf-8")
    css = (_PROFILE_WEBAPP / "mini-app-trainer-profile.css").read_text(encoding="utf-8")
    assert "catalog:" in js
    assert "vitrine:" in js  # legacy alias kept for old deep links
    assert "if (task === 'vitrine') task = 'catalog'" in js
    assert "buildCatalogFocusedRail" in js
    assert "containerId: 'profileNavPhoto'" in js
    assert "containerId: 'profileNavContacts'" in js
    assert 'id="profileNavPhoto"' in html
    assert 'id="profileNavContacts"' in html
    assert "task=catalog" in js_home
    assert "openHubCatalogProfileGaps" in js_home
    assert "task=vitrine" not in js_home
    assert "from=hub" in js_home
    assert "navigateTo('trainer-profile')" not in js_home
    assert "navigateToWithHash('trainer-profile'" not in js_home
    assert ".profile-block-tour-bar" not in css

