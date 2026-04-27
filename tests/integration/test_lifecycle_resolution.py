"""
Integration tests for resolve_lifecycle_snapshot / trainer_can.

Covers each lifecycle state against a real DB to verify:
- the SQL query reads the right fields,
- subscription expiry boundary maps to LEAD_MODE,
- trainer_can correctly composes lifecycle and module gates.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.lifecycle_use_cases import (
    Capability,
    LifecycleStage,
    resolve_lifecycle_snapshot,
    resolve_lifecycle_stage,
    trainer_can,
)
from src.infrastructure.db.models import (
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_TRIAL,
    SUBSCRIPTION_TIER_CRM,
    TRAINER_STATUS_ACTIVE,
    TRAINER_STATUS_DEACTIVATED,
    TRAINER_STATUS_PENDING_PROFILE,
)


async def _create_trainer(
    session: AsyncSession,
    *,
    status: str = TRAINER_STATUS_ACTIVE,
    is_catalog_visible: bool = True,
) -> int:
    r = await session.execute(
        text(
            "INSERT INTO trainers (status, is_catalog_visible) VALUES (:s, :v) RETURNING id"
        ),
        {"s": status, "v": is_catalog_visible},
    )
    (trainer_id,) = r.fetchone()
    await session.commit()
    return trainer_id


async def _ensure_paid_plan_id(session: AsyncSession) -> int:
    """Reuse seed plan if present, otherwise create a non-trial plan for the test."""
    r = await session.execute(
        text(
            """
            SELECT id FROM subscription_plans
            WHERE COALESCE(is_trial, false) = false
            ORDER BY id LIMIT 1
            """
        )
    )
    row = r.fetchone()
    if row is not None:
        return int(row[0])
    r = await session.execute(
        text(
            """
            INSERT INTO subscription_plans (name, price_cents, period_days, is_trial, sort_order)
            VALUES ('Test Paid', 2900, 30, false, 99) RETURNING id
            """
        )
    )
    (plan_id,) = r.fetchone()
    await session.commit()
    return int(plan_id)


async def _grant_subscription(
    session: AsyncSession,
    *,
    trainer_id: int,
    status: str,
    expires_in_days: int,
    modules: dict[str, bool] | None = None,
) -> None:
    plan_id = await _ensure_paid_plan_id(session)
    now = datetime.now(timezone.utc)
    started_at = now - timedelta(days=1)
    expires_at = now + timedelta(days=expires_in_days)
    mods = modules if modules is not None else {"online": False, "analytics": False, "groups": False}
    await session.execute(
        text(
            """
            INSERT INTO trainer_subscriptions
                (trainer_id, plan_id, started_at, expires_at, status, tier, modules)
            VALUES (:tid, :pid, :s_at, :e_at, :st, :tier, CAST(:mods AS jsonb))
            """
        ),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "s_at": started_at,
            "e_at": expires_at,
            "st": status,
            "tier": SUBSCRIPTION_TIER_CRM,
            "mods": json.dumps(mods, ensure_ascii=False),
        },
    )
    await session.commit()


# --- resolve_lifecycle_snapshot per stage ---


@pytest.mark.asyncio
async def test_missing_trainer_resolves_to_churned(db_session: AsyncSession) -> None:
    snap = await resolve_lifecycle_snapshot(db_session, trainer_id=99_999_999)
    assert snap.stage == LifecycleStage.CHURNED
    assert snap.trainer_status is None
    assert snap.has_active_subscription is False
    assert snap.is_catalog_visible is False


@pytest.mark.asyncio
async def test_pending_profile_trainer_is_onboarding(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session, status=TRAINER_STATUS_PENDING_PROFILE)
    snap = await resolve_lifecycle_snapshot(db_session, trainer_id=trainer_id)
    assert snap.stage == LifecycleStage.ONBOARDING


@pytest.mark.asyncio
async def test_active_trainer_with_active_subscription_is_active(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    await _grant_subscription(
        db_session,
        trainer_id=trainer_id,
        status=SUBSCRIPTION_STATUS_ACTIVE,
        expires_in_days=15,
    )
    snap = await resolve_lifecycle_snapshot(db_session, trainer_id=trainer_id)
    assert snap.stage == LifecycleStage.ACTIVE
    assert snap.has_active_subscription is True
    assert snap.is_catalog_visible is True


@pytest.mark.asyncio
async def test_trial_subscription_yields_active(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    await _grant_subscription(
        db_session,
        trainer_id=trainer_id,
        status=SUBSCRIPTION_STATUS_TRIAL,
        expires_in_days=7,
    )
    stage = await resolve_lifecycle_stage(db_session, trainer_id=trainer_id)
    assert stage == LifecycleStage.ACTIVE


@pytest.mark.asyncio
async def test_active_trainer_no_subscription_is_lead_mode(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    snap = await resolve_lifecycle_snapshot(db_session, trainer_id=trainer_id)
    assert snap.stage == LifecycleStage.LEAD_MODE
    assert snap.has_active_subscription is False
    assert snap.is_catalog_visible is True


@pytest.mark.asyncio
async def test_expired_trial_yields_lead_mode(db_session: AsyncSession) -> None:
    """Trial expired (past_due) — the canonical Lead Mode path."""
    trainer_id = await _create_trainer(db_session)
    await _grant_subscription(
        db_session,
        trainer_id=trainer_id,
        status=SUBSCRIPTION_STATUS_PAST_DUE,
        expires_in_days=-2,  # already expired
    )
    snap = await resolve_lifecycle_snapshot(db_session, trainer_id=trainer_id)
    assert snap.stage == LifecycleStage.LEAD_MODE
    assert snap.last_subscription_expires_at is not None


@pytest.mark.asyncio
async def test_active_trainer_no_sub_hidden_is_churned(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session, is_catalog_visible=False)
    stage = await resolve_lifecycle_stage(db_session, trainer_id=trainer_id)
    assert stage == LifecycleStage.CHURNED


@pytest.mark.asyncio
async def test_active_trainer_with_sub_hidden_is_active(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session, is_catalog_visible=False)
    await _grant_subscription(
        db_session,
        trainer_id=trainer_id,
        status=SUBSCRIPTION_STATUS_ACTIVE,
        expires_in_days=15,
    )
    stage = await resolve_lifecycle_stage(db_session, trainer_id=trainer_id)
    # Paid + hidden = paused-but-Pro, still ACTIVE.
    assert stage == LifecycleStage.ACTIVE


@pytest.mark.asyncio
async def test_deactivated_trainer_is_churned(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session, status=TRAINER_STATUS_DEACTIVATED)
    stage = await resolve_lifecycle_stage(db_session, trainer_id=trainer_id)
    assert stage == LifecycleStage.CHURNED


@pytest.mark.asyncio
async def test_subscription_at_exact_now_is_treated_as_expired(
    db_session: AsyncSession,
) -> None:
    """expires_at = now (boundary): row is past `now()`, so trainer is in LEAD_MODE."""
    trainer_id = await _create_trainer(db_session)
    plan_id = await _ensure_paid_plan_id(db_session)
    now = datetime.now(timezone.utc)
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_subscriptions
                (trainer_id, plan_id, started_at, expires_at, status, tier, modules)
            VALUES (:tid, :pid, :s_at, :e_at, :st, :tier, CAST(:mods AS jsonb))
            """
        ),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "s_at": now - timedelta(days=14),
            "e_at": now - timedelta(milliseconds=1),
            "st": SUBSCRIPTION_STATUS_PAST_DUE,
            "tier": SUBSCRIPTION_TIER_CRM,
            "mods": json.dumps({"online": False, "analytics": False, "groups": False}),
        },
    )
    await db_session.commit()
    stage = await resolve_lifecycle_stage(db_session, trainer_id=trainer_id)
    assert stage == LifecycleStage.LEAD_MODE


# --- trainer_can: composite gate ---


@pytest.mark.asyncio
async def test_trainer_can_lead_mode_allows_only_presence(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    # Lead Mode (no subscription, visible).
    assert await trainer_can(db_session, trainer_id, Capability.CATALOG_VISIBILITY) is True
    assert await trainer_can(db_session, trainer_id, Capability.RECEIVE_LEADS) is True
    assert await trainer_can(db_session, trainer_id, Capability.READ_OPERATIONS) is True
    assert await trainer_can(db_session, trainer_id, Capability.CRM_BASE) is False
    assert await trainer_can(db_session, trainer_id, Capability.ONLINE_BOOKING) is False
    assert await trainer_can(db_session, trainer_id, Capability.ANALYTICS) is False
    assert await trainer_can(db_session, trainer_id, Capability.GROUPS) is False


@pytest.mark.asyncio
async def test_trainer_can_active_with_crm_only(db_session: AsyncSession) -> None:
    """ACTIVE without paid modules — CRM_BASE allowed, paid modules denied."""
    trainer_id = await _create_trainer(db_session)
    await _grant_subscription(
        db_session,
        trainer_id=trainer_id,
        status=SUBSCRIPTION_STATUS_ACTIVE,
        expires_in_days=30,
        modules={"online": False, "analytics": False, "groups": False},
    )
    assert await trainer_can(db_session, trainer_id, Capability.CRM_BASE) is True
    assert await trainer_can(db_session, trainer_id, Capability.ONLINE_BOOKING) is False
    assert await trainer_can(db_session, trainer_id, Capability.ANALYTICS) is False
    assert await trainer_can(db_session, trainer_id, Capability.GROUPS) is False
    # Presence capabilities still allowed in ACTIVE.
    assert await trainer_can(db_session, trainer_id, Capability.CATALOG_VISIBILITY) is True
    assert await trainer_can(db_session, trainer_id, Capability.READ_OPERATIONS) is True


@pytest.mark.asyncio
async def test_trainer_can_active_with_online_module(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    await _grant_subscription(
        db_session,
        trainer_id=trainer_id,
        status=SUBSCRIPTION_STATUS_ACTIVE,
        expires_in_days=30,
        modules={"online": True, "analytics": False, "groups": False},
    )
    assert await trainer_can(db_session, trainer_id, Capability.ONLINE_BOOKING) is True
    assert await trainer_can(db_session, trainer_id, Capability.ANALYTICS) is False
    assert await trainer_can(db_session, trainer_id, Capability.GROUPS) is False


@pytest.mark.asyncio
async def test_trainer_can_active_with_full_bundle(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    await _grant_subscription(
        db_session,
        trainer_id=trainer_id,
        status=SUBSCRIPTION_STATUS_TRIAL,
        expires_in_days=14,
        modules={"online": True, "analytics": True, "groups": True},
    )
    for cap in Capability:
        assert await trainer_can(db_session, trainer_id, cap) is True, f"{cap} should pass"


@pytest.mark.asyncio
async def test_trainer_can_churned_blocks_everything(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session, status=TRAINER_STATUS_DEACTIVATED)
    for cap in Capability:
        assert await trainer_can(db_session, trainer_id, cap) is False


@pytest.mark.asyncio
async def test_trainer_can_onboarding_blocks_everything(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session, status=TRAINER_STATUS_PENDING_PROFILE)
    for cap in Capability:
        assert await trainer_can(db_session, trainer_id, cap) is False


@pytest.mark.asyncio
async def test_last_subscription_expires_at_anchors_recovery(
    db_session: AsyncSession,
) -> None:
    """Recovery nudges schedule from last_subscription_expires_at — must be returned."""
    trainer_id = await _create_trainer(db_session)
    await _grant_subscription(
        db_session,
        trainer_id=trainer_id,
        status=SUBSCRIPTION_STATUS_PAST_DUE,
        expires_in_days=-3,
    )
    snap = await resolve_lifecycle_snapshot(db_session, trainer_id=trainer_id)
    assert snap.stage == LifecycleStage.LEAD_MODE
    assert snap.last_subscription_expires_at is not None
    delta = datetime.now(timezone.utc) - snap.last_subscription_expires_at
    assert timedelta(days=2, hours=23) < delta < timedelta(days=3, hours=1)
