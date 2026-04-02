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


# --- Pure function tests (no DB) ---


class TestTierSatisfies:
    """Matrix tests for tier_satisfies: analytics > online > crm > none."""

    @pytest.mark.parametrize(
        "current,required,expected",
        [
            # none satisfies nothing except none
            (SUBSCRIPTION_TIER_NONE, SUBSCRIPTION_TIER_NONE, True),
            (SUBSCRIPTION_TIER_NONE, SUBSCRIPTION_TIER_CRM, False),
            (SUBSCRIPTION_TIER_NONE, SUBSCRIPTION_TIER_ONLINE, False),
            (SUBSCRIPTION_TIER_NONE, SUBSCRIPTION_TIER_ANALYTICS, False),
            # crm satisfies crm and none
            (SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_NONE, True),
            (SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_CRM, True),
            (SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE, False),
            (SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ANALYTICS, False),
            # online satisfies online, crm, none
            (SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_NONE, True),
            (SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_CRM, True),
            (SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_ONLINE, True),
            (SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_ANALYTICS, False),
            # analytics satisfies everything
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
    """Tests for tier_includes: what features are unlocked at each tier."""

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


class TestGetEffectiveSubscriptionTier:
    """Tests for get_effective_subscription_tier with mocked DB."""

    @pytest.mark.asyncio
    async def test_no_subscription_returns_none(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        tier = await get_effective_subscription_tier(mock_session, trainer_id=1)
        assert tier == SUBSCRIPTION_TIER_NONE

    @pytest.mark.asyncio
    async def test_active_subscription_returns_tier(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (SUBSCRIPTION_TIER_ONLINE,)
        mock_session.execute.return_value = mock_result

        tier = await get_effective_subscription_tier(mock_session, trainer_id=1)
        assert tier == SUBSCRIPTION_TIER_ONLINE


class TestGetTrainerSubscriptionStatus:
    """Tests for get_trainer_subscription_status with mocked DB."""

    @pytest.mark.asyncio
    async def test_inactive_subscription_status(self) -> None:
        mock_session = AsyncMock()
        
        # First call: get_effective_subscription_tier → none
        # Second call: get subscription details → none
        mock_result1 = MagicMock()
        mock_result1.fetchone.return_value = None
        mock_result2 = MagicMock()
        mock_result2.fetchone.return_value = None
        
        mock_session.execute.side_effect = [mock_result1, mock_result2]

        status = await get_trainer_subscription_status(mock_session, trainer_id=1)
        
        assert status["is_active"] is False
        assert status["tier"] == SUBSCRIPTION_TIER_NONE
        assert status["effective_tier"] == SUBSCRIPTION_TIER_NONE
        assert status["unlocked_features"] == []

    @pytest.mark.asyncio
    async def test_active_subscription_status(self) -> None:
        mock_session = AsyncMock()
        
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=30)
        started_at = now - timedelta(days=5)
        
        # First call: get_effective_subscription_tier → online
        mock_result1 = MagicMock()
        mock_result1.fetchone.return_value = (SUBSCRIPTION_TIER_ONLINE,)
        
        # Second call: get subscription details
        mock_result2 = MagicMock()
        mock_result2.fetchone.return_value = (
            123,  # id
            SUBSCRIPTION_TIER_ONLINE,  # tier
            expires_at,  # expires_at
            "active",  # status
            started_at,  # started_at
            1,  # billing_period_months
        )

        mock_result3 = MagicMock()
        mock_result3.fetchone.return_value = ("Онлайн-запись",)

        mock_session.execute.side_effect = [mock_result1, mock_result2, mock_result3]

        status = await get_trainer_subscription_status(mock_session, trainer_id=1)
        
        assert status["is_active"] is True
        assert status["is_trial"] is False
        assert status["tier_name_ru"] == "Онлайн-запись"
        assert status["tier"] == SUBSCRIPTION_TIER_ONLINE
        assert status["effective_tier"] == SUBSCRIPTION_TIER_ONLINE
        assert status["billing_period_months"] == 1
        assert SUBSCRIPTION_TIER_CRM in status["unlocked_features"]
        assert SUBSCRIPTION_TIER_ONLINE in status["unlocked_features"]


class TestExpiredSubscription:
    """Tests for expired subscription behavior."""

    @pytest.mark.asyncio
    async def test_expired_subscription_returns_none_tier(self) -> None:
        """When subscription is expired, effective tier should be 'none'."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        # DB query filters by expires_at > now, so expired won't be returned
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        tier = await get_effective_subscription_tier(mock_session, trainer_id=1)
        assert tier == SUBSCRIPTION_TIER_NONE


class TestMockCheckout:
    """Tests for set_subscription_after_mock_payment."""

    @pytest.mark.asyncio
    async def test_invalid_tier_returns_none(self) -> None:
        mock_session = AsyncMock()
        
        result = await set_subscription_after_mock_payment(
            mock_session, trainer_id=1, tier="invalid_tier", period_months=1
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_tier_creates_subscription(self) -> None:
        mock_session = AsyncMock()
        
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=30)
        
        # Mock period pricing lookup (get_tier_period_pricing join)
        mock_pricing_result = MagicMock()
        mock_pricing_result.fetchone.return_value = (
            2900,  # price_cents
            "BYN",  # currency
            30,  # period_days
            "Онлайн-запись",  # name_ru
        )
        
        # Mock check for active subscription (none)
        mock_active_result = MagicMock()
        mock_active_result.fetchone.return_value = None
        
        # Mock plan lookup
        mock_plan_result = MagicMock()
        mock_plan_result.fetchone.return_value = (1,)  # plan_id
        
        # Mock insert
        mock_insert_result = MagicMock()
        mock_insert_result.fetchone.return_value = (
            999,  # subscription_id
            now,  # started_at
            expires_at,  # expires_at
        )
        
        mock_session.execute.side_effect = [
            mock_pricing_result,
            mock_active_result,
            mock_plan_result,
            mock_insert_result,
        ]

        result = await set_subscription_after_mock_payment(
            mock_session, trainer_id=1, tier=SUBSCRIPTION_TIER_ONLINE, period_months=1
        )
        
        assert result is not None
        assert result["tier"] == SUBSCRIPTION_TIER_ONLINE
        assert result["subscription_id"] == 999
        assert result["price_cents"] == 2900
        assert result["currency"] == "BYN"
        assert result["period_days"] == 30
        assert result["period_months"] == 1
        mock_session.commit.assert_called_once()


class TestTierCatalog:
    """Tests for get_subscription_tier_catalog."""

    @pytest.mark.asyncio
    async def test_catalog_returns_all_active_tiers(self) -> None:
        mock_session = AsyncMock()
        mock_tiers = MagicMock()
        mock_tiers.fetchall.return_value = [
            ("crm", "BYN", "CRM", "Базовый функционал", ["Feature 1"], 1),
            ("online", "BYN", "Онлайн-запись", "Клиенты записываются", ["Feature 2"], 2),
            ("analytics", "BYN", "Аналитика", "Отчёты", ["Feature 3"], 3),
        ]
        mock_periods = MagicMock()
        mock_periods.fetchall.return_value = [
            ("crm", 1, 1900, 30),
            ("crm", 3, 5000, 90),
            ("crm", 12, 18000, 365),
            ("online", 1, 2900, 30),
            ("online", 3, 7800, 90),
            ("online", 12, 27000, 365),
            ("analytics", 1, 4900, 30),
            ("analytics", 3, 13000, 90),
            ("analytics", 12, 45000, 365),
        ]
        mock_session.execute.side_effect = [mock_tiers, mock_periods]

        catalog = await get_subscription_tier_catalog(mock_session)
        
        assert len(catalog) == 3
        assert catalog[0]["tier"] == "crm"
        assert catalog[1]["tier"] == "online"
        assert catalog[2]["tier"] == "analytics"
        assert catalog[0]["prices_by_period"]["1"] == 1900
        assert catalog[1]["prices_by_period"]["3"] == 7800
        
        # Check includes_tiers is computed correctly
        assert catalog[0]["includes_tiers"] == [SUBSCRIPTION_TIER_CRM]
        assert SUBSCRIPTION_TIER_CRM in catalog[1]["includes_tiers"]
        assert SUBSCRIPTION_TIER_ONLINE in catalog[1]["includes_tiers"]
