"""Tests for subscription tier use cases: hierarchy, effective tier, mock checkout."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from src.application.subscription_tier_use_cases import (
    tier_satisfies,
    tier_includes,
    get_effective_subscription_tier,
    get_subscription_tier_catalog,
    get_trainer_subscription_status,
    set_subscription_after_mock_payment,
)
from src.infrastructure.db.models import (
    SUBSCRIPTION_TIER_NONE,
    SUBSCRIPTION_TIER_CRM,
    SUBSCRIPTION_TIER_ONLINE,
    SUBSCRIPTION_TIER_ANALYTICS,
)


def _mods(online: bool = False, analytics: bool = False, groups: bool = False) -> dict:
    return {"online": online, "analytics": analytics, "groups": groups}


# --- Pure function tests (no DB) ---


class TestTierSatisfies:
    """Matrix tests for tier_satisfies on synthetic effective tier levels."""

    @pytest.mark.parametrize(
        "current,required,expected",
        [
            (SUBSCRIPTION_TIER_NONE, SUBSCRIPTION_TIER_NONE, True),
            (SUBSCRIPTION_TIER_NONE, SUBSCRIPTION_TIER_CRM, False),
            (SUBSCRIPTION_TIER_NONE, SUBSCRIPTION_TIER_ONLINE, False),
            (SUBSCRIPTION_TIER_NONE, SUBSCRIPTION_TIER_ANALYTICS, False),
            (SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_NONE, True),
            (SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_CRM, True),
            (SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE, False),
            (SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ANALYTICS, False),
            (SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_NONE, True),
            (SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_CRM, True),
            (SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_ONLINE, True),
            (SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_ANALYTICS, False),
            (SUBSCRIPTION_TIER_ANALYTICS, SUBSCRIPTION_TIER_NONE, True),
            (SUBSCRIPTION_TIER_ANALYTICS, SUBSCRIPTION_TIER_CRM, True),
            (SUBSCRIPTION_TIER_ANALYTICS, SUBSCRIPTION_TIER_ONLINE, True),
            (SUBSCRIPTION_TIER_ANALYTICS, SUBSCRIPTION_TIER_ANALYTICS, True),
        ],
    )
    def test_tier_hierarchy_matrix(self, current: str, required: str, expected: bool) -> None:
        assert tier_satisfies(current, required) == expected

    def test_unknown_tier_treated_as_none(self) -> None:
        assert tier_satisfies("unknown", SUBSCRIPTION_TIER_CRM) is False
        assert tier_satisfies(SUBSCRIPTION_TIER_CRM, "unknown") is True


class TestTierIncludes:
    """Tests for tier_includes: what features are unlocked at each synthetic tier."""

    def test_none_includes_nothing(self) -> None:
        assert tier_includes(SUBSCRIPTION_TIER_NONE) == []

    def test_crm_includes_only_crm(self) -> None:
        result = tier_includes(SUBSCRIPTION_TIER_CRM)
        assert result == [SUBSCRIPTION_TIER_CRM]

    def test_online_includes_crm_and_online(self) -> None:
        result = tier_includes(SUBSCRIPTION_TIER_ONLINE)
        assert SUBSCRIPTION_TIER_CRM in result
        assert SUBSCRIPTION_TIER_ONLINE in result
        assert SUBSCRIPTION_TIER_ANALYTICS not in result

    def test_analytics_includes_all(self) -> None:
        result = tier_includes(SUBSCRIPTION_TIER_ANALYTICS)
        assert SUBSCRIPTION_TIER_CRM in result
        assert SUBSCRIPTION_TIER_ONLINE in result
        assert SUBSCRIPTION_TIER_ANALYTICS in result


# --- Async DB tests (with mocked session) ---


def _ent_rows(rows: list[tuple] | None) -> MagicMock:
    """Mock fetchall result for get_trainer_entitlements (returns rows of (tier, modules))."""
    m = MagicMock()
    m.fetchall.return_value = rows or []
    return m


def _current_rows(rows: list[tuple] | None) -> MagicMock:
    """Mock fetchall for the 'currently-active rows' query in get_trainer_subscription_status."""
    m = MagicMock()
    m.fetchall.return_value = rows or []
    return m


def _next_row(row: tuple | None) -> MagicMock:
    """Mock fetchone for the 'queued next plan' query."""
    m = MagicMock()
    m.fetchone.return_value = row
    return m


class TestGetEffectiveSubscriptionTier:
    """get_effective_subscription_tier: synthetic tier from CRM row + modules (union across overlapping rows)."""

    @pytest.mark.asyncio
    async def test_no_subscription_returns_none(self) -> None:
        mock_session = AsyncMock()
        mock_session.execute.return_value = _ent_rows([])

        tier = await get_effective_subscription_tier(mock_session, trainer_id=1)
        assert tier == SUBSCRIPTION_TIER_NONE

    @pytest.mark.asyncio
    async def test_online_module_returns_online_effective(self) -> None:
        mock_session = AsyncMock()
        mock_session.execute.return_value = _ent_rows([(SUBSCRIPTION_TIER_CRM, _mods(online=True))])

        tier = await get_effective_subscription_tier(mock_session, trainer_id=1)
        assert tier == SUBSCRIPTION_TIER_ONLINE

    @pytest.mark.asyncio
    async def test_legacy_online_tier_row_infer_modules(self) -> None:
        """Old tier column without JSON modules still maps to online."""
        mock_session = AsyncMock()
        mock_session.execute.return_value = _ent_rows([(SUBSCRIPTION_TIER_ONLINE, _mods())])

        tier = await get_effective_subscription_tier(mock_session, trainer_id=1)
        assert tier == SUBSCRIPTION_TIER_ONLINE

    @pytest.mark.asyncio
    async def test_overlapping_trial_and_paid_unions_modules(self) -> None:
        """
        Regression: when a trial row (full modules) overlaps with a queued but started
        paid row (CRM only), entitlements must reflect the union — never downgrade.
        """
        mock_session = AsyncMock()
        mock_session.execute.return_value = _ent_rows([
            (SUBSCRIPTION_TIER_CRM, _mods(online=True, analytics=True, groups=True)),
            (SUBSCRIPTION_TIER_CRM, _mods()),
        ])

        tier = await get_effective_subscription_tier(mock_session, trainer_id=1)
        assert tier == SUBSCRIPTION_TIER_ANALYTICS


class TestGetTrainerSubscriptionStatus:
    """get_trainer_subscription_status: 2 entitlement reads + current rows + next row."""

    @pytest.mark.asyncio
    async def test_inactive_subscription_status(self) -> None:
        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            _ent_rows([]),             # get_effective_subscription_tier → entitlements
            _ent_rows([]),             # entitlements (union) inside status
            _current_rows([]),         # rows covering now
            _next_row(None),           # queued next plan
        ]

        status = await get_trainer_subscription_status(mock_session, trainer_id=1)

        assert status["is_active"] is False
        assert status["tier"] == SUBSCRIPTION_TIER_NONE
        assert status["effective_tier"] == SUBSCRIPTION_TIER_NONE
        assert status["unlocked_features"] == []
        assert status["next_plan"] is None

    @pytest.mark.asyncio
    async def test_active_subscription_status(self) -> None:
        mock_session = AsyncMock()

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=30)
        started_at = now - timedelta(days=5)
        mods = _mods(online=True)
        ent_rows_data = [(SUBSCRIPTION_TIER_CRM, mods)]
        current_rows_data = [(
            123, SUBSCRIPTION_TIER_CRM, mods, expires_at, "active", started_at, 1,
        )]
        mock_session.execute.side_effect = [
            _ent_rows(ent_rows_data),     # effective tier
            _ent_rows(ent_rows_data),     # entitlements (union)
            _current_rows(current_rows_data),
            _next_row(None),
        ]

        status = await get_trainer_subscription_status(mock_session, trainer_id=1)

        assert status["is_active"] is True
        assert status["is_trial"] is False
        # Label comes from the composed helper, not a DB lookup.
        assert status["tier_name_ru"] == "CRM + Онлайн-запись"
        assert status["tier"] == SUBSCRIPTION_TIER_CRM
        assert status["effective_tier"] == SUBSCRIPTION_TIER_ONLINE
        assert status["billing_period_months"] == 1
        assert status["unlocked_features"] == ["crm", "online"]
        assert status["modules"]["online"] is True
        assert status["next_plan"] is None

    @pytest.mark.asyncio
    async def test_trial_overlap_no_downgrade_and_reports_next_plan(self) -> None:
        """
        Key regression: admin activated a CRM-only paid plan 1 day before trial ends.
        Until trial expires the trainer must keep full access AND see the queued plan.
        """
        mock_session = AsyncMock()
        now = datetime.now(timezone.utc)
        trial_started = now - timedelta(days=20)
        trial_expires = now + timedelta(days=1)
        paid_started = trial_expires
        paid_expires = trial_expires + timedelta(days=365)
        full_mods = _mods(online=True, analytics=True, groups=True)
        crm_only = _mods()

        ent_rows_data = [
            (SUBSCRIPTION_TIER_CRM, full_mods),  # trial row covers now
        ]
        current_rows_data = [
            (111, SUBSCRIPTION_TIER_CRM, full_mods, trial_expires, "trial", trial_started, None),
        ]
        next_row_data = (
            222, SUBSCRIPTION_TIER_CRM, crm_only, paid_expires, "active", paid_started, 12,
        )
        infer_result = MagicMock()
        infer_result.fetchone.return_value = None  # trial length doesn't match any billing period
        mock_session.execute.side_effect = [
            _ent_rows(ent_rows_data),
            _ent_rows(ent_rows_data),
            _current_rows(current_rows_data),
            _next_row(next_row_data),
            infer_result,  # _infer_billing_period_months for the trial row
        ]

        status = await get_trainer_subscription_status(mock_session, trainer_id=1)

        # Currently active window = trial with full access.
        assert status["is_trial"] is True
        assert status["tier_name_ru"] == "Полный доступ"
        assert status["unlocked_features"] == ["crm", "online", "analytics", "groups"]
        # Next plan surfaced for UI so trainer/admin see what kicks in after trial.
        assert status["next_plan"] is not None
        assert status["next_plan"]["tier_name_ru"] == "CRM"
        assert status["next_plan"]["billing_period_months"] == 12


class TestExpiredSubscription:
    """Expired subscription behavior."""

    @pytest.mark.asyncio
    async def test_expired_subscription_returns_none_tier(self) -> None:
        mock_session = AsyncMock()
        mock_session.execute.return_value = _ent_rows([])

        tier = await get_effective_subscription_tier(mock_session, trainer_id=1)
        assert tier == SUBSCRIPTION_TIER_NONE


class TestMockCheckout:
    """set_subscription_after_mock_payment maps legacy tier → constructor (CRM + modules)."""

    @pytest.mark.asyncio
    async def test_invalid_tier_returns_none(self) -> None:
        mock_session = AsyncMock()

        result = await set_subscription_after_mock_payment(
            mock_session, trainer_id=1, tier="invalid_tier", period_months=1
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_online_tier_creates_subscription(self) -> None:
        mock_session = AsyncMock()

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=30)

        mock_base_pricing = MagicMock()
        mock_base_pricing.fetchone.return_value = (
            2000,
            "BYN",
            30,
            "База CRM",
        )
        mock_online_pricing = MagicMock()
        mock_online_pricing.fetchone.return_value = (
            1500,
            30,
            "BYN",
            "Онлайн-запись",
        )

        mock_active_result = MagicMock()
        mock_active_result.fetchone.return_value = None

        mock_plan_result = MagicMock()
        mock_plan_result.fetchone.return_value = (1,)

        mock_insert_result = MagicMock()
        mock_insert_result.fetchone.return_value = (
            999,
            now,
            expires_at,
        )

        # TASK-044: set_subscription_constructor_after_mock_payment now resolves the
        # trainer's price_group (city → cities.country/price_group) before pricing lookups.
        # No profile row in this mock → resolver falls back to BY/BY_BASE (today's default).
        mock_price_group_result = MagicMock()
        mock_price_group_result.fetchone.return_value = None

        mock_session.execute.side_effect = [
            mock_price_group_result,
            mock_base_pricing,
            mock_online_pricing,
            mock_active_result,
            mock_plan_result,
            mock_insert_result,
        ]

        result = await set_subscription_after_mock_payment(
            mock_session, trainer_id=1, tier=SUBSCRIPTION_TIER_ONLINE, period_months=1
        )

        assert result is not None
        assert result["tier"] == SUBSCRIPTION_TIER_CRM
        assert result["modules"]["online"] is True
        assert result["subscription_id"] == 999
        assert result["price_cents"] == 3500
        assert result["currency"] == "BYN"
        assert result["period_days"] == 30
        assert result["period_months"] == 1
        mock_session.commit.assert_called_once()


class TestTierCatalog:
    """get_subscription_tier_catalog builds legacy cards from constructor pricing."""

    @pytest.mark.asyncio
    async def test_catalog_returns_all_active_tiers(self) -> None:
        mock_session = AsyncMock()

        mock_base_row = MagicMock()
        mock_base_row.fetchone.return_value = (
            "crm",
            "BYN",
            "CRM",
            "Базовый функционал",
            ["Feature 1"],
            1,
        )
        mock_base_periods = MagicMock()
        mock_base_periods.fetchall.return_value = [
            (1, 2000, 30),
            (3, 5400, 90),
            (12, 19200, 365),
        ]
        byn = "BYN"
        mock_modules = MagicMock()
        mock_modules.fetchall.return_value = [
            ("online", 1, 1500, 30, byn, "Онлайн"),
            ("online", 3, 4050, 90, byn, "Онлайн"),
            ("online", 12, 14400, 365, byn, "Онлайн"),
            ("analytics", 1, 500, 30, byn, "Аналитика"),
            ("analytics", 3, 1350, 90, byn, "Аналитика"),
            ("analytics", 12, 4800, 365, byn, "Аналитика"),
            ("groups", 1, 500, 30, byn, "Группы"),
            ("groups", 3, 1350, 90, byn, "Группы"),
            ("groups", 12, 4800, 365, byn, "Группы"),
        ]

        mock_session.execute.side_effect = [mock_base_row, mock_base_periods, mock_modules]

        catalog = await get_subscription_tier_catalog(mock_session)

        assert len(catalog) == 3
        assert catalog[0]["tier"] == "crm"
        assert catalog[1]["tier"] == "online"
        assert catalog[2]["tier"] == "analytics"
        assert catalog[0]["prices_by_period"]["1"] == 2000
        assert catalog[1]["prices_by_period"]["3"] == 9450

        assert catalog[0]["includes_tiers"] == [SUBSCRIPTION_TIER_CRM]
        assert SUBSCRIPTION_TIER_CRM in catalog[1]["includes_tiers"]
        assert SUBSCRIPTION_TIER_ONLINE in catalog[1]["includes_tiers"]
