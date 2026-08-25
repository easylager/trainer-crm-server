"""Collective overlay Wave P0/P1 foundation tests."""
import pytest

pytestmark = pytest.mark.collective
from unittest.mock import AsyncMock, MagicMock

from src.application.collective_use_cases import (
    ORG_FORMAT_CENTER,
    ORG_FORMAT_STUDIO,
    build_collective_client_landing_payload,
    normalize_collective_slug,
    consume_collective_invite_token,
    issue_collective_invite_token,
    get_collective_entitlements_for_member,
)
from src.application.subscription_tier_use_cases import (
    SUBSCRIPTION_TIER_CRM,
    TrainerEntitlements,
    get_effective_entitlements,
    get_trainer_entitlements,
    merge_entitlements,
)


def _mods(online: bool = False, analytics: bool = False, groups: bool = False) -> dict:
    return {"online": online, "analytics": analytics, "groups": groups}


from src.application.trainer_start_payload import (
    TrainerStartKind,
    parse_trainer_start_payload,
)


class TestTrainerStartPayload:
    def test_collective_claim_prefix(self) -> None:
        parsed = parse_trainer_start_payload("col_claim_abc123")
        assert parsed.kind == TrainerStartKind.COLLECTIVE_CLAIM
        assert parsed.collective_token == "abc123"

    def test_collective_invite_prefix(self) -> None:
        parsed = parse_trainer_start_payload("col_inv_xyz")
        assert parsed.kind == TrainerStartKind.COLLECTIVE_INVITE
        assert parsed.collective_token == "xyz"

    def test_link_still_parsed(self) -> None:
        parsed = parse_trainer_start_payload("link_secret")
        assert parsed.kind == TrainerStartKind.LINK
        assert parsed.link_token == "secret"

    def test_join_payload(self) -> None:
        parsed = parse_trainer_start_payload("join")
        assert parsed.kind == TrainerStartKind.JOIN
        assert parsed.ref_code is None

    def test_join_with_referral(self) -> None:
        parsed = parse_trainer_start_payload("join_ref_REF9")
        assert parsed.kind == TrainerStartKind.JOIN
        assert parsed.ref_code == "REF9"


class TestNormalizeCollectiveSlug:
    def test_valid_slug(self) -> None:
        assert normalize_collective_slug("Ice-Yoga-Lane") == "ice-yoga-lane"

    def test_rejects_spaces(self) -> None:
        assert normalize_collective_slug("ice yoga") is None


class TestCollectiveClientLandingPayload:
    def test_studio_variant_and_city(self) -> None:
        payload = build_collective_client_landing_payload(
            {
                "slug": "ice-studio",
                "display_name": "Ice Studio",
                "tagline": "Йога для всех",
                "organization_format": ORG_FORMAT_STUDIO,
                "brand_tokens": {"default_city_id": 3},
            },
            webapp_base_url="https://app.example.com",
        )
        assert payload is not None
        assert payload["landing_variant"] == "studio"
        assert payload["display_name"] == "Ice Studio"
        assert payload["tagline"] == "Йога для всех"
        assert "collective=ice-studio" in payload["catalog_url"]
        assert "city_id=3" in payload["catalog_url"]

    def test_center_variant(self) -> None:
        payload = build_collective_client_landing_payload(
            {
                "slug": "throwing-center",
                "display_name": "Throwing Center",
                "organization_format": ORG_FORMAT_CENTER,
            },
            webapp_base_url="https://app.example.com",
        )
        assert payload is not None
        assert payload["landing_variant"] == "center"

    def test_rejects_non_https_base(self) -> None:
        assert (
            build_collective_client_landing_payload(
                {"slug": "x", "organization_format": ORG_FORMAT_STUDIO},
                webapp_base_url="http://insecure.example",
            )
            is None
        )


class TestMergeEntitlements:
    def test_own_only_unchanged(self) -> None:
        own = TrainerEntitlements(has_base_crm=True, modules=_mods(online=True), raw_tier="crm")
        merged = merge_entitlements(own, TrainerEntitlements(has_base_crm=False, modules=_mods(), raw_tier=None))
        assert merged.has_base_crm is True
        assert merged.modules.get("online") is True

    def test_union_modules(self) -> None:
        own = TrainerEntitlements(has_base_crm=True, modules=_mods(), raw_tier="crm")
        coll = TrainerEntitlements(has_base_crm=True, modules=_mods(online=True), raw_tier="crm")
        merged = merge_entitlements(own, coll)
        assert merged.modules.get("online") is True


def _ent_row(tier: str | None, modules: dict | None) -> tuple | None:
    if tier is None:
        return None
    return (tier, modules)


def _result_mock(row: tuple | None) -> MagicMock:
    m = MagicMock()
    m.fetchone.return_value = row
    m.fetchall.return_value = [row] if row is not None else []
    return m


class TestEffectiveEntitlementsSolo:
    """Without collective membership, effective == own."""

    @pytest.mark.asyncio
    async def test_solo_matches_own_entitlements(self) -> None:
        mock_session = AsyncMock()
        ent_row = _ent_row(SUBSCRIPTION_TIER_CRM, _mods(online=True))

        async def execute_side_effect(query, params=None):
            sql = str(query)
            if "trainer_subscriptions" in sql:
                return _result_mock(ent_row)
            if "collective_members" in sql:
                m = MagicMock()
                m.fetchone.return_value = None
                return m
            return _result_mock(None)

        mock_session.execute.side_effect = execute_side_effect

        own = await get_trainer_entitlements(mock_session, trainer_id=42)
        effective = await get_effective_entitlements(mock_session, trainer_id=42)
        assert effective.has_base_crm == own.has_base_crm
        assert effective.modules == own.modules


class TestCollectiveEntitlementsMember:
    @pytest.mark.asyncio
    async def test_returns_none_without_subscription_row(self) -> None:
        mock_session = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            if "collective_members" in sql and "collective_subscriptions" not in sql:
                m = MagicMock()
                m.fetchone.return_value = (1, "studio", "Studio", None, None, "owner", 5)
                return m
            if "collective_subscriptions" in sql:
                m = MagicMock()
                m.fetchall.return_value = []
                return m
            m = MagicMock()
            m.fetchone.return_value = None
            return m

        mock_session.execute.side_effect = execute_side_effect
        ent = await get_collective_entitlements_for_member(mock_session, trainer_id=7)
        assert ent is None
