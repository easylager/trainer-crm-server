"""
E2E-style API tests for POST /api/webapp/trainer/subscription-stub-confirm.

Covers the production rule: when payment_sandbox is false, stub-confirm is allowed only for
invoices with amount_cents == 0 and referral_bonus_days_applied > 0 (referral fully covers due).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.infrastructure.db.models import INVOICE_STATUS_SENT, REFERRAL_CREDIT_REASON_ADMIN
from src.shared.config import Settings


@pytest.fixture
async def require_trainer_invoice_referral_columns(db_session: AsyncSession) -> None:
    """trainer_invoices.referral_* from migration 0121_trainer_invoice_referral."""
    r = await db_session.execute(
        text(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'trainer_invoices'
              AND column_name = 'referral_bonus_days_applied'
            LIMIT 1
            """
        )
    )
    if r.fetchone() is None:
        pytest.skip("need alembic migration 0121 (trainer_invoices referral discount columns)")


def _fresh_trainer_telegram_id() -> int:
    return 5_100_000_000 + (uuid.uuid4().int % 3_000_000_000)


async def _insert_subscription_plan(session: AsyncSession) -> int:
    r = await session.execute(
        text(
            """
            INSERT INTO subscription_plans (name, price_cents, period_days, is_trial, sort_order)
            VALUES ('StubConfirmTestPlan', 9900, 30, false, 0)
            RETURNING id
            """
        )
    )
    return int(r.scalar_one())


async def _grant_referral_days(session: AsyncSession, trainer_id: int, days: int) -> None:
    now = datetime.now(timezone.utc)
    await session.execute(
        text(
            """
            INSERT INTO trainer_referral_credits (trainer_id, amount_days, reason, created_at)
            VALUES (:tid, :days, :reason, :now)
            """
        ),
        {"tid": trainer_id, "days": days, "reason": REFERRAL_CREDIT_REASON_ADMIN, "now": now},
    )


async def _insert_pending_zero_referral_invoice(
    session: AsyncSession,
    *,
    trainer_id: int,
    plan_id: int,
    bonus_days: int,
    list_price_cents: int,
) -> int:
    now = datetime.now(timezone.utc)
    r = await session.execute(
        text(
            """
            INSERT INTO trainer_invoices (
                trainer_id, subscription_plan_id, amount_cents,
                period_start, period_end, due_date, status,
                referral_bonus_days_applied, amount_cents_before_referral
            )
            VALUES (
                :tid, :pid, 0,
                :ps, :pe, :dd, :st,
                :bonus, :before
            )
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "ps": now - timedelta(days=1),
            "pe": now + timedelta(days=29),
            "dd": now + timedelta(days=5),
            "st": INVOICE_STATUS_SENT,
            "bonus": bonus_days,
            "before": list_price_cents,
        },
    )
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_subscription_stub_confirm_zero_amount_referral_production_ok(
    app_use_test_db,
    db_session: AsyncSession,
    require_trainer_invoice_referral_columns,
) -> None:
    """payment_sandbox=false: zero-amount invoice with bonus days confirms and redeems credit."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Stub", "last_name": "Confirm", "age": 30}},
        )
        assert create_resp.status_code == 200, create_resp.text
        trainer_id = int(create_resp.json()["id"])

    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    plan_id = await _insert_subscription_plan(db_session)
    await _grant_referral_days(db_session, trainer_id, 30)
    bonus = 30
    invoice_id = await _insert_pending_zero_referral_invoice(
        db_session,
        trainer_id=trainer_id,
        plan_id=plan_id,
        bonus_days=bonus,
        list_price_cents=9900,
    )
    await db_session.commit()

    real_settings = Settings()
    mock_settings_inst = MagicMock()
    mock_settings_inst.payment_sandbox = False
    mock_settings_inst.telegram_bot_token_trainer = real_settings.telegram_bot_token_trainer

    with (
        patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)),
        patch("src.api.routes.webapp.Settings", return_value=mock_settings_inst),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/subscription-stub-confirm",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"invoice_id": invoice_id},
            )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"success": True}

    r_inv = await db_session.execute(
        text("SELECT status, amount_cents FROM trainer_invoices WHERE id = :iid"),
        {"iid": invoice_id},
    )
    row_inv = r_inv.fetchone()
    assert row_inv is not None
    assert row_inv[0] == "paid"
    assert int(row_inv[1]) == 0

    r_sub = await db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM trainer_subscriptions
            WHERE trainer_id = :tid AND status = 'active'
            """
        ),
        {"tid": trainer_id},
    )
    assert int(r_sub.scalar() or 0) >= 1

    r_bal = await db_session.execute(
        text("SELECT COALESCE(SUM(amount_days), 0) FROM trainer_referral_credits WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    assert int(r_bal.scalar() or 0) == 0


@pytest.mark.asyncio
async def test_subscription_stub_confirm_production_rejects_nonzero_amount(
    app_use_test_db,
    db_session: AsyncSession,
    require_trainer_invoice_referral_columns,
) -> None:
    """payment_sandbox=false: invoice with amount due cannot be confirmed via stub."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Pay", "last_name": "Wall", "age": 28}},
        )
        assert create_resp.status_code == 200
        trainer_id = int(create_resp.json()["id"])

    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    plan_id = await _insert_subscription_plan(db_session)
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainer_invoices (
                trainer_id, subscription_plan_id, amount_cents,
                period_start, period_end, due_date, status,
                referral_bonus_days_applied, amount_cents_before_referral
            )
            VALUES (
                :tid, :pid, 1000,
                :ps, :pe, :dd, :st,
                5, 5000
            )
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "ps": now - timedelta(days=1),
            "pe": now + timedelta(days=29),
            "dd": now + timedelta(days=5),
            "st": INVOICE_STATUS_SENT,
        },
    )
    invoice_id = int(r.scalar_one())
    await db_session.commit()

    real_settings = Settings()
    mock_settings_inst = MagicMock()
    mock_settings_inst.payment_sandbox = False
    mock_settings_inst.telegram_bot_token_trainer = real_settings.telegram_bot_token_trainer

    with (
        patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)),
        patch("src.api.routes.webapp.Settings", return_value=mock_settings_inst),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/subscription-stub-confirm",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"invoice_id": invoice_id},
            )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Not available when payment_sandbox is false"


@pytest.mark.asyncio
async def test_subscription_stub_confirm_production_rejects_zero_without_bonus(
    app_use_test_db,
    db_session: AsyncSession,
    require_trainer_invoice_referral_columns,
) -> None:
    """payment_sandbox=false: amount 0 with no referral bonus is not stub-confirmable."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Zero", "last_name": "NoBonus", "age": 27}},
        )
        assert create_resp.status_code == 200
        trainer_id = int(create_resp.json()["id"])

    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    plan_id = await _insert_subscription_plan(db_session)
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainer_invoices (
                trainer_id, subscription_plan_id, amount_cents,
                period_start, period_end, due_date, status,
                referral_bonus_days_applied
            )
            VALUES (
                :tid, :pid, 0,
                :ps, :pe, :dd, :st,
                0
            )
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "ps": now - timedelta(days=1),
            "pe": now + timedelta(days=29),
            "dd": now + timedelta(days=5),
            "st": INVOICE_STATUS_SENT,
        },
    )
    invoice_id = int(r.scalar_one())
    await db_session.commit()

    real_settings = Settings()
    mock_settings_inst = MagicMock()
    mock_settings_inst.payment_sandbox = False
    mock_settings_inst.telegram_bot_token_trainer = real_settings.telegram_bot_token_trainer

    with (
        patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=tg)),
        patch("src.api.routes.webapp.Settings", return_value=mock_settings_inst),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/subscription-stub-confirm",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"invoice_id": invoice_id},
            )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Not available when payment_sandbox is false"
