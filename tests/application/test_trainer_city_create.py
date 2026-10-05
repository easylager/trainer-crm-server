"""Trainer-proposed cities (TASK-170)."""

import uuid

import pytest
from sqlalchemy import text

from src.application.trainer_city_create_use_cases import (
    create_trainer_city,
    trainer_may_use_city_id,
)
from src.application.trainer_use_cases import create_trainer
from src.infrastructure.repositories.catalog_repository import CatalogRepository


async def _trainer_id(db_session, *, phone_suffix: str = "2233") -> int:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    r2 = await db_session.execute(text("SELECT id FROM cities WHERE is_active ORDER BY id LIMIT 1"))
    city_id = r2.scalar()
    if sid is None or city_id is None:
        pytest.skip("need seed")
    return await create_trainer(
        db_session,
        profile={
            "first_name": "T",
            "last_name": "C",
            "phone": f"+37529111{phone_suffix}",
            "city_id": city_id,
        },
        service_ids=[sid],
        arena_ids=[],
    )


@pytest.mark.asyncio
async def test_create_trainer_city_inactive_until_moderation(db_session) -> None:
    trainer_id = await _trainer_id(db_session)
    unique = f"Город-Тест-{uuid.uuid4().hex[:8]}"

    result = await create_trainer_city(db_session, trainer_id, name=unique)
    assert result["status"] == "created"
    cid = int(result["city_id"])
    assert result["is_active"] is False

    row = (
        await db_session.execute(
            text(
                "SELECT is_active, created_by_trainer_id FROM cities WHERE id = :id"
            ),
            {"id": cid},
        )
    ).fetchone()
    assert row is not None
    assert row[0] is False
    assert row[1] == trainer_id

    assert await trainer_may_use_city_id(db_session, trainer_id, cid) is True
    other_tid = trainer_id + 99999
    assert await trainer_may_use_city_id(db_session, other_tid, cid) is False


@pytest.mark.asyncio
async def test_create_trainer_city_dedupes_active_name(db_session) -> None:
    trainer_id = await _trainer_id(db_session)
    r = await db_session.execute(
        text("SELECT id, name FROM cities WHERE is_active ORDER BY id LIMIT 1")
    )
    row = r.fetchone()
    assert row is not None
    active_id, active_name = int(row[0]), row[1]

    result = await create_trainer_city(db_session, trainer_id, name=active_name.lower())
    assert result["status"] == "existing_active"
    assert int(result["city_id"]) == active_id


@pytest.mark.asyncio
async def test_create_trainer_city_rejects_other_trainers_pending(db_session) -> None:
    trainer_a = await _trainer_id(db_session, phone_suffix="2201")
    trainer_b = await _trainer_id(db_session, phone_suffix="2202")
    assert trainer_a != trainer_b
    unique = f"Чужой-Pending-{uuid.uuid4().hex[:8]}"

    created = await create_trainer_city(db_session, trainer_a, name=unique)
    assert created["status"] == "created"
    cid = int(created["city_id"])

    with pytest.raises(ValueError, match="другим тренером"):
        await create_trainer_city(db_session, trainer_b, name=unique.lower())

    assert await trainer_may_use_city_id(db_session, trainer_b, cid) is False


@pytest.mark.asyncio
async def test_public_catalog_lists_only_active_cities(db_session) -> None:
    trainer_id = await _trainer_id(db_session)
    unique = f"Скрытый-{uuid.uuid4().hex[:8]}"
    created = await create_trainer_city(db_session, trainer_id, name=unique)
    cid = int(created["city_id"])

    repo = CatalogRepository(db_session)
    public = await repo.list_cities()
    assert cid not in {c["id"] for c in public}
