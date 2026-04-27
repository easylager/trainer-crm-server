"""
Trainer lifecycle: derived state (no extra DB columns) used as the single source of truth for
"what is this trainer currently allowed to do?".

Two-level gate model:

    Level 1 — LifecycleStage (this module)
        Coarse state derived from (Trainer.status, active subscription?, is_catalog_visible).
        Answers: ONBOARDING / ACTIVE / LEAD_MODE / CHURNED.
        Decides: can the trainer do *anything* operational at all?

    Level 2 — Subscription module gates (subscription_tier_use_cases)
        Fine-grained checks for paid features inside ACTIVE: online booking, analytics, groups.
        Decides: which features inside ACTIVE are unlocked by which paid module?

`trainer_can(...)` composes both levels and is the recommended API for new code.
Existing `trainer_has_*_access` helpers stay untouched for backward compat — they are correct
inside ACTIVE and return False under no-subscription, which already coincides with LEAD_MODE
for module checks. New surfaces (Lead Mode UI, recovery nudges, redirect-tracking, read-only
ops view) should use this module instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import (
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_TRIAL,
    TRAINER_STATUS_ACTIVE,
    TRAINER_STATUS_DEACTIVATED,
    TRAINER_STATUS_PENDING_CONTRACT,
    TRAINER_STATUS_PENDING_PAYMENT,
    TRAINER_STATUS_PENDING_PROFILE,
)


class LifecycleStage(StrEnum):
    """Coarse lifecycle state derived from trainer + subscription rows. Never persisted."""

    ONBOARDING = "onboarding"
    ACTIVE = "active"
    LEAD_MODE = "lead_mode"
    CHURNED = "churned"


class Capability(StrEnum):
    """What a trainer is allowed to do, abstracted from the underlying paywall mechanism.

    Capabilities are grouped by intent so UI / API gates can declare what they need without
    knowing about subscription tiers or lifecycle stages.
    """

    # Marketplace presence — Lead Mode preserves these to keep the trainer as supply.
    CATALOG_VISIBILITY = "catalog_visibility"
    RECEIVE_LEADS = "receive_leads"
    # Existing-commitments view — see "Graceful Degradation" in the design doc.
    READ_OPERATIONS = "read_operations"
    # Operational control layer — paywalled. Lost in Lead Mode.
    CRM_BASE = "crm_base"
    ONLINE_BOOKING = "online_booking"
    ANALYTICS = "analytics"
    GROUPS = "groups"


# Stage → structurally permitted capabilities (before module checks).
# This is the heart of the Lead Mode contract: "presence stays, control is paywalled".
_STAGE_CAPABILITIES: Final[dict[LifecycleStage, frozenset[Capability]]] = {
    LifecycleStage.ONBOARDING: frozenset(),  # nothing operational; UI shows the setup wizard
    LifecycleStage.ACTIVE: frozenset(
        {
            Capability.CATALOG_VISIBILITY,
            Capability.RECEIVE_LEADS,
            Capability.READ_OPERATIONS,
            Capability.CRM_BASE,
            Capability.ONLINE_BOOKING,
            Capability.ANALYTICS,
            Capability.GROUPS,
        }
    ),
    LifecycleStage.LEAD_MODE: frozenset(
        {
            Capability.CATALOG_VISIBILITY,
            Capability.RECEIVE_LEADS,
            Capability.READ_OPERATIONS,
        }
    ),
    LifecycleStage.CHURNED: frozenset(),
}

# Capabilities inside ACTIVE that need an additional paid-module check.
# Other capabilities in ACTIVE are unconditional once the trainer reaches ACTIVE.
_MODULE_GATED_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {Capability.ONLINE_BOOKING, Capability.ANALYTICS, Capability.GROUPS}
)

# Trainer.status values we treat as "still going through setup" — not yet in caller-visible flow.
_ONBOARDING_STATUSES: Final[frozenset[str]] = frozenset(
    {
        TRAINER_STATUS_PENDING_PROFILE,
        TRAINER_STATUS_PENDING_CONTRACT,
        TRAINER_STATUS_PENDING_PAYMENT,
    }
)


@dataclass(frozen=True, slots=True)
class LifecycleSnapshot:
    """One-shot snapshot of a trainer's lifecycle context. UI/nudge engines read this."""

    trainer_id: int
    stage: LifecycleStage
    trainer_status: str | None
    has_active_subscription: bool
    is_catalog_visible: bool
    last_subscription_expires_at: datetime | None
    """expires_at of the most recent (trial or paid) row — anchors recovery nudges as ``since``."""

    @property
    def is_lead_mode(self) -> bool:
        return self.stage == LifecycleStage.LEAD_MODE

    @property
    def is_active(self) -> bool:
        return self.stage == LifecycleStage.ACTIVE

    def as_dict(self) -> dict[str, object]:
        return {
            "trainer_id": self.trainer_id,
            "stage": self.stage.value,
            "trainer_status": self.trainer_status,
            "has_active_subscription": self.has_active_subscription,
            "is_catalog_visible": self.is_catalog_visible,
            "last_subscription_expires_at": (
                self.last_subscription_expires_at.isoformat()
                if self.last_subscription_expires_at
                else None
            ),
            "is_lead_mode": self.is_lead_mode,
            "is_active": self.is_active,
        }


def stage_allows(stage: LifecycleStage, capability: Capability) -> bool:
    """Pure: is this capability *structurally* permitted at this lifecycle stage?

    Does not consult subscription modules — that's `trainer_can`'s job. Useful in tests and
    in templating where you only have a stage value.
    """
    return capability in _STAGE_CAPABILITIES[stage]


def stage_capabilities(stage: LifecycleStage) -> frozenset[Capability]:
    """Return the full capability set for a stage — for debug/inspection."""
    return _STAGE_CAPABILITIES[stage]


async def resolve_lifecycle_snapshot(
    session: AsyncSession, trainer_id: int
) -> LifecycleSnapshot:
    """
    One round-trip resolution: trainer row + active-subscription existence + last-expiry anchor.

    Defensive default: if the trainer row is missing entirely, returns CHURNED with all flags
    cleared. This keeps callers from raising on race conditions (e.g. trainer deleted while a
    request is in flight).
    """
    now = datetime.now(timezone.utc)
    result = await session.execute(
        text(
            """
            SELECT
                t.status,
                t.is_catalog_visible,
                EXISTS(
                    SELECT 1
                    FROM trainer_subscriptions ts
                    WHERE ts.trainer_id = t.id
                      AND ts.started_at <= :now
                      AND ts.expires_at > :now
                      AND ts.status IN (:s_trial, :s_active)
                ) AS has_active_sub,
                (
                    SELECT MAX(ts.expires_at)
                    FROM trainer_subscriptions ts
                    WHERE ts.trainer_id = t.id
                ) AS last_expires_at
            FROM trainers t
            WHERE t.id = :tid
            """
        ),
        {
            "tid": trainer_id,
            "now": now,
            "s_trial": SUBSCRIPTION_STATUS_TRIAL,
            "s_active": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    row = result.fetchone()
    if row is None:
        return LifecycleSnapshot(
            trainer_id=trainer_id,
            stage=LifecycleStage.CHURNED,
            trainer_status=None,
            has_active_subscription=False,
            is_catalog_visible=False,
            last_subscription_expires_at=None,
        )

    trainer_status: str = row[0]
    is_catalog_visible: bool = bool(row[1])
    has_active_sub: bool = bool(row[2])
    last_expires_at: datetime | None = row[3]

    stage = _derive_stage(
        trainer_status=trainer_status,
        is_catalog_visible=is_catalog_visible,
        has_active_sub=has_active_sub,
    )
    return LifecycleSnapshot(
        trainer_id=trainer_id,
        stage=stage,
        trainer_status=trainer_status,
        has_active_subscription=has_active_sub,
        is_catalog_visible=is_catalog_visible,
        last_subscription_expires_at=last_expires_at,
    )


async def resolve_lifecycle_stage(session: AsyncSession, trainer_id: int) -> LifecycleStage:
    """Convenience wrapper when only the stage is needed."""
    snap = await resolve_lifecycle_snapshot(session, trainer_id)
    return snap.stage


def _derive_stage(
    *, trainer_status: str | None, is_catalog_visible: bool, has_active_sub: bool
) -> LifecycleStage:
    """Pure mapping function — the single place where the lifecycle decision tree lives."""
    if trainer_status is None:
        return LifecycleStage.CHURNED
    if trainer_status in _ONBOARDING_STATUSES:
        return LifecycleStage.ONBOARDING
    if trainer_status == TRAINER_STATUS_DEACTIVATED:
        return LifecycleStage.CHURNED
    # Beyond this point: status == active (or any future "active-equivalent" status).
    if trainer_status != TRAINER_STATUS_ACTIVE:
        # Defensive: unknown status — treat as churned to err on the safe side (no rights).
        return LifecycleStage.CHURNED
    if has_active_sub:
        # Active subscription with hidden catalog is still ACTIVE: the trainer paid for control,
        # they merely chose not to be discoverable right now.
        return LifecycleStage.ACTIVE
    # Active row, no subscription — Lead Mode if discoverable, else Churned (no supply, no pay).
    return LifecycleStage.LEAD_MODE if is_catalog_visible else LifecycleStage.CHURNED


async def trainer_can(
    session: AsyncSession,
    trainer_id: int,
    capability: Capability,
) -> bool:
    """
    Composite gate: lifecycle stage + paid-module check (where applicable).

    Recommended for all new gate decisions. Existing `trainer_has_*_access` helpers remain
    valid for code paths that already use them — they're equivalent inside ACTIVE.
    """
    stage = await resolve_lifecycle_stage(session, trainer_id)
    if not stage_allows(stage, capability):
        return False
    if stage != LifecycleStage.ACTIVE:
        # In LEAD_MODE/ONBOARDING/CHURNED, only structurally-allowed capabilities pass — and
        # those don't need module checks (catalog/leads/read are unconditional in LEAD_MODE).
        return True
    if capability not in _MODULE_GATED_CAPABILITIES:
        return True
    # Defer to existing module gates so the pricing logic stays in one place.
    # Local import: keeps module load order shallow and avoids a hard cycle with
    # subscription_tier_use_cases (which itself imports nothing from lifecycle_use_cases).
    from src.application.subscription_tier_use_cases import (
        trainer_allows_online_booking,
        trainer_has_analytics_access,
        trainer_has_groups_access,
    )

    if capability == Capability.ONLINE_BOOKING:
        return await trainer_allows_online_booking(session, trainer_id)
    if capability == Capability.ANALYTICS:
        return await trainer_has_analytics_access(session, trainer_id)
    if capability == Capability.GROUPS:
        return await trainer_has_groups_access(session, trainer_id)
    # Unreachable given _MODULE_GATED_CAPABILITIES, but keeps the type checker happy.
    return False


__all__ = [
    "LifecycleStage",
    "Capability",
    "LifecycleSnapshot",
    "stage_allows",
    "stage_capabilities",
    "resolve_lifecycle_snapshot",
    "resolve_lifecycle_stage",
    "trainer_can",
]
