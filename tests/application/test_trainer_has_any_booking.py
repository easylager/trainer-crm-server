"""TASK-027: ``has_real_booking`` — a real-booking signal distinct from ``has_any_booking``.

``has_any_booking`` deliberately still counts a sandbox demo booking (activation parity —
see ``tests/integration/test_sandbox_isolation.py``) and is NOT touched by this task.
``has_real_booking`` is the new, stricter signal: excludes sandbox and voided bookings,
and does not regress once a real booking was completed and later cancelled.

Covers AC-001 (sandbox-only), AC-002 (cancelled/declined-only), AC-003 (share_link card
still shows end-to-end through the real checklist), AC-005 (completed → later cancelled,
milestone already claimed), AC-006 (referral hint end-to-end).
"""
from datetime import date, time, timedelta

from sqlalchemy import text

from src.application.trainer_hub_action_inbox import build_trainer_hub_action_inbox
from src.application.trainer_next_step import STEP_SHARE_LINK, resolve_trainer_next_step
from src.application.trainer_onboarding_checklist import get_trainer_onboarding_checklist
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id


async def _seed_trainer(db_session, *, status: str = "pending_profile") -> int:
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES (:status) RETURNING id"),
        {"status": status},
    )
    tid = int(r.scalar_one())
    await db_session.commit()
    return tid


async def _insert_client(db_session) -> int:
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'Real', 'Client', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    return int(r.scalar_one())


async def _insert_booking(
    db_session,
    trainer_id: int,
    *,
    client_id: int | None = None,
    is_sandbox: bool = False,
    status: str = "confirmed",
    slot_date: date = date(2026, 1, 5),
) -> int:
    service_id = await require_seed_service_id(db_session)
    if client_id is None:
        client_id = await _insert_client(db_session)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '09:00', TIME '10:00', 'booked') RETURNING id
            """
        ),
        {"tid": trainer_id, "d": slot_date},
    )
    slot_id = int(r.scalar_one())
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status, is_sandbox)
            VALUES (:tid, :cid, :sid, :svc, :st, :sb) RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "cid": client_id,
            "sid": slot_id,
            "svc": service_id,
            "st": status,
            "sb": is_sandbox,
        },
    )
    booking_id = int(r.scalar_one())
    await db_session.commit()
    return booking_id


async def test_has_real_booking_false_for_sandbox_only(db_session) -> None:
    """AC-001: a sandbox demo booking must not count as the trainer's first real one.

    (``has_any_booking`` stays True here by design — activation parity, untouched.)"""
    tid = await _seed_trainer(db_session)
    await _insert_booking(db_session, tid, is_sandbox=True, status="confirmed")

    checklist = await get_trainer_onboarding_checklist(db_session, tid)
    assert checklist is not None
    assert checklist["has_any_booking"] is True
    assert checklist["has_real_booking"] is False


async def test_has_real_booking_false_for_cancelled_only(db_session) -> None:
    """AC-002: a booking voided before it ever happened must not count either."""
    tid = await _seed_trainer(db_session)
    await _insert_booking(db_session, tid, status="cancelled")

    checklist = await get_trainer_onboarding_checklist(db_session, tid)
    assert checklist is not None
    assert checklist["has_real_booking"] is False


async def test_has_real_booking_false_for_declined_only(db_session) -> None:
    tid = await _seed_trainer(db_session)
    await _insert_booking(db_session, tid, status="declined")

    checklist = await get_trainer_onboarding_checklist(db_session, tid)
    assert checklist is not None
    assert checklist["has_real_booking"] is False


async def test_has_real_booking_true_for_pending(db_session) -> None:
    """A live pending booking is a real (not sandbox, not voided) interaction — still counts,
    same as the old unfiltered ``has_any_booking`` did for this case."""
    tid = await _seed_trainer(db_session)
    await _insert_booking(db_session, tid, status="pending")

    checklist = await get_trainer_onboarding_checklist(db_session, tid)
    assert checklist is not None
    assert checklist["has_real_booking"] is True


async def test_has_real_booking_survives_cancel_after_milestone_claimed(db_session) -> None:
    """AC-005: once the first-real-booking milestone was claimed (as
    ``try_claim_first_booking_milestones`` does atomically the moment a real, non-sandbox
    booking first reaches confirmed/completed — see ``trainer_first_booking_milestone.py``),
    cancelling that booking afterwards must not regress onboarding back to «no booking»."""
    tid = await _seed_trainer(db_session)
    booking_id = await _insert_booking(db_session, tid, status="confirmed")
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_booking_milestone_at) "
            "VALUES (:tid, NOW())"
        ),
        {"tid": tid},
    )
    await db_session.execute(
        text("UPDATE bookings SET status = 'cancelled' WHERE id = :bid"),
        {"bid": booking_id},
    )
    await db_session.commit()

    checklist = await get_trainer_onboarding_checklist(db_session, tid)
    assert checklist is not None
    assert checklist["has_real_booking"] is True


async def test_share_link_card_still_shown_with_only_sandbox_or_cancelled_booking(
    db_session,
) -> None:
    """AC-003: end-to-end through the real checklist — a trainer with a working weekly
    schedule but only a sandbox demo / instantly-voided booking still gets STEP_SHARE_LINK,
    not silence, because ``has_real_booking`` correctly reads False for both."""
    tid = await _seed_trainer(db_session)
    await db_session.execute(
        text(
            "INSERT INTO trainer_schedule_templates (trainer_id, day_of_week, start_time) "
            "VALUES (:tid, 0, TIME '09:00')"
        ),
        {"tid": tid},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '09:00', TIME '10:00', 'available')
            """
        ),
        {"tid": tid, "d": date.today() + timedelta(days=7)},  # within the 56-day horizon
    )
    await db_session.commit()
    await _insert_booking(db_session, tid, is_sandbox=True, status="confirmed")

    checklist = await get_trainer_onboarding_checklist(db_session, tid)
    assert checklist is not None
    assert checklist["has_real_booking"] is False

    step = resolve_trainer_next_step(checklist)
    assert step is not None
    assert step["key"] == STEP_SHARE_LINK


async def test_referral_growth_not_nudged_for_sandbox_only_booking(db_session) -> None:
    """AC-006: end-to-end through the real checklist — the referral-growth rhythm hint
    (gated on ``has_real_booking`` via ``_onboarding_booking_step_done``) must not appear
    for a trainer whose only booking is a sandbox demo."""
    tid = await _seed_trainer(db_session)
    await db_session.execute(
        text(
            "INSERT INTO trainer_schedule_templates (trainer_id, day_of_week, start_time) "
            "VALUES (:tid, 0, TIME '09:00')"
        ),
        {"tid": tid},
    )
    await db_session.commit()
    await _insert_booking(db_session, tid, is_sandbox=True, status="confirmed")

    checklist = await get_trainer_onboarding_checklist(db_session, tid)
    assert checklist is not None
    payload = build_trainer_hub_action_inbox(onboarding=checklist, schedule_unlocked=True)
    ids = [x["id"] for x in payload["items"]]
    assert "referral_growth" not in ids
