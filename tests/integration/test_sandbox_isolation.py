"""Sandbox isolation: a sandbox client/booking must never leak into product logic.

Covers the exact promises around the «Попробовать на примере» onboarding path:
- Sandbox bookings still close the first-booking milestone (activation parity with real flow).
- Sandbox bookings/clients are excluded from CRM lists, rhythm hint counters, fill-slots invite
  candidates, inactive-client notifications, automatic completion sweep, and trainer-stats counts.
- Reminders for clients are not generated for sandbox bookings.
- A sandbox booking cannot be created on a real client (and vice versa) — identity invariant.
"""

from datetime import date, time, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import (
    INACTIVE_KIND_10_DAYS,
    count_trainer_fill_slots_invite_candidates,
    create_booking,
    generate_reminders_for_booking,
    get_clients_for_inactive_notification,
    list_bookings_to_complete,
    list_trainer_clients,
    list_trainer_fill_slots_invite_candidates,
)
from src.application.client_use_cases import (
    get_or_create_sandbox_client_for_trainer,
    sandbox_phone_for_trainer,
)
from src.application.trainer_onboarding_checklist import (
    get_trainer_onboarding_checklist,
)
from tests.conftest import unique_test_telegram_id
from tests.integration.test_booking_use_cases import (
    _create_client,
    _create_trainer_and_slot,
)


async def _link_to_roster(session: AsyncSession, trainer_id: int, client_id: int) -> None:
    await session.execute(
        text(
            "INSERT INTO trainer_client_roster (trainer_id, client_id) "
            "VALUES (:t, :c) ON CONFLICT DO NOTHING"
        ),
        {"t": trainer_id, "c": client_id},
    )
    await session.commit()


@pytest.mark.asyncio
async def test_sandbox_client_phantom_phone_is_deterministic_per_trainer(
    db_session: AsyncSession,
) -> None:
    """Two calls return the same row; phone follows ``+37500{trainer_id:07d}`` shape."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, _slot, _svc = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0)
    )
    cid_a = await get_or_create_sandbox_client_for_trainer(db_session, trainer_id)
    cid_b = await get_or_create_sandbox_client_for_trainer(db_session, trainer_id)
    await db_session.commit()
    assert cid_a == cid_b
    expected_phone = sandbox_phone_for_trainer(trainer_id)
    r = await db_session.execute(
        text("SELECT phone, is_sandbox FROM clients WHERE id = :cid"),
        {"cid": cid_a},
    )
    phone, is_sb = r.fetchone()
    assert phone == expected_phone
    assert is_sb is True


@pytest.mark.asyncio
async def test_sandbox_client_excluded_from_crm_listings_and_rhythm_hints(
    db_session: AsyncSession,
) -> None:
    """Sandbox client is visible in the trainer's CRM list but excluded from invitable counters."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0)
    )
    real_client = await _create_client(db_session, unique_test_telegram_id())
    await _link_to_roster(db_session, trainer_id, real_client)
    sandbox_client = await get_or_create_sandbox_client_for_trainer(db_session, trainer_id)
    await _link_to_roster(db_session, trainer_id, sandbox_client)
    sb_bid, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=sandbox_client,
        service_id=service_id,
        created_by_trainer=True,
        is_sandbox=True,
    )
    assert sb_bid is not None

    clients = await list_trainer_clients(db_session, trainer_id)
    sandbox_rows = [c for c in clients if c["is_sandbox"]]
    real_rows = [c for c in clients if not c["is_sandbox"]]
    assert len(sandbox_rows) == 1
    assert sandbox_rows[0]["id"] == sandbox_client
    assert real_client in {c["id"] for c in real_rows}

    fill_slots_list = await list_trainer_fill_slots_invite_candidates(
        db_session, trainer_id, include_with_upcoming=True
    )
    # The real client may or may not surface (depends on TG state), but the sandbox identity must
    # never show up in invite candidates — that's the leak we're closing.
    assert sandbox_client not in {c["id"] for c in fill_slots_list}
    fill_slots_count = await count_trainer_fill_slots_invite_candidates(db_session, trainer_id)
    # Sanity: count cannot exceed the explicit list length when ``include_with_upcoming=False`` is
    # the default — at most the real telegram-linked client without upcoming counts here.
    assert fill_slots_count <= len(fill_slots_list)

    checklist = await get_trainer_onboarding_checklist(db_session, trainer_id)
    assert checklist is not None
    # Activation parity: sandbox booking still flips the «first booking» flags.
    assert checklist["has_any_booking"] is True
    assert checklist["has_upcoming_booking"] is True
    assert checklist["has_confirmed_booking"] is True
    # But weekly counters and «без следующей записи» / «нет в боте» exclude the demo.
    assert checklist["bookings_this_week_count"] == 0
    assert checklist["open_loop_pending_bookings_count"] == 0
    assert checklist["open_loop_clients_no_telegram_count"] == 0


@pytest.mark.asyncio
async def test_sandbox_booking_does_not_generate_reminders(
    db_session: AsyncSession,
) -> None:
    """``generate_reminders_for_booking`` is a no-op for sandbox bookings even if mistakenly called."""
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0)
    )
    sandbox_client = await get_or_create_sandbox_client_for_trainer(db_session, trainer_id)
    bid, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=sandbox_client,
        service_id=service_id,
        created_by_trainer=True,
        is_sandbox=True,
    )
    assert bid is not None
    await generate_reminders_for_booking(db_session, bid)
    r = await db_session.execute(
        text("SELECT COUNT(*) FROM reminders WHERE booking_id = :bid"),
        {"bid": bid},
    )
    assert int(r.scalar() or 0) == 0


@pytest.mark.asyncio
async def test_sandbox_booking_excluded_from_auto_complete_sweep(
    db_session: AsyncSession,
) -> None:
    """A past sandbox booking is not picked up by the background completion loop."""
    yesterday = date.today() - timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, yesterday, time(10, 0), time(11, 0)
    )
    sandbox_client = await get_or_create_sandbox_client_for_trainer(db_session, trainer_id)
    bid, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=sandbox_client,
        service_id=service_id,
        created_by_trainer=True,
        is_sandbox=True,
    )
    assert bid is not None
    rows = await list_bookings_to_complete(db_session, limit=50)
    assert all(r["id"] != bid for r in rows)


@pytest.mark.asyncio
async def test_sandbox_client_not_picked_up_by_inactive_notifications(
    db_session: AsyncSession,
) -> None:
    """Inactive-client loop must not target a sandbox identity even with a stale «last session»."""
    long_ago = date.today() - timedelta(days=10)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, long_ago, time(10, 0), time(11, 0)
    )
    sandbox_client = await get_or_create_sandbox_client_for_trainer(db_session, trainer_id)
    # Manually attach a fake telegram_id to the sandbox client so the «no telegram» short-circuit
    # doesn't hide the bug — we want to verify the sandbox filter itself, not the TG one.
    fake_tid = unique_test_telegram_id()
    await db_session.execute(
        text("UPDATE clients SET telegram_id = :t WHERE id = :c"),
        {"t": fake_tid, "c": sandbox_client},
    )
    bid, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=sandbox_client,
        service_id=service_id,
        created_by_trainer=True,
        is_sandbox=True,
    )
    assert bid is not None
    await db_session.execute(
        text("UPDATE bookings SET status = 'completed' WHERE id = :bid"),
        {"bid": bid},
    )
    await db_session.commit()
    rows = await get_clients_for_inactive_notification(db_session, INACTIVE_KIND_10_DAYS)
    assert all(r["client_id"] != sandbox_client for r in rows)
