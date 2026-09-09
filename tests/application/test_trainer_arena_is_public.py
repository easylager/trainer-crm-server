"""TASK-057: trainer_arenas.is_public — vitrine vs schedule eligibility."""

from datetime import date, time, timedelta

import pytest
from sqlalchemy import text

from src.application.booking_use_cases import create_booking, ensure_trainer_schedule_arena_link
from src.infrastructure.repositories.catalog_repository import CatalogRepository
from src.infrastructure.repositories.trainer_repository import TrainerRepository
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id


async def _two_same_city_arenas(session) -> tuple[int, int, int]:
    r = await session.execute(
        text(
            """
            SELECT id, city_id FROM arenas
            WHERE COALESCE(is_active, true)
            ORDER BY city_id, id
            """
        )
    )
    by_city: dict[int, list[int]] = {}
    for aid, cid in r.fetchall():
        by_city.setdefault(int(cid), []).append(int(aid))
        if len(by_city[int(cid)]) >= 2:
            aids = by_city[int(cid)]
            return aids[0], aids[1], int(cid)
    pytest.skip("Need two active arenas in the same city")


async def _foreign_city_arena(session, trainer_city_id: int) -> int:
    """Another city's arena (created in-test when the seed DB has only one city). Rolled back with the test txn."""
    r = await session.execute(
        text("SELECT id FROM cities WHERE id <> :cid ORDER BY id LIMIT 1"),
        {"cid": trainer_city_id},
    )
    row = r.fetchone()
    if row is None:
        r = await session.execute(
            text("INSERT INTO cities (name, is_active) VALUES ('TASK057 other city', true) RETURNING id")
        )
        other_city = int(r.scalar_one())
    else:
        other_city = int(row[0])
    r = await session.execute(
        text(
            """
            SELECT id FROM arenas
            WHERE city_id = :cid AND COALESCE(is_active, true)
            ORDER BY id LIMIT 1
            """
        ),
        {"cid": other_city},
    )
    row = r.fetchone()
    if row:
        return int(row[0])
    r = await session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, is_active)
            VALUES (:cid, 'TASK057 foreign rink', true)
            RETURNING id
            """
        ),
        {"cid": other_city},
    )
    return int(r.scalar_one())


async def _insert_catalog_trainer(session, *, city_id: int, service_id: int) -> int:
    r = await session.execute(
        text(
            """
            INSERT INTO trainers (status, is_catalog_visible)
            VALUES ('active', true)
            RETURNING id
            """
        )
    )
    trainer_id = int(r.scalar_one())
    await session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id)
            VALUES (:tid, 'Vitrine', 'Split', 30, :cid)
            """
        ),
        {"tid": trainer_id, "cid": city_id},
    )
    await session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 4000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await session.commit()
    return trainer_id


async def _insert_client(session) -> int:
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'L', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    await session.commit()
    return int(client_id)


async def _insert_available_slot(session, trainer_id: int, *, arena_id: int | None = None) -> int:
    tomorrow = date.today() + timedelta(days=2)
    r = await session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, arena_id)
            VALUES (:tid, :d, :st, :et, 'available', :aid)
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "d": tomorrow,
            "st": time(10, 0),
            "et": time(11, 0),
            "aid": arena_id,
        },
    )
    (slot_id,) = r.fetchone()
    await session.commit()
    return int(slot_id)


async def _link_flags(session, trainer_id: int, arena_id: int) -> tuple[bool, bool]:
    r = await session.execute(
        text(
            """
            SELECT is_public FROM trainer_arenas
            WHERE trainer_id = :tid AND arena_id = :aid
            """
        ),
        {"tid": trainer_id, "aid": arena_id},
    )
    row = r.fetchone()
    if row is None:
        return False, False
    return True, bool(row[0])


@pytest.mark.asyncio
async def test_legacy_insert_defaults_is_public_true(db_session) -> None:
    """AC-002: existing INSERT shape (no is_public) stays vitrine-public."""
    arena_a, _arena_second, city_a = await _two_same_city_arenas(db_session)
    service_id = await require_seed_service_id(db_session)
    trainer_id = await _insert_catalog_trainer(db_session, city_id=city_a, service_id=service_id)
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_a},
    )
    await db_session.commit()
    exists, is_public = await _link_flags(db_session, trainer_id, arena_a)
    assert exists is True
    assert is_public is True


@pytest.mark.asyncio
async def test_booking_unbound_arena_creates_non_public_link_hidden_from_catalog(db_session) -> None:
    """AC-001: book unbound same-city arena → is_public=false; catalog arena filter omits trainer."""
    arena_a, _arena_second, city_a = await _two_same_city_arenas(db_session)
    service_id = await require_seed_service_id(db_session)
    trainer_id = await _insert_catalog_trainer(db_session, city_id=city_a, service_id=service_id)
    client_id = await _insert_client(db_session)
    slot_id = await _insert_available_slot(db_session, trainer_id, arena_id=arena_a)

    booking_id, _mile = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        created_by_trainer=True,
        arena_id=arena_a,
    )
    assert booking_id is not None

    exists, is_public = await _link_flags(db_session, trainer_id, arena_a)
    assert exists is True
    assert is_public is False

    r_place = await db_session.execute(
        text("SELECT arena_id FROM bookings WHERE id = :bid"),
        {"bid": booking_id},
    )
    assert int(r_place.scalar_one()) == arena_a

    items, _total = await TrainerRepository(db_session).list_active_with_details(
        limit=50, offset=0, city_id=city_a, arena_ids=[arena_a]
    )
    assert trainer_id not in {t["id"] for t in items}

    catalog = CatalogRepository(db_session)
    arenas = await catalog.list_arenas(city_a, service_id=service_id)
    row = next((a for a in arenas if a["id"] == arena_a), None)
    assert row is not None
    public_ids = {
        t["id"]
        for t in (
            await TrainerRepository(db_session).list_active_with_details(
                limit=200, offset=0, city_id=city_a, service_id=service_id, arena_ids=[arena_a]
            )
        )[0]
    }
    assert trainer_id not in public_ids
    assert int(row.get("trainer_count") or 0) == len(public_ids)


@pytest.mark.asyncio
async def test_toggle_is_public_changes_catalog_listing(db_session) -> None:
    """AC-003: hiding then showing an arena immediately changes public listing."""
    arena_a, _arena_second, city_a = await _two_same_city_arenas(db_session)
    service_id = await require_seed_service_id(db_session)
    trainer_id = await _insert_catalog_trainer(db_session, city_id=city_a, service_id=service_id)
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_a},
    )
    await db_session.commit()

    repo = TrainerRepository(db_session)
    items, _ = await repo.list_active_with_details(
        limit=50, offset=0, city_id=city_a, arena_ids=[arena_a]
    )
    assert trainer_id in {t["id"] for t in items}

    ok = await repo.set_trainer_arena_is_public(trainer_id, arena_a, False)
    assert ok is True
    await db_session.commit()

    items, _ = await repo.list_active_with_details(
        limit=50, offset=0, city_id=city_a, arena_ids=[arena_a]
    )
    assert trainer_id not in {t["id"] for t in items}

    ok = await repo.set_trainer_arena_is_public(trainer_id, arena_a, True)
    assert ok is True
    await db_session.commit()

    items, _ = await repo.list_active_with_details(
        limit=50, offset=0, city_id=city_a, arena_ids=[arena_a]
    )
    assert trainer_id in {t["id"] for t in items}
    ours = next(t for t in items if t["id"] == trainer_id)
    assert arena_a in (ours.get("arena_ids") or [])


@pytest.mark.asyncio
async def test_refuse_other_city_does_not_create_link(db_session) -> None:
    """AC-004: arena in another city → refuse, no trainer_arenas row."""
    _arena_a, _arena_second, city_a = await _two_same_city_arenas(db_session)
    arena_b = await _foreign_city_arena(db_session, city_a)
    service_id = await require_seed_service_id(db_session)
    trainer_id = await _insert_catalog_trainer(db_session, city_id=city_a, service_id=service_id)

    err = await ensure_trainer_schedule_arena_link(db_session, trainer_id, arena_b)
    assert err is not None
    exists, _ = await _link_flags(db_session, trainer_id, arena_b)
    assert exists is False

    client_id = await _insert_client(db_session)
    slot_id = await _insert_available_slot(db_session, trainer_id, arena_id=arena_b)
    booking_id, _mile = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        created_by_trainer=True,
        arena_id=arena_b,
    )
    assert booking_id is None
    exists, _ = await _link_flags(db_session, trainer_id, arena_b)
    assert exists is False


@pytest.mark.asyncio
async def test_refuse_inactive_arena_does_not_create_link(db_session) -> None:
    """AC-004: inactive same-city arena → refuse, no trainer_arenas row."""
    arena_a, inactive_id, city_a = await _two_same_city_arenas(db_session)
    await db_session.execute(
        text("UPDATE arenas SET is_active = false WHERE id = :aid"),
        {"aid": inactive_id},
    )
    await db_session.commit()

    service_id = await require_seed_service_id(db_session)
    trainer_id = await _insert_catalog_trainer(db_session, city_id=city_a, service_id=service_id)

    err = await ensure_trainer_schedule_arena_link(db_session, trainer_id, inactive_id)
    assert err is not None
    exists, _ = await _link_flags(db_session, trainer_id, inactive_id)
    assert exists is False


@pytest.mark.asyncio
async def test_booking_place_stays_slot_arena_when_link_auto_created(db_session) -> None:
    """TASK-056: auto-created schedule link must not steal booking place to another arena."""
    arena_a, arena_second, city_a = await _two_same_city_arenas(db_session)
    service_id = await require_seed_service_id(db_session)
    trainer_id = await _insert_catalog_trainer(db_session, city_id=city_a, service_id=service_id)
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_a},
    )
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
        {"aid": arena_a, "tid": trainer_id},
    )
    await db_session.commit()

    client_id = await _insert_client(db_session)
    slot_id = await _insert_available_slot(db_session, trainer_id, arena_id=arena_second)
    booking_id, _mile = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        created_by_trainer=True,
        arena_id=arena_second,
    )
    assert booking_id is not None
    r_place = await db_session.execute(
        text("SELECT arena_id FROM bookings WHERE id = :bid"),
        {"bid": booking_id},
    )
    assert int(r_place.scalar_one()) == arena_second
    exists, is_public = await _link_flags(db_session, trainer_id, arena_second)
    assert exists is True
    assert is_public is False
