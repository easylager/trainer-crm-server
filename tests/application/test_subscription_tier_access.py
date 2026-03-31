"""Tests for subscription tier access control."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.application.subscription_tier_use_cases import (
    trainer_allows_online_booking,
    trainer_has_crm_access,
    trainer_has_analytics_access,
    get_trainer_booking_availability,
)
from src.infrastructure.db.models import (
    SUBSCRIPTION_TIER_NONE,
    SUBSCRIPTION_TIER_CRM,
    SUBSCRIPTION_TIER_ONLINE,
    SUBSCRIPTION_TIER_ANALYTICS,
)


class TestTrainerAllowsOnlineBooking:
    """Tests for trainer_allows_online_booking (tier >= online)."""

    @pytest.mark.asyncio
    async def test_no_subscription_denies_booking(self) -> None:
        """Trainer without subscription cannot allow online booking."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None  # No active subscription
        mock_session.execute.return_value = mock_result

        result = await trainer_allows_online_booking(mock_session, trainer_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_crm_tier_denies_booking(self) -> None:
        """Trainer with CRM tier cannot allow online booking."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (SUBSCRIPTION_TIER_CRM,)
        mock_session.execute.return_value = mock_result

        result = await trainer_allows_online_booking(mock_session, trainer_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_online_tier_allows_booking(self) -> None:
        """Trainer with online tier can allow online booking."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (SUBSCRIPTION_TIER_ONLINE,)
        mock_session.execute.return_value = mock_result

        result = await trainer_allows_online_booking(mock_session, trainer_id=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_analytics_tier_allows_booking(self) -> None:
        """Trainer with analytics tier can allow online booking (includes online)."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (SUBSCRIPTION_TIER_ANALYTICS,)
        mock_session.execute.return_value = mock_result

        result = await trainer_allows_online_booking(mock_session, trainer_id=1)
        assert result is True


class TestTrainerHasCrmAccess:
    """Tests for trainer_has_crm_access (tier >= crm)."""

    @pytest.mark.asyncio
    async def test_no_subscription_denies_crm(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        result = await trainer_has_crm_access(mock_session, trainer_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_crm_tier_allows_crm(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (SUBSCRIPTION_TIER_CRM,)
        mock_session.execute.return_value = mock_result

        result = await trainer_has_crm_access(mock_session, trainer_id=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_online_tier_allows_crm(self) -> None:
        """Online tier includes CRM."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (SUBSCRIPTION_TIER_ONLINE,)
        mock_session.execute.return_value = mock_result

        result = await trainer_has_crm_access(mock_session, trainer_id=1)
        assert result is True


class TestTrainerHasAnalyticsAccess:
    """Tests for trainer_has_analytics_access (tier >= analytics)."""

    @pytest.mark.asyncio
    async def test_crm_tier_denies_analytics(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (SUBSCRIPTION_TIER_CRM,)
        mock_session.execute.return_value = mock_result

        result = await trainer_has_analytics_access(mock_session, trainer_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_online_tier_denies_analytics(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (SUBSCRIPTION_TIER_ONLINE,)
        mock_session.execute.return_value = mock_result

        result = await trainer_has_analytics_access(mock_session, trainer_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_analytics_tier_allows_analytics(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (SUBSCRIPTION_TIER_ANALYTICS,)
        mock_session.execute.return_value = mock_result

        result = await trainer_has_analytics_access(mock_session, trainer_id=1)
        assert result is True


class TestGetTrainerBookingAvailability:
    """Tests for get_trainer_booking_availability (catalog display)."""

    @pytest.mark.asyncio
    async def test_no_subscription_returns_cannot_book(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        result = await get_trainer_booking_availability(mock_session, trainer_id=1)
        
        assert result["can_book"] is False
        assert result["tier"] == SUBSCRIPTION_TIER_NONE
        assert result["reason"] == "no_subscription"

    @pytest.mark.asyncio
    async def test_crm_tier_returns_cannot_book_crm_only(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (SUBSCRIPTION_TIER_CRM,)
        mock_session.execute.return_value = mock_result

        result = await get_trainer_booking_availability(mock_session, trainer_id=1)
        
        assert result["can_book"] is False
        assert result["tier"] == SUBSCRIPTION_TIER_CRM
        assert result["reason"] == "crm_only"

    @pytest.mark.asyncio
    async def test_online_tier_returns_can_book(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (SUBSCRIPTION_TIER_ONLINE,)
        mock_session.execute.return_value = mock_result

        result = await get_trainer_booking_availability(mock_session, trainer_id=1)
        
        assert result["can_book"] is True
        assert result["tier"] == SUBSCRIPTION_TIER_ONLINE
        assert result["reason"] is None

    @pytest.mark.asyncio
    async def test_analytics_tier_returns_can_book(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (SUBSCRIPTION_TIER_ANALYTICS,)
        mock_session.execute.return_value = mock_result

        result = await get_trainer_booking_availability(mock_session, trainer_id=1)
        
        assert result["can_book"] is True
        assert result["tier"] == SUBSCRIPTION_TIER_ANALYTICS
        assert result["reason"] is None


class TestTierAccessMatrix:
    """Integration tests for tier access matrix."""

    @pytest.mark.parametrize(
        "tier,crm_access,online_access,analytics_access",
        [
            (None, False, False, False),  # No subscription
            (SUBSCRIPTION_TIER_CRM, True, False, False),
            (SUBSCRIPTION_TIER_ONLINE, True, True, False),
            (SUBSCRIPTION_TIER_ANALYTICS, True, True, True),
        ],
    )
    @pytest.mark.asyncio
    async def test_tier_access_matrix(
        self,
        tier: str | None,
        crm_access: bool,
        online_access: bool,
        analytics_access: bool,
    ) -> None:
        """Verify access matrix for all tiers."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (tier,) if tier else None
        mock_session.execute.return_value = mock_result

        assert await trainer_has_crm_access(mock_session, 1) == crm_access
        
        # Reset mock for next call
        mock_session.execute.return_value = mock_result
        assert await trainer_allows_online_booking(mock_session, 1) == online_access
        
        mock_session.execute.return_value = mock_result
        assert await trainer_has_analytics_access(mock_session, 1) == analytics_access
