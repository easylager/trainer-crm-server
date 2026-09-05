"""TASK-056: booking place is the slot/event arena, not a silent primary override."""

from datetime import date, time, timedelta

import pytest
from sqlalchemy import text

from src.application.booking_use_cases import (
    BOOKING_ARENA_UNSPECIFIED_LABEL,
    active_booking_summaries_by_slot_for_trainer_range,
    create_booking,
    get_trainer_booking_detail_payload,
    list_bookings_for_trainer,
    resolve_arena_for_client_self_booking,
)
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id


async def _two_seeded_arenas(session) -> tuple[int, int, int]:
    r = await session.execute(
        text(
            """
            SELECT id, city_id FROM arenas
            WHERE COALESCE(is_active, true)
            ORDER BY id
            LIMIT 2
            """
        )
    )
    rows = r.fetchall()
    if len(rows) < 2:
        pytest.skip("Need at least two seeded arenas")
    return int(rows[0][0]), int(rows[1][0]), int(rows[0][1])


async def _seed_trainer_two_arenas(session, *, primary: int, secondary: int, city_id: int):
    service_id = await require_seed_service_id(session)
    r = await session.execute(
        text("INSERT INTO trainers (status, primary_arena_id) VALUES ('active', :a) RETURNING id"),
        {"a": primary},
    )
    trainer_id = int(r.scalar_one())
    await session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id)
            VALUES (:tid, 'Place', 'Test', 30, :cid)
            """
        ),
        {"tid": trainer_id, "cid": city_id},
    )
    await session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 4000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    for aid in (primary, secondary):
        await session.execute(
            text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
            {"tid": trainer_id, "aid": aid},
        )
    await session.commit()
    return trainer_id, service_id


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


@pytest.mark.asyncio
async def test_resolve_books_slot_arena_not_primary_when_client_came_from_slot_arena(db_session) -> None:
    """AC-001: filter/card arena X + slot on X → resolved arena is X, even if primary is Y."""
    primary, secondary, city_id = await _two_seeded_arenas(db_session)
    trainer_id, _sid = await _seed_trainer_two_arenas(
        db_session, primary=primary, secondary=secondary, city_id=city_id
    )

    resolved, err, mismatch = await resolve_arena_for_client_self_booking(
        db_session, trainer_id, secondary, secondary
    )
    assert err is None
    assert resolved == secondary
    assert mismatch is False


@pytest.mark.asyncio
async def test_resolve_mismatch_when_slot_place_differs_from_origin_arena(db_session) -> None:
    """AC-002: slot on primary Y, client came from X → book Y, mismatch True."""
    primary, secondary, city_id = await _two_seeded_arenas(db_session)
    trainer_id, _sid = await _seed_trainer_two_arenas(
        db_session, primary=primary, secondary=secondary, city_id=city_id
    )

    resolved, err, mismatch = await resolve_arena_for_client_self_booking(
        db_session, trainer_id, primary, secondary
    )
    assert err is None
    assert resolved == primary
    assert mismatch is True


@pytest.mark.asyncio
async def test_resolve_null_slot_uses_schedule_default_not_origin_override(db_session) -> None:
    """NULL slot → schedule default (primary). Origin X only sets mismatch, does not steal the place."""
    primary, secondary, city_id = await _two_seeded_arenas(db_session)
    trainer_id, _sid = await _seed_trainer_two_arenas(
        db_session, primary=primary, secondary=secondary, city_id=city_id
    )

    resolved, err, mismatch = await resolve_arena_for_client_self_booking(
        db_session, trainer_id, None, secondary
    )
    assert err is None
    assert resolved == primary
    assert mismatch is True


@pytest.mark.asyncio
async def test_resolve_single_arena_no_origin_matches_previous_behavior(db_session) -> None:
    """AC-005: one arena, no catalog filter — still that arena, no mismatch."""
    arena_id, city_id, _ = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(
        text("INSERT INTO trainers (status, primary_arena_id) VALUES ('active', :a) RETURNING id"),
        {"a": arena_id},
    )
    trainer_id = int(r.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id)
            VALUES (:tid, 'One', 'Arena', 30, :cid)
            """
        ),
        {"tid": trainer_id, "cid": city_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 4000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    await db_session.commit()

    resolved, err, mismatch = await resolve_arena_for_client_self_booking(
        db_session, trainer_id, None, None
    )
    assert err is None
    assert resolved == arena_id
    assert mismatch is False


@pytest.mark.asyncio
async def test_booking_without_arena_shows_placeholder_not_comma_list(db_session) -> None:
    """AC-003: no booking/slot arena → «место уточняет тренер», never all trainer rinks joined."""
    primary, secondary, city_id = await _two_seeded_arenas(db_session)
    trainer_id, service_id = await _seed_trainer_two_arenas(
        db_session, primary=primary, secondary=secondary, city_id=city_id
    )
    tomorrow = date.today() + timedelta(days=1)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :et, 'booked')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": tomorrow, "st": time(10, 0), "et": time(11, 0)},
    )
    (slot_id,) = r.fetchone()
    client_id = await _insert_client(db_session)
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status, arena_id)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed', NULL)
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    await db_session.commit()

    bookings = await list_bookings_for_trainer(db_session, trainer_id)
    assert len(bookings) == 1
    assert bookings[0]["arenas_str"] == BOOKING_ARENA_UNSPECIFIED_LABEL
    assert "," not in (bookings[0]["arenas_str"] or "")

    detail = await get_trainer_booking_detail_payload(db_session, bookings[0]["id"], trainer_id)
    assert detail is not None
    assert detail["arenas_str"] == BOOKING_ARENA_UNSPECIFIED_LABEL

    summaries = await active_booking_summaries_by_slot_for_trainer_range(
        db_session, trainer_id, tomorrow, tomorrow
    )
    assert summaries[slot_id]["venue_label"] == BOOKING_ARENA_UNSPECIFIED_LABEL


@pytest.mark.asyncio
async def test_existing_booking_arena_stays_when_trainer_changes_primary(db_session) -> None:
    """EDGE-002: persisted booking.arena_id does not follow a later primary change."""
    primary, secondary, city_id = await _two_seeded_arenas(db_session)
    trainer_id, service_id = await _seed_trainer_two_arenas(
        db_session, primary=primary, secondary=secondary, city_id=city_id
    )
    tomorrow = date.today() + timedelta(days=2)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, arena_id)
            VALUES (:tid, :d, :st, :et, 'available', :aid)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": tomorrow, "st": time(12, 0), "et": time(13, 0), "aid": secondary},
    )
    (slot_id,) = r.fetchone()
    client_id = await _insert_client(db_session)
    booking_id, _ = await create_booking(
        db_session,
        slot_id,
        trainer_id,
        client_id,
        service_id=service_id,
        arena_id=secondary,
    )
    assert booking_id
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
        {"aid": primary, "tid": trainer_id},
    )
    await db_session.commit()

    row = await db_session.execute(
        text("SELECT arena_id FROM bookings WHERE id = :bid"), {"bid": booking_id}
    )
    assert int(row.scalar_one()) == secondary
    detail = await get_trainer_booking_detail_payload(db_session, booking_id, trainer_id)
    assert detail is not None
    assert detail.get("arena_id") == secondary
