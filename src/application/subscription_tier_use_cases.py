"""
Subscription tiers: three-level access model (crm < online < analytics).

Domain logic for tier hierarchy, effective tier resolution, and mock checkout.
"""
import json
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
    SUBSCRIPTION_TIERS,
)


SubscriptionTier = Literal["none", "crm", "online", "analytics"]

# Billing periods (months) — must match DB CHECK and subscription_tier_period_pricing seed.
SUBSCRIPTION_BILLING_PERIOD_MONTHS: tuple[int, ...] = (1, 3, 12)


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

    Prices are authoritative per (tier, period_months) in subscription_tier_period_pricing.
    """
    result = await session.execute(
        text("""
            SELECT
                tier, currency,
                name_ru, short_description_ru, bullets_json, display_order
            FROM subscription_tier_pricing
            WHERE is_active = true
            ORDER BY display_order ASC
        """)
    )
    tier_rows = result.fetchall()
    if not tier_rows:
        return []

    result = await session.execute(
        text("""
            SELECT stpp.tier, stpp.period_months, stpp.price_cents, stpp.period_days
            FROM subscription_tier_period_pricing stpp
            INNER JOIN subscription_tier_pricing stp ON stp.tier = stpp.tier
            WHERE stp.is_active = true
            ORDER BY stpp.tier, stpp.period_months
        """)
    )
    period_rows = result.fetchall()
    by_tier: dict[str, dict[str, int]] = {}
    days_by_tier: dict[str, dict[str, int]] = {}
    for tr, pm, cents, days in period_rows:
        key = str(int(pm))
        by_tier.setdefault(tr, {})[key] = cents
        days_by_tier.setdefault(tr, {})[key] = days

    out: list[dict] = []
    for row in tier_rows:
        tier = row[0]
        prices = by_tier.get(tier, {})
        days_map = days_by_tier.get(tier, {})
        out.append(
            {
                "tier": tier,
                "currency": row[1],
                "name_ru": row[2],
                "short_description_ru": row[3],
                "bullets": row[4] or [],
                "display_order": row[5],
                "includes_tiers": tier_includes(tier),
                "prices_by_period": prices,
                "period_days_by_period": days_map,
            }
        )
    return out


async def _infer_billing_period_months(
    session: AsyncSession,
    tier: str,
    started_at: datetime,
    expires_at: datetime,
) -> int | None:
    """Map segment length to catalog period_months when legacy rows lack billing_period_months."""
    if tier not in SUBSCRIPTION_TIERS:
        return None
    days = max(0, int((expires_at - started_at).total_seconds() // 86400))
    result = await session.execute(
        text("""
            SELECT period_months
            FROM subscription_tier_period_pricing
            WHERE tier = :tier AND ABS(period_days - :days) <= 2
            ORDER BY ABS(period_days - :days) ASC
            LIMIT 1
        """),
        {"tier": tier, "days": days},
    )
    r = result.fetchone()
    return int(r[0]) if r else None


async def get_trainer_subscription_status(session: AsyncSession, trainer_id: int) -> dict:
    """
    Get trainer's current subscription status for UI.
    
    Includes effective tier, expiration, and what's unlocked.
    """
    tier = await get_effective_subscription_tier(session, trainer_id)
    now = datetime.now(timezone.utc)
    
    # Get subscription details if active (latest segment by end date)
    result = await session.execute(
        text("""
            SELECT ts.id, ts.tier, ts.expires_at, ts.status, ts.started_at, ts.billing_period_months
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
        row_tier = row[1] or tier
        expires_at = row[2]
        started_at = row[4]
        stored_pm = row[5]
        billing_pm: int | None = int(stored_pm) if stored_pm is not None else None
        if billing_pm is None and row_tier and expires_at and started_at:
            billing_pm = await _infer_billing_period_months(session, row_tier, started_at, expires_at)
        return {
            "subscription_id": row[0],
            "tier": row_tier,
            "effective_tier": tier,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "status": row[3],
            "started_at": started_at.isoformat() if started_at else None,
            "billing_period_months": billing_pm,
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
        "billing_period_months": None,
        "is_active": False,
        "unlocked_features": [],
    }


async def get_tier_period_pricing(
    session: AsyncSession,
    tier: SubscriptionTier,
    period_months: int,
) -> dict | None:
    """Return price and renewal length for (tier, billing period). Server is source of truth for checkout."""
    if period_months not in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
        return None
    result = await session.execute(
        text("""
            SELECT stpp.price_cents, stp.currency, stpp.period_days, stp.name_ru
            FROM subscription_tier_period_pricing stpp
            INNER JOIN subscription_tier_pricing stp ON stp.tier = stpp.tier
            WHERE stpp.tier = :tier
              AND stpp.period_months = :pm
              AND stp.is_active = true
        """),
        {"tier": tier, "pm": period_months},
    )
    row = result.fetchone()
    if not row:
        return None
    return {
        "price_cents": row[0],
        "currency": row[1],
        "period_days": row[2],
        "name_ru": row[3],
    }


async def set_subscription_after_mock_payment(
    session: AsyncSession,
    trainer_id: int,
    tier: SubscriptionTier,
    period_months: int,
) -> dict | None:
    """
    Activate tier subscription after mock payment.

    Creates new trainer_subscription with tier and period from subscription_tier_period_pricing.
    Policy: replaces tier (doesn't stack), extends from now or current expires_at.
    """
    if tier not in (SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_ANALYTICS):
        return None
    if period_months not in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
        return None

    pricing = await get_tier_period_pricing(session, tier, period_months)
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
                (trainer_id, plan_id, tier, billing_period_months, started_at, expires_at, status)
            VALUES 
                (:tid, :pid, :tier, :bpm, :started_at, :expires_at, :status)
            RETURNING id, started_at, expires_at
        """),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "tier": tier,
            "bpm": period_months,
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
        "period_months": period_months,
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


async def _fetch_period_prices_for_tier(session: AsyncSession, tier: str) -> list[dict]:
    """Rows from subscription_tier_period_pricing for one tier."""
    result = await session.execute(
        text("""
            SELECT id, period_months, price_cents, period_days
            FROM subscription_tier_period_pricing
            WHERE tier = :tier
            ORDER BY period_months
        """),
        {"tier": tier},
    )
    return [
        {"id": r[0], "period_months": r[1], "price_cents": r[2], "period_days": r[3]}
        for r in result.fetchall()
    ]


def _tier_pricing_row_to_admin_dict(row, period_prices: list[dict]) -> dict:
    """Map DB row + period matrix to admin API dict (includes inactive tiers)."""
    p1 = next((p["price_cents"] for p in period_prices if p["period_months"] == 1), row[2])
    return {
        "id": row[0],
        "tier": row[1],
        "price_cents": p1,
        "currency": row[3],
        "period_days": row[4],
        "name_ru": row[5],
        "short_description_ru": row[6],
        "bullets": row[7] or [],
        "display_order": row[8],
        "is_active": row[9],
        "created_at": row[10].isoformat() if row[10] else None,
        "updated_at": row[11].isoformat() if row[11] else None,
        "period_prices": period_prices,
    }


async def fetch_tier_pricing_for_admin(session: AsyncSession, tier: str) -> dict | None:
    """Single tier row for admin, including when is_active is false."""
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
    if not row:
        return None
    period_prices = await _fetch_period_prices_for_tier(session, tier)
    return _tier_pricing_row_to_admin_dict(row, period_prices)


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
    out: list[dict] = []
    for row in rows:
        tier = row[1]
        period_prices = await _fetch_period_prices_for_tier(session, tier)
        out.append(_tier_pricing_row_to_admin_dict(row, period_prices))
    return out


async def update_subscription_tier_pricing(
    session: AsyncSession,
    tier: str,
    admin_telegram_id: int | None,
    *,
    period_prices: dict[str, int] | None = None,
    name_ru: str | None = None,
    short_description_ru: str | None = None,
    bullets: list[str] | None = None,
    display_order: int | None = None,
    is_active: bool | None = None,
) -> dict | None:
    """
    Update tier metadata and/or per-period prices. Changes are logged to audit tables.

    Returns updated record or None if tier not found.
    """
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

    updates = []
    params: dict = {"tier": tier}
    changed_fields: dict = {}

    if name_ru is not None and name_ru != old_values["name_ru"]:
        updates.append("name_ru = :name_ru")
        params["name_ru"] = name_ru
        changed_fields["name_ru"] = {"old": old_values["name_ru"], "new": name_ru}

    if short_description_ru is not None and short_description_ru != old_values["short_description_ru"]:
        updates.append("short_description_ru = :short_description_ru")
        params["short_description_ru"] = short_description_ru
        changed_fields["short_description_ru"] = {
            "old": old_values["short_description_ru"],
            "new": short_description_ru,
        }

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

    period_changed = False
    if period_prices:
        for key, new_cents in period_prices.items():
            try:
                pm = int(key)
            except (TypeError, ValueError):
                continue
            if pm not in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
                continue
            if new_cents < 0:
                continue
            cur = await session.execute(
                text("""
                    SELECT id, price_cents FROM subscription_tier_period_pricing
                    WHERE tier = :tier AND period_months = :pm
                """),
                {"tier": tier, "pm": pm},
            )
            crow = cur.fetchone()
            if not crow or crow[1] == new_cents:
                continue
            row_id = crow[0]
            old_cents = crow[1]
            await session.execute(
                text("""
                    UPDATE subscription_tier_period_pricing
                    SET price_cents = :pc, updated_at = NOW()
                    WHERE id = :id
                """),
                {"pc": new_cents, "id": row_id},
            )
            period_changed = True
            audit_payload = {
                "tier": tier,
                "period_months": pm,
                "price_cents": {"old": old_cents, "new": new_cents},
            }
            await session.execute(
                text("""
                    INSERT INTO subscription_tier_period_pricing_audit
                        (tier_period_pricing_id, admin_telegram_id, changed_fields)
                    VALUES (:tid, :admin_tid, CAST(:changed AS jsonb))
                """),
                {
                    "tid": row_id,
                    "admin_tid": admin_telegram_id,
                    "changed": json.dumps(audit_payload),
                },
            )

    if not updates and not period_changed:
        return await fetch_tier_pricing_for_admin(session, tier)

    if updates:
        updates.append("updated_at = NOW()")
        await session.execute(
            text(f"UPDATE subscription_tier_pricing SET {', '.join(updates)} WHERE tier = :tier"),
            params,
        )
        if changed_fields:
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
    return await fetch_tier_pricing_for_admin(session, tier)
