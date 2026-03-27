"""
Subscription tiers: three-level access model (crm < online < analytics).

Domain logic for tier hierarchy, effective tier resolution, and mock checkout.
"""
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import (
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_TRIAL,
    SUBSCRIPTION_TIER_ANALYTICS,
    SUBSCRIPTION_TIER_CRM,
    SUBSCRIPTION_TIER_LEVELS,
    SUBSCRIPTION_TIER_NONE,
    SUBSCRIPTION_TIER_ONLINE,
)


SubscriptionTier = Literal["none", "crm", "online", "analytics"]


def tier_satisfies(current: SubscriptionTier, required: SubscriptionTier) -> bool:
    """
    Check if current tier meets or exceeds the required tier.
    
    Hierarchy: analytics > online > crm > none
    Example: tier_satisfies("online", "crm") → True (online includes crm)
    """
    return SUBSCRIPTION_TIER_LEVELS.get(current, 0) >= SUBSCRIPTION_TIER_LEVELS.get(required, 0)


def tier_includes(tier: SubscriptionTier) -> list[str]:
    """Return list of features/tiers included in given tier (for UI display)."""
    if tier == SUBSCRIPTION_TIER_ANALYTICS:
        return [SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_ANALYTICS]
    if tier == SUBSCRIPTION_TIER_ONLINE:
        return [SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE]
    if tier == SUBSCRIPTION_TIER_CRM:
        return [SUBSCRIPTION_TIER_CRM]
    return []


async def get_effective_subscription_tier(session: AsyncSession, trainer_id: int) -> SubscriptionTier:
    """
    Resolve trainer's effective tier considering expiration.
    
    Returns highest active tier or 'none' if no valid subscription.
    """
    now = datetime.now(timezone.utc)
    result = await session.execute(
        text("""
            SELECT tier
            FROM trainer_subscriptions
            WHERE trainer_id = :tid
              AND expires_at > :now
              AND status IN (:s1, :s2)
              AND tier IS NOT NULL
            ORDER BY 
                CASE tier 
                    WHEN 'analytics' THEN 3 
                    WHEN 'online' THEN 2 
                    WHEN 'crm' THEN 1 
                    ELSE 0 
                END DESC
            LIMIT 1
        """),
        {
            "tid": trainer_id,
            "now": now,
            "s1": SUBSCRIPTION_STATUS_TRIAL,
            "s2": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    row = result.fetchone()
    return row[0] if row else SUBSCRIPTION_TIER_NONE


async def get_subscription_tier_catalog(session: AsyncSession) -> list[dict]:
    """
    Get all active tier pricing for catalog display.
    
    Returns list ordered by display_order with pricing and descriptions.
    """
    result = await session.execute(
        text("""
            SELECT 
                tier, price_cents, currency, period_days, 
                name_ru, short_description_ru, bullets_json, display_order
            FROM subscription_tier_pricing
            WHERE is_active = true
            ORDER BY display_order ASC
        """)
    )
    rows = result.fetchall()
    return [
        {
            "tier": row[0],
            "price_cents": row[1],
            "currency": row[2],
            "period_days": row[3],
            "name_ru": row[4],
            "short_description_ru": row[5],
            "bullets": row[6] or [],
            "display_order": row[7],
            "includes_tiers": tier_includes(row[0]),
        }
        for row in rows
    ]


async def get_trainer_subscription_status(session: AsyncSession, trainer_id: int) -> dict:
    """
    Get trainer's current subscription status for UI.
    
    Includes effective tier, expiration, and what's unlocked.
    """
    tier = await get_effective_subscription_tier(session, trainer_id)
    now = datetime.now(timezone.utc)
    
    # Get subscription details if active
    result = await session.execute(
        text("""
            SELECT ts.id, ts.tier, ts.expires_at, ts.status, ts.started_at
            FROM trainer_subscriptions ts
            WHERE ts.trainer_id = :tid
              AND ts.expires_at > :now
              AND ts.status IN (:s1, :s2)
            ORDER BY ts.expires_at DESC
            LIMIT 1
        """),
        {
            "tid": trainer_id,
            "now": now,
            "s1": SUBSCRIPTION_STATUS_TRIAL,
            "s2": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    row = result.fetchone()
    
    if row:
        return {
            "subscription_id": row[0],
            "tier": row[1] or tier,
            "effective_tier": tier,
            "expires_at": row[2].isoformat() if row[2] else None,
            "status": row[3],
            "started_at": row[4].isoformat() if row[4] else None,
            "is_active": True,
            "unlocked_features": tier_includes(tier),
        }
    
    return {
        "subscription_id": None,
        "tier": SUBSCRIPTION_TIER_NONE,
        "effective_tier": SUBSCRIPTION_TIER_NONE,
        "expires_at": None,
        "status": None,
        "started_at": None,
        "is_active": False,
        "unlocked_features": [],
    }


async def get_tier_pricing(session: AsyncSession, tier: SubscriptionTier) -> dict | None:
    """Get pricing info for a specific tier."""
    result = await session.execute(
        text("""
            SELECT id, tier, price_cents, currency, period_days, name_ru
            FROM subscription_tier_pricing
            WHERE tier = :tier AND is_active = true
        """),
        {"tier": tier},
    )
    row = result.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "tier": row[1],
        "price_cents": row[2],
        "currency": row[3],
        "period_days": row[4],
        "name_ru": row[5],
    }


async def set_subscription_after_mock_payment(
    session: AsyncSession,
    trainer_id: int,
    tier: SubscriptionTier,
) -> dict | None:
    """
    Activate tier subscription after mock payment.
    
    Creates new trainer_subscription with tier and period from pricing.
    Policy: replaces tier (doesn't stack), extends from now or current expires_at.
    """
    if tier not in (SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_ANALYTICS):
        return None
    
    pricing = await get_tier_pricing(session, tier)
    if not pricing:
        return None
    
    now = datetime.now(timezone.utc)
    
    # Check if there's an active subscription to extend from
    result = await session.execute(
        text("""
            SELECT expires_at FROM trainer_subscriptions
            WHERE trainer_id = :tid 
              AND expires_at > :now
              AND status IN (:s1, :s2)
            ORDER BY expires_at DESC
            LIMIT 1
        """),
        {
            "tid": trainer_id,
            "now": now,
            "s1": SUBSCRIPTION_STATUS_TRIAL,
            "s2": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    row = result.fetchone()
    
    # Start from current expiration or now
    started_at = row[0] if row and row[0] > now else now
    expires_at = started_at + timedelta(days=pricing["period_days"])
    
    # Get or create a dummy plan_id (use first non-trial plan)
    plan_result = await session.execute(
        text("SELECT id FROM subscription_plans WHERE is_trial = false ORDER BY sort_order LIMIT 1")
    )
    plan_row = plan_result.fetchone()
    plan_id = plan_row[0] if plan_row else 1
    
    # Insert new subscription with tier
    result = await session.execute(
        text("""
            INSERT INTO trainer_subscriptions 
                (trainer_id, plan_id, tier, started_at, expires_at, status)
            VALUES 
                (:tid, :pid, :tier, :started_at, :expires_at, :status)
            RETURNING id, started_at, expires_at
        """),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "tier": tier,
            "started_at": started_at,
            "expires_at": expires_at,
            "status": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    row = result.fetchone()
    await session.commit()
    
    return {
        "subscription_id": row[0],
        "tier": tier,
        "started_at": row[1].isoformat(),
        "expires_at": row[2].isoformat(),
        "price_cents": pricing["price_cents"],
        "currency": pricing["currency"],
        "period_days": pricing["period_days"],
    }


async def trainer_has_tier_access(
    session: AsyncSession,
    trainer_id: int,
    required_tier: SubscriptionTier,
) -> bool:
    """Check if trainer has at least the required tier level."""
    current = await get_effective_subscription_tier(session, trainer_id)
    return tier_satisfies(current, required_tier)


async def trainer_allows_online_booking(session: AsyncSession, trainer_id: int) -> bool:
    """
    Check if trainer's subscription allows clients to book via catalog.
    
    Requires tier >= 'online'. Without this tier, clients can see trainer
    in catalog but cannot self-book (must contact directly).
    """
    return await trainer_has_tier_access(session, trainer_id, SUBSCRIPTION_TIER_ONLINE)


async def trainer_has_crm_access(session: AsyncSession, trainer_id: int) -> bool:
    """
    Check if trainer has CRM access (tier >= 'crm').
    
    CRM tier includes: schedule, templates, slots, manual booking,
    client management, passes, certificates.
    """
    return await trainer_has_tier_access(session, trainer_id, SUBSCRIPTION_TIER_CRM)


async def trainer_has_analytics_access(session: AsyncSession, trainer_id: int) -> bool:
    """
    Check if trainer has analytics access (tier >= 'analytics').
    
    Analytics tier includes: all CRM + online features, plus
    statistics, reports, data exports.
    """
    return await trainer_has_tier_access(session, trainer_id, SUBSCRIPTION_TIER_ANALYTICS)


async def get_trainer_booking_availability(session: AsyncSession, trainer_id: int) -> dict:
    """
    Get trainer's booking availability info for catalog display.
    
    Returns:
        - can_book: True if clients can self-book (tier >= online)
        - tier: current effective tier
        - reason: explanation if can_book is False
    """
    tier = await get_effective_subscription_tier(session, trainer_id)
    can_book = tier_satisfies(tier, SUBSCRIPTION_TIER_ONLINE)
    
    if can_book:
        return {"can_book": True, "tier": tier, "reason": None}
    
    if tier == SUBSCRIPTION_TIER_NONE:
        reason = "no_subscription"
    elif tier == SUBSCRIPTION_TIER_CRM:
        reason = "crm_only"
    else:
        reason = "tier_insufficient"
    
    return {"can_book": False, "tier": tier, "reason": reason}


# --- Admin functions for tier pricing management ---


def _tier_pricing_row_to_admin_dict(row) -> dict:
    """Map DB row to admin API dict (includes inactive tiers)."""
    return {
        "id": row[0],
        "tier": row[1],
        "price_cents": row[2],
        "currency": row[3],
        "period_days": row[4],
        "name_ru": row[5],
        "short_description_ru": row[6],
        "bullets": row[7] or [],
        "display_order": row[8],
        "is_active": row[9],
        "created_at": row[10].isoformat() if row[10] else None,
        "updated_at": row[11].isoformat() if row[11] else None,
    }


async def fetch_tier_pricing_for_admin(session: AsyncSession, tier: str) -> dict | None:
    """Single tier row for admin, including when is_active is false (unlike get_tier_pricing)."""
    result = await session.execute(
        text("""
            SELECT
                id, tier, price_cents, currency, period_days,
                name_ru, short_description_ru, bullets_json,
                display_order, is_active, created_at, updated_at
            FROM subscription_tier_pricing
            WHERE tier = :tier
        """),
        {"tier": tier},
    )
    row = result.fetchone()
    return _tier_pricing_row_to_admin_dict(row) if row else None


async def list_subscription_tier_pricing_for_admin(session: AsyncSession) -> list[dict]:
    """Get all tier pricing records for admin editing (including inactive)."""
    result = await session.execute(
        text("""
            SELECT 
                id, tier, price_cents, currency, period_days,
                name_ru, short_description_ru, bullets_json,
                display_order, is_active, created_at, updated_at
            FROM subscription_tier_pricing
            ORDER BY display_order ASC
        """)
    )
    rows = result.fetchall()
    return [_tier_pricing_row_to_admin_dict(row) for row in rows]


async def update_subscription_tier_pricing(
    session: AsyncSession,
    tier: str,
    admin_telegram_id: int | None,
    *,
    price_cents: int | None = None,
    period_days: int | None = None,
    name_ru: str | None = None,
    short_description_ru: str | None = None,
    bullets: list[str] | None = None,
    display_order: int | None = None,
    is_active: bool | None = None,
) -> dict | None:
    """
    Update tier pricing and log changes to audit table.
    
    Returns updated record or None if tier not found.
    """
    # Get current values for audit
    result = await session.execute(
        text("""
            SELECT id, price_cents, period_days, name_ru, short_description_ru, 
                   bullets_json, display_order, is_active
            FROM subscription_tier_pricing
            WHERE tier = :tier
        """),
        {"tier": tier},
    )
    row = result.fetchone()
    if not row:
        return None
    
    tier_pricing_id = row[0]
    old_values = {
        "price_cents": row[1],
        "period_days": row[2],
        "name_ru": row[3],
        "short_description_ru": row[4],
        "bullets": row[5],
        "display_order": row[6],
        "is_active": row[7],
    }
    
    # Build update query
    updates = []
    params: dict = {"tier": tier}
    changed_fields: dict = {}
    
    if price_cents is not None and price_cents != old_values["price_cents"]:
        updates.append("price_cents = :price_cents")
        params["price_cents"] = price_cents
        changed_fields["price_cents"] = {"old": old_values["price_cents"], "new": price_cents}
    
    if period_days is not None and period_days != old_values["period_days"]:
        updates.append("period_days = :period_days")
        params["period_days"] = period_days
        changed_fields["period_days"] = {"old": old_values["period_days"], "new": period_days}
    
    if name_ru is not None and name_ru != old_values["name_ru"]:
        updates.append("name_ru = :name_ru")
        params["name_ru"] = name_ru
        changed_fields["name_ru"] = {"old": old_values["name_ru"], "new": name_ru}
    
    if short_description_ru is not None and short_description_ru != old_values["short_description_ru"]:
        updates.append("short_description_ru = :short_description_ru")
        params["short_description_ru"] = short_description_ru
        changed_fields["short_description_ru"] = {"old": old_values["short_description_ru"], "new": short_description_ru}
    
    if bullets is not None and bullets != old_values["bullets"]:
        updates.append("bullets_json = :bullets_json")
        params["bullets_json"] = bullets
        changed_fields["bullets"] = {"old": old_values["bullets"], "new": bullets}
    
    if display_order is not None and display_order != old_values["display_order"]:
        updates.append("display_order = :display_order")
        params["display_order"] = display_order
        changed_fields["display_order"] = {"old": old_values["display_order"], "new": display_order}
    
    if is_active is not None and is_active != old_values["is_active"]:
        updates.append("is_active = :is_active")
        params["is_active"] = is_active
        changed_fields["is_active"] = {"old": old_values["is_active"], "new": is_active}
    
    if not updates:
        # Nothing to update, return current state (include inactive — get_tier_pricing filters is_active)
        return await fetch_tier_pricing_for_admin(session, tier)
    
    updates.append("updated_at = NOW()")
    
    # Execute update
    await session.execute(
        text(f"UPDATE subscription_tier_pricing SET {', '.join(updates)} WHERE tier = :tier"),
        params,
    )
    
    # Log to audit table
    if changed_fields:
        import json
        # Use CAST(... AS jsonb), not :param::jsonb — text() won't bind the latter on asyncpg.
        await session.execute(
            text("""
                INSERT INTO subscription_tier_pricing_audit
                    (tier_pricing_id, admin_telegram_id, changed_fields)
                VALUES (:tid, :admin_tid, CAST(:changed AS jsonb))
            """),
            {
                "tid": tier_pricing_id,
                "admin_tid": admin_telegram_id,
                "changed": json.dumps(changed_fields),
            },
        )
    
    await session.commit()

    # Return updated record (must not use get_tier_pricing: it hides inactive tiers)
    return await fetch_tier_pricing_for_admin(session, tier)
