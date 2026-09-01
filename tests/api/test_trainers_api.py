"""
API tests for trainer list endpoints. Use test DB (same DATABASE_URL as pytest).
"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.schemas import TRAINER_EDUCATION_OPTIONS
from src.application.subscription_use_cases import create_trial_subscription


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


@pytest.mark.asyncio
async def test_public_trainer_reviews_404_for_unknown_trainer(app_use_test_db) -> None:
    """GET /api/public/trainers/{id}/reviews returns 404 when trainer is missing."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/public/trainers/999999/reviews")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_trainer_education_options_returns_supported_values(app_use_test_db) -> None:
    """GET /api/trainers/education-options returns allowed values for UI select."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/trainers/education-options")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == list(TRAINER_EDUCATION_OPTIONS)


@pytest.mark.asyncio
async def test_patch_profile_accepts_supported_education_value(app_use_test_db) -> None:
    """PATCH /api/trainers/{id}/profile stores education from supported options."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Тест", "last_name": "Тренер", "age": 30}},
        )
        trainer_id = create_resp.json()["id"]
        education = TRAINER_EDUCATION_OPTIONS[0]
        patch_resp = await client.patch(
            f"/api/trainers/{trainer_id}/profile",
            json={"profile": {"education": education}},
        )
        get_resp = await client.get(f"/api/trainers/{trainer_id}")
    assert patch_resp.status_code == 200
    assert get_resp.status_code == 200
    assert get_resp.json()["profile"]["education"] == education


@pytest.mark.asyncio
async def test_trainer_education_create_and_list_returns_pending(app_use_test_db) -> None:
    """POST/GET /api/trainers/{id}/education stores structured pending entry."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Иван", "last_name": "Тренер", "age": 31}},
        )
        trainer_id = create_resp.json()["id"]
        post_resp = await client.post(
            f"/api/trainers/{trainer_id}/education",
            json={
                "education_type": "formal_education",
                "institution_name": "БГУФК",
                "program_or_title": "Тренер по хоккею",
            },
        )
        list_resp = await client.get(f"/api/trainers/{trainer_id}/education")
    assert post_resp.status_code == 201
    created = post_resp.json()
    assert created["moderation_status"] == "pending_moderation"
    assert "id" in created
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) >= 1
    assert items[0]["institution_name"] == "БГУФК"
    assert items[0]["moderation_status"] == "pending_moderation"


@pytest.mark.asyncio
async def test_trainer_education_patch_keeps_pending_for_non_approved(app_use_test_db) -> None:
    """PATCH /api/trainers/{id}/education/{eid} updates non-approved rows in place."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Петр", "last_name": "Тренер", "age": 29}},
        )
        trainer_id = create_resp.json()["id"]
        post_resp = await client.post(
            f"/api/trainers/{trainer_id}/education",
            json={
                "education_type": "course_or_certificate",
                "institution_name": "Skillbox",
                "program_or_title": "Спортивная физиология",
            },
        )
        education_id = post_resp.json()["id"]
        patch_resp = await client.patch(
            f"/api/trainers/{trainer_id}/education/{education_id}",
            json={"program_or_title": "Спортивная физиология PRO"},
        )
        list_resp = await client.get(f"/api/trainers/{trainer_id}/education")
    assert patch_resp.status_code == 200
    body = patch_resp.json()
    assert body["moderation_status"] == "pending_moderation"
    assert body["revision_created"] is False
    items = list_resp.json()["items"]
    assert items[0]["program_or_title"] == "Спортивная физиология PRO"


@pytest.mark.asyncio
async def test_trainer_education_patch_creates_revision_for_approved(app_use_test_db, db_session) -> None:
    """PATCH creates pending revision when source education already approved."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Сергей", "last_name": "Тренер", "age": 35}},
        )
        trainer_id = create_resp.json()["id"]
        post_resp = await client.post(
            f"/api/trainers/{trainer_id}/education",
            json={
                "education_type": "formal_education",
                "institution_name": "БГУ",
                "program_or_title": "Физическая культура",
            },
        )
        education_id = post_resp.json()["id"]
    await db_session.execute(
        text(
            """
            UPDATE trainer_education
            SET moderation_status = 'approved',
                approved_snapshot = true
            WHERE id = :eid
            """
        ),
        {"eid": education_id},
    )
    await db_session.commit()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        patch_resp = await client.patch(
            f"/api/trainers/{trainer_id}/education/{education_id}",
            json={"program_or_title": "Физическая культура и спорт"},
        )
    assert patch_resp.status_code == 200
    body = patch_resp.json()
    assert body["revision_created"] is True
    rows = await db_session.execute(
        text("SELECT COUNT(*) FROM trainer_education WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    assert int(rows.scalar() or 0) == 2


@pytest.mark.asyncio
async def test_public_trainer_education_returns_only_approved_records(app_use_test_db, db_session) -> None:
    """Public endpoint returns only approved snapshot records."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Олег", "last_name": "Тренер", "age": 33}},
        )
        trainer_id = create_resp.json()["id"]
        await client.patch(f"/api/trainers/{trainer_id}/status", json={"status": "active"})
        # Since 0182_catalog_opt_in the catalog is opt-in: `active` alone no longer publishes a card.
        await db_session.execute(
            text("UPDATE trainers SET is_catalog_visible = true WHERE id = :tid"),
            {"tid": trainer_id},
        )
        await db_session.commit()
        approved_resp = await client.post(
            f"/api/trainers/{trainer_id}/education",
            json={
                "education_type": "formal_education",
                "institution_name": "БНТУ",
                "program_or_title": "Теория спорта",
            },
        )
        pending_resp = await client.post(
            f"/api/trainers/{trainer_id}/education",
            json={
                "education_type": "course_or_certificate",
                "institution_name": "Coursera",
                "program_or_title": "Sport Nutrition",
            },
        )
        approved_id = approved_resp.json()["id"]
    await create_trial_subscription(db_session, trainer_id)
    await db_session.execute(
        text(
            """
            UPDATE trainer_education
            SET moderation_status = 'approved',
                approved_snapshot = CASE WHEN id = :approved_id THEN true ELSE false END
            WHERE trainer_id = :tid
            """
        ),
        {"tid": trainer_id, "approved_id": approved_id},
    )
    await db_session.commit()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        public_resp = await client.get(f"/api/public/trainers/{trainer_id}/education")
    assert pending_resp.status_code == 201
    assert public_resp.status_code == 200
    items = public_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == approved_id
