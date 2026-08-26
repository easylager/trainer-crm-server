"""
Collective (studio) overlay: optional group of trainers sharing brand + billing shell.

Wave P0: schema, admin draft/claim tokens, bootstrap payload, entitlements stub.
Bookings and clients remain per-trainer.
"""
from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from urllib.parse import quote
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.config import Settings

from src.application.subscription_tier_use_cases import (
    TrainerEntitlements,
    SUBSCRIPTION_BILLING_PERIOD_MONTHS,
    default_modules_dict,
    infer_modules_from_legacy_tier,
    normalize_modules_dict,
)
from src.application.brand_presentation import (
    MAX_COLLECTIVE_GALLERY_ITEMS,
    list_accent_preset_options,
    normalize_brand_tokens,
    normalize_default_city_id,
    normalize_gallery_keys,
    public_asset_url,
    resolve_accent_preset,
)
from src.application.trainer_use_cases import MAX_TRAINER_PHOTO_BYTES, trainer_photo_bytes_look_like_image
from src.infrastructure import s3
from src.infrastructure.db.models import (
    INVOICE_STATUS_CANCELLED,
    INVOICE_STATUS_OVERDUE,
    INVOICE_STATUS_PAID,
    INVOICE_STATUS_SENT,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_TRIAL,
    SUBSCRIPTION_TIER_ANALYTICS,
    SUBSCRIPTION_TIER_CRM,
    SUBSCRIPTION_TIER_ONLINE,
    TRAINER_STATUS_PENDING_PROFILE,
)

import logging

logger = logging.getLogger(__name__)

_COLLECTIVE_ROW_SELECT = """
    id, slug, display_name, tagline, logo_key, cover_key, about, gallery_keys, brand_tokens,
    primary_arena_id, status, seat_limit, schedule_mode, organization_format
"""

COLLECTIVE_STATUS_DRAFT = "draft"
COLLECTIVE_STATUS_ACTIVE = "active"
COLLECTIVE_STATUS_SUSPENDED = "suspended"

SCHEDULE_MODE_MEMBER_AUTONOMOUS = "member_autonomous"
SCHEDULE_MODE_STUDIO_CENTRAL = "studio_central"

MEMBER_ROLE_OWNER = "owner"
MEMBER_ROLE_ADMIN = "admin"
MEMBER_ROLE_MEMBER = "member"

STUDIO_ACCESS_MODE_FULL = "full_trainer"
STUDIO_ACCESS_MODE_ADMIN_ONLY = "studio_admin_only"

COLLECTIVE_STUDIO_ADMIN_ROLES = frozenset({MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN})

COLLECTIVE_DRAFT_SEAT_MIN = 2
COLLECTIVE_DRAFT_SEAT_MAX = 50

MEMBER_STATUS_INVITED = "invited"
MEMBER_STATUS_ACTIVE = "active"
MEMBER_STATUS_LEFT = "left"

TOKEN_KIND_CLAIM = "claim"
TOKEN_KIND_INVITE = "invite"

DEFAULT_COLLECTIVE_CLAIM_EXPIRE_DAYS = 14
DEFAULT_COLLECTIVE_INVITE_EXPIRE_DAYS = 14
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


ORG_FORMAT_STUDIO = "studio"
ORG_FORMAT_CENTER = "center"
ORG_FORMAT_CENTER_HYBRID = "center_hybrid"
CANONICAL_ORG_FORMATS = frozenset({ORG_FORMAT_STUDIO, ORG_FORMAT_CENTER, ORG_FORMAT_CENTER_HYBRID})


@dataclass(frozen=True)
class CollectiveMembershipContext:
    collective_id: int
    slug: str
    display_name: str
    tagline: str | None
    logo_key: str | None
    role: Literal["owner", "admin", "member"]
    seat_limit: int
    schedule_mode: str = SCHEDULE_MODE_MEMBER_AUTONOMOUS
    organization_format: str = ORG_FORMAT_STUDIO


@dataclass(frozen=True)
class ConsumeCollectiveClaimResult:
    collective_id: int | None = None
    slug: str | None = None
    display_name: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ConsumeCollectiveInviteResult:
    collective_id: int | None = None
    slug: str | None = None
    display_name: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class CollectiveOrgFormatPreset:
    """Admin draft preset — maps product format to schedule + owner access."""

    key: str
    label_ru: str
    schedule_mode: str
    seat_limit_default: int
    owner_studio_access_mode: str


COLLECTIVE_ORG_FORMAT_PRESETS: dict[str, CollectiveOrgFormatPreset] = {
    ORG_FORMAT_STUDIO: CollectiveOrgFormatPreset(
        key=ORG_FORMAT_STUDIO,
        label_ru="Студия — автономные тренеры, без центральной сетки",
        schedule_mode=SCHEDULE_MODE_MEMBER_AUTONOMOUS,
        seat_limit_default=5,
        owner_studio_access_mode=STUDIO_ACCESS_MODE_FULL,
    ),
    ORG_FORMAT_CENTER: CollectiveOrgFormatPreset(
        key=ORG_FORMAT_CENTER,
        label_ru="Центр — сетка admin/owner, owner без личного CRM",
        schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
        seat_limit_default=8,
        owner_studio_access_mode=STUDIO_ACCESS_MODE_ADMIN_ONLY,
    ),
    ORG_FORMAT_CENTER_HYBRID: CollectiveOrgFormatPreset(
        key=ORG_FORMAT_CENTER_HYBRID,
        label_ru="Центр + owner-тренер — сетка и личные клиенты",
        schedule_mode=SCHEDULE_MODE_STUDIO_CENTRAL,
        seat_limit_default=8,
        owner_studio_access_mode=STUDIO_ACCESS_MODE_FULL,
    ),
}

COLLECTIVE_ORG_FORMAT_ALIASES: dict[str, str] = {
    "studio": ORG_FORMAT_STUDIO,
    "ice": ORG_FORMAT_STUDIO,
    "autonomous": ORG_FORMAT_STUDIO,
    "white": ORG_FORMAT_STUDIO,
    "white-label": ORG_FORMAT_STUDIO,
    "whitelabel": ORG_FORMAT_STUDIO,
    "member": ORG_FORMAT_STUDIO,
    "coworking": ORG_FORMAT_STUDIO,
    "lanes": ORG_FORMAT_STUDIO,
    "rental": ORG_FORMAT_STUDIO,
    ORG_FORMAT_CENTER: ORG_FORMAT_CENTER,
    "central": ORG_FORMAT_CENTER,
    "manager": ORG_FORMAT_CENTER,
    "facility": ORG_FORMAT_CENTER,
    "admin_only": ORG_FORMAT_CENTER,
    "non_trainer": ORG_FORMAT_CENTER,
    "operator": ORG_FORMAT_CENTER,
    ORG_FORMAT_CENTER_HYBRID: ORG_FORMAT_CENTER_HYBRID,
    "hybrid": ORG_FORMAT_CENTER_HYBRID,
    "owner_trainer": ORG_FORMAT_CENTER_HYBRID,
    "throwing": ORG_FORMAT_CENTER_HYBRID,
    "studio_central": ORG_FORMAT_CENTER_HYBRID,
}

COLLECTIVE_DRAFT_OWNER_ALIASES: dict[str, str] = {
    "trainer": STUDIO_ACCESS_MODE_FULL,
    "coach": STUDIO_ACCESS_MODE_FULL,
    "full": STUDIO_ACCESS_MODE_FULL,
    "full_trainer": STUDIO_ACCESS_MODE_FULL,
    "manager": STUDIO_ACCESS_MODE_ADMIN_ONLY,
    "admin": STUDIO_ACCESS_MODE_ADMIN_ONLY,
    "facility": STUDIO_ACCESS_MODE_ADMIN_ONLY,
    "non_trainer": STUDIO_ACCESS_MODE_ADMIN_ONLY,
    "studio_admin_only": STUDIO_ACCESS_MODE_ADMIN_ONLY,
}


@dataclass(frozen=True)
class CollectiveDraftAdminSpec:
    slug: str
    display_name: str
    organization_format: str
    schedule_mode: str
    seat_limit: int
    owner_studio_access_mode: str


def normalize_organization_format(raw: str | None) -> str:
    """Map legacy draft keys and derive canonical product format."""
    key = (raw or ORG_FORMAT_STUDIO).strip().lower()
    legacy = {
        "ice": ORG_FORMAT_STUDIO,
        "coworking": ORG_FORMAT_STUDIO,
        "manager": ORG_FORMAT_CENTER,
    }
    if key in legacy:
        return legacy[key]
    if key in CANONICAL_ORG_FORMATS:
        return key
    resolved = COLLECTIVE_ORG_FORMAT_ALIASES.get(key)
    if resolved in CANONICAL_ORG_FORMATS:
        return resolved
    return ORG_FORMAT_STUDIO


def derive_stored_organization_format(
    schedule_mode: str,
    owner_studio_access_mode: str,
) -> str:
    """Canonical stored format from schedule + intended owner access."""
    if schedule_mode == SCHEDULE_MODE_MEMBER_AUTONOMOUS:
        return ORG_FORMAT_STUDIO
    if owner_studio_access_mode == STUDIO_ACCESS_MODE_ADMIN_ONLY:
        return ORG_FORMAT_CENTER
    return ORG_FORMAT_CENTER_HYBRID


def list_collective_org_format_presets() -> list[CollectiveOrgFormatPreset]:
    return list(COLLECTIVE_ORG_FORMAT_PRESETS.values())


def resolve_collective_org_format_key(raw: str | None) -> str | None:
    key = (raw or ORG_FORMAT_STUDIO).strip().lower()
    if not key:
        return ORG_FORMAT_STUDIO
    resolved = COLLECTIVE_ORG_FORMAT_ALIASES.get(key)
    if resolved and resolved in COLLECTIVE_ORG_FORMAT_PRESETS:
        return resolved
    return None


def parse_admin_collective_draft_body(body: str) -> CollectiveDraftAdminSpec | str:
    """
    Parse admin bot `/collective_draft slug|Name|format|seats|owner`.

    Returns spec or machine-readable error code (invalid_slug, invalid_format, …).
    """
    parts = [(p or "").strip() for p in (body or "").split("|")]
    if len(parts) < 2:
        return "missing_fields"
    slug_raw, display_name = parts[0], parts[1]
    if not slug_raw or not display_name:
        return "missing_fields"

    norm_slug = normalize_collective_slug(slug_raw)
    if not norm_slug:
        return "invalid_slug"

    format_key = resolve_collective_org_format_key(parts[2] if len(parts) > 2 else ORG_FORMAT_STUDIO)
    if format_key is None:
        return "invalid_format"
    preset = COLLECTIVE_ORG_FORMAT_PRESETS[format_key]

    seat_limit = preset.seat_limit_default
    if len(parts) > 3 and parts[3]:
        try:
            seat_limit = int(parts[3])
        except ValueError:
            return "invalid_seats"
        if seat_limit < COLLECTIVE_DRAFT_SEAT_MIN or seat_limit > COLLECTIVE_DRAFT_SEAT_MAX:
            return "invalid_seats"

    owner_mode = preset.owner_studio_access_mode
    if len(parts) > 4 and parts[4]:
        owner_key = parts[4].strip().lower()
        resolved_owner = COLLECTIVE_DRAFT_OWNER_ALIASES.get(owner_key)
        if resolved_owner is None:
            return "invalid_owner_mode"
        owner_mode = resolved_owner

    if preset.schedule_mode == SCHEDULE_MODE_MEMBER_AUTONOMOUS:
        if owner_mode == STUDIO_ACCESS_MODE_ADMIN_ONLY:
            return "invalid_owner_mode"

    org_format = derive_stored_organization_format(preset.schedule_mode, owner_mode)

    return CollectiveDraftAdminSpec(
        slug=norm_slug,
        display_name=display_name[:128],
        organization_format=org_format,
        schedule_mode=preset.schedule_mode,
        seat_limit=seat_limit,
        owner_studio_access_mode=owner_mode,
    )


def is_collective_studio_admin_role(role: str | None) -> bool:
    """Owner or studio admin may manage center grid and delegate bookings (ADR-003 §7)."""
    return (role or "").strip() in COLLECTIVE_STUDIO_ADMIN_ROLES


def is_collective_owner_role(role: str | None) -> bool:
    return (role or "").strip() == MEMBER_ROLE_OWNER


def normalize_collective_slug(raw: str) -> str | None:
    slug = (raw or "").strip().lower()
    if not slug or len(slug) > 64:
        return None
    if not _SLUG_RE.match(slug):
        return None
    return slug


async def get_trainer_studio_access_mode(session: AsyncSession, trainer_id: int) -> str:
    """full_trainer (default) or studio_admin_only — ADR-003 W5."""
    r = await session.execute(
        text("SELECT studio_access_mode FROM trainers WHERE id = :tid"),
        {"tid": int(trainer_id)},
    )
    row = r.fetchone()
    if row is None:
        return STUDIO_ACCESS_MODE_FULL
    mode = (str(row[0]) if row[0] else STUDIO_ACCESS_MODE_FULL).strip()
    return mode if mode in (STUDIO_ACCESS_MODE_FULL, STUDIO_ACCESS_MODE_ADMIN_ONLY) else STUDIO_ACCESS_MODE_FULL


async def get_effective_studio_access_mode(session: AsyncSession, trainer_id: int) -> str:
    """Admin-only shell applies only while trainer has an active collective membership."""
    mode = await get_trainer_studio_access_mode(session, trainer_id)
    if mode != STUDIO_ACCESS_MODE_ADMIN_ONLY:
        return mode
    memberships = await list_active_collective_memberships(session, trainer_id)
    if not memberships:
        return STUDIO_ACCESS_MODE_FULL
    return mode


async def get_collective_entitlements_for_member(
    session: AsyncSession,
    trainer_id: int,
) -> TrainerEntitlements | None:
    """
    Union of collective subscription grants across all active memberships (ADR-003 §5).

    Returns None when trainer has no membership or no collective has an active subscription row.
    """
    memberships = await list_active_collective_memberships(session, trainer_id)
    if not memberships:
        return None

    now = datetime.now(timezone.utc)
    union = default_modules_dict()
    any_raw_tier: str | None = None
    found_any = False

    for membership in memberships:
        result = await session.execute(
            text(
                """
                SELECT tier, modules
                FROM collective_subscriptions
                WHERE collective_id = :cid
                  AND started_at <= :now
                  AND expires_at > :now
                  AND status IN (:s1, :s2)
                  AND tier IS NOT NULL
                """
            ),
            {
                "cid": membership.collective_id,
                "now": now,
                "s1": SUBSCRIPTION_STATUS_TRIAL,
                "s2": SUBSCRIPTION_STATUS_ACTIVE,
            },
        )
        for row in result.fetchall():
            found_any = True
            raw_tier = row[0]
            mods = normalize_modules_dict(row[1])
            if raw_tier in (SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_ANALYTICS) and not any(mods.values()):
                mods = infer_modules_from_legacy_tier(raw_tier)
            for key in union:
                if mods.get(key):
                    union[key] = True
            any_raw_tier = any_raw_tier or raw_tier

    if not found_any:
        return None
    return TrainerEntitlements(has_base_crm=True, modules=union, raw_tier=any_raw_tier)


_MEMBERSHIP_SELECT_SQL = """
    SELECT
        c.id,
        c.slug,
        c.display_name,
        c.tagline,
        c.logo_key,
        cm.role,
        c.seat_limit,
        c.schedule_mode,
        c.organization_format
    FROM collective_members cm
    INNER JOIN collectives c ON c.id = cm.collective_id
    WHERE cm.trainer_id = :tid
      AND cm.status = :active
      AND c.status = :collective_active
"""


def _membership_from_row(row: Any) -> CollectiveMembershipContext:
    role = str(row[5])
    if role not in (MEMBER_ROLE_OWNER, MEMBER_ROLE_ADMIN, MEMBER_ROLE_MEMBER):
        role = MEMBER_ROLE_MEMBER
    schedule_mode = str(row[7] or SCHEDULE_MODE_MEMBER_AUTONOMOUS)
    org_format = normalize_organization_format(str(row[8]) if len(row) > 8 and row[8] else None)
    return CollectiveMembershipContext(
        collective_id=int(row[0]),
        slug=str(row[1]),
        display_name=str(row[2]),
        tagline=(str(row[3]).strip() if row[3] else None),
        logo_key=(str(row[4]).strip() if row[4] else None),
        role=role,  # type: ignore[arg-type]
        seat_limit=int(row[6]),
        schedule_mode=schedule_mode,
        organization_format=org_format,
    )


async def list_active_collective_memberships(
    session: AsyncSession,
    trainer_id: int,
) -> list[CollectiveMembershipContext]:
    """All active studio memberships for trainer (ADR-003 W4 multi-collective)."""
    result = await session.execute(
        text(
            _MEMBERSHIP_SELECT_SQL
            + """
            ORDER BY
                CASE WHEN cm.role = :owner THEN 0 WHEN cm.role = :admin THEN 1 ELSE 2 END,
                cm.joined_at ASC NULLS LAST,
                c.id ASC
            """
        ),
        {
            "tid": trainer_id,
            "active": MEMBER_STATUS_ACTIVE,
            "collective_active": COLLECTIVE_STATUS_ACTIVE,
            "owner": MEMBER_ROLE_OWNER,
            "admin": MEMBER_ROLE_ADMIN,
        },
    )
    return [_membership_from_row(row) for row in result.fetchall()]


async def resolve_collective_membership(
    session: AsyncSession,
    trainer_id: int,
    *,
    collective_slug: str | None = None,
) -> CollectiveMembershipContext | None:
    """Pick membership by slug or default primary (owner-first, oldest join)."""
    norm_slug = normalize_collective_slug(collective_slug) if collective_slug else None
    if norm_slug:
        result = await session.execute(
            text(_MEMBERSHIP_SELECT_SQL + " AND c.slug = :slug LIMIT 1"),
            {
                "tid": trainer_id,
                "active": MEMBER_STATUS_ACTIVE,
                "collective_active": COLLECTIVE_STATUS_ACTIVE,
                "slug": norm_slug,
            },
        )
        row = result.fetchone()
        return _membership_from_row(row) if row else None

    memberships = await list_active_collective_memberships(session, trainer_id)
    return memberships[0] if memberships else None


async def get_active_collective_membership(
    session: AsyncSession,
    trainer_id: int,
) -> CollectiveMembershipContext | None:
    """Primary active collective row for trainer, if any (backward-compatible)."""
    return await resolve_collective_membership(session, trainer_id)


def _collective_client_start_payload(slug: str) -> str:
    return f"col_{slug}"


def build_collective_catalog_webapp_url(
    slug: str,
    *,
    default_city_id: int | None = None,
) -> str | None:
    """Direct catalog URL for studio landing (?collective=). Used for copy/reference only."""
    norm = normalize_collective_slug(slug)
    if not norm:
        return None
    base = (Settings().webapp_base_url or "").strip().rstrip("/")
    if not base:
        return None
    url = f"{base}/webapp/catalog?collective={norm}&tab=catalog"
    city_id = normalize_default_city_id(default_city_id)
    if city_id is not None:
        url += f"&city_id={city_id}"
    return url


def build_collective_client_deep_link(slug: str) -> str | None:
    """Client bot entry for studio landing (Wave P1 UI)."""
    settings = Settings()
    client_uname = (settings.client_bot_username or "").strip().lstrip("@")
    if not client_uname:
        return None
    return f"https://t.me/{client_uname}?start={_collective_client_start_payload(slug)}"


def build_collective_client_landing_payload(
    collective: dict[str, Any],
    *,
    webapp_base_url: str,
) -> dict[str, Any] | None:
    """Format-aware client bot landing for ``col_<slug>`` (O6.13–O6.14)."""
    slug = str(collective.get("slug") or "").strip()
    if not slug:
        return None
    base = (webapp_base_url or "").strip().rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    fmt = normalize_organization_format(collective.get("organization_format"))
    tokens = normalize_brand_tokens(collective.get("brand_tokens"))
    default_city_id = tokens.get("default_city_id")
    catalog_url = f"{base}/webapp/catalog?collective={quote(slug)}&tab=catalog"
    if default_city_id is not None:
        catalog_url += f"&city_id={int(default_city_id)}"
    brand = collective_brand_kit_enrichment(collective)
    return {
        "landing_variant": "studio" if fmt == ORG_FORMAT_STUDIO else "center",
        "catalog_url": catalog_url,
        "cover_url": brand.get("cover_url"),
        "display_name": (collective.get("display_name") or slug).strip(),
        "tagline": (collective.get("tagline") or "").strip() or None,
    }


def build_trainer_collective_bootstrap_payload(
    membership: CollectiveMembershipContext | None,
    *,
    subscription_covers: list[str] | None = None,
    memberships: list[CollectiveMembershipContext] | None = None,
    studio_access_mode: str = STUDIO_ACCESS_MODE_FULL,
) -> dict[str, Any] | None:
    """Hub bootstrap slice; null for solo trainers."""
    from src.application.organization_capabilities import capabilities_for_collective_membership

    all_memberships = list(memberships or [])
    if membership is None and all_memberships:
        membership = all_memberships[0]
    if membership is None:
        return None
    if not all_memberships:
        all_memberships = [membership]
    client_link = build_collective_client_deep_link(membership.slug)
    collectives = [
        {
            "collective_id": m.collective_id,
            "slug": m.slug,
            "display_name": m.display_name,
            "role": m.role,
            "schedule_mode": m.schedule_mode,
            "organization_format": m.organization_format,
            "capabilities": capabilities_for_collective_membership(
                organization_format=m.organization_format,
                schedule_mode=m.schedule_mode,
                role=m.role,
                studio_access_mode=studio_access_mode,
            ),
        }
        for m in all_memberships
    ]
    primary_caps = capabilities_for_collective_membership(
        organization_format=membership.organization_format,
        schedule_mode=membership.schedule_mode,
        role=membership.role,
        studio_access_mode=studio_access_mode,
    )
    return {
        "collective_id": membership.collective_id,
        "slug": membership.slug,
        "display_name": membership.display_name,
        "tagline": membership.tagline,
        "logo_key": membership.logo_key,
        "role": membership.role,
        "seat_limit": membership.seat_limit,
        "schedule_mode": membership.schedule_mode,
        "organization_format": membership.organization_format,
        "capabilities": primary_caps,
        "client_link": client_link,
        "subscription_covers": list(subscription_covers or []),
        "collectives": collectives,
        "has_multiple_memberships": len(all_memberships) > 1,
        "studio_access_mode": studio_access_mode,
    }


async def create_collective_draft(
    session: AsyncSession,
    *,
    slug: str,
    display_name: str,
    tagline: str | None = None,
    seat_limit: int = 5,
    primary_arena_id: int | None = None,
    schedule_mode: str = SCHEDULE_MODE_MEMBER_AUTONOMOUS,
    owner_studio_access_mode: str = STUDIO_ACCESS_MODE_FULL,
    organization_format: str = ORG_FORMAT_STUDIO,
) -> dict[str, Any]:
    """Admin: create draft studio before owner claim."""
    norm_slug = normalize_collective_slug(slug)
    if not norm_slug:
        raise ValueError("slug_invalid")
    name = (display_name or "").strip()
    if not name:
        raise ValueError("display_name_required")
    if schedule_mode not in (SCHEDULE_MODE_MEMBER_AUTONOMOUS, SCHEDULE_MODE_STUDIO_CENTRAL):
        raise ValueError("invalid_schedule_mode")
    if owner_studio_access_mode not in (STUDIO_ACCESS_MODE_FULL, STUDIO_ACCESS_MODE_ADMIN_ONLY):
        raise ValueError("invalid_owner_studio_access_mode")
    fmt = normalize_organization_format(organization_format)
    if fmt not in CANONICAL_ORG_FORMATS:
        fmt = derive_stored_organization_format(schedule_mode, owner_studio_access_mode)
    limit = max(COLLECTIVE_DRAFT_SEAT_MIN, min(int(seat_limit), COLLECTIVE_DRAFT_SEAT_MAX))
    now = datetime.now(timezone.utc)
    result = await session.execute(
        text(
            """
            INSERT INTO collectives (
                slug, display_name, tagline, primary_arena_id,
                status, seat_limit, schedule_mode,
                owner_studio_access_mode, organization_format,
                created_at, updated_at
            )
            VALUES (
                :slug, :name, :tagline, :arena_id,
                :status, :seat_limit, :schedule_mode,
                :owner_mode, :org_format,
                :now, :now
            )
            RETURNING id, slug, display_name, status, seat_limit, schedule_mode,
                      owner_studio_access_mode, organization_format
            """
        ),
        {
            "slug": norm_slug,
            "name": name[:128],
            "tagline": (tagline or "").strip()[:2000] or None,
            "arena_id": primary_arena_id,
            "status": COLLECTIVE_STATUS_DRAFT,
            "seat_limit": limit,
            "schedule_mode": schedule_mode,
            "owner_mode": owner_studio_access_mode,
            "org_format": fmt,
            "now": now,
        },
    )
    row = result.fetchone()
    await session.commit()
    if row is None:
        raise RuntimeError("collective_insert_failed")
    return {
        "id": int(row[0]),
        "slug": str(row[1]),
        "display_name": str(row[2]),
        "status": str(row[3]),
        "seat_limit": int(row[4]),
        "schedule_mode": str(row[5]),
        "owner_studio_access_mode": str(row[6]),
        "organization_format": str(row[7]),
    }


async def issue_collective_claim_token(
    session: AsyncSession,
    collective_id: int,
    *,
    expire_days: int = DEFAULT_COLLECTIVE_CLAIM_EXPIRE_DAYS,
) -> dict[str, Any] | None:
    """One-time owner activation link for a draft collective."""
    check = await session.execute(
        text("SELECT id, slug, status FROM collectives WHERE id = :id"),
        {"id": collective_id},
    )
    row = check.fetchone()
    if row is None:
        return None
    if str(row[2]) != COLLECTIVE_STATUS_DRAFT:
        return None

    days = max(1, min(int(expire_days), 90))
    raw = secrets.token_urlsafe(32)
    token = raw[:64] if len(raw) > 64 else raw
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=days)

    await session.execute(
        text(
            """
            INSERT INTO collective_tokens (token, kind, collective_id, expires_at, created_at)
            VALUES (:token, :kind, :cid, :exp, :now)
            """
        ),
        {
            "token": token,
            "kind": TOKEN_KIND_CLAIM,
            "cid": collective_id,
            "exp": expires_at,
            "now": now,
        },
    )
    await session.commit()

    settings = Settings()
    trainer_uname = (getattr(settings, "trainer_bot_username", None) or "").strip().lstrip("@")
    start_payload = f"col_claim_{token}"
    deep_link = f"https://t.me/{trainer_uname}?start={start_payload}" if trainer_uname else None

    return {
        "collective_id": collective_id,
        "slug": str(row[1]),
        "token": token,
        "start_payload": start_payload,
        "expires_at": expires_at.isoformat(),
        "deep_link": deep_link,
    }


async def consume_collective_claim_token(
    session: AsyncSession,
    token: str,
    trainer_id: int,
) -> ConsumeCollectiveClaimResult:
    """
    Assign owner to draft collective and activate studio.

    Caller must ensure trainer_id is linked to the Telegram user opening the link.
    """
    now = datetime.now(timezone.utc)
    tok = (token or "").strip()
    if not tok:
        return ConsumeCollectiveClaimResult(error="invalid_token")

    result = await session.execute(
        text(
            """
            SELECT ct.collective_id, c.slug, c.display_name, c.status,
                   c.owner_studio_access_mode
            FROM collective_tokens ct
            INNER JOIN collectives c ON c.id = ct.collective_id
            WHERE ct.token = :token
              AND ct.kind = :kind
              AND ct.used_at IS NULL
              AND ct.expires_at > :now
            FOR UPDATE OF ct
            """
        ),
        {"token": tok, "kind": TOKEN_KIND_CLAIM, "now": now},
    )
    row = result.fetchone()
    if row is None:
        return ConsumeCollectiveClaimResult(error="invalid_token")

    collective_id = int(row[0])
    slug = str(row[1])
    display_name = str(row[2])
    status = str(row[3])
    owner_access_mode = str(row[4] or STUDIO_ACCESS_MODE_FULL).strip()
    if owner_access_mode not in (STUDIO_ACCESS_MODE_FULL, STUDIO_ACCESS_MODE_ADMIN_ONLY):
        owner_access_mode = STUDIO_ACCESS_MODE_FULL
    if status != COLLECTIVE_STATUS_DRAFT:
        return ConsumeCollectiveClaimResult(error="collective_not_draft")

    dup_member = await session.execute(
        text(
            """
            SELECT 1 FROM collective_members
            WHERE collective_id = :cid AND trainer_id = :tid AND status = :active
            """
        ),
        {"cid": collective_id, "tid": trainer_id, "active": MEMBER_STATUS_ACTIVE},
    )
    if dup_member.fetchone():
        return ConsumeCollectiveClaimResult(error="already_in_collective")

    owner_check = await session.execute(
        text("SELECT owner_trainer_id FROM collectives WHERE id = :id FOR UPDATE"),
        {"id": collective_id},
    )
    owner_row = owner_check.fetchone()
    if owner_row is None:
        return ConsumeCollectiveClaimResult(error="collective_missing")
    if owner_row[0] is not None and int(owner_row[0]) != trainer_id:
        return ConsumeCollectiveClaimResult(error="already_claimed")

    await session.execute(
        text(
            """
            UPDATE collectives
            SET owner_trainer_id = :tid,
                status = :active,
                updated_at = :now
            WHERE id = :cid
            """
        ),
        {
            "tid": trainer_id,
            "active": COLLECTIVE_STATUS_ACTIVE,
            "now": now,
            "cid": collective_id,
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO collective_members (
                collective_id, trainer_id, role, status, joined_at
            )
            VALUES (:cid, :tid, :role, :status, :now)
            ON CONFLICT (collective_id, trainer_id)
            DO UPDATE SET
                role = EXCLUDED.role,
                status = EXCLUDED.status,
                joined_at = EXCLUDED.joined_at,
                left_at = NULL
            """
        ),
        {
            "cid": collective_id,
            "tid": trainer_id,
            "role": MEMBER_ROLE_OWNER,
            "status": MEMBER_STATUS_ACTIVE,
            "now": now,
        },
    )
    await session.execute(
        text(
            """
            UPDATE trainers
            SET studio_access_mode = :mode
            WHERE id = :tid
            """
        ),
        {"mode": owner_access_mode, "tid": int(trainer_id)},
    )
    await session.execute(
        text("UPDATE collective_tokens SET used_at = :now WHERE token = :token"),
        {"now": now, "token": tok},
    )
    await session.commit()
    return ConsumeCollectiveClaimResult(
        collective_id=collective_id,
        slug=slug,
        display_name=display_name,
    )


async def count_active_collective_members(session: AsyncSession, collective_id: int) -> int:
    result = await session.execute(
        text(
            """
            SELECT COUNT(*)::int
            FROM collective_members
            WHERE collective_id = :cid AND status = :active
            """
        ),
        {"cid": collective_id, "active": MEMBER_STATUS_ACTIVE},
    )
    row = result.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def collective_storage_key_allowed(collective_id: int, file_key: str | None) -> bool:
    prefix = f"collectives/{collective_id}/"
    return s3.resolve_object_key_under_prefixes(file_key, (prefix,)) is not None


def _row_to_collective_dict(row: Any) -> dict[str, Any]:
    return {
        "id": int(row[0]),
        "slug": str(row[1]),
        "display_name": str(row[2]),
        "tagline": (str(row[3]).strip() if row[3] else None),
        "logo_key": (str(row[4]).strip() if row[4] else None),
        "cover_key": (str(row[5]).strip() if row[5] else None),
        "about": (str(row[6]).strip() if row[6] else None),
        "gallery_keys": normalize_gallery_keys(row[7]),
        "brand_tokens": row[8],
        "primary_arena_id": int(row[9]) if row[9] is not None else None,
        "status": str(row[10]),
        "seat_limit": int(row[11]),
        "schedule_mode": str(row[12]) if len(row) > 12 and row[12] else SCHEDULE_MODE_MEMBER_AUTONOMOUS,
        "organization_format": normalize_organization_format(
            str(row[13]) if len(row) > 13 and row[13] else None
        ),
    }


def collective_brand_kit_enrichment(
    row: dict[str, Any],
    *,
    include_owner_options: bool = False,
) -> dict[str, Any]:
    gallery = normalize_gallery_keys(row.get("gallery_keys"))
    tokens = normalize_brand_tokens(row.get("brand_tokens"))
    accent = resolve_accent_preset(tokens["accent_preset"])
    payload: dict[str, Any] = {
        "logo_url": public_asset_url(row.get("logo_key")),
        "cover_key": row.get("cover_key"),
        "cover_url": public_asset_url(row.get("cover_key")),
        "about": (row.get("about") or "").strip() or None,
        "gallery_keys": gallery,
        "gallery": [{"key": key, "url": public_asset_url(key)} for key in gallery],
        "accent_preset": accent["id"],
        "accent": {
            "accent": accent.get("accent"),
            "accent_soft": accent.get("accent_soft"),
            "accent_border": accent.get("accent_border"),
        },
        "contacts": dict(tokens.get("contacts") or {}),
    }
    if include_owner_options:
        payload["accent_presets"] = list_accent_preset_options()
    return payload


async def collective_location_payload(
    session: AsyncSession,
    row: dict[str, Any],
) -> dict[str, Any]:
    """Resolved studio city/venue for admin UI and public landing."""
    tokens = normalize_brand_tokens(row.get("brand_tokens"))
    default_city_id = tokens.get("default_city_id")
    default_city_name: str | None = None
    if default_city_id is not None:
        city_row = await session.execute(
            text("SELECT name FROM cities WHERE id = :cid AND is_active LIMIT 1"),
            {"cid": default_city_id},
        )
        city_val = city_row.fetchone()
        if city_val is None:
            default_city_id = None
        else:
            default_city_name = str(city_val[0]).strip() or None

    primary_arena_id = row.get("primary_arena_id")
    primary_arena_name: str | None = None
    primary_arena_city_name: str | None = None
    primary_arena_city_id: int | None = None
    if primary_arena_id is not None:
        arena_row = await session.execute(
            text(
                """
                SELECT a.name, c.name, c.id
                FROM arenas a
                LEFT JOIN cities c ON c.id = a.city_id
                WHERE a.id = :aid AND a.is_active
                LIMIT 1
                """
            ),
            {"aid": primary_arena_id},
        )
        arena_val = arena_row.fetchone()
        if arena_val is None:
            primary_arena_id = None
        else:
            primary_arena_name = (str(arena_val[0]).strip() if arena_val[0] else None) or None
            primary_arena_city_name = (str(arena_val[1]).strip() if arena_val[1] else None) or None
            primary_arena_city_id = int(arena_val[2]) if arena_val[2] is not None else None

    slug = (row.get("slug") or "").strip()
    return {
        "default_city_id": default_city_id,
        "default_city_name": default_city_name,
        "primary_arena_id": primary_arena_id,
        "primary_arena_name": primary_arena_name,
        "primary_arena_city_name": primary_arena_city_name,
        "primary_arena_city_id": primary_arena_city_id,
        "catalog_webapp_url": build_collective_catalog_webapp_url(
            slug,
            default_city_id=default_city_id,
        ),
    }


async def get_collective_by_slug(
    session: AsyncSession,
    slug: str,
    *,
    active_only: bool = True,
) -> dict[str, Any] | None:
    norm = normalize_collective_slug(slug)
    if not norm:
        return None
    status_clause = " AND status = :active" if active_only else ""
    result = await session.execute(
        text(
            f"""
            SELECT {_COLLECTIVE_ROW_SELECT}
            FROM collectives
            WHERE slug = :slug{status_clause}
            LIMIT 1
            """
        ),
        {"slug": norm, "active": COLLECTIVE_STATUS_ACTIVE} if active_only else {"slug": norm},
    )
    row = result.fetchone()
    if row is None:
        return None
    return _row_to_collective_dict(row)


async def list_active_trainer_ids_for_collective_slug(
    session: AsyncSession,
    slug: str,
) -> list[int] | None:
    """Trainer ids for catalog filter; None when slug unknown or studio not active."""
    collective = await get_collective_by_slug(session, slug, active_only=True)
    if collective is None:
        return None
    result = await session.execute(
        text(
            """
            SELECT cm.trainer_id
            FROM collective_members cm
            WHERE cm.collective_id = :cid AND cm.status = :active
            ORDER BY cm.trainer_id
            """
        ),
        {"cid": collective["id"], "active": MEMBER_STATUS_ACTIVE},
    )
    return [int(r[0]) for r in result.fetchall()]


async def list_collective_members_for_studio(
    session: AsyncSession,
    collective_id: int,
) -> list[dict[str, Any]]:
    result = await session.execute(
        text(
            """
            SELECT
                cm.trainer_id,
                cm.role,
                cm.status,
                cm.joined_at,
                tp.first_name,
                tp.last_name,
                t.telegram_username
            FROM collective_members cm
            INNER JOIN trainers t ON t.id = cm.trainer_id
            LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
            WHERE cm.collective_id = :cid
              AND cm.status IN (:active, :invited)
            ORDER BY
                CASE cm.role WHEN :owner THEN 0 ELSE 1 END,
                cm.joined_at NULLS LAST,
                cm.trainer_id
            """
        ),
        {
            "cid": collective_id,
            "active": MEMBER_STATUS_ACTIVE,
            "invited": MEMBER_STATUS_INVITED,
            "owner": MEMBER_ROLE_OWNER,
        },
    )
    out: list[dict[str, Any]] = []
    for row in result.fetchall():
        first = (str(row[4]).strip() if row[4] else "") or ""
        last = (str(row[5]).strip() if row[5] else "") or ""
        display = " ".join(p for p in (first, last) if p).strip()
        out.append(
            {
                "trainer_id": int(row[0]),
                "role": str(row[1]),
                "status": str(row[2]),
                "joined_at": row[3].isoformat() if row[3] else None,
                "display_name": display or None,
                "telegram_username": (str(row[6]).strip() if row[6] else None),
            }
        )
    return out


def build_trainer_collective_invite_deep_link(token: str) -> str | None:
    settings = Settings()
    trainer_uname = (getattr(settings, "trainer_bot_username", None) or "").strip().lstrip("@")
    if not trainer_uname:
        return None
    return f"https://t.me/{trainer_uname}?start=col_inv_{token}"


async def ensure_trainer_id_for_collective_bot_user(
    session: AsyncSession,
    telegram_id: int,
    *,
    telegram_username: str | None = None,
) -> tuple[int | None, str | None]:
    """
    Resolve trainer id for collective claim/invite deep links.

    Creates pending_profile trainer when Telegram is not linked yet.
    """
    from sqlalchemy.exc import IntegrityError

    from src.application.trainer_link import get_trainer_id_by_telegram_id

    existing = await get_trainer_id_by_telegram_id(session, telegram_id)
    if existing is not None:
        return existing, None

    username_val = (telegram_username or "").strip()[:64] or None
    now = datetime.now(timezone.utc)
    created = await session.execute(
        text(
            """
            INSERT INTO trainers (status, telegram_id, telegram_username, created_at)
            VALUES (:st, :tid, :tuname, :now)
            RETURNING id
            """
        ),
        {
            "st": TRAINER_STATUS_PENDING_PROFILE,
            "tid": telegram_id,
            "tuname": username_val,
            "now": now,
        },
    )
    row = created.fetchone()
    if row is None:
        return None, "create_failed"
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        retry = await get_trainer_id_by_telegram_id(session, telegram_id)
        if retry is not None:
            return retry, None
        return None, "telegram_other_trainer"
    return int(row[0]), None


async def _assert_collective_owner(
    session: AsyncSession,
    collective_id: int,
    trainer_id: int,
) -> str | None:
    result = await session.execute(
        text(
            """
            SELECT c.status, c.owner_trainer_id
            FROM collectives c
            WHERE c.id = :cid
            """
        ),
        {"cid": collective_id},
    )
    row = result.fetchone()
    if row is None:
        return "collective_missing"
    if str(row[0]) != COLLECTIVE_STATUS_ACTIVE:
        return "collective_not_active"
    if row[1] is None or int(row[1]) != trainer_id:
        return "not_owner"
    return None


async def _assert_collective_studio_admin(
    session: AsyncSession,
    collective_id: int,
    trainer_id: int,
) -> str | None:
    """Owner (collectives.owner_trainer_id or member role) or studio admin member."""
    result = await session.execute(
        text(
            """
            SELECT c.status, c.owner_trainer_id
            FROM collectives c
            WHERE c.id = :cid
            """
        ),
        {"cid": collective_id},
    )
    row = result.fetchone()
    if row is None:
        return "collective_missing"
    if str(row[0]) != COLLECTIVE_STATUS_ACTIVE:
        return "collective_not_active"
    if row[1] is not None and int(row[1]) == int(trainer_id):
        return None
    mem = await session.execute(
        text(
            """
            SELECT role FROM collective_members
            WHERE collective_id = :cid AND trainer_id = :tid AND status = :active
            """
        ),
        {
            "cid": collective_id,
            "tid": int(trainer_id),
            "active": MEMBER_STATUS_ACTIVE,
        },
    )
    mem_row = mem.fetchone()
    if mem_row is None:
        return "not_studio_admin"
    if is_collective_studio_admin_role(str(mem_row[0])):
        return None
    return "not_studio_admin"


async def promote_collective_member_to_admin(
    session: AsyncSession,
    collective_id: int,
    owner_trainer_id: int,
    target_trainer_id: int,
) -> dict[str, Any]:
    """Owner promotes an active member to studio admin (W5)."""
    owner_err = await _assert_collective_owner(session, collective_id, owner_trainer_id)
    if owner_err:
        return {"error": owner_err}
    if int(target_trainer_id) == int(owner_trainer_id):
        return {"error": "cannot_promote_owner"}
    target_row = await session.execute(
        text(
            """
            SELECT role, status FROM collective_members
            WHERE collective_id = :cid AND trainer_id = :tid
            FOR UPDATE
            """
        ),
        {"cid": collective_id, "tid": int(target_trainer_id)},
    )
    row = target_row.fetchone()
    if row is None:
        return {"error": "member_not_found"}
    if str(row[1]) != MEMBER_STATUS_ACTIVE:
        return {"error": "target_not_active_member"}
    if str(row[0]) == MEMBER_ROLE_OWNER:
        return {"error": "already_owner"}
    if str(row[0]) == MEMBER_ROLE_ADMIN:
        return {"error": "already_admin"}
    await session.execute(
        text(
            """
            UPDATE collective_members SET role = :admin
            WHERE collective_id = :cid AND trainer_id = :tid
            """
        ),
        {"admin": MEMBER_ROLE_ADMIN, "cid": collective_id, "tid": int(target_trainer_id)},
    )
    await session.commit()
    return {"promoted_trainer_id": int(target_trainer_id), "role": MEMBER_ROLE_ADMIN}


async def issue_collective_invite_token(
    session: AsyncSession,
    collective_id: int,
    issuer_trainer_id: int,
    *,
    expire_days: int = DEFAULT_COLLECTIVE_INVITE_EXPIRE_DAYS,
) -> dict[str, Any] | None:
    """Owner-only one-time invite for a new studio member."""
    owner_err = await _assert_collective_owner(session, collective_id, issuer_trainer_id)
    if owner_err:
        return None

    seat_row = await session.execute(
        text("SELECT seat_limit FROM collectives WHERE id = :id"),
        {"id": collective_id},
    )
    seat = seat_row.fetchone()
    if seat is None:
        return None
    seat_limit = int(seat[0])
    active_count = await count_active_collective_members(session, collective_id)
    if active_count >= seat_limit:
        return {"error": "seats_full", "seat_limit": seat_limit, "active_count": active_count}

    days = max(1, min(int(expire_days), 90))
    raw = secrets.token_urlsafe(32)
    token = raw[:64] if len(raw) > 64 else raw
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=days)

    await session.execute(
        text(
            """
            INSERT INTO collective_tokens (token, kind, collective_id, expires_at, created_at)
            VALUES (:token, :kind, :cid, :exp, :now)
            """
        ),
        {
            "token": token,
            "kind": TOKEN_KIND_INVITE,
            "cid": collective_id,
            "exp": expires_at,
            "now": now,
        },
    )
    await session.commit()

    return {
        "collective_id": collective_id,
        "token": token,
        "start_payload": f"col_inv_{token}",
        "expires_at": expires_at.isoformat(),
        "deep_link": build_trainer_collective_invite_deep_link(token),
        "seat_limit": seat_limit,
        "active_count": active_count,
    }


async def count_pending_collective_invite_tokens(
    session: AsyncSession,
    collective_id: int,
) -> int:
    """Unused, non-expired invite tokens awaiting col_inv_* consumption."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        text(
            """
            SELECT COUNT(*)::int
            FROM collective_tokens
            WHERE collective_id = :cid
              AND kind = :kind
              AND used_at IS NULL
              AND expires_at > :now
            """
        ),
        {"cid": collective_id, "kind": TOKEN_KIND_INVITE, "now": now},
    )
    row = result.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


async def revoke_pending_collective_invites(
    session: AsyncSession,
    collective_id: int,
    owner_trainer_id: int,
) -> dict[str, Any]:
    """Owner invalidates all outstanding invite links."""
    owner_err = await _assert_collective_owner(session, collective_id, owner_trainer_id)
    if owner_err:
        return {"error": owner_err}

    now = datetime.now(timezone.utc)
    result = await session.execute(
        text(
            """
            UPDATE collective_tokens
            SET used_at = :now
            WHERE collective_id = :cid
              AND kind = :kind
              AND used_at IS NULL
              AND expires_at > :now
            RETURNING id
            """
        ),
        {"cid": collective_id, "kind": TOKEN_KIND_INVITE, "now": now},
    )
    revoked = len(result.fetchall())
    await session.commit()
    return {"revoked_count": revoked}


async def remove_collective_member(
    session: AsyncSession,
    collective_id: int,
    owner_trainer_id: int,
    target_trainer_id: int,
) -> dict[str, Any]:
    """Owner removes an active member or cancels a pending invited row."""
    owner_err = await _assert_collective_owner(session, collective_id, owner_trainer_id)
    if owner_err:
        return {"error": owner_err}
    if int(target_trainer_id) == int(owner_trainer_id):
        return {"error": "cannot_remove_self"}

    member_row = await session.execute(
        text(
            """
            SELECT role, status
            FROM collective_members
            WHERE collective_id = :cid AND trainer_id = :tid
            FOR UPDATE
            """
        ),
        {"cid": collective_id, "tid": int(target_trainer_id)},
    )
    row = member_row.fetchone()
    if row is None:
        return {"error": "member_not_found"}
    role = str(row[0])
    status = str(row[1])
    if role == MEMBER_ROLE_OWNER:
        return {"error": "cannot_remove_owner"}
    if status not in (MEMBER_STATUS_ACTIVE, MEMBER_STATUS_INVITED):
        return {"error": "member_not_removable"}

    now = datetime.now(timezone.utc)
    await session.execute(
        text(
            """
            UPDATE collective_members
            SET status = :left, left_at = :now
            WHERE collective_id = :cid AND trainer_id = :tid
            """
        ),
        {
            "left": MEMBER_STATUS_LEFT,
            "now": now,
            "cid": collective_id,
            "tid": int(target_trainer_id),
        },
    )
    await session.commit()
    return {"removed_trainer_id": int(target_trainer_id)}


async def preview_collective_member_removal(
    session: AsyncSession,
    collective_id: int,
    owner_trainer_id: int,
    target_trainer_id: int,
) -> dict[str, Any]:
    """Soft validation before owner removes a member (O7.3)."""
    owner_err = await _assert_collective_owner(session, collective_id, owner_trainer_id)
    if owner_err:
        return {"error": owner_err}

    member_row = await session.execute(
        text(
            """
            SELECT role, status
            FROM collective_members
            WHERE collective_id = :cid AND trainer_id = :tid
            """
        ),
        {"cid": collective_id, "tid": int(target_trainer_id)},
    )
    row = member_row.fetchone()
    if row is None:
        return {"error": "member_not_found"}
    if str(row[0]) == MEMBER_ROLE_OWNER:
        return {"error": "cannot_remove_owner"}
    if int(target_trainer_id) == int(owner_trainer_id):
        return {"error": "cannot_remove_self"}

    today = date.today()
    duty_r = await session.execute(
        text(
            """
            SELECT COUNT(*)::int
            FROM collective_session_coaches csc
            INNER JOIN collective_sessions cs ON cs.id = csc.collective_session_id
            WHERE cs.collective_id = :cid
              AND csc.trainer_id = :tid
              AND cs.slot_date >= :today
              AND cs.status = 'available'
            """
        ),
        {"cid": collective_id, "tid": int(target_trainer_id), "today": today},
    )
    future_duty_sessions = int(duty_r.scalar_one() or 0)

    bookings_r = await session.execute(
        text(
            """
            SELECT COUNT(*)::int
            FROM collective_session_bookings b
            INNER JOIN collective_sessions cs ON cs.id = b.collective_session_id
            WHERE b.collective_id = :cid
              AND b.status IN ('pending', 'confirmed')
              AND cs.slot_date >= :today
              AND (b.trainer_id = :tid OR b.center_coach_id = :tid)
            """
        ),
        {"cid": collective_id, "tid": int(target_trainer_id), "today": today},
    )
    active_center_bookings = int(bookings_r.scalar_one() or 0)

    warnings: list[str] = []
    if future_duty_sessions:
        warnings.append(
            f"У тренера {future_duty_sessions} будущих смен в сетке — снимите назначение или дождитесь даты."
        )
    if active_center_bookings:
        warnings.append(
            f"Есть {active_center_bookings} активных записей в центре с участием этого тренера."
        )

    return {
        "future_duty_sessions": future_duty_sessions,
        "active_center_bookings": active_center_bookings,
        "warnings": warnings,
    }


async def transfer_collective_ownership(
    session: AsyncSession,
    collective_id: int,
    owner_trainer_id: int,
    new_owner_trainer_id: int,
) -> dict[str, Any]:
    """Owner passes studio control to another active member."""
    owner_err = await _assert_collective_owner(session, collective_id, owner_trainer_id)
    if owner_err:
        return {"error": owner_err}

    new_tid = int(new_owner_trainer_id)
    old_tid = int(owner_trainer_id)
    if new_tid == old_tid:
        return {"error": "same_owner"}

    target_row = await session.execute(
        text(
            """
            SELECT status
            FROM collective_members
            WHERE collective_id = :cid AND trainer_id = :tid
            FOR UPDATE
            """
        ),
        {"cid": collective_id, "tid": new_tid},
    )
    target = target_row.fetchone()
    if target is None or str(target[0]) != MEMBER_STATUS_ACTIVE:
        return {"error": "target_not_active_member"}

    now = datetime.now(timezone.utc)
    await session.execute(
        text(
            """
            UPDATE collectives
            SET owner_trainer_id = :new_owner, updated_at = :now
            WHERE id = :cid
            """
        ),
        {"new_owner": new_tid, "now": now, "cid": collective_id},
    )
    await session.execute(
        text(
            """
            UPDATE collective_members
            SET role = :member
            WHERE collective_id = :cid AND trainer_id = :old_owner
            """
        ),
        {"member": MEMBER_ROLE_MEMBER, "cid": collective_id, "old_owner": old_tid},
    )
    await session.execute(
        text(
            """
            UPDATE collective_members
            SET role = :owner
            WHERE collective_id = :cid AND trainer_id = :new_owner
            """
        ),
        {"owner": MEMBER_ROLE_OWNER, "cid": collective_id, "new_owner": new_tid},
    )
    await session.commit()
    return {"new_owner_trainer_id": new_tid, "previous_owner_trainer_id": old_tid}


async def resolve_certificate_brand_for_trainer(
    session: AsyncSession,
    trainer_id: int,
) -> dict[str, str | None]:
    """
    Certificate PDF brand: studio white-label when trainer is an active collective member.
    Foot line may include platform powered-by attribution.
    """
    settings = Settings()
    platform = (settings.certificate_pdf_brand_display_name or "GLIDE").strip() or "GLIDE"
    platform_tagline = (settings.certificate_pdf_brand_tagline_ru or "").strip()

    membership = await get_active_collective_membership(session, trainer_id)
    if membership is None:
        return {
            "display_name": platform,
            "tagline": platform_tagline,
            "powered_by": None,
        }

    display = (membership.display_name or "").strip() or platform
    tagline = (membership.tagline or "").strip() or platform_tagline
    return {
        "display_name": display,
        "tagline": tagline,
        "powered_by": platform if display != platform else None,
    }


async def consume_collective_invite_token(
    session: AsyncSession,
    token: str,
    trainer_id: int,
) -> ConsumeCollectiveInviteResult:
    """Join active studio as member via col_inv_* deep link."""
    now = datetime.now(timezone.utc)
    tok = (token or "").strip()
    if not tok:
        return ConsumeCollectiveInviteResult(error="invalid_token")

    result = await session.execute(
        text(
            """
            SELECT ct.collective_id, c.slug, c.display_name, c.status, c.seat_limit
            FROM collective_tokens ct
            INNER JOIN collectives c ON c.id = ct.collective_id
            WHERE ct.token = :token
              AND ct.kind = :kind
              AND ct.used_at IS NULL
              AND ct.expires_at > :now
            FOR UPDATE OF ct
            """
        ),
        {"token": tok, "kind": TOKEN_KIND_INVITE, "now": now},
    )
    row = result.fetchone()
    if row is None:
        return ConsumeCollectiveInviteResult(error="invalid_token")

    collective_id = int(row[0])
    slug = str(row[1])
    display_name = str(row[2])
    status = str(row[3])
    seat_limit = int(row[4])
    if status != COLLECTIVE_STATUS_ACTIVE:
        return ConsumeCollectiveInviteResult(error="collective_not_active")

    dup_member = await session.execute(
        text(
            """
            SELECT 1 FROM collective_members
            WHERE collective_id = :cid AND trainer_id = :tid AND status = :active
            """
        ),
        {"cid": collective_id, "tid": trainer_id, "active": MEMBER_STATUS_ACTIVE},
    )
    if dup_member.fetchone():
        return ConsumeCollectiveInviteResult(error="already_member")

    active_count = await count_active_collective_members(session, collective_id)
    if active_count >= seat_limit:
        return ConsumeCollectiveInviteResult(error="seats_full")

    await session.execute(
        text(
            """
            INSERT INTO collective_members (
                collective_id, trainer_id, role, status, joined_at
            )
            VALUES (:cid, :tid, :role, :status, :now)
            ON CONFLICT (collective_id, trainer_id)
            DO UPDATE SET
                role = EXCLUDED.role,
                status = EXCLUDED.status,
                joined_at = EXCLUDED.joined_at,
                left_at = NULL
            """
        ),
        {
            "cid": collective_id,
            "tid": trainer_id,
            "role": MEMBER_ROLE_MEMBER,
            "status": MEMBER_STATUS_ACTIVE,
            "now": now,
        },
    )
    await session.execute(
        text("UPDATE collective_tokens SET used_at = :now WHERE token = :token"),
        {"now": now, "token": tok},
    )
    await session.commit()
    return ConsumeCollectiveInviteResult(
        collective_id=collective_id,
        slug=slug,
        display_name=display_name,
    )


def _infer_collective_subscription_tier(modules: dict[str, bool]) -> str:
    mods = normalize_modules_dict(modules)
    if mods.get("analytics"):
        return SUBSCRIPTION_TIER_ANALYTICS
    if mods.get("online"):
        return SUBSCRIPTION_TIER_ONLINE
    return SUBSCRIPTION_TIER_CRM


def _format_collective_modules_ru(modules: dict[str, bool]) -> str:
    mods = normalize_modules_dict(modules)
    parts = ["CRM"]
    for key, label in (("online", "online"), ("analytics", "analytics"), ("groups", "groups")):
        if mods.get(key):
            parts.append(label)
    return ", ".join(parts)


COLLECTIVE_MODULE_LABELS_RU: dict[str, str] = {
    "online": "Онлайн-запись",
    "analytics": "Аналитика",
    "groups": "Групповые занятия",
}


def format_collective_modules_list_ru(modules: dict[str, bool] | None) -> list[str]:
    """Human module names for studio subscription UI."""
    mods = normalize_modules_dict(modules or {})
    labels = ["CRM"]
    for key, label in COLLECTIVE_MODULE_LABELS_RU.items():
        if mods.get(key):
            labels.append(label)
    return labels


def studio_subscription_pool_payload(status: dict[str, Any] | None) -> dict[str, Any]:
    """Compact pool subscription slice for trainer «Студия» screen."""
    if not status:
        return {"active": False, "seats_used": 0, "seat_limit": 0}
    active = status.get("active_subscription")
    seats_used = int(status.get("active_member_count") or 0)
    seat_limit = int(status.get("seat_limit") or 0)
    payload: dict[str, Any] = {
        "active": active is not None,
        "seats_used": seats_used,
        "seat_limit": seat_limit,
        "seats_label": f"{seats_used} / {seat_limit} мест",
    }
    if active:
        expires_at = active.get("expires_at")
        payload["expires_at"] = expires_at
        payload["expires_date"] = expires_at[:10] if isinstance(expires_at, str) and len(expires_at) >= 10 else None
        payload["modules"] = format_collective_modules_list_ru(active.get("modules"))
        payload["tier"] = active.get("tier")
    return payload


async def get_collective_subscription_status(
    session: AsyncSession,
    *,
    slug: str | None = None,
    collective_id: int | None = None,
) -> dict[str, Any] | None:
    """Admin / studio: current and upcoming collective subscription rows."""
    collective: dict[str, Any] | None
    if collective_id is not None:
        result = await session.execute(
            text(
                """
                SELECT id, slug, display_name, status, seat_limit
                FROM collectives
                WHERE id = :id
                LIMIT 1
                """
            ),
            {"id": int(collective_id)},
        )
        row = result.fetchone()
        if row is None:
            return None
        collective = {
            "id": int(row[0]),
            "slug": str(row[1]),
            "display_name": str(row[2]),
            "status": str(row[3]),
            "seat_limit": int(row[4]),
        }
    else:
        collective = await get_collective_by_slug(session, slug or "", active_only=False)
    if collective is None:
        return None

    now = datetime.now(timezone.utc)
    subs_result = await session.execute(
        text(
            """
            SELECT tier, modules, status, started_at, expires_at
            FROM collective_subscriptions
            WHERE collective_id = :cid
            ORDER BY expires_at DESC
            LIMIT 5
            """
        ),
        {"cid": collective["id"]},
    )
    rows = subs_result.fetchall()
    active: dict[str, Any] | None = None
    history: list[dict[str, Any]] = []
    for row in rows:
        item = {
            "tier": str(row[0]) if row[0] is not None else None,
            "modules": normalize_modules_dict(row[1]),
            "status": str(row[2]),
            "started_at": row[3].isoformat() if row[3] else None,
            "expires_at": row[4].isoformat() if row[4] else None,
        }
        history.append(item)
        if active is None and row[3] <= now < row[4] and str(row[2]) in (
            SUBSCRIPTION_STATUS_TRIAL,
            SUBSCRIPTION_STATUS_ACTIVE,
        ):
            active = item

    active_count = await count_active_collective_members(session, int(collective["id"]))
    return {
        "collective_id": collective["id"],
        "slug": collective["slug"],
        "display_name": collective["display_name"],
        "status": collective["status"],
        "seat_limit": collective["seat_limit"],
        "active_member_count": active_count,
        "active_subscription": active,
        "history": history,
    }


async def count_pending_collective_claim_tokens(
    session: AsyncSession,
    collective_id: int,
) -> int:
    """Unused, non-expired owner claim tokens awaiting col_claim_* consumption."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        text(
            """
            SELECT COUNT(*)::int
            FROM collective_tokens
            WHERE collective_id = :cid
              AND kind = :kind
              AND used_at IS NULL
              AND expires_at > :now
            """
        ),
        {"cid": int(collective_id), "kind": TOKEN_KIND_CLAIM, "now": now},
    )
    row = result.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _owner_access_mode_label_ru(mode: str | None) -> str:
    if (mode or "").strip() == STUDIO_ACCESS_MODE_ADMIN_ONLY:
        return "manager (studio_admin_only)"
    return "trainer (full_trainer)"


def _collective_claim_state_label(
    *,
    collective_status: str,
    owner_trainer_id: int | None,
    pending_claim_tokens: int,
) -> str:
    if collective_status == COLLECTIVE_STATUS_DRAFT:
        if owner_trainer_id is not None:
            return "draft · owner assigned (unexpected)"
        if pending_claim_tokens > 0:
            return f"draft · claim link outstanding ({pending_claim_tokens})"
        return "draft · no active claim link"
    if owner_trainer_id is None:
        return f"{collective_status} · owner not set"
    return f"{collective_status} · claimed (owner trainer_id={owner_trainer_id})"


async def get_collective_ops_status(
    session: AsyncSession,
    *,
    slug: str,
) -> dict[str, Any] | None:
    """Admin ops snapshot: format, seats, owner mode, claim state (O8.2)."""
    norm = normalize_collective_slug(slug)
    if not norm:
        return None
    result = await session.execute(
        text(
            """
            SELECT id, slug, display_name, status, seat_limit, schedule_mode,
                   organization_format, owner_studio_access_mode, owner_trainer_id
            FROM collectives
            WHERE slug = :slug
            LIMIT 1
            """
        ),
        {"slug": norm},
    )
    row = result.fetchone()
    if row is None:
        return None

    collective_id = int(row[0])
    owner_trainer_id = int(row[8]) if row[8] is not None else None
    collective_status = str(row[3])
    pending_claims = await count_pending_collective_claim_tokens(session, collective_id)
    pending_invites = await count_pending_collective_invite_tokens(session, collective_id)
    active_count = await count_active_collective_members(session, collective_id)

    owner_name: str | None = None
    if owner_trainer_id is not None:
        owner_row = await session.execute(
            text(
                """
                SELECT tp.first_name, tp.last_name, t.telegram_username
                FROM trainers t
                LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
                WHERE t.id = :tid
                LIMIT 1
                """
            ),
            {"tid": owner_trainer_id},
        )
        o = owner_row.fetchone()
        if o:
            fn = (o[0] or "").strip()
            ln = (o[1] or "").strip()
            owner_name = " ".join(filter(None, [fn, ln])).strip() or None
            if not owner_name and o[2]:
                owner_name = f"@{str(o[2]).strip().lstrip('@')}"

    return {
        "collective_id": collective_id,
        "slug": str(row[1]),
        "display_name": str(row[2]),
        "status": collective_status,
        "organization_format": normalize_organization_format(str(row[6]) if row[6] else None),
        "schedule_mode": str(row[5] or SCHEDULE_MODE_MEMBER_AUTONOMOUS),
        "owner_studio_access_mode": str(row[7] or STUDIO_ACCESS_MODE_FULL),
        "owner_studio_access_mode_label": _owner_access_mode_label_ru(str(row[7])),
        "seat_limit": int(row[4]),
        "active_member_count": active_count,
        "pending_invite_count": pending_invites,
        "pending_claim_count": pending_claims,
        "owner_trainer_id": owner_trainer_id,
        "owner_display_name": owner_name,
        "claim_state_label": _collective_claim_state_label(
            collective_status=collective_status,
            owner_trainer_id=owner_trainer_id,
            pending_claim_tokens=pending_claims,
        ),
    }


async def get_trainer_suspended_collective_notice(
    session: AsyncSession,
    trainer_id: int,
) -> dict[str, Any] | None:
    """Banner payload when member's collective is suspended (O8.4)."""
    result = await session.execute(
        text(
            """
            SELECT c.slug, c.display_name, cm.role
            FROM collective_members cm
            INNER JOIN collectives c ON c.id = cm.collective_id
            WHERE cm.trainer_id = :tid
              AND cm.status = :active
              AND c.status = :suspended
            ORDER BY
                CASE cm.role WHEN :owner THEN 0 WHEN :admin THEN 1 ELSE 2 END,
                cm.joined_at NULLS LAST
            LIMIT 1
            """
        ),
        {
            "tid": int(trainer_id),
            "active": MEMBER_STATUS_ACTIVE,
            "suspended": COLLECTIVE_STATUS_SUSPENDED,
            "owner": MEMBER_ROLE_OWNER,
            "admin": MEMBER_ROLE_ADMIN,
        },
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "slug": str(row[0]),
        "display_name": str(row[1]),
        "role": str(row[2]),
        "message": (
            f"«{str(row[1])}» приостановлена — каталог и запись через бренд недоступны. "
            "Личный CRM работает как обычно."
        ),
    }


async def admin_grant_collective_subscription(
    session: AsyncSession,
    *,
    slug: str,
    period_months: int,
    modules: dict[str, bool] | None = None,
    admin_id: int,
    status: str = SUBSCRIPTION_STATUS_ACTIVE,
) -> dict[str, Any] | None:
    """
    Admin pilot grant: insert or extend collective_subscriptions row.

    Default modules: full studio pool (online + analytics + groups).
    """
    norm = normalize_collective_slug(slug)
    if not norm:
        return None
    collective = await get_collective_by_slug(session, norm, active_only=False)
    if collective is None:
        return None
    if collective["status"] not in (COLLECTIVE_STATUS_ACTIVE, COLLECTIVE_STATUS_DRAFT):
        return {"error": "collective_not_grantable", "slug": norm}

    months = int(period_months)
    if months < 1 or months > 24:
        return {"error": "invalid_period"}

    final_modules = normalize_modules_dict(
        modules
        if modules is not None
        else {"online": True, "analytics": True, "groups": True}
    )
    tier = _infer_collective_subscription_tier(final_modules)
    sub_status = status if status in (SUBSCRIPTION_STATUS_TRIAL, SUBSCRIPTION_STATUS_ACTIVE) else SUBSCRIPTION_STATUS_ACTIVE

    now = datetime.now(timezone.utc)
    extend_base = now
    current = await session.execute(
        text(
            """
            SELECT expires_at
            FROM collective_subscriptions
            WHERE collective_id = :cid
              AND started_at <= :now
              AND expires_at > :now
              AND status IN (:s1, :s2)
            ORDER BY expires_at DESC
            LIMIT 1
            """
        ),
        {
            "cid": collective["id"],
            "now": now,
            "s1": SUBSCRIPTION_STATUS_TRIAL,
            "s2": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    cur_row = current.fetchone()
    if cur_row is not None and cur_row[0] is not None:
        extend_base = max(now, cur_row[0])

    expires_at = extend_base + timedelta(days=months * 30)
    started_at = now
    extended_from_existing = cur_row is not None

    await session.execute(
        text(
            """
            INSERT INTO collective_subscriptions (
                collective_id, tier, modules, status, started_at, expires_at
            )
            VALUES (
                :cid, :tier, CAST(:mods AS jsonb), :status, :started, :expires
            )
            """
        ),
        {
            "cid": collective["id"],
            "tier": tier,
            "mods": json.dumps(final_modules),
            "status": sub_status,
            "started": started_at,
            "expires": expires_at,
        },
    )
    await session.commit()

    from src.shared.audit import ACTOR_ADMIN_BOT, audit_log

    audit_log(
        "admin.collective_subscription_granted",
        ACTOR_ADMIN_BOT,
        int(admin_id),
        {
            "collective_id": collective["id"],
            "slug": norm,
            "period_months": months,
            "modules": final_modules,
            "expires_at": expires_at.isoformat(),
        },
    )
    return {
        "collective_id": collective["id"],
        "slug": norm,
        "display_name": collective["display_name"],
        "period_months": months,
        "modules": final_modules,
        "modules_label": _format_collective_modules_ru(final_modules),
        "tier": tier,
        "status": sub_status,
        "started_at": started_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "extended_from_existing": extended_from_existing,
    }


DEFAULT_COLLECTIVE_POOL_MODULES: dict[str, bool] = {
    "online": True,
    "analytics": True,
    "groups": True,
}


def compute_collective_subscription_price_cents(
    seat_limit: int,
    period_months: int,
    *,
    cents_per_seat_month: int | None = None,
) -> int:
    """Pool price = rate × seats × months (BYN cents)."""
    rate = int(
        cents_per_seat_month
        if cents_per_seat_month is not None
        else Settings().collective_subscription_cents_per_seat_month
    )
    return rate * max(1, int(seat_limit)) * int(period_months)


async def _collective_subscription_extend_base(
    session: AsyncSession,
    collective_id: int,
    *,
    now: datetime | None = None,
) -> datetime:
    """Start of new pool period: now or end of current active subscription."""
    ts = now or datetime.now(timezone.utc)
    current = await session.execute(
        text(
            """
            SELECT expires_at
            FROM collective_subscriptions
            WHERE collective_id = :cid
              AND started_at <= :now
              AND expires_at > :now
              AND status IN (:s1, :s2)
            ORDER BY expires_at DESC
            LIMIT 1
            """
        ),
        {
            "cid": int(collective_id),
            "now": ts,
            "s1": SUBSCRIPTION_STATUS_TRIAL,
            "s2": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    cur_row = current.fetchone()
    if cur_row is not None and cur_row[0] is not None:
        return max(ts, cur_row[0])
    return ts


async def cancel_pending_collective_invoices(session: AsyncSession, collective_id: int) -> None:
    await session.execute(
        text(
            """
            UPDATE collective_invoices SET status = :cancelled
            WHERE collective_id = :cid AND status IN (:sent, :overdue)
            """
        ),
        {
            "cancelled": INVOICE_STATUS_CANCELLED,
            "cid": int(collective_id),
            "sent": INVOICE_STATUS_SENT,
            "overdue": INVOICE_STATUS_OVERDUE,
        },
    )


async def get_pending_collective_invoice(
    session: AsyncSession,
    collective_id: int,
) -> dict[str, Any] | None:
    r = await session.execute(
        text(
            """
            SELECT id, amount_cents, period_months, modules, seat_limit,
                   period_start, period_end, status
            FROM collective_invoices
            WHERE collective_id = :cid AND status IN (:sent, :overdue)
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {
            "cid": int(collective_id),
            "sent": INVOICE_STATUS_SENT,
            "overdue": INVOICE_STATUS_OVERDUE,
        },
    )
    row = r.fetchone()
    if row is None:
        return None
    return {
        "invoice_id": int(row[0]),
        "amount_cents": int(row[1]),
        "period_months": int(row[2]),
        "modules": normalize_modules_dict(row[3]),
        "seat_limit": int(row[4]),
        "period_start": row[5],
        "period_end": row[6],
        "status": str(row[7]),
    }


async def create_collective_subscription_invoice(
    session: AsyncSession,
    *,
    collective_id: int,
    requested_by_trainer_id: int,
    period_months: int,
    modules: dict[str, bool] | None = None,
) -> dict[str, Any] | None:
    """
    Owner self-service: unpaid pool invoice for ERIP / bePaid.

    Amount = collective_subscription_cents_per_seat_month × seat_limit × period_months.
    """
    months = int(period_months)
    if months not in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
        return None

    collective = await session.execute(
        text(
            """
            SELECT id, slug, display_name, status, seat_limit, owner_trainer_id
            FROM collectives
            WHERE id = :id
            LIMIT 1
            """
        ),
        {"id": int(collective_id)},
    )
    row = collective.fetchone()
    if row is None:
        return None
    cid, slug, display_name, coll_status, seat_limit, owner_id = row
    if str(coll_status) not in (COLLECTIVE_STATUS_ACTIVE, COLLECTIVE_STATUS_DRAFT):
        return {"error": "collective_not_grantable", "slug": str(slug)}
    if int(owner_id or 0) != int(requested_by_trainer_id):
        return {"error": "not_owner"}

    final_modules = normalize_modules_dict(modules or DEFAULT_COLLECTIVE_POOL_MODULES)
    tier = _infer_collective_subscription_tier(final_modules)
    seats = max(1, int(seat_limit))
    amount_cents = compute_collective_subscription_price_cents(seats, months)

    now = datetime.now(timezone.utc)
    period_start = await _collective_subscription_extend_base(session, int(cid), now=now)
    period_end = period_start + timedelta(days=months * 30)
    due_date = period_end

    await cancel_pending_collective_invoices(session, int(cid))
    r_ins = await session.execute(
        text(
            """
            INSERT INTO collective_invoices (
                collective_id, requested_by_trainer_id, amount_cents, period_months,
                modules, seat_limit, period_start, period_end, due_date, status
            )
            VALUES (
                :cid, :tid, :amount, :months, CAST(:mods AS jsonb), :seats,
                :ps, :pe, :due, :status
            )
            RETURNING id, amount_cents, period_start, period_end
            """
        ),
        {
            "cid": int(cid),
            "tid": int(requested_by_trainer_id),
            "amount": amount_cents,
            "months": months,
            "mods": json.dumps(final_modules, ensure_ascii=False),
            "seats": seats,
            "ps": period_start,
            "pe": period_end,
            "due": due_date,
            "status": INVOICE_STATUS_SENT,
        },
    )
    ins = r_ins.fetchone()
    await session.commit()
    return {
        "invoice_id": int(ins[0]),
        "collective_id": int(cid),
        "slug": str(slug),
        "display_name": str(display_name),
        "amount_cents": int(ins[1]),
        "period_months": months,
        "modules": final_modules,
        "modules_label": _format_collective_modules_ru(final_modules),
        "tier": tier,
        "seat_limit": seats,
        "period_start": ins[2],
        "period_end": ins[3],
        "plan_name": f"Подписка студии · {seats} мест · {months} мес.",
    }


async def confirm_collective_invoice_after_payment(
    session: AsyncSession,
    invoice_id: int,
    payment_external_id: str,
) -> bool:
    """Mark collective invoice paid and activate pool subscription row."""
    r = await session.execute(
        text(
            """
            SELECT collective_id, amount_cents, period_months, modules, seat_limit,
                   period_start, period_end, status
            FROM collective_invoices
            WHERE id = :iid
            """
        ),
        {"iid": int(invoice_id)},
    )
    row = r.fetchone()
    if row is None:
        return False
    (
        collective_id,
        _amount,
        _period_months,
        checkout_modules,
        _seat_limit,
        period_start,
        period_end,
        status,
    ) = row
    if status == INVOICE_STATUS_PAID:
        return True
    if status not in (INVOICE_STATUS_SENT, INVOICE_STATUS_OVERDUE):
        return False

    final_modules = normalize_modules_dict(checkout_modules)
    tier = _infer_collective_subscription_tier(final_modules)
    now = datetime.now(timezone.utc)
    await session.execute(
        text(
            """
            UPDATE collective_invoices
            SET status = :paid, paid_at = :now, payment_external_id = :ext_id
            WHERE id = :iid
            """
        ),
        {
            "paid": INVOICE_STATUS_PAID,
            "now": now,
            "ext_id": payment_external_id[:256],
            "iid": int(invoice_id),
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO collective_subscriptions (
                collective_id, tier, modules, status, started_at, expires_at
            )
            VALUES (
                :cid, :tier, CAST(:mods AS jsonb), :status, :started, :expires
            )
            """
        ),
        {
            "cid": int(collective_id),
            "tier": tier,
            "mods": json.dumps(final_modules, ensure_ascii=False),
            "status": SUBSCRIPTION_STATUS_ACTIVE,
            "started": period_start,
            "expires": period_end,
        },
    )
    await session.commit()
    return True


async def admin_confirm_collective_invoice(
    session: AsyncSession,
    invoice_id: int,
    *,
    admin_id: int,
) -> dict[str, Any] | None:
    """Admin ERIP path: confirm unpaid collective invoice as paid."""
    r = await session.execute(
        text(
            """
            SELECT ci.collective_id, ci.status, c.slug, c.display_name
            FROM collective_invoices ci
            INNER JOIN collectives c ON c.id = ci.collective_id
            WHERE ci.id = :iid
            """
        ),
        {"iid": int(invoice_id)},
    )
    row = r.fetchone()
    if row is None:
        return None
    collective_id, status, slug, display_name = row
    if status not in (INVOICE_STATUS_SENT, INVOICE_STATUS_OVERDUE, INVOICE_STATUS_PAID):
        return None
    if status != INVOICE_STATUS_PAID:
        ok = await confirm_collective_invoice_after_payment(
            session,
            int(invoice_id),
            f"admin-colinv-{admin_id}-{invoice_id}",
        )
        if not ok:
            return None

    from src.shared.audit import ACTOR_ADMIN_BOT, audit_log

    audit_log(
        "admin.collective_invoice_confirmed",
        ACTOR_ADMIN_BOT,
        int(admin_id),
        {"invoice_id": int(invoice_id), "collective_id": int(collective_id), "slug": str(slug)},
    )
    sub_status = await get_collective_subscription_status(session, collective_id=int(collective_id))
    return {
        "invoice_id": int(invoice_id),
        "collective_id": int(collective_id),
        "slug": str(slug),
        "display_name": str(display_name),
        "subscription_status": sub_status,
    }


def collective_subscription_checkout_snapshot(
    *,
    seat_limit: int,
    checkout_mode: str,
    payment_sandbox: bool,
    pending: dict[str, Any] | None,
    support_url: str | None,
) -> dict[str, Any]:
    """Pricing + checkout mode for owner «Студия» screen."""
    seats = max(1, int(seat_limit))
    rate = Settings().collective_subscription_cents_per_seat_month
    pricing = []
    for months in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
        amount = compute_collective_subscription_price_cents(seats, months, cents_per_seat_month=rate)
        pricing.append(
            {
                "period_months": int(months),
                "amount_cents": amount,
                "amount_label": f"{amount / 100:.2f} BYN",
                "seats_label": f"{seats} мест × {months} мес.",
            }
        )
    pending_out: dict[str, Any] | None = None
    if pending:
        pe = pending.get("period_end")
        pending_out = {
            "invoice_id": pending["invoice_id"],
            "amount_cents": pending["amount_cents"],
            "period_months": pending["period_months"],
            "status": pending["status"],
            "period_end": pe.isoformat() if hasattr(pe, "isoformat") else pe,
        }
    return {
        "checkout_mode": checkout_mode,
        "payment_sandbox": payment_sandbox,
        "cents_per_seat_month": rate,
        "modules": format_collective_modules_list_ru(DEFAULT_COLLECTIVE_POOL_MODULES),
        "pricing": pricing,
        "pending_invoice": pending_out,
        "support_url": support_url,
    }


async def update_collective_brand(
    session: AsyncSession,
    *,
    collective_id: int,
    trainer_id: int,
    display_name: str | None = None,
    tagline: str | None = None,
    clear_tagline: bool = False,
    about: str | None = None,
    clear_about: bool = False,
    logo_key: str | None = None,
    clear_logo: bool = False,
    cover_key: str | None = None,
    clear_cover: bool = False,
    gallery_keys: list[str] | None = None,
    gallery_remove_key: str | None = None,
    accent_preset: str | None = None,
    contacts: dict[str, str] | None = None,
    primary_arena_id: int | None = None,
    clear_primary_arena: bool = False,
    default_city_id: int | None = None,
    clear_default_city: bool = False,
) -> dict[str, Any] | None:
    """Owner-only studio brand kit edit. Slug is immutable."""
    owner_err = await _assert_collective_owner(session, collective_id, trainer_id)
    if owner_err:
        return {"error": owner_err}

    slug_row = await session.execute(
        text("SELECT slug, brand_tokens, gallery_keys FROM collectives WHERE id = :id"),
        {"id": collective_id},
    )
    slug_val = slug_row.fetchone()
    if slug_val is None:
        return {"error": "collective_missing"}
    slug_str = str(slug_val[0])
    current_tokens = normalize_brand_tokens(slug_val[1])
    current_gallery = normalize_gallery_keys(slug_val[2])

    updates: list[str] = []
    params: dict[str, Any] = {"cid": collective_id, "now": datetime.now(timezone.utc)}

    if display_name is not None:
        name = display_name.strip()
        if not name:
            return {"error": "display_name_required"}
        updates.append("display_name = :name")
        params["name"] = name[:128]
    if clear_tagline:
        updates.append("tagline = NULL")
    elif tagline is not None:
        updates.append("tagline = :tagline")
        params["tagline"] = tagline.strip()[:2000] or None
    if clear_about:
        updates.append("about = NULL")
    elif about is not None:
        updates.append("about = :about")
        params["about"] = about.strip()[:4000] or None
    if clear_logo:
        updates.append("logo_key = NULL")
    elif logo_key is not None:
        key = logo_key.strip()
        if key and not collective_storage_key_allowed(collective_id, key):
            return {"error": "invalid_logo_key"}
        updates.append("logo_key = :logo_key")
        params["logo_key"] = key or None
    if clear_cover:
        updates.append("cover_key = NULL")
    elif cover_key is not None:
        key = cover_key.strip()
        if key and not collective_storage_key_allowed(collective_id, key):
            return {"error": "invalid_cover_key"}
        updates.append("cover_key = :cover_key")
        params["cover_key"] = key or None

    if clear_primary_arena:
        updates.append("primary_arena_id = NULL")
    elif primary_arena_id is not None:
        arena_check = await session.execute(
            text("SELECT id FROM arenas WHERE id = :aid AND is_active LIMIT 1"),
            {"aid": int(primary_arena_id)},
        )
        if arena_check.fetchone() is None:
            return {"error": "invalid_primary_arena"}
        updates.append("primary_arena_id = :primary_arena_id")
        params["primary_arena_id"] = int(primary_arena_id)

    gallery_changed = False
    next_gallery = list(current_gallery)
    if gallery_keys is not None:
        validated: list[str] = []
        for raw_key in normalize_gallery_keys(gallery_keys):
            if not collective_storage_key_allowed(collective_id, raw_key):
                return {"error": "invalid_gallery_key"}
            validated.append(raw_key)
        if len(validated) > MAX_COLLECTIVE_GALLERY_ITEMS:
            return {"error": "gallery_too_large"}
        next_gallery = validated
        gallery_changed = True
    elif gallery_remove_key:
        rm = gallery_remove_key.strip()
        next_gallery = [k for k in next_gallery if k != rm]
        gallery_changed = True
    if gallery_changed:
        updates.append("gallery_keys = CAST(:gallery_keys AS jsonb)")
        params["gallery_keys"] = json.dumps(next_gallery)

    tokens_changed = False
    next_tokens = dict(current_tokens)
    if accent_preset is not None:
        preset = accent_preset.strip().lower()
        resolved = resolve_accent_preset(preset)
        next_tokens["accent_preset"] = resolved["id"]
        tokens_changed = True
    if contacts is not None:
        merged = dict(next_tokens.get("contacts") or {})
        for field in ("address", "phone", "instagram", "telegram"):
            if field in contacts:
                merged[field] = str(contacts[field] or "").strip()[:500]
        next_tokens["contacts"] = merged
        tokens_changed = True
    if clear_default_city:
        next_tokens["default_city_id"] = None
        tokens_changed = True
    elif default_city_id is not None:
        norm_city_id = normalize_default_city_id(default_city_id)
        if norm_city_id is None:
            return {"error": "invalid_default_city"}
        city_check = await session.execute(
            text("SELECT id FROM cities WHERE id = :cid AND is_active LIMIT 1"),
            {"cid": norm_city_id},
        )
        if city_check.fetchone() is None:
            return {"error": "invalid_default_city"}
        next_tokens["default_city_id"] = norm_city_id
        tokens_changed = True
    if tokens_changed:
        updates.append("brand_tokens = CAST(:brand_tokens AS jsonb)")
        params["brand_tokens"] = json.dumps(next_tokens)

    if not updates:
        return {"error": "nothing_to_update"}

    await session.execute(
        text(
            f"""
            UPDATE collectives
            SET {", ".join(updates)}, updated_at = :now
            WHERE id = :cid
            """
        ),
        params,
    )
    await session.commit()

    refreshed = await get_collective_by_slug(session, slug_str, active_only=False)
    if refreshed is None:
        return {"error": "collective_missing"}
    kit = collective_brand_kit_enrichment(refreshed)
    location = await collective_location_payload(session, refreshed)
    return {
        "collective_id": refreshed["id"],
        "slug": refreshed["slug"],
        "display_name": refreshed["display_name"],
        "tagline": refreshed["tagline"],
        "logo_key": refreshed["logo_key"],
        **kit,
        **location,
    }


async def upload_collective_asset_from_bytes(
    session: AsyncSession,
    *,
    collective_id: int,
    trainer_id: int,
    body: bytes,
    content_type: str,
    kind: str,
) -> dict[str, Any]:
    """Owner uploads logo, cover, or gallery image; persists key on collective row."""
    owner_err = await _assert_collective_owner(session, collective_id, trainer_id)
    if owner_err:
        return {"error": owner_err}
    if len(body) > MAX_TRAINER_PHOTO_BYTES:
        return {"error": "too_large"}
    if not trainer_photo_bytes_look_like_image(body):
        return {"error": "not_image"}
    kind_norm = (kind or "gallery").strip().lower()
    if kind_norm not in ("logo", "cover", "gallery"):
        return {"error": "invalid_kind"}

    if kind_norm == "gallery":
        row = await session.execute(
            text("SELECT gallery_keys FROM collectives WHERE id = :id"),
            {"id": collective_id},
        )
        existing = row.scalar_one_or_none()
        if len(normalize_gallery_keys(existing)) >= MAX_COLLECTIVE_GALLERY_ITEMS:
            return {"error": "gallery_full"}

    try:
        file_key = s3.upload_collective_image(collective_id, body, content_type, kind=kind_norm)
    except Exception:
        logger.exception(
            "collective asset upload failed collective_id=%s kind=%s",
            collective_id,
            kind_norm,
        )
        return {"error": "storage"}

    now = datetime.now(timezone.utc)
    if kind_norm == "logo":
        await session.execute(
            text("UPDATE collectives SET logo_key = :k, updated_at = :now WHERE id = :cid"),
            {"k": file_key, "now": now, "cid": collective_id},
        )
    elif kind_norm == "cover":
        await session.execute(
            text("UPDATE collectives SET cover_key = :k, updated_at = :now WHERE id = :cid"),
            {"k": file_key, "now": now, "cid": collective_id},
        )
    else:
        row = await session.execute(
            text("SELECT gallery_keys FROM collectives WHERE id = :id FOR UPDATE"),
            {"id": collective_id},
        )
        gallery = normalize_gallery_keys(row.scalar_one_or_none())
        gallery.append(file_key)
        await session.execute(
            text(
                """
                UPDATE collectives
                SET gallery_keys = CAST(:g AS jsonb), updated_at = :now
                WHERE id = :cid
                """
            ),
            {"g": json.dumps(gallery), "now": now, "cid": collective_id},
        )
    await session.commit()
    return {
        "file_key": file_key,
        "url": public_asset_url(file_key),
        "kind": kind_norm,
    }


async def get_trainer_collective_studio_payload(
    session: AsyncSession,
    trainer_id: int,
    *,
    collective_slug: str | None = None,
) -> dict[str, Any] | None:
    """Trainer mini-app «Студия» screen data; null for solo trainers."""
    membership = await resolve_collective_membership(session, trainer_id, collective_slug=collective_slug)
    if membership is None:
        return None

    all_memberships = await list_active_collective_memberships(session, trainer_id)
    memberships_summary = [
        {
            "collective_id": m.collective_id,
            "slug": m.slug,
            "display_name": m.display_name,
            "role": m.role,
            "schedule_mode": m.schedule_mode,
            "organization_format": m.organization_format,
        }
        for m in all_memberships
    ]

    members = await list_collective_members_for_studio(session, membership.collective_id)
    active_count = await count_active_collective_members(session, membership.collective_id)
    client_link = build_collective_client_deep_link(membership.slug)

    coll_ent = await get_collective_entitlements_for_member(session, trainer_id)
    from src.application.subscription_tier_use_cases import unlocked_capability_codes

    subscription_covers: list[str] = []
    if coll_ent is not None:
        subscription_covers = unlocked_capability_codes(coll_ent)

    seats_available = active_count < membership.seat_limit
    pending_invite_count = await count_pending_collective_invite_tokens(
        session, membership.collective_id
    )
    sub_status = await get_collective_subscription_status(
        session, collective_id=membership.collective_id
    )
    subscription_pool = studio_subscription_pool_payload(sub_status)

    subscription_checkout: dict[str, Any] | None = None
    if membership.role == MEMBER_ROLE_OWNER:
        settings = Settings()
        pending = await get_pending_collective_invoice(session, membership.collective_id)
        subscription_checkout = collective_subscription_checkout_snapshot(
            seat_limit=membership.seat_limit,
            checkout_mode=settings.resolved_trainer_subscription_checkout_mode(),
            payment_sandbox=settings.payment_sandbox,
            pending=pending,
            support_url=settings.subscription_support_url,
        )

    row = await get_collective_by_slug(session, membership.slug, active_only=False)
    is_studio_admin = is_collective_studio_admin_role(membership.role)
    is_owner = is_collective_owner_role(membership.role)
    kit = collective_brand_kit_enrichment(row or {}, include_owner_options=is_studio_admin)
    location = await collective_location_payload(session, row or {"slug": membership.slug, "brand_tokens": None, "primary_arena_id": None})
    schedule_mode = (
        str(row.get("schedule_mode") or SCHEDULE_MODE_MEMBER_AUTONOMOUS)
        if row
        else SCHEDULE_MODE_MEMBER_AUTONOMOUS
    )
    studio_access_mode = await get_effective_studio_access_mode(session, trainer_id)
    org_format = membership.organization_format
    from src.application.organization_capabilities import capabilities_for_collective_membership

    capabilities = capabilities_for_collective_membership(
        organization_format=org_format,
        schedule_mode=schedule_mode,
        role=membership.role,
        studio_access_mode=studio_access_mode,
    )

    my_center_duties: list[dict[str, Any]] = []
    if schedule_mode == SCHEDULE_MODE_STUDIO_CENTRAL:
        from src.application.collective_session_use_cases import list_center_duties_for_trainer

        today = date.today()
        duties = await list_center_duties_for_trainer(
            session,
            trainer_id=trainer_id,
            from_date=today,
            to_date=today + timedelta(days=28),
        )
        my_center_duties = [
            d for d in duties if d.get("collective_slug") == membership.slug
        ]

    return {
        "collective_id": membership.collective_id,
        "slug": membership.slug,
        "display_name": membership.display_name,
        "tagline": membership.tagline,
        "logo_key": membership.logo_key,
        "role": membership.role,
        "seat_limit": membership.seat_limit,
        "schedule_mode": schedule_mode,
        "organization_format": org_format,
        "capabilities": capabilities,
        "studio_access_mode": studio_access_mode,
        "can_manage_center_schedule": is_studio_admin
        and schedule_mode == SCHEDULE_MODE_STUDIO_CENTRAL,
        "can_delegate_booking": is_studio_admin
        and schedule_mode == SCHEDULE_MODE_STUDIO_CENTRAL,
        "active_count": active_count,
        "client_link": client_link,
        "catalog_webapp_url": location.get("catalog_webapp_url"),
        "subscription_covers": subscription_covers,
        "members": members,
        "can_invite": is_owner and seats_available,
        "seats_available": seats_available,
        "can_edit_brand": is_studio_admin,
        "can_manage_team": is_owner,
        "can_promote_admin": is_owner,
        "pending_invite_count": pending_invite_count,
        "subscription_pool": subscription_pool,
        "subscription_checkout": subscription_checkout,
        "memberships": memberships_summary,
        "has_multiple_memberships": len(all_memberships) > 1,
        "my_center_duties": my_center_duties,
        "self_trainer_id": int(trainer_id),
        **kit,
        **location,
    }
