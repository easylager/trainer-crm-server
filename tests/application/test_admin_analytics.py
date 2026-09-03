"""Smoke + behaviour tests for advanced admin analytics use cases.

The five admin Mini-Apps (Money / Growth / Retention / Engagement / Clients)
each consume one of these use cases. The tests guarantee:

1. Every documented dict key is always present (Mini-Apps can't render undefined).
2. The query chain doesn't poison its own transaction — i.e. it returns a usable
   dict even after several internal queries succeed in sequence.
3. Behavioural deltas: when we insert a fixture, the relevant counter goes up
   exactly by the expected amount.

We avoid absolute "== 0" assertions because the integration test DB
(``trainer_crm_test`` / ``trainer_crm`` with PYTEST_RELAX_DATABASE_NAME=1)
may already contain seed data. We verify *deltas*.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.admin_analytics_use_cases import (
    get_admin_clients_stats,
    get_admin_engagement_stats,
    get_admin_growth_stats,
    get_admin_money_stats,
    get_admin_product_analytics,
    get_admin_retention_stats,
    get_admin_trainers_hub_stats,
)
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id


# ──────────────────────────────────────────────────────────────────────────
# Required keys per Mini-App contract.
# ──────────────────────────────────────────────────────────────────────────

_MONEY_KEYS = {
    "today",
    "mrr_cents", "arr_cents", "active_paid_subscriptions",
    "revenue_paid_30d_cents", "revenue_paid_prev_30d_cents", "revenue_paid_mom_pct",
    "paid_invoices_30d_count",
    "gmv_30d_cents", "gmv_prev_30d_cents", "gmv_mom_pct", "gmv_by_month",
    "subscription_mix",
    "top_paying_trainers",
    "pending_invoices", "pending_invoices_count", "pending_invoices_total_cents",
    "paying_trainers_total", "avg_paid_invoice_cents",
}

_GROWTH_KEYS = {
    "today",
    "new_trainers_7d", "new_trainers_30d", "new_trainers_prev_30d", "new_trainers_mom_pct",
    "new_trainers_by_month",
    "trial_starts_90d", "trial_paid_90d", "trial_to_paid_pct", "trial_to_paid_pct_prev",
    "median_days_to_first_paid", "p90_days_to_first_paid", "median_days_to_first_booking",
    "referral_invites_total", "referral_credited_total",
    "referral_credit_days_total", "referral_credit_days_30d",
    "top_referrers", "recent_signups",
}

_RETENTION_KEYS = {
    "today",
    "churn_count_30d", "base_active_30d_ago", "churn_rate_30d_pct", "churned_trainers",
    "expiring_7d_count", "expiring_14d_count", "expiring_30d_count", "expiring_soon",
    "sleeping_30_count", "sleeping_60_count", "sleeping_90_count", "sleeping_trainers",
    "revival_count_30d", "revived_trainers",
    "cohort_retention",
}

_ENGAGEMENT_KEYS = {
    "today",
    "dau", "wau", "mau", "trainers_active",
    "wau_share_pct", "mau_share_pct",
    "avg_bookings_per_active_30d", "median_bookings_per_active_30d",
    "feature_usage", "top_active_trainers",
    "dow_labels", "dow_counts",
}

_CLIENTS_KEYS = {
    "today",
    "clients_total", "clients_with_telegram",
    "clients_active_30d", "clients_active_90d",
    "new_clients_30d", "new_clients_prev_30d", "new_clients_mom_pct",
    "clients_repeat_90d", "repeat_rate_pct", "avg_bookings_per_client_90d",
    "requests_30d", "requests_with_response_30d", "requests_with_booking_30d",
    "request_response_pct", "request_booking_pct",
    "top_cities", "top_trainers_by_clients", "recent_requests",
}

_TRAINERS_HUB_KEYS = {
    "today",
    "paying_count", "trial_count", "live_7d_count", "sleeping_paid_count",
    "onboarding_count", "ghost_count",
    "trial_starts_90d", "trial_paid_90d", "trial_to_paid_pct",
    "expiring_paid", "top_by_bookings", "sleeping_paid",
}


# ──────────────────────────────────────────────────────────────────────────
# Shape tests — "every Mini-App contract key exists, no key is missing".
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_money_shape(db_session: AsyncSession) -> None:
    data = await get_admin_money_stats(db_session)
    missing = _MONEY_KEYS - set(data.keys())
    assert not missing, f"missing money keys: {missing}"
    assert isinstance(data["gmv_by_month"], list) and len(data["gmv_by_month"]) == 6
    for row in data["gmv_by_month"]:
        assert {"month", "gmv_cents"} <= row.keys()
    assert isinstance(data["subscription_mix"], list)
    assert isinstance(data["top_paying_trainers"], list)
    assert isinstance(data["pending_invoices"], list)


@pytest.mark.asyncio
async def test_growth_shape(db_session: AsyncSession) -> None:
    data = await get_admin_growth_stats(db_session)
    missing = _GROWTH_KEYS - set(data.keys())
    assert not missing, f"missing growth keys: {missing}"
    assert isinstance(data["new_trainers_by_month"], list) and len(data["new_trainers_by_month"]) == 6
    assert isinstance(data["top_referrers"], list)
    assert isinstance(data["recent_signups"], list)


@pytest.mark.asyncio
async def test_retention_shape(db_session: AsyncSession) -> None:
    data = await get_admin_retention_stats(db_session)
    missing = _RETENTION_KEYS - set(data.keys())
    assert not missing, f"missing retention keys: {missing}"
    assert isinstance(data["expiring_soon"], list)
    assert isinstance(data["sleeping_trainers"], list)
    assert isinstance(data["revived_trainers"], list)
    assert isinstance(data["cohort_retention"], list)


@pytest.mark.asyncio
async def test_engagement_shape(db_session: AsyncSession) -> None:
    data = await get_admin_engagement_stats(db_session)
    missing = _ENGAGEMENT_KEYS - set(data.keys())
    assert not missing, f"missing engagement keys: {missing}"
    assert len(data["dow_labels"]) == 7 and len(data["dow_counts"]) == 7
    feats = {f["feature"] for f in data["feature_usage"]}
    assert {"groups", "online", "analytics", "passes", "certificates"}.issubset(feats)
    for f in data["feature_usage"]:
        assert {"feature", "label", "users", "share_pct"} <= f.keys()


@pytest.mark.asyncio
async def test_clients_shape(db_session: AsyncSession) -> None:
    data = await get_admin_clients_stats(db_session)
    missing = _CLIENTS_KEYS - set(data.keys())
    assert not missing, f"missing clients keys: {missing}"
    assert isinstance(data["top_cities"], list)
    assert isinstance(data["top_trainers_by_clients"], list)
    assert isinstance(data["recent_requests"], list)


@pytest.mark.asyncio
async def test_trainers_hub_shape(db_session: AsyncSession) -> None:
    data = await get_admin_trainers_hub_stats(db_session)
    missing = _TRAINERS_HUB_KEYS - set(data.keys())
    assert not missing, f"missing trainers hub keys: {missing}"
    assert isinstance(data["expiring_paid"], list)
    assert isinstance(data["top_by_bookings"], list)
    assert isinstance(data["sleeping_paid"], list)


# ──────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────────────────────────────────


async def _insert_trainer(session: AsyncSession, *, status: str = "active",
                          created_offset_days: int = 0) -> int:
    created_at = datetime.now(timezone.utc) - timedelta(days=created_offset_days)
    r = await session.execute(
        text(
            """
            INSERT INTO trainers (status, created_at, schedule_grid_step_minutes)
            VALUES (:s, :c, 15)
            RETURNING id
            """
        ),
        {"s": status, "c": created_at},
    )
    return int(r.scalar_one())


async def _insert_subscription_plan(session: AsyncSession) -> int:
    r = await session.execute(
        text(
            """
            INSERT INTO subscription_plans (name, price_cents, period_days, is_trial, sort_order)
            VALUES ('TestPlanForAnalytics', 9900, 30, false, 0)
            RETURNING id
            """
        )
    )
    return int(r.scalar_one())


async def _insert_subscription(
    session: AsyncSession,
    *,
    trainer_id: int,
    plan_id: int,
    status: str,
    days_ago_started: int,
    days_until_expires: int,
    billing_period_months: int | None = None,
    modules: dict | None = None,
) -> int:
    started = datetime.now(timezone.utc) - timedelta(days=days_ago_started)
    expires = datetime.now(timezone.utc) + timedelta(days=days_until_expires)
    mods = modules or {"online": False, "analytics": False, "groups": False}
    r = await session.execute(
        text(
            """
            INSERT INTO trainer_subscriptions
                (trainer_id, plan_id, modules, billing_period_months, started_at, expires_at, status)
            VALUES (:t, :p, CAST(:m AS jsonb), :bm, :s, :e, :st)
            RETURNING id
            """
        ),
        {
            "t": trainer_id,
            "p": plan_id,
            "m": json.dumps(mods),
            "bm": billing_period_months,
            "s": started,
            "e": expires,
            "st": status,
        },
    )
    return int(r.scalar_one())


async def _insert_invoice(
    session: AsyncSession,
    *,
    trainer_id: int,
    plan_id: int,
    amount_cents: int,
    status: str,
    paid_offset_days: int | None,
    billing_period_months: int | None = None,
) -> int:
    now = datetime.now(timezone.utc)
    paid_at = (now - timedelta(days=paid_offset_days)) if paid_offset_days is not None else None
    r = await session.execute(
        text(
            """
            INSERT INTO trainer_invoices
                (trainer_id, subscription_plan_id, amount_cents,
                 period_start, period_end, due_date, status, paid_at,
                 checkout_billing_period_months,
                 referral_bonus_days_applied, amount_cents_before_referral)
            VALUES (:t, :p, :a, :ps, :pe, :dd, :s, :pa, :bm, 0, :a)
            RETURNING id
            """
        ),
        {
            "t": trainer_id,
            "p": plan_id,
            "a": amount_cents,
            "ps": now - timedelta(days=10),
            "pe": now + timedelta(days=20),
            "dd": now + timedelta(days=5),
            "s": status,
            "pa": paid_at,
            "bm": billing_period_months,
        },
    )
    return int(r.scalar_one())


# ──────────────────────────────────────────────────────────────────────────
# Behaviour tests — measure deltas vs. baseline.
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_money_pending_invoice_appears_in_drilldown(db_session: AsyncSession) -> None:
    """A new pending invoice must show up in the pending list with correct fields."""
    plan_id = await _insert_subscription_plan(db_session)
    tid = await _insert_trainer(db_session)
    iid = await _insert_invoice(
        db_session,
        trainer_id=tid,
        plan_id=plan_id,
        amount_cents=4900,
        status="sent",
        paid_offset_days=None,
    )
    data = await get_admin_money_stats(db_session)
    matching = [p for p in data["pending_invoices"] if p["invoice_id"] == iid]
    assert len(matching) == 1
    assert matching[0]["trainer_id"] == tid
    assert matching[0]["amount_cents"] == 4900
    assert matching[0]["status"] == "sent"
    # New required field that replaced the bogus `created_at`
    assert "issued_at" in matching[0]


@pytest.mark.asyncio
async def test_money_active_paid_subscription_increments_count(db_session: AsyncSession) -> None:
    """Adding one active paid subscription with a matching paid invoice bumps active_paid by 1."""
    before = await get_admin_money_stats(db_session)
    plan_id = await _insert_subscription_plan(db_session)
    tid = await _insert_trainer(db_session)
    await _insert_subscription(
        db_session, trainer_id=tid, plan_id=plan_id, status="active",
        days_ago_started=10, days_until_expires=20, billing_period_months=1,
    )
    await _insert_invoice(
        db_session, trainer_id=tid, plan_id=plan_id, amount_cents=9900,
        status="paid", paid_offset_days=10, billing_period_months=1,
    )
    after = await get_admin_money_stats(db_session)
    assert after["active_paid_subscriptions"] == before["active_paid_subscriptions"] + 1
    # MRR for this sub = 9900/1 month = 9900 cents added.
    assert after["mrr_cents"] == before["mrr_cents"] + 9900


@pytest.mark.asyncio
async def test_money_yearly_invoice_normalizes_to_monthly_mrr(db_session: AsyncSession) -> None:
    """A 12-month invoice for 120 BYN must contribute exactly 10 BYN/mo to MRR."""
    before = await get_admin_money_stats(db_session)
    plan_id = await _insert_subscription_plan(db_session)
    tid = await _insert_trainer(db_session)
    await _insert_subscription(
        db_session, trainer_id=tid, plan_id=plan_id, status="active",
        days_ago_started=10, days_until_expires=355, billing_period_months=12,
    )
    await _insert_invoice(
        db_session, trainer_id=tid, plan_id=plan_id, amount_cents=12000,
        status="paid", paid_offset_days=10, billing_period_months=12,
    )
    after = await get_admin_money_stats(db_session)
    # Δ MRR = 12000 / 12 = 1000 cents
    assert after["mrr_cents"] - before["mrr_cents"] == 1000
    # ARR is always 12× MRR
    assert after["arr_cents"] == after["mrr_cents"] * 12


@pytest.mark.asyncio
async def test_growth_new_trainer_counter_increments(db_session: AsyncSession) -> None:
    before = await get_admin_growth_stats(db_session)
    await _insert_trainer(db_session, created_offset_days=0)
    after = await get_admin_growth_stats(db_session)
    assert after["new_trainers_7d"] == before["new_trainers_7d"] + 1
    assert after["new_trainers_30d"] == before["new_trainers_30d"] + 1


@pytest.mark.asyncio
async def test_retention_expiring_soon_includes_new_subscription(db_session: AsyncSession) -> None:
    before = await get_admin_retention_stats(db_session)
    plan_id = await _insert_subscription_plan(db_session)
    tid = await _insert_trainer(db_session)
    await _insert_subscription(
        db_session, trainer_id=tid, plan_id=plan_id, status="active",
        days_ago_started=27, days_until_expires=3,
    )
    after = await get_admin_retention_stats(db_session)
    assert after["expiring_7d_count"] == before["expiring_7d_count"] + 1
    assert after["expiring_30d_count"] == before["expiring_30d_count"] + 1
    assert any(row["trainer_id"] == tid for row in after["expiring_soon"])


@pytest.mark.asyncio
async def test_retention_sleeping_includes_trainer_with_no_bookings(db_session: AsyncSession) -> None:
    """A trainer who created their account 60+ days ago and never booked counts as sleeping."""
    before = await get_admin_retention_stats(db_session)
    await _insert_trainer(db_session, status="active", created_offset_days=60)
    after = await get_admin_retention_stats(db_session)
    assert after["sleeping_30_count"] >= before["sleeping_30_count"] + 1
    assert after["sleeping_60_count"] >= before["sleeping_60_count"] + 1


@pytest.mark.asyncio
async def test_engagement_feature_share_never_exceeds_100_percent(db_session: AsyncSession) -> None:
    """Feature adoption numerators must be scoped to active trainers only."""
    data = await get_admin_engagement_stats(db_session)
    active = data["trainers_active"]
    for feat in data["feature_usage"]:
        assert feat["users"] <= active, feat
        if feat["share_pct"] is not None:
            assert feat["share_pct"] <= 100.0, feat


@pytest.mark.asyncio
async def test_engagement_online_module_ignores_non_active_trainer(db_session: AsyncSession) -> None:
    before = await get_admin_engagement_stats(db_session)
    plan_id = await _insert_subscription_plan(db_session)
    pending_tid = await _insert_trainer(db_session, status="pending_profile")
    await _insert_subscription(
        db_session,
        trainer_id=pending_tid,
        plan_id=plan_id,
        status="active",
        days_ago_started=1,
        days_until_expires=29,
        modules={"online": True, "analytics": False, "groups": False},
    )
    after = await get_admin_engagement_stats(db_session)
    online_before = next(f for f in before["feature_usage"] if f["feature"] == "online")
    online_after = next(f for f in after["feature_usage"] if f["feature"] == "online")
    assert online_after["users"] == online_before["users"]
    assert after["trainers_active"] == before["trainers_active"]


async def _insert_confirmed_booking(session: AsyncSession, trainer_id: int, *, days_ago: int = 0) -> int:
    """Non-sandbox confirmed booking for ``trainer_id`` — for activation-funnel/proof-of-value deltas."""
    service_id = await require_seed_service_id(session)
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'Ana', 'Lytics', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    slot_date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).date()
    r = await session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '09:00', TIME '10:00', 'booked') RETURNING id
            """
        ),
        {"tid": trainer_id, "d": slot_date},
    )
    (slot_id,) = r.fetchone()
    r = await session.execute(
        text(
            """
            INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status)
            VALUES (:tid, :cid, :sid, :svc, 'confirmed') RETURNING id
            """
        ),
        {"tid": trainer_id, "cid": client_id, "sid": slot_id, "svc": service_id},
    )
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_activation_funnel_first_booking_counts_pending_profile_trainer(
    db_session: AsyncSession,
) -> None:
    """TASK-026 AC-005: activation funnel's has_first_booking must not require status='active'."""
    before = await get_admin_product_analytics(db_session)
    trainer_id = await _insert_trainer(db_session, status="pending_profile")
    await _insert_confirmed_booking(db_session, trainer_id)
    after = await get_admin_product_analytics(db_session)
    assert after["activation_funnel"]["has_first_booking"] == (
        before["activation_funnel"]["has_first_booking"] + 1
    )
    # The catalog-publication step is untouched by this — status stayed pending_profile.
    assert after["activation_funnel"]["activated"] == before["activation_funnel"]["activated"]


@pytest.mark.asyncio
async def test_activation_funnel_activated_still_requires_catalog_status(
    db_session: AsyncSession,
) -> None:
    """TASK-026 AC-005: `activated` (catalog publication) stays strictly status='active'."""
    before = await get_admin_product_analytics(db_session)
    await _insert_trainer(db_session, status="pending_profile")
    after_pending = await get_admin_product_analytics(db_session)
    assert after_pending["activation_funnel"]["activated"] == before["activation_funnel"]["activated"]

    await _insert_trainer(db_session, status="active")
    after_active = await get_admin_product_analytics(db_session)
    assert after_active["activation_funnel"]["activated"] == (
        after_pending["activation_funnel"]["activated"] + 1
    )


@pytest.mark.asyncio
async def test_proof_of_value_counts_pending_profile_trainer(db_session: AsyncSession) -> None:
    """TASK-026 AC-005: proof-of-value denominator/counters include working, unmoderated trainers."""
    before = await get_admin_product_analytics(db_session)
    trainer_id = await _insert_trainer(db_session, status="pending_profile")
    await _insert_confirmed_booking(db_session, trainer_id)
    after = await get_admin_product_analytics(db_session)
    assert after["proof_of_value"]["active_total"] == before["proof_of_value"]["active_total"] + 1
    assert after["proof_of_value"]["first_booking"] == before["proof_of_value"]["first_booking"] + 1


@pytest.mark.asyncio
async def test_engagement_active_trainer_count_excludes_deactivated(db_session: AsyncSession) -> None:
    before = await get_admin_engagement_stats(db_session)
    await _insert_trainer(db_session, status="active")
    await _insert_trainer(db_session, status="active")
    await _insert_trainer(db_session, status="deactivated")
    after = await get_admin_engagement_stats(db_session)
    # Only 'active' rows count toward trainers_active.
    assert after["trainers_active"] == before["trainers_active"] + 2


# ──────────────────────────────────────────────────────────────────────────
# Helper-function tests — pure logic, no DB round-trip.
# ──────────────────────────────────────────────────────────────────────────


def test_pct_helper_returns_none_for_zero_denominator() -> None:
    from src.application.admin_analytics_use_cases import _pct
    assert _pct(0, 0) is None
    assert _pct(5, None) is None
    assert _pct(50, 200) == 25.0


def test_mom_pct_helper_handles_zero_previous() -> None:
    from src.application.admin_analytics_use_cases import _mom_pct
    assert _mom_pct(10, 0) is None
    assert _mom_pct(0, 10) == -100.0
    assert _mom_pct(150, 100) == 50.0


def test_module_combo_label_and_key() -> None:
    from src.application.admin_analytics_use_cases import _module_combo_key, _module_combo_label
    assert _module_combo_label({}) == "CRM (только база)"
    assert _module_combo_label({"online": True, "groups": True, "analytics": False}) == "CRM + Онлайн-запись + Группы"
    # Ordering: online-groups-analytics, '0'/'1' bits.
    assert _module_combo_key({"online": True, "groups": False, "analytics": True}) == "1-0-1"
    assert _module_combo_key(None) == "0-0-0"


# ──────────────────────────────────────────────────────────────────────────
# TASK-028: hint funnel + feature adoption distribution
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hint_funnel_counts_shown_clicked_dismissed(db_session: AsyncSession) -> None:
    from src.application.platform_audit_use_cases import insert_platform_audit_from_record

    tid = await _insert_trainer(db_session)
    before = await get_admin_product_analytics(db_session)
    before_row = next((r for r in before["hint_funnel"] if r["item_id"] == "share_link"), None)
    before_shown = before_row["shown"] if before_row else 0
    before_clicked = before_row["clicked"] if before_row else 0
    before_dismissed = before_row["dismissed"] if before_row else 0

    for event in (
        "trainer.hub.inbox_item_shown",
        "trainer.hub.inbox_item_shown",
        "trainer.hub.hint_clicked",
        "trainer.hub.hint_dismissed",
    ):
        await insert_platform_audit_from_record(
            db_session,
            {
                "event": event,
                "actor_type": "api",
                "actor_id": str(tid),
                "payload": {"trainer_id": tid, "item_id": "share_link"},
            },
        )
    await db_session.commit()

    after = await get_admin_product_analytics(db_session)
    after_row = next(r for r in after["hint_funnel"] if r["item_id"] == "share_link")
    assert after_row["shown"] == before_shown + 2
    assert after_row["clicked"] == before_clicked + 1
    assert after_row["dismissed"] == before_dismissed + 1


@pytest.mark.asyncio
async def test_feature_adoption_counts_trainer_at_day7_and_day14(db_session: AsyncSession) -> None:
    from src.application.trainer_feature_tracking import (
        FEATURE_CLIENT_NOTE_WRITTEN,
        FEATURE_PASS_ISSUED,
        record_feature_first_use,
    )

    # Created 20 days ago — eligible for both the day7 and day14 marks.
    tid = await _insert_trainer(db_session, created_offset_days=20)
    await record_feature_first_use(db_session, tid, FEATURE_PASS_ISSUED)
    await record_feature_first_use(db_session, tid, FEATURE_CLIENT_NOTE_WRITTEN)
    await db_session.commit()
    # Backdate first_used_at so both claims land within the trainer's first 14 days.
    await db_session.execute(
        text(
            """
            UPDATE trainer_feature_first_use
            SET first_used_at = (SELECT created_at FROM trainers WHERE id = :tid) + INTERVAL '3 days'
            WHERE trainer_id = :tid
            """
        ),
        {"tid": tid},
    )
    await db_session.commit()

    data = await get_admin_product_analytics(db_session)
    adoption = data["feature_adoption"]
    assert adoption["total_features"] == 11
    day14_bucket = {row["features_touched"]: row["trainers"] for row in adoption["day14"]}
    assert day14_bucket.get(2, 0) >= 1
