"""Trainer can change service/tariff on active individual bookings."""
from datetime import date, time, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id

from src.application.booking_use_cases import (
    booking_service_edit_policy,
    create_booking,
    fetch_reminder_session_cards_map,
    generate_reminders_for_booking,
    resolve_booking_service_edit_ui_flags,
    update_trainer_booking_arena,
    update_trainer_booking_service,
)


@pytest.mark.asyncio
async def test_booking_service_edit_policy_allows_completed(db_session: AsyncSession) -> None:
    ctx = {
        "status": "completed",
        "slot_capacity": 1,
        "has_pass_redemption": False,
        "has_cert_credit": False,
        "problem_reported": False,
        "client_no_show_recorded": False,
        "slot_date": date.today() - timedelta(days=3),
        "slot_end_time": time(11, 0),
    }
    pol = booking_service_edit_policy(ctx)
    assert pol["allowed"] is True


@pytest.mark.asyncio
async def test_booking_service_edit_policy_allows_past_confirmed(db_session: AsyncSession) -> None:
    ctx = {
        "status": "confirmed",
        "slot_capacity": 1,
        "has_pass_redemption": False,
        "has_cert_credit": False,
        "problem_reported": False,
        "client_no_show_recorded": False,
        "slot_date": date.today() - timedelta(days=1),
        "slot_end_time": time(9, 0),
    }
    pol = booking_service_edit_policy(ctx)
    assert pol["allowed"] is True


@pytest.mark.asyncio
async def test_resolve_service_edit_flags_single_service_no_tier_choice(
    db_session: AsyncSession,
) -> None:
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.commit()
    ctx = {
        "status": "confirmed",
        "service_id": service_id,
        "slot_capacity": 1,
        "has_pass_redemption": False,
        "has_cert_credit": False,
        "problem_reported": False,
        "client_no_show_recorded": False,
        "slot_date": date.today() + timedelta(days=2),
        "slot_end_time": None,
    }
    flags = await resolve_booking_service_edit_ui_flags(db_session, trainer_id, ctx)
    assert flags["allowed"] is False
    assert flags["can_edit_service"] is False
    assert flags["can_edit_tier"] is False
    assert flags["can_edit_arena"] is False


@pytest.mark.asyncio
async def test_resolve_service_edit_flags_allows_arena_when_multiple(
    db_session: AsyncSession,
) -> None:
    service_id = await require_seed_service_id(db_session)
    arena_a, city_id, _ = await require_seed_arena_city_name(db_session)
    r_a2 = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, sort_order, is_active)
            VALUES (:cid, 'Test arena B', 99, true)
            RETURNING id
            """
        ),
        {"cid": city_id},
    )
    (arena_b,) = r_a2.fetchone()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :a1), (:tid, :a2)"),
        {"tid": trainer_id, "a1": arena_a, "a2": arena_b},
    )
    await db_session.commit()
    ctx = {
        "status": "confirmed",
        "service_id": service_id,
        "slot_capacity": 1,
        "has_pass_redemption": False,
        "has_cert_credit": False,
        "problem_reported": False,
        "client_no_show_recorded": False,
        "slot_date": date.today() + timedelta(days=2),
        "slot_end_time": None,
    }
    flags = await resolve_booking_service_edit_ui_flags(db_session, trainer_id, ctx)
    assert flags["allowed"] is True
    assert flags["can_edit_service"] is False
    assert flags["can_edit_tier"] is False
    assert flags["can_edit_arena"] is True


@pytest.mark.asyncio
async def test_update_trainer_booking_arena_changes_venue(db_session: AsyncSession) -> None:
    service_id = await require_seed_service_id(db_session)
    arena_a, city_id, _ = await require_seed_arena_city_name(db_session)
    r_a2 = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, sort_order, is_active)
            VALUES (:cid, 'Patch arena alt', 98, true)
            RETURNING id, trim(both FROM name)
            """
        ),
        {"cid": city_id},
    )
    arena_b, arena_b_name = r_a2.fetchone()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'T', 'T', 30)"
        ),
        {"tid": trainer_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :a1), (:tid, :a2)"),
        {"tid": trainer_id, "a1": arena_a, "a2": int(arena_b)},
    )
    tomorrow = date.today() + timedelta(days=2)
    r_slot = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, '10:00', '11:00', 'available')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": tomorrow},
    )
    (slot_id,) = r_slot.fetchone()
    ctg = unique_test_telegram_id()
    phone, phone_normalized = belarus_test_phone(ctg)
    r_cl = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'C', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": ctg, "phone": phone, "pn": phone_normalized},
    )
    (client_id,) = r_cl.fetchone()
    await db_session.commit()

    booking_id, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        arena_id=arena_a,
        created_by_trainer=True,
    )
    assert booking_id is not None
    await db_session.commit()

    detail, err = await update_trainer_booking_arena(
        db_session,
        booking_id,
        trainer_id,
        int(arena_b),
    )
    assert err is None
    assert detail is not None
    assert detail["arena_id"] == int(arena_b)
    assert detail["arenas_str"] == str(arena_b_name).strip()

    r_check = await db_session.execute(
        text("SELECT arena_id FROM bookings WHERE id = :bid"),
        {"bid": booking_id},
    )
    assert int(r_check.scalar()) == int(arena_b)


@pytest.mark.asyncio
async def test_resolve_service_edit_flags_allows_tier_when_multiple(
    db_session: AsyncSession,
) -> None:
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_service_price_variants (trainer_id, service_id, label, price_cents, sort_order, tier_kind)
            VALUES (:tid, :sid, 'Взрослый', 5000, 0, 'adult'), (:tid, :sid, 'Детский', 3000, 1, 'child')
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.commit()
    ctx = {
        "status": "confirmed",
        "service_id": service_id,
        "slot_capacity": 1,
        "has_pass_redemption": False,
        "has_cert_credit": False,
        "problem_reported": False,
        "client_no_show_recorded": False,
        "slot_date": date.today() + timedelta(days=2),
        "slot_end_time": None,
    }
    flags = await resolve_booking_service_edit_ui_flags(db_session, trainer_id, ctx)
    assert flags["allowed"] is True
    assert flags["can_edit_service"] is False
    assert flags["can_edit_tier"] is True


async def test_booking_service_edit_policy_blocks_group_slot(db_session: AsyncSession) -> None:
    ctx = {"status": "confirmed", "slot_capacity": 4, "has_pass_redemption": False, "has_cert_credit": False}
    pol = booking_service_edit_policy(ctx)
    assert pol["allowed"] is False
    assert pol["service_locked"] is True


@pytest.mark.asyncio
async def test_update_trainer_booking_service_changes_tier(db_session: AsyncSession) -> None:
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'T', 'T', 30)"
        ),
        {"tid": trainer_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    r_var = await db_session.execute(
        text(
            """
            INSERT INTO trainer_service_price_variants (trainer_id, service_id, label, price_cents, sort_order, tier_kind)
            VALUES (:tid, :sid, 'Взрослый', 5000, 0, 'adult'),
                   (:tid, :sid, 'Детский', 3000, 1, 'child')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    variant_rows = r_var.fetchall()
    adult_id = int(variant_rows[0][0])
    child_id = int(variant_rows[1][0])
    tomorrow = date.today() + timedelta(days=2)
    r_slot = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, '10:00', '11:00', 'available')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": tomorrow},
    )
    (slot_id,) = r_slot.fetchone()
    ctg = unique_test_telegram_id()
    phone, phone_normalized = belarus_test_phone(ctg)
    r_cl = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'C', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": ctg, "phone": phone, "pn": phone_normalized},
    )
    (client_id,) = r_cl.fetchone()
    await db_session.commit()

    booking_id, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        service_price_variant_id=adult_id,
        created_by_trainer=True,
    )
    assert booking_id is not None
    await db_session.commit()

    detail, err = await update_trainer_booking_service(
        db_session,
        booking_id,
        trainer_id,
        service_id,
        child_id,
    )
    assert err is None
    assert detail is not None
    assert detail["service_price_variant_id"] == child_id
    assert detail["booking_price_cents"] == 3000

    r_check = await db_session.execute(
        text(
            "SELECT service_price_variant_id, booking_price_cents FROM bookings WHERE id = :bid"
        ),
        {"bid": booking_id},
    )
    row = r_check.fetchone()
    assert int(row[0]) == child_id
    assert int(row[1]) == 3000


@pytest.mark.asyncio
async def test_reminder_payload_uses_live_booking_after_service_update(
    db_session: AsyncSession,
) -> None:
    """No client push on edit; pending reminders read current service/price at send time."""
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'T', 'T', 30)"
        ),
        {"tid": trainer_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    r_var = await db_session.execute(
        text(
            """
            INSERT INTO trainer_service_price_variants (trainer_id, service_id, label, price_cents, sort_order, tier_kind)
            VALUES (:tid, :sid, 'Взрослый', 5000, 0, 'adult'),
                   (:tid, :sid, 'Детский', 3000, 1, 'child')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    rows_var = r_var.fetchall()
    adult_id = int(rows_var[0][0])
    child_id = int(rows_var[1][0])
    tomorrow = date.today() + timedelta(days=2)
    r_slot = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, '10:00', '11:00', 'available')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": tomorrow},
    )
    (slot_id,) = r_slot.fetchone()
    ctg = unique_test_telegram_id()
    phone, phone_normalized = belarus_test_phone(ctg)
    r_cl = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'C', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": ctg, "phone": phone, "pn": phone_normalized},
    )
    (client_id,) = r_cl.fetchone()
    await db_session.commit()

    booking_id, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        service_price_variant_id=adult_id,
        created_by_trainer=True,
    )
    assert booking_id is not None
    await db_session.commit()

    await generate_reminders_for_booking(db_session, booking_id)
    await db_session.commit()

    _, err = await update_trainer_booking_service(
        db_session,
        booking_id,
        trainer_id,
        service_id,
        child_id,
    )
    assert err is None

    snap = await fetch_reminder_session_cards_map(db_session, [booking_id])
    card = snap[booking_id]
    assert card["booking_price_cents"] == 3000


@pytest.mark.asyncio
async def test_update_trainer_booking_service_on_completed_past_slot(
    db_session: AsyncSession,
) -> None:
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'T', 'T', 30)"
        ),
        {"tid": trainer_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    r_var = await db_session.execute(
        text(
            """
            INSERT INTO trainer_service_price_variants (trainer_id, service_id, label, price_cents, sort_order, tier_kind)
            VALUES (:tid, :sid, 'Взрослый', 5000, 0, 'adult'),
                   (:tid, :sid, 'Детский', 3000, 1, 'child')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    variant_rows = r_var.fetchall()
    adult_id = int(variant_rows[0][0])
    child_id = int(variant_rows[1][0])
    past_day = date.today() - timedelta(days=4)
    r_slot = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, '10:00', '11:00', 'booked')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": past_day},
    )
    (slot_id,) = r_slot.fetchone()
    ctg = unique_test_telegram_id()
    phone, phone_normalized = belarus_test_phone(ctg)
    r_cl = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'C', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": ctg, "phone": phone, "pn": phone_normalized},
    )
    (client_id,) = r_cl.fetchone()
    r_b = await db_session.execute(
        text(
            """
            INSERT INTO bookings (
                slot_id, trainer_id, client_id, service_id, status,
                service_price_variant_id, booking_price_cents, price_tier_kind
            )
            VALUES (:sid, :tid, :cid, :svc, 'completed', :vid, 5000, 'adult')
            RETURNING id
            """
        ),
        {
            "sid": slot_id,
            "tid": trainer_id,
            "cid": client_id,
            "svc": service_id,
            "vid": adult_id,
        },
    )
    (booking_id,) = r_b.fetchone()
    await db_session.commit()

    detail, err = await update_trainer_booking_service(
        db_session,
        int(booking_id),
        trainer_id,
        service_id,
        child_id,
    )
    assert err is None
    assert detail is not None
    assert detail["booking_price_cents"] == 3000
    assert detail["service_price_variant_id"] == child_id

