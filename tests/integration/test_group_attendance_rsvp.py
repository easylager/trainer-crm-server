"""
Group cohort RSVP: prompts, HMAC, booking from «Буду», idempotency, capacity.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id

from src.application.group_attendance_use_cases import (
    attendance_rsvp_sign,
    attendance_rsvp_verify,
    list_pending_attendance_prompts,
    respond_attendance_rsvp,
    rsvp_hmac_secret,
    sync_group_attendance_prompts,
)
from src.application.training_group_use_cases import MEMBER_ACTIVE


async def _trainer_service(session: AsyncSession) -> tuple[int, int]:
    service_id = await require_seed_service_id(session)
    arena_id, _, _ = await require_seed_arena_city_name(session)
    r = await session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'T', 'T', 30)"
        ),
        {"tid": trainer_id},
    )
    await session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    await session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    await session.commit()
    return int(trainer_id), int(service_id)


@pytest.mark.asyncio
async def test_rsvp_hmac_roundtrip(db_session: AsyncSession) -> None:
    secret = rsvp_hmac_secret("test-token")
    s = attendance_rsvp_sign(42, "y", secret)
    assert attendance_rsvp_verify(42, "y", s, secret)
    assert not attendance_rsvp_verify(42, "y", s + "x", secret)


@pytest.mark.asyncio
async def test_rsvp_confirm_creates_booking_and_counts(db_session: AsyncSession) -> None:
    trainer_id, service_id = await _trainer_service(db_session)
    tid_a = unique_test_telegram_id()
    tid_b = unique_test_telegram_id()
    r = await db_session.execute(
        text("INSERT INTO clients (telegram_id, first_name) VALUES (:t, 'A') RETURNING id"),
        {"t": tid_a},
    )
    (cid_a,) = r.fetchone()
    r = await db_session.execute(
        text("INSERT INTO clients (telegram_id, first_name) VALUES (:t, 'B') RETURNING id"),
        {"t": tid_b},
    )
    (cid_b,) = r.fetchone()
    r = await db_session.execute(
        text(
            """
            INSERT INTO training_groups (trainer_id, name, service_id, arena_id, max_members, status, catalog_visible)
            SELECT :tid, 'G1', :sid, (SELECT id FROM arenas ORDER BY id LIMIT 1), 2, 'active', false
            RETURNING id
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    (gid,) = r.fetchone()
    gid = int(gid)
    await db_session.execute(
        text(
            """
            INSERT INTO training_group_members (training_group_id, client_id, status)
            VALUES (:gid, :a, :st), (:gid, :b, :st)
            """
        ),
        {"gid": gid, "a": cid_a, "b": cid_b, "st": MEMBER_ACTIVE},
    )
    slot_date = date.today() + timedelta(days=3)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id, training_group_id)
            VALUES (
              :tid, :sd, '10:00', '11:00', 'available', 2, :svc, :gid
            )
            RETURNING id
            """
        ),
        {"tid": trainer_id, "sd": slot_date, "svc": service_id, "gid": gid},
    )
    (slot_id,) = r.fetchone()
    slot_id = int(slot_id)
    await db_session.execute(
        text(
            """
            INSERT INTO group_attendance_prompts (slot_id, client_id, training_group_id, send_at, status)
            VALUES
              (:sid, :ca, :gid, NOW() - interval '1 minute', 'sent'),
              (:sid, :cb, :gid, NOW() - interval '1 minute', 'sent')
            """
        ),
        {"sid": slot_id, "ca": cid_a, "cb": cid_b, "gid": gid},
    )
    await db_session.commit()

    rlist = await list_pending_attendance_prompts(db_session, limit=10)
    assert len(rlist) == 0

    r = await db_session.execute(
        text("SELECT id FROM group_attendance_prompts WHERE client_id = :ca"),
        {"ca": cid_a},
    )
    pid_a = int(r.scalar())
    r = await db_session.execute(
        text("SELECT id FROM group_attendance_prompts WHERE client_id = :cb"),
        {"cb": cid_b},
    )
    pid_b = int(r.scalar())

    ok, msg = await respond_attendance_rsvp(prompt_id=pid_a, telegram_user_id=tid_a, accept=True)
    assert ok, msg
    ok2, _ = await respond_attendance_rsvp(prompt_id=pid_a, telegram_user_id=tid_a, accept=True)
    assert ok2

    ok, msg = await respond_attendance_rsvp(prompt_id=pid_b, telegram_user_id=tid_b, accept=True)
    assert ok

    r = await db_session.execute(
        text(
            """
            SELECT COUNT(*)::int FROM bookings
            WHERE slot_id = :sid AND status IN ('pending', 'confirmed')
            """
        ),
        {"sid": slot_id},
    )
    assert int(r.scalar()) == 2

    r = await db_session.execute(
        text("SELECT COUNT(*)::int FROM bookings WHERE slot_id = :sid AND client_id = :cid"),
        {"sid": slot_id, "cid": cid_b},
    )
    assert int(r.scalar()) == 1


@pytest.mark.asyncio
async def test_sync_creates_prompt_rows(db_session: AsyncSession) -> None:
    trainer_id, service_id = await _trainer_service(db_session)
    tid = unique_test_telegram_id()
    r = await db_session.execute(
        text("INSERT INTO clients (telegram_id, first_name) VALUES (:t, 'C') RETURNING id"),
        {"t": tid},
    )
    (cid,) = r.fetchone()
    r = await db_session.execute(
        text(
            """
            INSERT INTO training_groups (trainer_id, name, service_id, arena_id, max_members, status, catalog_visible)
            SELECT :tid, 'G2', :sid, (SELECT id FROM arenas ORDER BY id LIMIT 1), 4, 'active', false
            RETURNING id
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    (gid,) = r.fetchone()
    gid = int(gid)
    await db_session.execute(
        text(
            "INSERT INTO training_group_members (training_group_id, client_id, status) VALUES (:gid, :cid, :st)"
        ),
        {"gid": gid, "cid": cid, "st": MEMBER_ACTIVE},
    )
    slot_date = date.today() + timedelta(days=5)
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id, training_group_id)
            VALUES (:tid, :sd, '12:00', '13:00', 'available', 4, :svc, :gid)
            """
        ),
        {"tid": trainer_id, "sd": slot_date, "svc": service_id, "gid": gid},
    )
    await db_session.commit()

    n = await sync_group_attendance_prompts(db_session, 24)
    assert n >= 1
    r = await db_session.execute(text("SELECT COUNT(*)::int FROM group_attendance_prompts"))
    assert int(r.scalar()) >= 1
