"""
Integration tests for the onboarding-reactivation scheduler (TASK-011).

Covers:
- segment membership: telegram-linked pending_profile trainers, and active trainers with zero
  bookings ever, are candidates; trainers without telegram_id or outside these shapes are not,
- stage resolution end-to-end through the real checklist/readiness queries (empty form, no booking),
- cancel-on-progress: a trainer who gets their first booking drops out of the segment,
- step scheduling (D+1/D+3/D+7) anchored on trainers.created_at,
- idempotency: mark_onboarding_nudge_sent never inserts the same (trainer, step) twice.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import create_booking
from src.application.trainer_onboarding_recovery_use_cases import (
    ONBOARDING_TRIAL_OVER_GRACE_DAYS,
    STAGE_EMPTY_FORM,
    STAGE_NO_BOOKING,
    compute_due_onboarding_nudges,
    list_onboarding_candidates,
    mark_onboarding_nudge_sent,
)
from src.infrastructure.db.models import (
    ONBOARDING_NUDGE_STEP_D1,
    ONBOARDING_NUDGE_STEP_D3,
    ONBOARDING_NUDGE_STEP_D7,
    ONBOARDING_NUDGE_STEP_TRIAL_OVER,
    TRAINER_STATUS_ACTIVE,
    TRAINER_STATUS_DEACTIVATED,
    TRAINER_STATUS_PENDING_PROFILE,
)
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id


# --- helpers -----------------------------------------------------------------

_TG_BASE = 9_600_000_000
_tg_seq = 0


def _next_tg() -> int:
    global _tg_seq
    _tg_seq += 1
    return _TG_BASE + _tg_seq


async def _create_trainer(
    session: AsyncSession,
    *,
    telegram_id: int | None,
    status: str = TRAINER_STATUS_PENDING_PROFILE,
    created_days_ago: int = 0,
) -> int:
    created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    r = await session.execute(
        text(
            """
            INSERT INTO trainers (status, telegram_id, created_at)
            VALUES (:s, :tg, :ca) RETURNING id
            """
        ),
        {"s": status, "tg": telegram_id, "ca": created_at},
    )
    (trainer_id,) = r.fetchone()
    await session.commit()
    return trainer_id


async def _give_first_booking(session: AsyncSession, trainer_id: int) -> None:
    """Minimal slot + client + booking so has_any_booking flips True for this trainer."""
    from datetime import date, time

    service_id = await require_seed_service_id(session)
    await session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    r = await session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :et, 'available') RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "d": date.today() + timedelta(days=1),
            "st": time(10, 0),
            "et": time(11, 0),
        },
    )
    (slot_id,) = r.fetchone()
    await session.commit()

    tg = unique_test_telegram_id()
    phone, phone_normalized = belarus_test_phone(tg)
    r = await session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'Test', 'Client', :phone, :phone_normalized)
            RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "phone_normalized": phone_normalized},
    )
    (client_id,) = r.fetchone()
    await session.commit()

    await create_booking(
        session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
    )


async def _give_non_real_booking(
    session: AsyncSession, trainer_id: int, *, is_sandbox: bool = False, status: str = "confirmed"
) -> None:
    """TASK-027: a sandbox demo or an instantly-voided booking — must NOT drop the trainer
    out of the reactivation segment, unlike a real booking (``_give_first_booking`` above)."""
    from datetime import date, time

    service_id = await require_seed_service_id(session)
    tg = unique_test_telegram_id()
    phone, phone_normalized = belarus_test_phone(tg)
    r = await session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'Test', 'Client', :phone, :phone_normalized) RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "phone_normalized": phone_normalized},
    )
    (client_id,) = r.fetchone()
    r = await session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '10:00', TIME '11:00', 'booked') RETURNING id
            """
        ),
        {"tid": trainer_id, "d": date.today() + timedelta(days=1)},
    )
    (slot_id,) = r.fetchone()
    await session.execute(
        text(
            """
            INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status, is_sandbox)
            VALUES (:tid, :cid, :sid, :svc, :st, :sb)
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
    await session.commit()


async def _ensure_trial_plan(session: AsyncSession) -> int:
    """TASK-035: minimal is_trial=true plan row, reused across tests (mirrors the non-trial
    ``_ensure_plan`` helper in ``test_lead_mode_recovery.py``)."""
    r = await session.execute(
        text("SELECT id FROM subscription_plans WHERE COALESCE(is_trial, false) = true LIMIT 1")
    )
    row = r.fetchone()
    if row:
        return int(row[0])
    r = await session.execute(
        text(
            """
            INSERT INTO subscription_plans (name, price_cents, period_days, is_trial, sort_order)
            VALUES ('Onboarding Reactivation Test Trial', 0, 14, true, 1) RETURNING id
            """
        )
    )
    (pid,) = r.fetchone()
    await session.commit()
    return int(pid)


async def _insert_trial_subscription(
    session: AsyncSession, *, trainer_id: int, expires_days_ago: int
) -> None:
    """A trial subscription whose ``expires_at`` is ``expires_days_ago`` days in the past (0 means
    "expires right now"). Status intentionally kept 'trial' — ``get_trial_expired_days_ago`` must
    find it by plan shape (``is_trial``), not by a status a background job hasn't flipped yet."""
    plan_id = await _ensure_trial_plan(session)
    now = datetime.now(timezone.utc)
    expires_at = now - timedelta(days=expires_days_ago)
    started_at = expires_at - timedelta(days=14)
    await session.execute(
        text(
            """
            INSERT INTO trainer_subscriptions (trainer_id, plan_id, started_at, expires_at, status)
            VALUES (:tid, :pid, :s, :e, 'trial')
            """
        ),
        {"tid": trainer_id, "pid": plan_id, "s": started_at, "e": expires_at},
    )
    await session.commit()


# --- tests -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_pending_profile_is_candidate_with_empty_form_stage(
    db_session: AsyncSession,
) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg())
    candidates = await list_onboarding_candidates(db_session)
    mine = [c for c in candidates if c.trainer_id == tid]
    assert len(mine) == 1
    assert mine[0].stage == STAGE_EMPTY_FORM


@pytest.mark.asyncio
async def test_active_with_zero_bookings_is_candidate_with_no_booking_stage(
    db_session: AsyncSession,
) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg(), status=TRAINER_STATUS_ACTIVE)
    candidates = await list_onboarding_candidates(db_session)
    mine = [c for c in candidates if c.trainer_id == tid]
    assert len(mine) == 1
    assert mine[0].stage == STAGE_NO_BOOKING


@pytest.mark.asyncio
async def test_active_with_a_booking_is_not_a_candidate(db_session: AsyncSession) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg(), status=TRAINER_STATUS_ACTIVE)
    await _give_first_booking(db_session, tid)

    candidates = await list_onboarding_candidates(db_session)
    mine = [c for c in candidates if c.trainer_id == tid]
    assert mine == [], "Trainer with a first booking must drop out of the reactivation segment"


@pytest.mark.asyncio
async def test_active_with_only_sandbox_booking_stays_a_candidate(
    db_session: AsyncSession,
) -> None:
    """TASK-027 AC-004: a sandbox demo must not mute the whole reactivation series."""
    tid = await _create_trainer(db_session, telegram_id=_next_tg(), status=TRAINER_STATUS_ACTIVE)
    await _give_non_real_booking(db_session, tid, is_sandbox=True, status="confirmed")

    candidates = await list_onboarding_candidates(db_session)
    mine = [c for c in candidates if c.trainer_id == tid]
    assert len(mine) == 1
    assert mine[0].stage == STAGE_NO_BOOKING


@pytest.mark.asyncio
async def test_active_with_only_cancelled_booking_stays_a_candidate(
    db_session: AsyncSession,
) -> None:
    """TASK-027 AC-004: a booking voided before it happened must not mute the series either."""
    tid = await _create_trainer(db_session, telegram_id=_next_tg(), status=TRAINER_STATUS_ACTIVE)
    await _give_non_real_booking(db_session, tid, is_sandbox=False, status="cancelled")

    candidates = await list_onboarding_candidates(db_session)
    mine = [c for c in candidates if c.trainer_id == tid]
    assert len(mine) == 1
    assert mine[0].stage == STAGE_NO_BOOKING


@pytest.mark.asyncio
async def test_no_telegram_id_excluded(db_session: AsyncSession) -> None:
    tid = await _create_trainer(db_session, telegram_id=None)
    candidates = await list_onboarding_candidates(db_session)
    mine = [c for c in candidates if c.trainer_id == tid]
    assert mine == []


@pytest.mark.asyncio
async def test_deactivated_status_excluded(db_session: AsyncSession) -> None:
    tid = await _create_trainer(
        db_session, telegram_id=_next_tg(), status=TRAINER_STATUS_DEACTIVATED
    )
    candidates = await list_onboarding_candidates(db_session)
    mine = [c for c in candidates if c.trainer_id == tid]
    assert mine == []


@pytest.mark.asyncio
async def test_due_nudge_fires_d1_after_one_day(db_session: AsyncSession) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg(), created_days_ago=1)
    due = await compute_due_onboarding_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert len(mine) == 1
    assert mine[0].step == ONBOARDING_NUDGE_STEP_D1
    assert mine[0].stage == STAGE_EMPTY_FORM


@pytest.mark.asyncio
async def test_due_nudge_not_yet_at_day_zero(db_session: AsyncSession) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg(), created_days_ago=0)
    due = await compute_due_onboarding_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert mine == []


@pytest.mark.asyncio
async def test_after_d1_sent_d3_due_at_3_days(db_session: AsyncSession) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg(), created_days_ago=3)
    inserted = await mark_onboarding_nudge_sent(
        db_session, trainer_id=tid, step=ONBOARDING_NUDGE_STEP_D1, stage_anchor=STAGE_EMPTY_FORM
    )
    assert inserted is True

    due = await compute_due_onboarding_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert len(mine) == 1
    assert mine[0].step == ONBOARDING_NUDGE_STEP_D3


@pytest.mark.asyncio
async def test_mark_nudge_sent_is_idempotent(db_session: AsyncSession) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg())
    first = await mark_onboarding_nudge_sent(
        db_session, trainer_id=tid, step=ONBOARDING_NUDGE_STEP_D1, stage_anchor=STAGE_EMPTY_FORM
    )
    second = await mark_onboarding_nudge_sent(
        db_session, trainer_id=tid, step=ONBOARDING_NUDGE_STEP_D1, stage_anchor=STAGE_EMPTY_FORM
    )
    assert first is True
    assert second is False, "Re-marking the same step must be a no-op"


@pytest.mark.asyncio
async def test_mark_nudge_sent_rejects_unknown_step(db_session: AsyncSession) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg())
    with pytest.raises(ValueError):
        await mark_onboarding_nudge_sent(
            db_session, trainer_id=tid, step="d999", stage_anchor=None
        )


@pytest.mark.asyncio
async def test_trainer_progressing_out_of_segment_stops_further_nudges(
    db_session: AsyncSession,
) -> None:
    """Cancel-on-progress: first booking removes an active trainer from due nudges too."""
    tid = await _create_trainer(
        db_session, telegram_id=_next_tg(), status=TRAINER_STATUS_ACTIVE, created_days_ago=5
    )
    due_before = await compute_due_onboarding_nudges(db_session)
    assert any(n.trainer_id == tid for n in due_before)

    await _give_first_booking(db_session, tid)

    due_after = await compute_due_onboarding_nudges(db_session)
    assert not any(n.trainer_id == tid for n in due_after)


# --- TASK-035: trial-over step for trainers stuck in pending_profile past their trial ----------


@pytest.mark.asyncio
async def test_trial_over_step_fires_for_stalled_pending_profile_trainer(
    db_session: AsyncSession,
) -> None:
    """AC-001: pending_profile, no bookings, trial expired 20 days ago — not silence."""
    tid = await _create_trainer(db_session, telegram_id=_next_tg(), created_days_ago=20)
    await _insert_trial_subscription(db_session, trainer_id=tid, expires_days_ago=20)

    due = await compute_due_onboarding_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert len(mine) == 1
    assert mine[0].step == ONBOARDING_NUDGE_STEP_TRIAL_OVER


@pytest.mark.asyncio
async def test_trial_over_step_not_yet_due_within_grace_period(db_session: AsyncSession) -> None:
    """Trial just expired (within ``ONBOARDING_TRIAL_OVER_GRACE_DAYS``) — falls back to the
    normal D+1/D+3/D+7 pick instead of the trial-over step firing same-day as billing's own
    'trial ends today' reminder."""
    tid = await _create_trainer(db_session, telegram_id=_next_tg(), created_days_ago=20)
    assert ONBOARDING_TRIAL_OVER_GRACE_DAYS >= 1
    await _insert_trial_subscription(db_session, trainer_id=tid, expires_days_ago=0)

    due = await compute_due_onboarding_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert len(mine) == 1
    assert mine[0].step == ONBOARDING_NUDGE_STEP_D7


@pytest.mark.asyncio
async def test_trial_over_step_is_idempotent(db_session: AsyncSession) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg(), created_days_ago=20)
    await _insert_trial_subscription(db_session, trainer_id=tid, expires_days_ago=20)
    for step in (
        ONBOARDING_NUDGE_STEP_D1,
        ONBOARDING_NUDGE_STEP_D3,
        ONBOARDING_NUDGE_STEP_D7,
        ONBOARDING_NUDGE_STEP_TRIAL_OVER,
    ):
        await mark_onboarding_nudge_sent(
            db_session, trainer_id=tid, step=step, stage_anchor=STAGE_EMPTY_FORM
        )

    due = await compute_due_onboarding_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert mine == []


@pytest.mark.asyncio
async def test_trial_over_step_excluded_for_active_no_booking_stage(
    db_session: AsyncSession,
) -> None:
    """Regression for the TASK-035 Decision: STAGE_NO_BOOKING (active, no bookings) is out of
    scope — it must keep getting the plain D+1/D+3/D+7 series, never `trialend`."""
    tid = await _create_trainer(
        db_session, telegram_id=_next_tg(), status=TRAINER_STATUS_ACTIVE, created_days_ago=20
    )
    await _insert_trial_subscription(db_session, trainer_id=tid, expires_days_ago=20)

    due = await compute_due_onboarding_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert len(mine) == 1
    assert mine[0].step == ONBOARDING_NUDGE_STEP_D7


@pytest.mark.asyncio
async def test_trial_over_step_excluded_for_deactivated_trainer(db_session: AsyncSession) -> None:
    """EDGE-002: an admin deactivation after trial expiry must stop the series outright."""
    tid = await _create_trainer(
        db_session, telegram_id=_next_tg(), status=TRAINER_STATUS_DEACTIVATED, created_days_ago=20
    )
    await _insert_trial_subscription(db_session, trainer_id=tid, expires_days_ago=20)

    due = await compute_due_onboarding_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert mine == []


@pytest.mark.asyncio
async def test_no_trial_row_leaves_normal_series_unaffected(db_session: AsyncSession) -> None:
    """A trainer who never had a trial subscription row keeps the plain offset-based pick."""
    tid = await _create_trainer(db_session, telegram_id=_next_tg(), created_days_ago=1)

    due = await compute_due_onboarding_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert len(mine) == 1
    assert mine[0].step == ONBOARDING_NUDGE_STEP_D1
