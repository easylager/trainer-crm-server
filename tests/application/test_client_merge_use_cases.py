"""
merge_clients: absorb a duplicate `clients` row (trainer typo'd a phone; the client later
self-registered with the correct number under a fresh row) into the account that actually
has a live Telegram identity — bookings, passes, edges etc. must all land on the survivor,
duplicates must dedupe instead of violating unique constraints, and reminders must be
regenerated for any booking that moved (the original row often had no telegram_id yet, so
the reminder pipeline had nothing to send to).
"""
from __future__ import annotations

from datetime import time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.client_use_cases import merge_clients


async def _insert_client(
    db_session: AsyncSession,
    *,
    telegram_id: int | None = None,
    first_name: str | None = "Client",
    last_name: str | None = None,
    phone: str | None = None,
    phone_normalized: str | None = None,
) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (first_name, last_name, telegram_id, phone, phone_normalized, is_sandbox)
            VALUES (:fn, :ln, :tid, :ph, :phn, false)
            RETURNING id
            """
        ),
        {"fn": first_name, "ln": last_name, "tid": telegram_id, "ph": phone, "phn": phone_normalized},
    )
    return int(r.scalar_one())


async def _insert_trainer(db_session: AsyncSession) -> int:
    r = await db_session.execute(
        text("INSERT INTO trainers (status, schedule_grid_step_minutes) VALUES ('active', 15) RETURNING id")
    )
    return int(r.scalar_one())


async def _insert_slot(db_session: AsyncSession, trainer_id: int, *, slot_date, start_hour: int) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :et, 'booked')
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "d": slot_date,
            "st": time(start_hour, 0),
            "et": time(start_hour + 1, 0),
        },
    )
    return int(r.scalar_one())


async def _insert_service(db_session: AsyncSession) -> int:
    r = await db_session.execute(text("INSERT INTO services (name) VALUES ('Тест') RETURNING id"))
    return int(r.scalar_one())


async def _insert_booking(
    db_session: AsyncSession, *, client_id: int, trainer_id: int, slot_id: int, service_id: int, status: str = "confirmed"
) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (client_id, trainer_id, slot_id, service_id, status)
            VALUES (:cid, :tid, :sid, :svc, :st)
            RETURNING id
            """
        ),
        {"cid": client_id, "tid": trainer_id, "sid": slot_id, "svc": service_id, "st": status},
    )
    return int(r.scalar_one())


async def _insert_client_session(db_session: AsyncSession, telegram_id: int) -> None:
    await db_session.execute(
        text("INSERT INTO client_sessions (telegram_id, state) VALUES (:tid, 'idle') ON CONFLICT DO NOTHING"),
        {"tid": telegram_id},
    )


async def _insert_edge(db_session: AsyncSession, *, client_id: int, telegram_id: int, trainer_id: int) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO client_trainer_edges (client_id, telegram_id, trainer_id)
            VALUES (:cid, :tid, :trid)
            RETURNING id
            """
        ),
        {"cid": client_id, "tid": telegram_id, "trid": trainer_id},
    )
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_merge_clients_rejects_same_id(db_session: AsyncSession) -> None:
    cid = await _insert_client(db_session, telegram_id=910001)
    await db_session.commit()
    with pytest.raises(ValueError):
        await merge_clients(db_session, cid, cid)


@pytest.mark.asyncio
async def test_merge_clients_end_to_end_incident_shape(db_session: AsyncSession) -> None:
    """Mirrors the real incident: trainer-added stub (wrong phone, no telegram, has history)
    merged into the client's real self-registered account (correct phone, has telegram)."""
    from datetime import date, timedelta

    trainer_id = await _insert_trainer(db_session)
    service_id = await _insert_service(db_session)
    slot_day = date.today() + timedelta(days=5)
    slot_id = await _insert_slot(db_session, trainer_id, slot_date=slot_day, start_hour=17)

    from_cid = await _insert_client(
        db_session, telegram_id=None, first_name="Татьяна", last_name="Силантьева",
        phone="+375296818574", phone_normalized="375296818574",
    )
    to_cid = await _insert_client(
        db_session, telegram_id=910100, first_name="Татьяна", last_name=None,
        phone="+375296817574", phone_normalized="375296817574",
    )
    booking_id = await _insert_booking(
        db_session, client_id=from_cid, trainer_id=trainer_id, slot_id=slot_id, service_id=service_id
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_client_roster (trainer_id, client_id) VALUES (:t, :c)"
        ),
        {"t": trainer_id, "c": from_cid},
    )
    r = await db_session.execute(
        text(
            "INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents) "
            "VALUES (:t, 'Тест', 8, 10000) RETURNING id"
        ),
        {"t": trainer_id},
    )
    pass_product_id = int(r.scalar_one())
    await db_session.execute(
        text(
            "INSERT INTO pass_instances (client_id, pass_product_id, sessions_remaining, sessions_total, status, price_cents) "
            "VALUES (:c, :pp, 7, 8, 'active', 10000)"
        ),
        {"c": from_cid, "pp": pass_product_id},
    )
    await db_session.commit()

    # Reminder pipeline never had a chat to target when the booking was created (no telegram_id).
    r = await db_session.execute(text("SELECT COUNT(*) FROM reminders WHERE booking_id = :b"), {"b": booking_id})
    assert r.scalar_one() == 0

    snapshot = await merge_clients(db_session, from_cid, to_cid)

    # Old row gone, survivor absorbed everything.
    r = await db_session.execute(text("SELECT COUNT(*) FROM clients WHERE id = :c"), {"c": from_cid})
    assert r.scalar_one() == 0

    r = await db_session.execute(text("SELECT client_id, last_name FROM bookings b JOIN clients c ON c.id = b.client_id WHERE b.id = :b"), {"b": booking_id})
    row = r.fetchone()
    assert row[0] == to_cid

    r = await db_session.execute(text("SELECT last_name FROM clients WHERE id = :c"), {"c": to_cid})
    assert r.scalar_one() == "Силантьева"  # backfilled from the stub, survivor's own was empty

    r = await db_session.execute(
        text("SELECT client_id, sessions_remaining FROM pass_instances WHERE client_id = :c"), {"c": to_cid}
    )
    assert r.fetchone()[1] == 7

    r = await db_session.execute(text("SELECT COUNT(*) FROM trainer_client_roster WHERE client_id = :c"), {"c": to_cid})
    assert r.scalar_one() == 1

    # Reminders regenerated against the survivor's real telegram_id — this is the actual fix.
    r = await db_session.execute(
        text("SELECT client_telegram_id, status FROM reminders WHERE booking_id = :b"), {"b": booking_id}
    )
    reminder_rows = r.fetchall()
    assert reminder_rows, "expected reminders to be (re)generated after merge"
    assert all(row[0] == 910100 for row in reminder_rows)
    assert all(row[1] == "pending" for row in reminder_rows)

    # Audit trail.
    r = await db_session.execute(
        text("SELECT from_client_id, to_client_id, snapshot FROM client_merges WHERE from_client_id = :f"),
        {"f": from_cid},
    )
    audit = r.fetchone()
    assert audit[0] == from_cid
    assert audit[1] == to_cid
    assert audit[2]["moved_counts"]["bookings.client_id"] == 1
    assert audit[2]["from_client"]["phone_normalized"] == "375296818574"
    assert snapshot["to_client"]["telegram_id"] == 910100


@pytest.mark.asyncio
async def test_merge_clients_dedupes_client_trainer_edges_and_repoints_telegram_id(
    db_session: AsyncSession,
) -> None:
    trainer_a = await _insert_trainer(db_session)
    trainer_b = await _insert_trainer(db_session)
    from_tid, to_tid = 910201, 910202
    await _insert_client_session(db_session, from_tid)
    await _insert_client_session(db_session, to_tid)

    from_cid = await _insert_client(db_session, telegram_id=from_tid)
    to_cid = await _insert_client(db_session, telegram_id=to_tid)

    # Conflict: both duplicates already have an edge with trainer_a — dedupe must keep the
    # survivor's row (and not try to insert a second (client_id, trainer_id) pair).
    await _insert_edge(db_session, client_id=from_cid, telegram_id=from_tid, trainer_id=trainer_a)
    await _insert_edge(db_session, client_id=to_cid, telegram_id=to_tid, trainer_id=trainer_a)
    # No conflict: only the stub has an edge with trainer_b — must move over, with its
    # telegram_id corrected to the survivor's own (not the stub's now-defunct account).
    await _insert_edge(db_session, client_id=from_cid, telegram_id=from_tid, trainer_id=trainer_b)
    await db_session.commit()

    await merge_clients(db_session, from_cid, to_cid)

    r = await db_session.execute(
        text("SELECT trainer_id, telegram_id FROM client_trainer_edges WHERE client_id = :c ORDER BY trainer_id"),
        {"c": to_cid},
    )
    rows = r.fetchall()
    assert [row[0] for row in rows] == sorted([trainer_a, trainer_b])
    assert all(row[1] == to_tid for row in rows), "edges must address the survivor's own telegram_id"

    r = await db_session.execute(text("SELECT COUNT(*) FROM client_trainer_edges WHERE client_id = :c"), {"c": from_cid})
    assert r.scalar_one() == 0


@pytest.mark.asyncio
async def test_merge_clients_dedupes_client_profile_links(db_session: AsyncSession) -> None:
    account_tid = 910301
    other_account_tid = 910302

    from_cid = await _insert_client(db_session, telegram_id=None)
    to_cid = await _insert_client(db_session, telegram_id=None)

    # Same guardian account already linked to both duplicate profiles — conflict on
    # (account_telegram_id, profile_client_id) once profile_client_id is repointed.
    await db_session.execute(
        text("INSERT INTO client_profile_links (account_telegram_id, profile_client_id) VALUES (:a, :c)"),
        {"a": account_tid, "c": from_cid},
    )
    await db_session.execute(
        text("INSERT INTO client_profile_links (account_telegram_id, profile_client_id) VALUES (:a, :c)"),
        {"a": account_tid, "c": to_cid},
    )
    # A different guardian account only linked to the stub — must move over untouched.
    await db_session.execute(
        text("INSERT INTO client_profile_links (account_telegram_id, profile_client_id) VALUES (:a, :c)"),
        {"a": other_account_tid, "c": from_cid},
    )
    await db_session.commit()

    await merge_clients(db_session, from_cid, to_cid)

    r = await db_session.execute(
        text("SELECT account_telegram_id FROM client_profile_links WHERE profile_client_id = :c ORDER BY account_telegram_id"),
        {"c": to_cid},
    )
    assert [row[0] for row in r.fetchall()] == sorted([account_tid, other_account_tid])


@pytest.mark.asyncio
async def test_merge_clients_dedupes_session_milestone_notifications(db_session: AsyncSession) -> None:
    from_cid = await _insert_client(db_session, telegram_id=None)
    to_cid = await _insert_client(db_session, telegram_id=910401)

    # Both already got the "5 sessions" push — must not duplicate (unique client_id+target).
    await db_session.execute(
        text(
            "INSERT INTO client_session_milestone_notifications (client_id, milestone_target, completed_total_at_send) "
            "VALUES (:c, 5, 5)"
        ),
        {"c": from_cid},
    )
    await db_session.execute(
        text(
            "INSERT INTO client_session_milestone_notifications (client_id, milestone_target, completed_total_at_send) "
            "VALUES (:c, 5, 5)"
        ),
        {"c": to_cid},
    )
    # Only the stub reached "10 sessions" — must carry over.
    await db_session.execute(
        text(
            "INSERT INTO client_session_milestone_notifications (client_id, milestone_target, completed_total_at_send) "
            "VALUES (:c, 10, 10)"
        ),
        {"c": from_cid},
    )
    await db_session.commit()

    await merge_clients(db_session, from_cid, to_cid)

    r = await db_session.execute(
        text("SELECT milestone_target FROM client_session_milestone_notifications WHERE client_id = :c ORDER BY milestone_target"),
        {"c": to_cid},
    )
    assert [row[0] for row in r.fetchall()] == [5, 10]


@pytest.mark.asyncio
async def test_merge_clients_moves_family_access_members(db_session: AsyncSession) -> None:
    from_cid = await _insert_client(db_session, telegram_id=None)
    to_cid = await _insert_client(db_session, telegram_id=910501)
    member_tid = 910502

    await db_session.execute(
        text(
            "INSERT INTO client_family_access_members (primary_client_id, member_telegram_id) VALUES (:p, :m)"
        ),
        {"p": from_cid, "m": member_tid},
    )
    await db_session.commit()

    await merge_clients(db_session, from_cid, to_cid)

    r = await db_session.execute(
        text("SELECT primary_client_id FROM client_family_access_members WHERE member_telegram_id = :m"),
        {"m": member_tid},
    )
    assert r.scalar_one() == to_cid
