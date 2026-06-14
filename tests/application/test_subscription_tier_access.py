"""Tests for subscription entitlements (CRM base + modules)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.application.subscription_tier_use_cases import (
    get_trainer_booking_availability,
    trainer_allows_online_booking,
    trainer_has_analytics_access,
    trainer_has_crm_access,
    trainer_has_groups_access,
)
from src.infrastructure.db.models import (
    SUBSCRIPTION_TIER_CRM,
    SUBSCRIPTION_TIER_ANALYTICS,
    SUBSCRIPTION_TIER_NONE,
    SUBSCRIPTION_TIER_ONLINE,
)


@pytest.fixture(autouse=True)
def _solo_trainer_no_collective_entitlements(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit mocks only subscription SQL — collective membership lookup must stay empty."""

    async def _no_collective(_session: object, _trainer_id: int) -> None:
        return None

    monkeypatch.setattr(
        "src.application.collective_use_cases.get_collective_entitlements_for_member",
        _no_collective,
    )


class _DualResultMock:
    """
    Session.execute().fetchone() / fetchall() helper: both return consistent data so
    existing tests (written against fetchone) keep passing alongside get_trainer_entitlements,
    which now uses fetchall to union modules across overlapping rows.
    """

    def __init__(self, row: tuple | None) -> None:
        self._row = row

    def fetchone(self) -> tuple | None:
        return self._row

    def fetchall(self) -> list:
        return [self._row] if self._row is not None else []


def _mods(online: bool = False, analytics: bool = False, groups: bool = False) -> dict:
    return {"online": online, "analytics": analytics, "groups": groups}


def _ent_row(tier: str | None, modules: dict | None) -> tuple | None:
    if tier is None:
        return None
    return (tier, modules)


def _result_mock(row: tuple | None) -> MagicMock:
    """
    Build a result mock that answers both fetchone() and fetchall() consistently.

    get_trainer_entitlements switched to fetchall (module union across overlapping
    rows); older tests rely on fetchone semantics. This keeps both shapes working.
    """
    m = MagicMock()
    m.fetchone.return_value = row
    m.fetchall.return_value = [row] if row is not None else []
    return m


class TestTrainerAllowsOnlineBooking:
    """trainer_allows_online_booking: CRM base + online module."""

    @pytest.mark.asyncio
    async def test_no_subscription_denies_booking(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        result = await trainer_allows_online_booking(mock_session, trainer_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_crm_only_denies_booking(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = _ent_row(SUBSCRIPTION_TIER_CRM, _mods())
        mock_session.execute.return_value = mock_result

        result = await trainer_allows_online_booking(mock_session, trainer_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_online_module_allows_booking(self) -> None:
        mock_session = AsyncMock()
        mock_session.execute.return_value = _DualResultMock(
            _ent_row(SUBSCRIPTION_TIER_CRM, _mods(online=True))
        )

        result = await trainer_allows_online_booking(mock_session, trainer_id=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_analytics_without_online_denies_booking(self) -> None:
        """Independent modules: analytics does not imply online."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = _ent_row(
            SUBSCRIPTION_TIER_CRM, _mods(online=False, analytics=True)
        )
        mock_session.execute.return_value = mock_result

        result = await trainer_allows_online_booking(mock_session, trainer_id=1)
        assert result is False


class TestTrainerHasCrmAccess:
    """trainer_has_crm_access: any active subscription row with tier set."""

    @pytest.mark.asyncio
    async def test_no_subscription_denies_crm(self) -> None:
        mock_session = AsyncMock()
        mock_session.execute.return_value = _DualResultMock(None)

        result = await trainer_has_crm_access(mock_session, trainer_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_crm_base_allows_crm(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = _ent_row(SUBSCRIPTION_TIER_CRM, _mods())
        mock_session.execute.return_value = mock_result

        result = await trainer_has_crm_access(mock_session, trainer_id=1)
        assert result is True


class TestTrainerHasAnalyticsAccess:
    """trainer_has_analytics_access: CRM + analytics module."""

    @pytest.mark.asyncio
    async def test_crm_only_denies_analytics(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = _ent_row(SUBSCRIPTION_TIER_CRM, _mods())
        mock_session.execute.return_value = mock_result

        result = await trainer_has_analytics_access(mock_session, trainer_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_online_only_denies_analytics(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = _ent_row(SUBSCRIPTION_TIER_CRM, _mods(online=True))
        mock_session.execute.return_value = mock_result

        result = await trainer_has_analytics_access(mock_session, trainer_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_analytics_module_allows_analytics(self) -> None:
        mock_session = AsyncMock()
        mock_session.execute.return_value = _DualResultMock(
            _ent_row(SUBSCRIPTION_TIER_CRM, _mods(analytics=True))
        )

        result = await trainer_has_analytics_access(mock_session, trainer_id=1)
        assert result is True


class TestTrainerHasGroupsAccess:
    @pytest.mark.asyncio
    async def test_groups_module(self) -> None:
        mock_session = AsyncMock()
        mock_session.execute.return_value = _DualResultMock(
            _ent_row(SUBSCRIPTION_TIER_CRM, _mods(groups=True))
        )
        assert await trainer_has_groups_access(mock_session, 1) is True


class TestGetTrainerBookingAvailability:
    """get_trainer_booking_availability uses two entitlement reads."""

    @pytest.mark.asyncio
    async def test_no_subscription_returns_cannot_book(self) -> None:
        mock_session = AsyncMock()
        mock_session.execute.return_value = _DualResultMock(None)

        result = await get_trainer_booking_availability(mock_session, trainer_id=1)

        assert result["can_book"] is False
        assert result["tier"] == SUBSCRIPTION_TIER_NONE
        assert result["reason"] == "no_subscription"

    @pytest.mark.asyncio
    async def test_crm_only_returns_crm_only(self) -> None:
        """effective tier → allows_online → has_crm (three entitlement reads)."""
        mock_session = AsyncMock()
        row = _ent_row(SUBSCRIPTION_TIER_CRM, _mods())
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        mock_session.execute.return_value = mock_result

        result = await get_trainer_booking_availability(mock_session, trainer_id=1)

        assert result["can_book"] is False
        assert result["tier"] == SUBSCRIPTION_TIER_CRM
        assert result["reason"] == "crm_only"

    @pytest.mark.asyncio
    async def test_online_module_returns_can_book(self) -> None:
        mock_session = AsyncMock()
        row = _ent_row(SUBSCRIPTION_TIER_CRM, _mods(online=True))
        mock_session.execute.return_value = _DualResultMock(row)

        result = await get_trainer_booking_availability(mock_session, trainer_id=1)

        assert result["can_book"] is True
        assert result["tier"] == SUBSCRIPTION_TIER_ONLINE
        assert result["reason"] is None


class TestTierAccessMatrix:
    """Parametrized entitlements matrix."""

    @pytest.mark.parametrize(
        "modules,crm_access,online_access,analytics_access",
        [
            (None, False, False, False),
            (_mods(), True, False, False),
            (_mods(online=True), True, True, False),
            (_mods(online=True, analytics=True), True, True, True),
            (_mods(analytics=True), True, False, True),
        ],
    )
    @pytest.mark.asyncio
    async def test_tier_access_matrix(
        self,
        modules: dict | None,
        crm_access: bool,
        online_access: bool,
        analytics_access: bool,
    ) -> None:
        mock_session = AsyncMock()
        row = None if modules is None else _ent_row(SUBSCRIPTION_TIER_CRM, modules)
        mock_session.execute.return_value = _DualResultMock(row)

        assert await trainer_has_crm_access(mock_session, 1) == crm_access
        mock_session.execute.return_value = _DualResultMock(row)
        assert await trainer_allows_online_booking(mock_session, 1) == online_access
        mock_session.execute.return_value = _DualResultMock(row)
        assert await trainer_has_analytics_access(mock_session, 1) == analytics_access
