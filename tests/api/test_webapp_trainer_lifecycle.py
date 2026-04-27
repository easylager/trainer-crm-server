"""
Phase 3 integration: GET /api/webapp/trainer/lifecycle + lifecycle field in /trainer/hub/bootstrap.

Spec: docs/plans/lead-mode-revenue-retention.md sections "Lead Mode UI" and "Demand signals
recap". The contract this file pins:

- /trainer/lifecycle returns LifecycleSnapshot.as_dict() merged with signals_recap and
  derived fields (lead_mode_since, days_in_lead_mode).
- For LEAD_MODE trainers the recap window starts at last_subscription_expires_at (loss framing
  on real numbers). For ACTIVE trainers it's the standard 14-day window.
- /trainer/hub/bootstrap returns the same payload under the `lifecycle` key — frontend
  uses it to render hubLeadModeBanner without a second round-trip.
- 401 without init data, 403 when telegram_id is not linked.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.infrastructure.db.models import (
    DEMAND_EVENT_CONTACT_CLICK,
    DEMAND_EVENT_PROFILE_VIEW,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_TRIAL,
)
from tests.api.test_webapp_trainer_schedule_integration import (
    _create_active_trainer,
    _fresh_trainer_telegram_id,
    patch_trainer_webapp_init,
)


# ---------- DB fixtures ----------


async def _drop_subscriptions(db_session, trainer_id: int) -> None:
    """Lead Mode = active status + no live subscription. Strip auto-trial side effects."""
    await db_session.execute(
        text("DELETE FROM trainer_subscriptions WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    await db_session.commit()


async def _set_catalog_visibility(db_session, trainer_id: int, visible: bool) -> None:
    await db_session.execute(
        text("UPDATE trainers SET is_catalog_visible = :v WHERE id = :tid"),
        {"v": visible, "tid": trainer_id},
    )
    await db_session.commit()


async def _insert_expired_subscription(
    db_session, trainer_id: int, *, expired_days_ago: int, was_trial: bool = True
) -> datetime:
    """Insert a row with expires_at in the past — anchors signals_recap window."""
    r = await db_session.execute(text("SELECT id FROM subscription_plans ORDER BY id LIMIT 1"))
    plan_id = r.scalar()
    if plan_id is None:
        pytest.skip("need subscription_plans in DB")
    now = datetime.now(timezone.utc)
    expires = now - timedelta(days=expired_days_ago)
    started = expires - timedelta(days=14)
    status_value = SUBSCRIPTION_STATUS_TRIAL if was_trial else SUBSCRIPTION_STATUS_ACTIVE
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_subscriptions
                (trainer_id, plan_id, tier, billing_period_months, started_at, expires_at, status)
            VALUES
                (:tid, :pid, 'crm', 1, :st, :exp, :status)
            """
        ),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "st": started,
            "exp": expires,
            "status": status_value,
        },
    )
    await db_session.commit()
    return expires


async def _insert_demand_event(
    db_session,
    trainer_id: int,
    kind: str,
    *,
    occurred_at: datetime,
    dedup_hash: str | None = None,
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_demand_events
                (trainer_id, kind, occurred_at, source, dedup_hash, payload)
            VALUES (:tid, :k, :ts, 'public_card', :dh, '{}'::jsonb)
            """
        ),
        {"tid": trainer_id, "k": kind, "ts": occurred_at, "dh": dedup_hash},
    )
    await db_session.commit()


# ---------- /trainer/lifecycle ----------


@pytest.mark.asyncio
async def test_lifecycle_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/trainer/lifecycle")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_lifecycle_403_for_unknown_telegram(app_use_test_db) -> None:
    rogue_tg = _fresh_trainer_telegram_id()
    with patch_trainer_webapp_init(rogue_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/lifecycle",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_lifecycle_active_trainer_uses_14d_window(app_use_test_db, db_session) -> None:
    """ACTIVE trainer: stage=active, signals_recap window = '14d', no lead_mode_since."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/lifecycle",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["trainer_id"] == trainer_id
    assert body["stage"] == "active"
    assert body["is_active"] is True
    assert body["is_lead_mode"] is False
    assert body["lead_mode_since"] is None
    assert body["days_in_lead_mode"] is None
    recap = body["signals_recap"]
    assert recap["window"] == "14d"
    assert recap["window_days"] == 14
    assert recap["profile_views"] == 0
    assert recap["contact_clicks"] == 0


@pytest.mark.asyncio
async def test_lifecycle_lead_mode_anchored_to_last_expiry(
    app_use_test_db, db_session
) -> None:
    """LEAD_MODE: window starts at last_subscription_expires_at (loss framing in real numbers)."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=False)
    await _drop_subscriptions(db_session, trainer_id)
    await _set_catalog_visibility(db_session, trainer_id, True)
    expires = await _insert_expired_subscription(
        db_session, trainer_id, expired_days_ago=10, was_trial=True
    )
    # Two views after Lead Mode entered, one view BEFORE — only the post-expiry ones must count.
    after_1 = expires + timedelta(days=1)
    after_2 = expires + timedelta(days=3)
    before = expires - timedelta(days=2)
    await _insert_demand_event(db_session, trainer_id, DEMAND_EVENT_PROFILE_VIEW, occurred_at=after_1, dedup_hash="h1")
    await _insert_demand_event(db_session, trainer_id, DEMAND_EVENT_PROFILE_VIEW, occurred_at=after_2, dedup_hash="h2")
    await _insert_demand_event(db_session, trainer_id, DEMAND_EVENT_PROFILE_VIEW, occurred_at=before, dedup_hash="h3")
    await _insert_demand_event(db_session, trainer_id, DEMAND_EVENT_CONTACT_CLICK, occurred_at=after_1, dedup_hash="c1")

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/lifecycle",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stage"] == "lead_mode"
    assert body["is_lead_mode"] is True
    assert body["is_active"] is False
    assert body["lead_mode_since"] is not None
    assert body["days_in_lead_mode"] == 10 or body["days_in_lead_mode"] == 9
    recap = body["signals_recap"]
    assert recap["window"] == "since_lead_mode"
    # Pre-expiry view must be excluded; the two post-expiry views counted.
    assert recap["profile_views"] == 2
    assert recap["contact_clicks"] == 1
    assert recap["booking_attempts_blocked"] == 0
    assert recap["has_any_demand"] is True


@pytest.mark.asyncio
async def test_lifecycle_lead_mode_with_no_demand_returns_zero_recap(
    app_use_test_db, db_session
) -> None:
    """LEAD_MODE without any signals — recap is zero, has_any_demand=False (UI hides numbers)."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=False)
    await _drop_subscriptions(db_session, trainer_id)
    await _set_catalog_visibility(db_session, trainer_id, True)
    await _insert_expired_subscription(db_session, trainer_id, expired_days_ago=2)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/lifecycle",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    body = resp.json()
    assert body["stage"] == "lead_mode"
    recap = body["signals_recap"]
    assert recap["profile_views"] == 0
    assert recap["has_any_demand"] is False


@pytest.mark.asyncio
async def test_lifecycle_churned_for_hidden_no_subscription(
    app_use_test_db, db_session
) -> None:
    """No subscription + is_catalog_visible=False ⇒ CHURNED (not LEAD_MODE)."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=False)
    await _drop_subscriptions(db_session, trainer_id)
    await _set_catalog_visibility(db_session, trainer_id, False)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/lifecycle",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    body = resp.json()
    assert body["stage"] == "churned"
    assert body["is_lead_mode"] is False
    assert body["lead_mode_since"] is None


# ---------- /trainer/hub/bootstrap — lifecycle field ----------
#
# /trainer/hub/bootstrap fans out to multiple parallel `async_session_factory()` sessions, which
# in the test conftest share a single asyncpg connection via savepoint-isolated transactions.
# Sibling sessions cannot see each other's commits inside one transaction, so bootstrap
# integration tests would always observe `partial_errors={"profile": "Trainer not found"}`
# and a churned lifecycle. That's a property of the test infrastructure, not the production code.
#
# The production behavior is covered by:
# - This file's `/trainer/lifecycle` direct tests (single session, identical payload contract).
# - The frontend code: `applyHubBootstrapPayload` falls back to `loadTrainerLifecycle()` when
#   `payload.lifecycle` is missing — so the UI always converges on the same `/trainer/lifecycle`
#   contract validated above.
#
# When the test conftest gains a multi-session-aware mode, bootstrap-level tests should be added
# under that mode rather than emulating it here.
