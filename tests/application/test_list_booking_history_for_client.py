"""
TASK-007: client booking history — the complement of list_bookings_for_client.

Partition invariant: upcoming ∪ history = all of the client's bookings, no gaps, no
overlap. The predicate is deliberately NOT "slot_end < now" — a booking cancelled for a
FUTURE slot must show up in history immediately (status NOT IN pending/confirmed), or it
would vanish from both lists. See TASK-007-client-booking-history.md AC-004.
"""
import pytest
from sqlalchemy import text

from src.application.booking_use_cases import (
    list_booking_history_for_client,
    list_bookings_for_client,
    list_client_booking_trainer_options,
)

from tests.application.test_list_bookings_for_trainer_hub import _seed_trainer_with_service
from tests.conftest import belarus_test_phone, unique_test_telegram_id


async def _seed_client(db_session, tg: int) -> int:
    phone, phone_n = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'L', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    return int(client_id)


async def _seed_slot(db_session, trainer_id: int, *, day_offset: int) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (
                :tid,
                (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date + make_interval(days => :off),
                TIME '10:00',
                TIME '11:00',
                'booked'
            )
            RETURNING id
            """
        ),
        {"tid": trainer_id, "off": day_offset},
    )
    (slot_id,) = r.fetchone()
    return int(slot_id)


async def _seed_booking(
    db_session, *, slot_id: int, trainer_id: int, client_id: int, service_id: int,
    status: str, is_sandbox: bool = False,
) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status, is_sandbox)
            VALUES (:sid, :tid, :cid, :svc, :status, :sandbox)
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id, "status": status, "sandbox": is_sandbox},
    )
    (booking_id,) = r.fetchone()
    return int(booking_id)


@pytest.mark.asyncio
async def test_history_includes_all_terminal_statuses_and_excludes_upcoming(db_session) -> None:
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tg = unique_test_telegram_id()
    client_id = await _seed_client(db_session, tg)

    past_slot = await _seed_slot(db_session, trainer_id, day_offset=-1)
    future_slot = await _seed_slot(db_session, trainer_id, day_offset=1)

    completed_id = await _seed_booking(db_session, slot_id=past_slot, trainer_id=trainer_id, client_id=client_id, service_id=service_id, status="completed")
    upcoming_id = await _seed_booking(db_session, slot_id=future_slot, trainer_id=trainer_id, client_id=client_id, service_id=service_id, status="confirmed")
    await db_session.commit()

    history_rows, has_more = await list_booking_history_for_client(db_session, tg)
    history_ids = {r["id"] for r in history_rows}
    assert history_ids == {completed_id}
    assert has_more is False

    upcoming_rows = await list_bookings_for_client(db_session, tg)
    upcoming_ids = {r["id"] for r in upcoming_rows}
    assert upcoming_ids == {upcoming_id}


@pytest.mark.asyncio
async def test_cancelled_future_booking_shows_in_history_not_upcoming(db_session) -> None:
    """The AC-004 gap this predicate was written to close."""
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tg = unique_test_telegram_id()
    client_id = await _seed_client(db_session, tg)

    future_slot = await _seed_slot(db_session, trainer_id, day_offset=3)
    cancelled_id = await _seed_booking(db_session, slot_id=future_slot, trainer_id=trainer_id, client_id=client_id, service_id=service_id, status="cancelled")
    await db_session.commit()

    upcoming_rows = await list_bookings_for_client(db_session, tg)
    assert cancelled_id not in {r["id"] for r in upcoming_rows}

    history_rows, _ = await list_booking_history_for_client(db_session, tg)
    assert {r["id"] for r in history_rows} == {cancelled_id}
    assert history_rows[0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_history_partition_covers_all_bookings_no_overlap(db_session) -> None:
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tg = unique_test_telegram_id()
    client_id = await _seed_client(db_session, tg)

    statuses_and_offsets = [
        ("completed", -5), ("cancelled", -2), ("declined", 4), ("no_show", -1),
        ("payment_dispute", -3), ("trainer_removed", -4), ("pending", 2), ("confirmed", 1),
    ]
    all_ids = set()
    for status, offset in statuses_and_offsets:
        slot_id = await _seed_slot(db_session, trainer_id, day_offset=offset)
        bid = await _seed_booking(db_session, slot_id=slot_id, trainer_id=trainer_id, client_id=client_id, service_id=service_id, status=status)
        all_ids.add(bid)
    await db_session.commit()

    upcoming_rows = await list_bookings_for_client(db_session, tg)
    history_rows, _ = await list_booking_history_for_client(db_session, tg, limit=100)
    upcoming_ids = {r["id"] for r in upcoming_rows}
    history_ids = {r["id"] for r in history_rows}

    assert upcoming_ids & history_ids == set()
    assert upcoming_ids | history_ids == all_ids


@pytest.mark.asyncio
async def test_history_excludes_sandbox(db_session) -> None:
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tg = unique_test_telegram_id()
    client_id = await _seed_client(db_session, tg)

    slot_id = await _seed_slot(db_session, trainer_id, day_offset=-1)
    await _seed_booking(db_session, slot_id=slot_id, trainer_id=trainer_id, client_id=client_id, service_id=service_id, status="completed", is_sandbox=True)
    await db_session.commit()

    history_rows, _ = await list_booking_history_for_client(db_session, tg)
    assert history_rows == []


@pytest.mark.asyncio
async def test_history_sorted_newest_first(db_session) -> None:
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tg = unique_test_telegram_id()
    client_id = await _seed_client(db_session, tg)

    older_slot = await _seed_slot(db_session, trainer_id, day_offset=-10)
    newer_slot = await _seed_slot(db_session, trainer_id, day_offset=-1)
    older_id = await _seed_booking(db_session, slot_id=older_slot, trainer_id=trainer_id, client_id=client_id, service_id=service_id, status="completed")
    newer_id = await _seed_booking(db_session, slot_id=newer_slot, trainer_id=trainer_id, client_id=client_id, service_id=service_id, status="completed")
    await db_session.commit()

    rows, _ = await list_booking_history_for_client(db_session, tg)
    assert [r["id"] for r in rows] == [newer_id, older_id]


@pytest.mark.asyncio
async def test_history_pagination_offset_and_has_more(db_session) -> None:
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tg = unique_test_telegram_id()
    client_id = await _seed_client(db_session, tg)

    ids_newest_first = []
    for i in range(5):
        # offset -1 (i=0) is closest to today = newest; offset -5 (i=4) is oldest.
        slot_id = await _seed_slot(db_session, trainer_id, day_offset=-(i + 1))
        bid = await _seed_booking(db_session, slot_id=slot_id, trainer_id=trainer_id, client_id=client_id, service_id=service_id, status="completed")
        ids_newest_first.append(bid)
    await db_session.commit()

    page1, has_more1 = await list_booking_history_for_client(db_session, tg, offset=0, limit=2)
    assert [r["id"] for r in page1] == ids_newest_first[0:2]
    assert has_more1 is True

    page2, has_more2 = await list_booking_history_for_client(db_session, tg, offset=2, limit=2)
    assert [r["id"] for r in page2] == ids_newest_first[2:4]
    assert has_more2 is True

    page3, has_more3 = await list_booking_history_for_client(db_session, tg, offset=4, limit=2)
    assert [r["id"] for r in page3] == ids_newest_first[4:5]
    assert has_more3 is False


@pytest.mark.asyncio
async def test_history_trainer_id_filter(db_session) -> None:
    trainer_a, service_a = await _seed_trainer_with_service(db_session)
    trainer_b, service_b = await _seed_trainer_with_service(db_session)
    tg = unique_test_telegram_id()
    client_id = await _seed_client(db_session, tg)

    slot_a = await _seed_slot(db_session, trainer_a, day_offset=-1)
    slot_b = await _seed_slot(db_session, trainer_b, day_offset=-1)
    id_a = await _seed_booking(db_session, slot_id=slot_a, trainer_id=trainer_a, client_id=client_id, service_id=service_a, status="completed")
    id_b = await _seed_booking(db_session, slot_id=slot_b, trainer_id=trainer_b, client_id=client_id, service_id=service_b, status="completed")
    await db_session.commit()

    rows, _ = await list_booking_history_for_client(db_session, tg, trainer_id=trainer_a)
    assert {r["id"] for r in rows} == {id_a}
    assert id_b not in {r["id"] for r in rows}


@pytest.mark.asyncio
async def test_history_survives_deactivated_trainer(db_session) -> None:
    """AC-009: a booking must stay visible in history after the trainer is deactivated (not deleted)."""
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tg = unique_test_telegram_id()
    client_id = await _seed_client(db_session, tg)

    slot_id = await _seed_slot(db_session, trainer_id, day_offset=-1)
    booking_id = await _seed_booking(db_session, slot_id=slot_id, trainer_id=trainer_id, client_id=client_id, service_id=service_id, status="completed")
    await db_session.execute(
        text("UPDATE trainers SET status = 'deactivated' WHERE id = :tid"), {"tid": trainer_id}
    )
    await db_session.commit()

    rows, _ = await list_booking_history_for_client(db_session, tg)
    assert len(rows) == 1
    assert rows[0]["id"] == booking_id
    assert rows[0]["trainer_name"]


@pytest.mark.asyncio
async def test_trainer_options_lists_distinct_trainers_excludes_sandbox(db_session) -> None:
    trainer_a, service_a = await _seed_trainer_with_service(db_session)
    trainer_b, service_b = await _seed_trainer_with_service(db_session)
    trainer_sandbox_only, service_c = await _seed_trainer_with_service(db_session)
    tg = unique_test_telegram_id()
    client_id = await _seed_client(db_session, tg)

    slot_a = await _seed_slot(db_session, trainer_a, day_offset=-1)
    slot_b = await _seed_slot(db_session, trainer_b, day_offset=2)
    slot_c = await _seed_slot(db_session, trainer_sandbox_only, day_offset=-1)
    await _seed_booking(db_session, slot_id=slot_a, trainer_id=trainer_a, client_id=client_id, service_id=service_a, status="completed")
    await _seed_booking(db_session, slot_id=slot_b, trainer_id=trainer_b, client_id=client_id, service_id=service_b, status="confirmed")
    await _seed_booking(db_session, slot_id=slot_c, trainer_id=trainer_sandbox_only, client_id=client_id, service_id=service_c, status="completed", is_sandbox=True)
    await db_session.commit()

    options = await list_client_booking_trainer_options(db_session, tg)
    trainer_ids = {o["trainer_id"] for o in options}
    assert trainer_ids == {trainer_a, trainer_b}
    assert all(o["trainer_name"] for o in options)


@pytest.mark.asyncio
async def test_trainer_options_single_trainer(db_session) -> None:
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tg = unique_test_telegram_id()
    client_id = await _seed_client(db_session, tg)

    slot_id = await _seed_slot(db_session, trainer_id, day_offset=-1)
    await _seed_booking(db_session, slot_id=slot_id, trainer_id=trainer_id, client_id=client_id, service_id=service_id, status="completed")
    await db_session.commit()

    options = await list_client_booking_trainer_options(db_session, tg)
    assert len(options) == 1
    assert options[0]["trainer_id"] == trainer_id
