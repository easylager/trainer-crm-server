"""Integration tests for Care Pulse's trainer-candidate gating (TASK-026).

``list_due_care_pulses`` end-to-end: candidate SQL in ``_list_trainer_facts`` + the pure
picker in ``pick_trainer_pulse``. Distinct from ``test_care_pulse_pure.py``, which only
exercises the picker with hand-built kwargs and never touches the DB or the candidate query.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import text

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

from src.application.care_pulse_use_cases import list_due_care_pulses
from src.infrastructure.db.models import CARE_PULSE_KIND_TOMORROW_PLAN
from src.shared.notification_hours import NOTIFICATION_TZ
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id


def _next_monday_on_or_after(d: date) -> date:
    """Care Pulse stays silent on Sunday (weekday_mon0 == 6) — anchor tests on a Monday."""
    days_ahead = (7 - d.weekday()) % 7
    return d + timedelta(days=days_ahead or 7)


async def _seed_trainer_with_tomorrow_session(
    db_session,
    *,
    status: str,
    telegram_id: int | None,
    today: date,
) -> int:
    r = await db_session.execute(
        text(
            "INSERT INTO trainers (status, telegram_id, is_catalog_visible) "
            "VALUES (:status, :tg, false) RETURNING id"
        ),
        {"status": status, "tg": telegram_id},
    )
    (trainer_id,) = r.fetchone()

    tg_client = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg_client)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'Tomorrow', 'Client', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg_client, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()

    service_id = await require_seed_service_id(db_session)
    tomorrow = today + timedelta(days=1)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '09:00', TIME '10:00', 'booked') RETURNING id
            """
        ),
        {"tid": trainer_id, "d": tomorrow},
    )
    (slot_id,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status)
            VALUES (:tid, :cid, :sid, :svc, 'confirmed')
            """
        ),
        {"tid": trainer_id, "cid": client_id, "sid": slot_id, "svc": service_id},
    )
    return trainer_id


@pytest.mark.asyncio
async def test_care_pulse_includes_pending_profile_trainer_with_tomorrow_session(db_session) -> None:
    """TASK-026 AC-002: onboarding v2 — still-unmoderated trainer gets tomorrow_plan."""
    today = _next_monday_on_or_after(date.today())
    tg = unique_test_telegram_id()
    trainer_id = await _seed_trainer_with_tomorrow_session(
        db_session, status="pending_profile", telegram_id=tg, today=today
    )
    await db_session.commit()

    now_minsk = datetime.combine(today, time(13, 0), tzinfo=ZoneInfo(NOTIFICATION_TZ))
    pulses = await list_due_care_pulses(db_session, now_minsk)
    matches = [p for p in pulses if p.recipient_id == trainer_id]
    assert len(matches) == 1
    assert matches[0].kind == CARE_PULSE_KIND_TOMORROW_PLAN


@pytest.mark.asyncio
async def test_care_pulse_excludes_deactivated_trainer(db_session) -> None:
    """TASK-026 AC-003 (care-pulse half): explicit deactivation is the only closing status."""
    today = _next_monday_on_or_after(date.today())
    tg = unique_test_telegram_id()
    trainer_id = await _seed_trainer_with_tomorrow_session(
        db_session, status="deactivated", telegram_id=tg, today=today
    )
    await db_session.commit()

    now_minsk = datetime.combine(today, time(13, 0), tzinfo=ZoneInfo(NOTIFICATION_TZ))
    pulses = await list_due_care_pulses(db_session, now_minsk)
    assert trainer_id not in {p.recipient_id for p in pulses if p.audience == "trainer"}


async def _insert_expired_trial_subscription(db_session, *, trainer_id: int) -> None:
    """TASK-035: candidate SQL must not gate on subscription state at all — a trainer whose
    trial burned out long ago is exactly the segment this task stops from going silent."""
    r = await db_session.execute(
        text("SELECT id FROM subscription_plans WHERE COALESCE(is_trial, false) = true LIMIT 1")
    )
    row = r.fetchone()
    if row:
        plan_id = int(row[0])
    else:
        r = await db_session.execute(
            text(
                """
                INSERT INTO subscription_plans (name, price_cents, period_days, is_trial, sort_order)
                VALUES ('Care Pulse Test Trial', 0, 14, true, 1) RETURNING id
                """
            )
        )
        (plan_id,) = r.fetchone()
    now = datetime.now(ZoneInfo(NOTIFICATION_TZ))
    expires_at = now - timedelta(days=20)
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_subscriptions (trainer_id, plan_id, started_at, expires_at, status)
            VALUES (:tid, :pid, :s, :e, 'trial')
            """
        ),
        {"tid": trainer_id, "pid": plan_id, "s": expires_at - timedelta(days=14), "e": expires_at},
    )


@pytest.mark.asyncio
async def test_care_pulse_includes_pending_profile_trainer_with_expired_trial(db_session) -> None:
    """TASK-035 AC-002: expired-trial pending_profile trainer stays a care-pulse candidate."""
    today = _next_monday_on_or_after(date.today())
    tg = unique_test_telegram_id()
    trainer_id = await _seed_trainer_with_tomorrow_session(
        db_session, status="pending_profile", telegram_id=tg, today=today
    )
    await _insert_expired_trial_subscription(db_session, trainer_id=trainer_id)
    await db_session.commit()

    now_minsk = datetime.combine(today, time(13, 0), tzinfo=ZoneInfo(NOTIFICATION_TZ))
    pulses = await list_due_care_pulses(db_session, now_minsk)
    matches = [p for p in pulses if p.recipient_id == trainer_id]
    assert len(matches) == 1
    assert matches[0].kind == CARE_PULSE_KIND_TOMORROW_PLAN


@pytest.mark.asyncio
async def test_care_pulse_excludes_trainer_without_telegram(db_session) -> None:
    """TASK-026 AC-004 (care-pulse half): no telegram_id means no delivery channel at all."""
    today = _next_monday_on_or_after(date.today())
    trainer_id = await _seed_trainer_with_tomorrow_session(
        db_session, status="active", telegram_id=None, today=today
    )
    await db_session.commit()

    now_minsk = datetime.combine(today, time(13, 0), tzinfo=ZoneInfo(NOTIFICATION_TZ))
    pulses = await list_due_care_pulses(db_session, now_minsk)
    assert trainer_id not in {p.recipient_id for p in pulses if p.audience == "trainer"}
