"""Trainer self-service arena creation (TASK-046): real row, soft dup-check, no geocoding block."""

import pytest
from sqlalchemy import text

from src.application.trainer_arena_create_use_cases import (
    create_trainer_arena,
    find_possible_duplicate_arenas,
)
from src.application.trainer_use_cases import create_trainer, get_trainer


async def _minimal_trainer_id(db_session, *, city_id: int | None = None) -> tuple[int, int]:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    if city_id is None:
        r2 = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
        city_id = r2.scalar()
    if sid is None or city_id is None:
        pytest.skip("need seed services and cities")
    trainer_id = await create_trainer(
        db_session,
        profile={
            "first_name": "Ann",
            "last_name": "Xu",
            "phone": "+375291112233",
            "city_id": city_id,
        },
        service_ids=[sid],
        arena_ids=[],
    )
    return trainer_id, city_id


@pytest.fixture(autouse=True)
def _no_real_geocoding(monkeypatch):
    """Every test in this module must not hit the real Nominatim service."""

    async def _fake_geocode(address, city_name):
        return None

    monkeypatch.setattr(
        "src.application.trainer_arena_create_use_cases._geocode_address",
        _fake_geocode,
    )
    yield


@pytest.mark.asyncio
async def test_create_trainer_arena_creates_unconfirmed_row_and_auto_attaches(db_session) -> None:
    trainer_id, city_id = await _minimal_trainer_id(db_session)

    result = await create_trainer_arena(
        db_session,
        trainer_id,
        name="Ледовый дворец на Немиге",
        address="ул. Немига, 5",
    )
    assert result["status"] == "created"
    arena_id = result["arena_id"]
    assert arena_id

    row = (
        await db_session.execute(
            text(
                "SELECT is_active, is_confirmed, created_by_trainer_id, city_id "
                "FROM arenas WHERE id = :id"
            ),
            {"id": arena_id},
        )
    ).fetchone()
    assert row is not None
    assert row[0] is True
    assert row[1] is False
    assert row[2] == trainer_id
    assert row[3] == city_id

    trainer = result["trainer"]
    assert arena_id in (trainer.get("arena_ids") or [])


@pytest.mark.asyncio
async def test_create_trainer_arena_requires_name_and_address(db_session) -> None:
    trainer_id, _ = await _minimal_trainer_id(db_session)
    with pytest.raises(ValueError):
        await create_trainer_arena(db_session, trainer_id, name="", address="ул. Примерная, 1")
    with pytest.raises(ValueError):
        await create_trainer_arena(db_session, trainer_id, name="Арена", address="")


@pytest.mark.asyncio
async def test_create_trainer_arena_soft_duplicate_by_name_blocks_until_confirmed(db_session) -> None:
    trainer_id, city_id = await _minimal_trainer_id(db_session)
    first = await create_trainer_arena(db_session, trainer_id, name="Каток Минск", address="ул. А, 1")
    assert first["status"] == "created"

    second = await create_trainer_arena(
        db_session, trainer_id, name="каток   минск!", address="ул. Б, 2"
    )
    assert second["status"] == "duplicate_warning"
    assert second["duplicates"]
    assert second["duplicates"][0]["arena_id"] == first["arena_id"]

    third = await create_trainer_arena(
        db_session,
        trainer_id,
        name="каток   минск!",
        address="ул. Б, 2",
        confirm_duplicate=True,
    )
    assert third["status"] == "created"
    assert third["arena_id"] != first["arena_id"]


@pytest.mark.asyncio
async def test_find_possible_duplicate_arenas_by_radius(db_session) -> None:
    trainer_id, city_id = await _minimal_trainer_id(db_session)
    await db_session.execute(
        text(
            "INSERT INTO arenas (city_id, name, address, latitude, longitude, is_active, is_confirmed) "
            "VALUES (:cid, 'Существующая арена', 'адрес', 53.9, 27.5667, true, true)"
        ),
        {"cid": city_id},
    )
    await db_session.commit()

    near = await find_possible_duplicate_arenas(
        db_session, city_id, name="Совсем другое название", latitude=53.9005, longitude=27.5670
    )
    assert near, "point ~60m away must be flagged as a possible duplicate"

    far = await find_possible_duplicate_arenas(
        db_session, city_id, name="Совсем другое название", latitude=53.95, longitude=27.60
    )
    assert not far


@pytest.mark.asyncio
async def test_create_trainer_arena_requires_city_on_profile(db_session) -> None:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    if sid is None:
        pytest.skip("need seed services")
    trainer_id = await create_trainer(
        db_session,
        profile={"first_name": "No", "last_name": "City", "phone": "+375291112244"},
        service_ids=[sid],
        arena_ids=[],
    )
    with pytest.raises(ValueError):
        await create_trainer_arena(db_session, trainer_id, name="Арена", address="ул. Примерная, 1")


@pytest.mark.asyncio
async def test_create_trainer_arena_accepts_explicit_city_when_profile_city_missing(
    db_session,
) -> None:
    """Draft UX: city selected in form but not yet PATCH'ed — create still works (PDEC-001)."""
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    r2 = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    city_id = r2.scalar()
    if sid is None or city_id is None:
        pytest.skip("need seed services and cities")
    trainer_id = await create_trainer(
        db_session,
        profile={"first_name": "No", "last_name": "City", "phone": "+375291112255"},
        service_ids=[sid],
        arena_ids=[],
    )
    result = await create_trainer_arena(
        db_session,
        trainer_id,
        name="Новая арена черновик",
        address="ул. Черновиковая, 1",
        city_id=city_id,
    )
    assert result["status"] == "created"
    row = (
        await db_session.execute(
            text("SELECT city_id FROM arenas WHERE id = :id"),
            {"id": result["arena_id"]},
        )
    ).fetchone()
    assert row is not None and row[0] == city_id
    trainer = await get_trainer(db_session, trainer_id)
    assert (trainer.get("profile") or {}).get("city_id") == city_id
