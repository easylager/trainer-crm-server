"""
Tests for the 'add modules to current paid subscription' admin flow
(subscription_use_cases.admin_merge_modules_into_current_subscription +
compute_prorated_module_addon_cost_cents). These protect customer value so a
trainer who already paid for CRM/year doesn't wait until year-end to get newly
purchased modules.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.subscription_use_cases import (
    admin_merge_modules_into_current_subscription,
    compute_prorated_module_addon_cost_cents,
    get_active_paid_subscription_for_merge,
)


def _mods(online: bool = False, analytics: bool = False, groups: bool = False) -> dict:
    return {"online": online, "analytics": analytics, "groups": groups}


class TestComputeProratedModuleAddonCostCents:
    """Pro-ration math: monthly module price * (remaining_days / 30)."""

    @pytest.mark.asyncio
    async def test_no_remaining_days_is_zero(self) -> None:
        session = AsyncMock()
        assert await compute_prorated_module_addon_cost_cents(session, ["groups"], 0) == 0

    @pytest.mark.asyncio
    async def test_no_modules_is_zero(self) -> None:
        session = AsyncMock()
        assert await compute_prorated_module_addon_cost_cents(session, [], 30) == 0

    @pytest.mark.asyncio
    async def test_full_month_charges_full_monthly_price(self) -> None:
        session = AsyncMock()
        with patch(
            "src.application.subscription_use_cases.get_module_period_pricing",
            new=AsyncMock(return_value={"price_cents": 900, "period_days": 30}),
        ):
            cost = await compute_prorated_module_addon_cost_cents(session, ["groups"], 30)
        assert cost == 900

    @pytest.mark.asyncio
    async def test_half_month_charges_half_price(self) -> None:
        session = AsyncMock()
        with patch(
            "src.application.subscription_use_cases.get_module_period_pricing",
            new=AsyncMock(return_value={"price_cents": 900, "period_days": 30}),
        ):
            cost = await compute_prorated_module_addon_cost_cents(session, ["groups"], 15)
        assert cost == 450  # 900 * 15/30

    @pytest.mark.asyncio
    async def test_multiple_modules_accumulate(self) -> None:
        session = AsyncMock()
        with patch(
            "src.application.subscription_use_cases.get_module_period_pricing",
            new=AsyncMock(return_value={"price_cents": 600, "period_days": 30}),
        ):
            cost = await compute_prorated_module_addon_cost_cents(
                session, ["groups", "analytics"], 30
            )
        assert cost == 1200  # two modules at full monthly price

    @pytest.mark.asyncio
    async def test_missing_pricing_returns_none(self) -> None:
        session = AsyncMock()
        with patch(
            "src.application.subscription_use_cases.get_module_period_pricing",
            new=AsyncMock(return_value=None),
        ):
            cost = await compute_prorated_module_addon_cost_cents(session, ["groups"], 30)
        assert cost is None


class TestGetActivePaidSubscriptionForMerge:
    """Surface the trainer's currently-active non-trial row so admin UI can offer merge."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_row(self) -> None:
        session = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = None
        session.execute.return_value = result

        assert await get_active_paid_subscription_for_merge(session, trainer_id=1) is None

    @pytest.mark.asyncio
    async def test_returns_row_with_remaining_days(self) -> None:
        session = AsyncMock()
        now = datetime.now(timezone.utc)
        started = now - timedelta(days=300)
        expires = now + timedelta(days=60)
        result = MagicMock()
        result.fetchone.return_value = (777, "crm", _mods(online=True), started, expires, 12)
        session.execute.return_value = result

        row = await get_active_paid_subscription_for_merge(session, trainer_id=1)
        assert row is not None
        assert row["subscription_id"] == 777
        assert row["tier"] == "crm"
        assert row["modules"]["online"] is True
        assert row["billing_period_months"] == 12
        # ~60 days remaining (allow 59/60 slack for boundary rounding).
        assert 59 <= row["remaining_days"] <= 60


class TestAdminMergeModulesIntoCurrentSubscription:
    """End-to-end logic for the merge flow (trainer has year of CRM, wants +groups now)."""

    @pytest.mark.asyncio
    async def test_noop_when_invoice_not_pending(self) -> None:
        session = AsyncMock()
        r = MagicMock()
        r.fetchone.return_value = (42, "paid")  # already paid
        session.execute.return_value = r

        out = await admin_merge_modules_into_current_subscription(
            session, invoice_id=1, add_modules=_mods(groups=True), admin_id=999
        )
        assert out is None

    @pytest.mark.asyncio
    async def test_noop_when_no_active_paid_subscription(self) -> None:
        """
        Admin tries merge for a trainer who only has a trial — nothing to merge into.
        """
        session = AsyncMock()
        # Invoice lookup returns sent invoice; merge target query returns no paid row.
        session.execute.side_effect = [
            MagicMock(**{"fetchone.return_value": (42, "sent")}),       # invoice row
            MagicMock(**{"fetchone.return_value": None}),               # no active paid
        ]

        out = await admin_merge_modules_into_current_subscription(
            session, invoice_id=1, add_modules=_mods(groups=True), admin_id=999
        )
        assert out is None

    @pytest.mark.asyncio
    async def test_all_requested_modules_already_active_is_idempotent(self) -> None:
        """
        If admin tries to add modules that are already on the current subscription,
        we don't charge or change anything — return a success marker so UX is friendly.
        """
        session = AsyncMock()
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=60)
        session.execute.side_effect = [
            MagicMock(**{"fetchone.return_value": (42, "sent")}),
            MagicMock(**{"fetchone.return_value": (
                777, "crm", _mods(groups=True), now - timedelta(days=10), expires, 3,
            )}),
        ]

        out = await admin_merge_modules_into_current_subscription(
            session, invoice_id=1, add_modules=_mods(groups=True), admin_id=999
        )
        assert out is not None
        assert out["amount_cents"] == 0
        assert out["merged"] is True
        assert out["modules"]["groups"] is True

    @pytest.mark.asyncio
    async def test_merge_adds_modules_prorated(self) -> None:
        """
        Happy path: trainer has CRM-only year, admin adds groups. Current expires_at
        is preserved, modules are union'ed, invoice is rewritten to describe the delta.
        """
        session = AsyncMock()
        now = datetime.now(timezone.utc)
        started = now - timedelta(days=300)
        expires = now + timedelta(days=60)
        session.execute.side_effect = [
            MagicMock(**{"fetchone.return_value": (42, "sent")}),            # invoice lookup
            MagicMock(**{"fetchone.return_value": (
                777, "crm", _mods(), started, expires, 12,
            )}),                                                             # active paid
            MagicMock(),                                                     # UPDATE subs
            MagicMock(),                                                     # UPDATE invoice
        ]
        session.commit = AsyncMock()

        with patch(
            "src.application.subscription_use_cases.get_module_period_pricing",
            new=AsyncMock(return_value={"price_cents": 900, "period_days": 30}),
        ):
            out = await admin_merge_modules_into_current_subscription(
                session, invoice_id=1, add_modules=_mods(groups=True), admin_id=999
            )

        assert out is not None
        assert out["trainer_id"] == 42
        assert out["merged"] is True
        assert out["modules"]["groups"] is True
        assert out["added_modules"] == ["groups"]
        assert out["period_end"] == expires
        # ~60 days at 900 cents/30 days = ~1800 cents (allow off-by-one for boundary).
        assert 1770 <= out["amount_cents"] <= 1800
        assert out["period_months"] == 0
        session.commit.assert_awaited()
