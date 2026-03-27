"""Web App trainer profile API: initData auth, aggregate GET, PATCH (Part 1)."""
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app


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
    with (
        patch("src.api.routes.webapp_trainer_profile.validate_init_data", return_value=True),
        patch("src.api.routes.webapp_trainer_profile.parse_user_id_from_init_data", return_value=tg),
    ):
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

    with (
        patch("src.api.routes.webapp_trainer_profile.validate_init_data", return_value=True),
        patch("src.api.routes.webapp_trainer_profile.parse_user_id_from_init_data", return_value=tg),
    ):
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
    assert "education_entries" in data
    assert isinstance(data["education_entries"], list)


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

    with (
        patch("src.api.routes.webapp_trainer_profile.validate_init_data", return_value=True),
        patch("src.api.routes.webapp_trainer_profile.parse_user_id_from_init_data", return_value=tg),
    ):
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

    with (
        patch("src.api.routes.webapp_trainer_profile.validate_init_data", return_value=True),
        patch("src.api.routes.webapp_trainer_profile.parse_user_id_from_init_data", return_value=tg),
    ):
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

    with (
        patch("src.api.routes.webapp_trainer_profile.validate_init_data", return_value=True),
        patch("src.api.routes.webapp_trainer_profile.parse_user_id_from_init_data", return_value=tg),
    ):
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

    with (
        patch("src.api.routes.webapp_trainer_profile.validate_init_data", return_value=True),
        patch("src.api.routes.webapp_trainer_profile.parse_user_id_from_init_data", return_value=tg),
    ):
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
