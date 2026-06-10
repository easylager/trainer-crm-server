"""Web App trainer profile API: initData auth, aggregate GET, PATCH (Part 1)."""
import uuid
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
async def test_webapp_trainer_catalog_visibility_patch_403_when_not_active(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Не", "last_name": "Актив", "age": 29}},
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
            resp = await client.patch(
                "/api/webapp/trainer/catalog-visibility",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"is_catalog_visible": False},
            )
    assert resp.status_code == 403


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
