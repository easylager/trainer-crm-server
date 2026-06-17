"""Organization capability resolver (Epic O0)."""
import pytest

from src.application.collective_use_cases import (
    MEMBER_ROLE_ADMIN,
    MEMBER_ROLE_MEMBER,
    MEMBER_ROLE_OWNER,
    ORG_FORMAT_CENTER,
    ORG_FORMAT_CENTER_HYBRID,
    ORG_FORMAT_STUDIO,
    SCHEDULE_MODE_MEMBER_AUTONOMOUS,
    SCHEDULE_MODE_STUDIO_CENTRAL,
    STUDIO_ACCESS_MODE_ADMIN_ONLY,
    STUDIO_ACCESS_MODE_FULL,
)
from src.application.organization_capabilities import (
    CATALOG_MODE_CENTER_GRID,
    CATALOG_MODE_STUDIO_ROSTER,
    HERO_VARIANT_CENTER,
    HERO_VARIANT_STUDIO,
    SHELL_NAV_FULL,
    SHELL_NAV_ORGANIZATION_ADMIN,
    organization_capabilities_to_dict,
    resolve_organization_capabilities,
    resolve_public_collective_capabilities,
    resolve_solo_trainer_capabilities,
)

pytestmark = pytest.mark.collective


def _caps(**kwargs):
    return organization_capabilities_to_dict(resolve_organization_capabilities(**kwargs))


class TestResolveOrganizationCapabilities:
    @pytest.mark.parametrize(
        ("role", "expected_invite", "expected_brand", "expected_grid"),
        [
            (MEMBER_ROLE_OWNER, True, True, False),
            (MEMBER_ROLE_ADMIN, False, True, False),
            (MEMBER_ROLE_MEMBER, False, False, False),
        ],
    )
    def test_studio_role_matrix(self, role, expected_invite, expected_brand, expected_grid) -> None:
        c = _caps(
            organization_format=ORG_FORMAT_STUDIO,
            schedule_mode=SCHEDULE_MODE_MEMBER_AUTONOMOUS,
            role=role,
            studio_access_mode=STUDIO_ACCESS_MODE_FULL,
        )
        assert c["organization_format"] == ORG_FORMAT_STUDIO
        assert c["catalog_mode"] == CATALOG_MODE_STUDIO_ROSTER
        assert c["hero_variant"] == HERO_VARIANT_STUDIO
        assert c["shell_nav_profile"] == SHELL_NAV_FULL
        assert c["show_personal_crm"] is True
        assert c["show_center_grid"] is expected_grid
        assert c["show_center_passes"] is expected_grid
        assert c["show_team_invite"] is expected_invite
        assert c["show_brand_edit"] is expected_brand
        assert c["collective_screen_title"] == "Студия"
        assert c["show_coaches_catalog_tab"] is False

    def test_center_owner_admin_only(self) -> None:
        c = _caps(
            organization_format=ORG_FORMAT_CENTER,
            schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
            role=MEMBER_ROLE_OWNER,
            studio_access_mode=STUDIO_ACCESS_MODE_ADMIN_ONLY,
        )
        assert c["catalog_mode"] == CATALOG_MODE_CENTER_GRID
        assert c["hero_variant"] == HERO_VARIANT_CENTER
        assert c["shell_nav_profile"] == SHELL_NAV_FULL
        assert c["show_personal_crm"] is True
        assert c["show_center_grid"] is True
        assert c["show_center_passes"] is True
        assert c["show_team_invite"] is True
        assert c["show_brand_edit"] is True
        assert c["collective_screen_title"] == "Центр"

    @pytest.mark.parametrize(
        "role",
        [MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN, MEMBER_ROLE_MEMBER],
    )
    def test_center_member_coach_keeps_personal_crm(self, role) -> None:
        c = _caps(
            organization_format=ORG_FORMAT_CENTER,
            schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
            role=role,
            studio_access_mode=STUDIO_ACCESS_MODE_FULL,
        )
        assert c["show_personal_crm"] is True
        assert c["shell_nav_profile"] == SHELL_NAV_FULL
        assert c["show_center_grid"] is (role in (MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN))
        assert c["show_team_invite"] is (role == MEMBER_ROLE_OWNER)

    def test_center_hybrid_owner(self) -> None:
        c = _caps(
            organization_format=ORG_FORMAT_CENTER_HYBRID,
            schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
            role=MEMBER_ROLE_OWNER,
            studio_access_mode=STUDIO_ACCESS_MODE_FULL,
        )
        assert c["show_personal_crm"] is True
        assert c["show_center_grid"] is True
        assert c["show_coaches_catalog_tab"] is True
        assert c["collective_screen_title"] == "Центр"

    def test_center_hybrid_member_no_admin_tabs(self) -> None:
        c = _caps(
            organization_format=ORG_FORMAT_CENTER_HYBRID,
            schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
            role=MEMBER_ROLE_MEMBER,
            studio_access_mode=STUDIO_ACCESS_MODE_FULL,
        )
        assert c["show_personal_crm"] is True
        assert c["show_center_grid"] is False
        assert c["show_brand_edit"] is False


class TestSoloAndPublicCapabilities:
    def test_solo_trainer_full(self) -> None:
        caps = resolve_solo_trainer_capabilities(STUDIO_ACCESS_MODE_FULL)
        assert caps.show_personal_crm is True
        assert caps.shell_nav_profile == SHELL_NAV_FULL
        assert caps.organization_format is None

    def test_public_studio_catalog(self) -> None:
        payload = resolve_public_collective_capabilities(
            organization_format=ORG_FORMAT_STUDIO,
            schedule_mode=SCHEDULE_MODE_MEMBER_AUTONOMOUS,
        )
        assert payload["catalog_mode"] == CATALOG_MODE_STUDIO_ROSTER
        assert payload["hero_variant"] == HERO_VARIANT_STUDIO
        assert payload["show_coaches_catalog_tab"] is False

    def test_public_center_hybrid_catalog(self) -> None:
        payload = resolve_public_collective_capabilities(
            organization_format=ORG_FORMAT_CENTER_HYBRID,
            schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
        )
        assert payload["catalog_mode"] == CATALOG_MODE_CENTER_GRID
        assert payload["hero_variant"] == HERO_VARIANT_CENTER
        assert payload["show_coaches_catalog_tab"] is True

    def test_legacy_ice_normalizes_to_studio(self) -> None:
        c = _caps(
            organization_format="ice",
            schedule_mode=SCHEDULE_MODE_MEMBER_AUTONOMOUS,
            role=MEMBER_ROLE_OWNER,
            studio_access_mode=STUDIO_ACCESS_MODE_FULL,
        )
        assert c["organization_format"] == ORG_FORMAT_STUDIO
