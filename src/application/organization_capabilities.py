"""
Organization capability resolver — single product contract for trainer UI and catalog.

Maps ``organization_format`` + membership role + trainer ``studio_access_mode`` to
feature flags so mini-apps avoid scattering ``schedule_mode`` conditionals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from src.application.collective_use_cases import (
    MEMBER_ROLE_ADMIN,
    MEMBER_ROLE_OWNER,
    ORG_FORMAT_CENTER,
    ORG_FORMAT_CENTER_HYBRID,
    ORG_FORMAT_STUDIO,
    SCHEDULE_MODE_STUDIO_CENTRAL,
    STUDIO_ACCESS_MODE_ADMIN_ONLY,
    STUDIO_ACCESS_MODE_FULL,
    normalize_organization_format,
)

CATALOG_MODE_STUDIO_ROSTER = "studio_roster"
CATALOG_MODE_CENTER_GRID = "center_grid"

SHELL_NAV_FULL = "full"
SHELL_NAV_ORGANIZATION_ADMIN = "organization_admin"

HERO_VARIANT_STUDIO = "studio"
HERO_VARIANT_CENTER = "center"

MemberRole = Literal["owner", "admin", "member"]
ShellNavProfile = Literal["full", "organization_admin"]


@dataclass(frozen=True)
class OrganizationCapabilities:
    """Resolved feature flags for one trainer × collective context."""

    organization_format: str | None
    show_personal_crm: bool
    show_center_grid: bool
    show_center_passes: bool
    show_team_invite: bool
    show_brand_edit: bool
    catalog_mode: str | None
    shell_nav_profile: ShellNavProfile
    hero_variant: str | None
    organization_label: str
    collective_screen_title: str
    show_coaches_catalog_tab: bool


def resolve_organization_capabilities(
    *,
    organization_format: str | None,
    schedule_mode: str,
    role: str,
    studio_access_mode: str,
) -> OrganizationCapabilities:
    """Trainer mini-app capabilities for a collective membership context."""
    fmt = normalize_organization_format(organization_format)
    is_studio_admin = role in (MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN)
    is_owner = role == MEMBER_ROLE_OWNER
    is_central = schedule_mode == SCHEDULE_MODE_STUDIO_CENTRAL
    admin_only_account = studio_access_mode == STUDIO_ACCESS_MODE_ADMIN_ONLY

    # Owners keep full trainer shell even when claim used the «manager» alias (facility operator who also coaches).
    show_personal_crm = not admin_only_account or is_owner
    show_center_grid = is_central and is_studio_admin
    show_center_passes = show_center_grid
    show_team_invite = is_owner
    show_brand_edit = is_studio_admin

    if fmt == ORG_FORMAT_STUDIO:
        catalog_mode = CATALOG_MODE_STUDIO_ROSTER
        hero_variant = HERO_VARIANT_STUDIO
        organization_label = "студия"
        collective_screen_title = "Студия"
        show_coaches_catalog_tab = False
    else:
        catalog_mode = CATALOG_MODE_CENTER_GRID
        hero_variant = HERO_VARIANT_CENTER
        organization_label = "центр"
        collective_screen_title = "Центр"
        show_coaches_catalog_tab = fmt == ORG_FORMAT_CENTER_HYBRID

    shell_nav_profile: ShellNavProfile = (
        SHELL_NAV_FULL if show_personal_crm else SHELL_NAV_ORGANIZATION_ADMIN
    )

    return OrganizationCapabilities(
        organization_format=fmt,
        show_personal_crm=show_personal_crm,
        show_center_grid=show_center_grid,
        show_center_passes=show_center_passes,
        show_team_invite=show_team_invite,
        show_brand_edit=show_brand_edit,
        catalog_mode=catalog_mode,
        shell_nav_profile=shell_nav_profile,
        hero_variant=hero_variant,
        organization_label=organization_label,
        collective_screen_title=collective_screen_title,
        show_coaches_catalog_tab=show_coaches_catalog_tab,
    )


def resolve_solo_trainer_capabilities(
    studio_access_mode: str = STUDIO_ACCESS_MODE_FULL,
) -> OrganizationCapabilities:
    """Solo trainer without collective membership — full CRM shell by default."""
    admin_only_account = studio_access_mode == STUDIO_ACCESS_MODE_ADMIN_ONLY
    return OrganizationCapabilities(
        organization_format=None,
        show_personal_crm=not admin_only_account,
        show_center_grid=False,
        show_center_passes=False,
        show_team_invite=False,
        show_brand_edit=False,
        catalog_mode=None,
        shell_nav_profile=(
            SHELL_NAV_ORGANIZATION_ADMIN if admin_only_account else SHELL_NAV_FULL
        ),
        hero_variant=None,
        organization_label="тренер",
        collective_screen_title="Студия",
        show_coaches_catalog_tab=False,
    )


def resolve_public_collective_capabilities(
    *,
    organization_format: str | None,
    schedule_mode: str,
) -> dict[str, Any]:
    """Client catalog / public landing — no trainer role."""
    fmt = normalize_organization_format(organization_format)
    if fmt == ORG_FORMAT_STUDIO:
        return {
            "organization_format": fmt,
            "catalog_mode": CATALOG_MODE_STUDIO_ROSTER,
            "hero_variant": HERO_VARIANT_STUDIO,
            "show_coaches_catalog_tab": False,
        }
    return {
        "organization_format": fmt,
        "catalog_mode": CATALOG_MODE_CENTER_GRID,
        "hero_variant": HERO_VARIANT_CENTER,
        "show_coaches_catalog_tab": fmt == ORG_FORMAT_CENTER_HYBRID,
    }


def organization_capabilities_to_dict(caps: OrganizationCapabilities) -> dict[str, Any]:
    return {
        "organization_format": caps.organization_format,
        "show_personal_crm": caps.show_personal_crm,
        "show_center_grid": caps.show_center_grid,
        "show_center_passes": caps.show_center_passes,
        "show_team_invite": caps.show_team_invite,
        "show_brand_edit": caps.show_brand_edit,
        "catalog_mode": caps.catalog_mode,
        "shell_nav_profile": caps.shell_nav_profile,
        "hero_variant": caps.hero_variant,
        "organization_label": caps.organization_label,
        "collective_screen_title": caps.collective_screen_title,
        "show_coaches_catalog_tab": caps.show_coaches_catalog_tab,
    }


def capabilities_for_collective_membership(
    *,
    organization_format: str,
    schedule_mode: str,
    role: str,
    studio_access_mode: str,
) -> dict[str, Any]:
    """JSON-ready capabilities dict for API payloads."""
    caps = resolve_organization_capabilities(
        organization_format=organization_format,
        schedule_mode=schedule_mode,
        role=role,
        studio_access_mode=studio_access_mode,
    )
    return organization_capabilities_to_dict(caps)
