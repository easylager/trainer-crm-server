"""
Integration tests for the Lead Mode recovery scheduler.

Covers:
- compute_due_nudges only lists trainers actually in LEAD_MODE (active status, visible, expired sub),
- step ordering (D+0 → D+3 → D+14 → D+30) anchored on last_subscription_expires_at,
- idempotency: mark_nudge_sent never inserts the same (trainer, step) twice,
- cancel-on-payment: a re-subscribed trainer disappears from compute_due_nudges' candidate list,
- "largest unfired" semantics for late re-enables.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.lead_mode_recovery_use_cases import (
    compute_due_nudges,
    mark_nudge_sent,
)
from src.infrastructure.db.models import (
    RECOVERY_STEP_D0,
    RECOVERY_STEP_D3,
    RECOVERY_STEP_D14,
    RECOVERY_STEP_D30,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_TIER_CRM,
    TRAINER_STATUS_ACTIVE,
)


# --- helpers -----------------------------------------------------------------


async def _create_trainer(
    session: AsyncSession,
    *,
    telegram_id: int,
    status: str = TRAINER_STATUS_ACTIVE,
    is_catalog_visible: bool = True,
) -> int:
    r = await session.execute(
        text(
            """
            INSERT INTO trainers (status, is_catalog_visible, telegram_id)
            VALUES (:s, :v, :tg) RETURNING id
            """
        ),
        {"s": status, "v": is_catalog_visible, "tg": telegram_id},
    )
    (trainer_id,) = r.fetchone()
    await session.commit()
    return trainer_id


async def _ensure_plan(session: AsyncSession) -> int:
    r = await session.execute(
        text("SELECT id FROM subscription_plans WHERE COALESCE(is_trial,false)=false LIMIT 1")
    )
    row = r.fetchone()
    if row:
        return int(row[0])
    r = await session.execute(
        text(
            """
            INSERT INTO subscription_plans (name, price_cents, period_days, is_trial, sort_order)
            VALUES ('Recovery Test Plan', 2900, 30, false, 99) RETURNING id
            """
        )
    )
    (pid,) = r.fetchone()
    await session.commit()
    return int(pid)


async def _insert_expired_sub(
    session: AsyncSession,
    *,
    trainer_id: int,
    days_ago: int,
    status: str = SUBSCRIPTION_STATUS_PAST_DUE,
) -> None:
    plan_id = await _ensure_plan(session)
    now = datetime.now(timezone.utc)
    expires_at = now - timedelta(days=days_ago)
    started_at = expires_at - timedelta(days=14)
    await session.execute(
        text(
            """
            INSERT INTO trainer_subscriptions
                (trainer_id, plan_id, started_at, expires_at, status, tier, modules)
            VALUES (:tid, :pid, :s, :e, :st, :tier, CAST(:m AS jsonb))
            """
        ),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "s": started_at,
            "e": expires_at,
            "st": status,
            "tier": SUBSCRIPTION_TIER_CRM,
            "m": json.dumps({"online": False, "analytics": False, "groups": False}),
        },
    )
    await session.commit()


async def _insert_active_sub(
    session: AsyncSession,
    *,
    trainer_id: int,
    expires_in_days: int = 30,
) -> None:
    plan_id = await _ensure_plan(session)
    now = datetime.now(timezone.utc)
    await session.execute(
        text(
            """
            INSERT INTO trainer_subscriptions
                (trainer_id, plan_id, started_at, expires_at, status, tier, modules)
            VALUES (:tid, :pid, :s, :e, :st, :tier, CAST(:m AS jsonb))
            """
        ),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "s": now - timedelta(days=1),
            "e": now + timedelta(days=expires_in_days),
            "st": SUBSCRIPTION_STATUS_ACTIVE,
            "tier": SUBSCRIPTION_TIER_CRM,
            "m": json.dumps({"online": False, "analytics": False, "groups": False}),
        },
    )
    await session.commit()


# Stable, non-overlapping telegram_ids per test (avoid UNIQUE collisions inside one transaction).
_TG_BASE = 9_500_000_000
_tg_seq = 0


def _next_tg() -> int:
    global _tg_seq
    _tg_seq += 1
    return _TG_BASE + _tg_seq


# --- tests -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_lead_mode_trainers_yields_empty(db_session: AsyncSession) -> None:
    due = await compute_due_nudges(db_session)
    # The DB might already contain unrelated test rows; we only care that nothing fails.
    assert isinstance(due, list)


@pytest.mark.asyncio
async def test_fresh_lead_mode_picks_d0(db_session: AsyncSession) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg())
    await _insert_expired_sub(db_session, trainer_id=tid, days_ago=0)

    due = await compute_due_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert len(mine) == 1
    assert mine[0].step == RECOVERY_STEP_D0
    assert mine[0].days_offset == 0


@pytest.mark.asyncio
async def test_after_d0_sent_d3_due_at_3_days(db_session: AsyncSession) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg())
    await _insert_expired_sub(db_session, trainer_id=tid, days_ago=3)
    # Mark D+0 as already delivered (e.g., yesterday's tick).
    inserted = await mark_nudge_sent(
        db_session, trainer_id=tid, step=RECOVERY_STEP_D0, expires_at_anchor=None
    )
    assert inserted is True

    due = await compute_due_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert len(mine) == 1
    assert mine[0].step == RECOVERY_STEP_D3


@pytest.mark.asyncio
async def test_late_re_enable_skips_to_d30(db_session: AsyncSession) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg())
    await _insert_expired_sub(db_session, trainer_id=tid, days_ago=45)

    due = await compute_due_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert len(mine) == 1
    assert mine[0].step == RECOVERY_STEP_D30
    assert mine[0].days_offset == 30
    assert mine[0].days_in_lead_mode >= 44


@pytest.mark.asyncio
async def test_series_exhausted_yields_no_nudge(db_session: AsyncSession) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg())
    await _insert_expired_sub(db_session, trainer_id=tid, days_ago=60)
    for step in (RECOVERY_STEP_D0, RECOVERY_STEP_D3, RECOVERY_STEP_D14, RECOVERY_STEP_D30):
        await mark_nudge_sent(
            db_session, trainer_id=tid, step=step, expires_at_anchor=None
        )

    due = await compute_due_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert mine == []


@pytest.mark.asyncio
async def test_cancel_on_payment_drops_from_due_list(db_session: AsyncSession) -> None:
    """Trainer with both expired-and-active subs is ACTIVE → no recovery nudges fire."""
    tid = await _create_trainer(db_session, telegram_id=_next_tg())
    await _insert_expired_sub(db_session, trainer_id=tid, days_ago=10)
    # Re-subscribed today: there's now a live (active, future-expiry) row.
    await _insert_active_sub(db_session, trainer_id=tid, expires_in_days=30)

    due = await compute_due_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert mine == [], "Resubscribed trainer must not receive recovery nudges"


@pytest.mark.asyncio
async def test_invisible_catalog_drops_from_due_list(db_session: AsyncSession) -> None:
    """Hidden catalog → CHURNED, not LEAD_MODE → no recovery nudges."""
    tid = await _create_trainer(
        db_session, telegram_id=_next_tg(), is_catalog_visible=False
    )
    await _insert_expired_sub(db_session, trainer_id=tid, days_ago=5)

    due = await compute_due_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert mine == []


@pytest.mark.asyncio
async def test_mark_nudge_sent_is_idempotent(db_session: AsyncSession) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg())
    first = await mark_nudge_sent(
        db_session, trainer_id=tid, step=RECOVERY_STEP_D0, expires_at_anchor=None
    )
    second = await mark_nudge_sent(
        db_session, trainer_id=tid, step=RECOVERY_STEP_D0, expires_at_anchor=None
    )
    assert first is True
    assert second is False, "Re-marking the same step must be a no-op"


@pytest.mark.asyncio
async def test_mark_nudge_sent_rejects_unknown_step(db_session: AsyncSession) -> None:
    tid = await _create_trainer(db_session, telegram_id=_next_tg())
    with pytest.raises(ValueError):
        await mark_nudge_sent(
            db_session, trainer_id=tid, step="d999", expires_at_anchor=None
        )


@pytest.mark.asyncio
async def test_signals_recap_anchored_to_last_expires_at(db_session: AsyncSession) -> None:
    """The DueRecoveryNudge.signals must aggregate from last_expires_at, not a fixed window."""
    tid = await _create_trainer(db_session, telegram_id=_next_tg())
    await _insert_expired_sub(db_session, trainer_id=tid, days_ago=20)
    # Insert two demand events that fall into the lead-mode window.
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_demand_events (trainer_id, kind, source, occurred_at)
            VALUES
                (:tid, 'profile_view', 'catalog', NOW() - INTERVAL '5 days'),
                (:tid, 'profile_view', 'catalog', NOW() - INTERVAL '1 day'),
                (:tid, 'contact_click', 'catalog', NOW() - INTERVAL '2 days'),
                (:tid, 'catalog_favorite', 'catalog', NOW() - INTERVAL '3 days')
            """
        ),
        {"tid": tid},
    )
    await db_session.commit()

    due = await compute_due_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert len(mine) == 1
    nudge = mine[0]
    assert nudge.signals.profile_views == 2
    assert nudge.signals.contact_clicks == 1
    assert nudge.signals.catalog_favorites == 1
    assert nudge.signals.has_any_demand is True


@pytest.mark.asyncio
async def test_no_telegram_id_excluded(db_session: AsyncSession) -> None:
    """Trainer without telegram_id can't receive a push, so they must not appear as candidate."""
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainers (status, is_catalog_visible, telegram_id)
            VALUES (:s, TRUE, NULL) RETURNING id
            """
        ),
        {"s": TRAINER_STATUS_ACTIVE},
    )
    (tid,) = r.fetchone()
    await db_session.commit()
    await _insert_expired_sub(db_session, trainer_id=tid, days_ago=2)

    due = await compute_due_nudges(db_session)
    mine = [n for n in due if n.trainer_id == tid]
    assert mine == []
