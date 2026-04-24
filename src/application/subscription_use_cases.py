"""
Trainer platform subscription: trial, paid plans, active check.
Single source for trainer_has_active_subscription used by catalog and payment flows.
"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.platform_settings_use_cases import (
    WELCOME_TRIAL_PERIOD_DAYS_KEY,
    get_platform_int,
)
from src.shared.config import Settings
from src.application.subscription_tier_use_cases import (
    SUBSCRIPTION_BILLING_PERIOD_MONTHS,
    SUBSCRIPTION_MODULE_ANALYTICS,
    SUBSCRIPTION_MODULE_ONLINE,
    SUBSCRIPTION_MODULES,
    SUBSCRIPTION_TIER_ANALYTICS,
    SUBSCRIPTION_TIER_CRM,
    SUBSCRIPTION_TIER_ONLINE,
    SUBSCRIPTION_TIERS,
    default_modules_dict,
    get_module_period_pricing,
    get_tier_period_pricing,
    normalize_modules_dict,
)
from src.infrastructure.db.models import (
    INVOICE_STATUS_CANCELLED,
    INVOICE_STATUS_OVERDUE,
    INVOICE_STATUS_PAID,
    INVOICE_STATUS_SENT,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_TRIAL,
)

# Welcome / trial: full product access — CRM base + all paid modules (incl. cohorts).
_TRIAL_MODULES_JSON = json.dumps({"online": True, "analytics": True, "groups": True}, ensure_ascii=False)
_DEFAULT_PAID_MODULES_JSON = json.dumps(
    {"online": False, "analytics": False, "groups": False}, ensure_ascii=False
)


async def trainer_has_active_subscription(session: AsyncSession, trainer_id: int) -> bool:
    """True if trainer has a subscription with expires_at > now() and status in (trial, active)."""
    now = datetime.now(timezone.utc)
    r = await session.execute(
        text("""
            SELECT 1
            FROM trainer_subscriptions
            WHERE trainer_id = :tid
              AND expires_at > :now
              AND status IN (:s1, :s2)
            LIMIT 1
        """),
        {"tid": trainer_id, "now": now, "s1": SUBSCRIPTION_STATUS_TRIAL, "s2": SUBSCRIPTION_STATUS_ACTIVE},
    )
    return r.fetchone() is not None


async def get_active_subscription(session: AsyncSession, trainer_id: int) -> dict | None:
    """Return current active subscription for trainer (for UI). None if none."""
    now = datetime.now(timezone.utc)
    r = await session.execute(
        text("""
            SELECT ts.id, ts.trainer_id, ts.plan_id, ts.started_at, ts.expires_at, ts.status,
                   sp.name AS plan_name, sp.price_cents, sp.period_days, sp.is_trial
            FROM trainer_subscriptions ts
            JOIN subscription_plans sp ON sp.id = ts.plan_id
            WHERE ts.trainer_id = :tid
              AND ts.expires_at > :now
              AND ts.status IN (:s1, :s2)
            ORDER BY ts.expires_at DESC
            LIMIT 1
        """),
        {"tid": trainer_id, "now": now, "s1": SUBSCRIPTION_STATUS_TRIAL, "s2": SUBSCRIPTION_STATUS_ACTIVE},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "trainer_id": row[1],
        "plan_id": row[2],
        "started_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
        "expires_at": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
        "status": row[5],
        "plan_name": row[6],
        "price_cents": row[7],
        "period_days": row[8],
        "is_trial": row[9],
    }


async def get_trial_plan_id(session: AsyncSession) -> int | None:
    """Return plan id for trial (is_trial=true). Used when creating trial subscription."""
    r = await session.execute(
        text("SELECT id FROM subscription_plans WHERE is_trial = true LIMIT 1")
    )
    row = r.fetchone()
    return row[0] if row else None


async def get_resolved_welcome_trial_days_for_display(session: AsyncSession) -> int:
    """Resolved trial length (env → DB → plan) for admin UI."""
    r = await session.execute(
        text("SELECT period_days FROM subscription_plans WHERE is_trial = true LIMIT 1")
    )
    row = r.fetchone()
    plan_days = int(row[0]) if row else 21
    return await resolve_trial_period_days(session, plan_days)


async def resolve_trial_period_days(session: AsyncSession, plan_default_days: int) -> int:
    """Trial length: TRIAL_PERIOD_DAYS env, else platform_settings, else plan row."""
    env_days = Settings().trial_period_days
    if env_days is not None and env_days > 0:
        return int(env_days)
    db_days = await get_platform_int(session, WELCOME_TRIAL_PERIOD_DAYS_KEY)
    if db_days is not None and db_days > 0:
        return int(db_days)
    return max(1, int(plan_default_days))


async def trainer_has_used_trial(session: AsyncSession, trainer_id: int) -> bool:
    """True if trainer already had a subscription with trial plan (one trial per trainer)."""
    r = await session.execute(
        text("""
            SELECT 1
            FROM trainer_subscriptions ts
            JOIN subscription_plans sp ON sp.id = ts.plan_id
            WHERE ts.trainer_id = :tid AND sp.is_trial = true
            LIMIT 1
        """),
        {"tid": trainer_id},
    )
    return r.fetchone() is not None


async def create_trial_subscription(session: AsyncSession, trainer_id: int) -> dict | None:
    """Create a trial subscription for trainer if they have not used trial yet. Returns subscription info or None."""
    if await trainer_has_used_trial(session, trainer_id):
        return None
    plan_id = await get_trial_plan_id(session)
    if not plan_id:
        return None
    r = await session.execute(
        text("""
            SELECT period_days FROM subscription_plans WHERE id = :pid
        """),
        {"pid": plan_id},
    )
    row = r.fetchone()
    if not row:
        return None
    period_days = await resolve_trial_period_days(session, int(row[0]))
    now = datetime.now(timezone.utc)
    started_at = now
    expires_at = now + timedelta(days=period_days)
    r = await session.execute(
        text("""
            INSERT INTO trainer_subscriptions
                (trainer_id, plan_id, tier, modules, started_at, expires_at, status)
            VALUES (:tid, :pid, :tier, CAST(:mods AS jsonb), :started_at, :expires_at, :status)
            RETURNING id, started_at, expires_at
        """),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "tier": SUBSCRIPTION_TIER_CRM,
            "mods": _TRIAL_MODULES_JSON,
            "started_at": started_at,
            "expires_at": expires_at,
            "status": SUBSCRIPTION_STATUS_TRIAL,
        },
    )
    row = r.fetchone()
    await session.commit()
    return {
        "id": row[0],
        "trainer_id": trainer_id,
        "plan_id": plan_id,
        "started_at": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]),
        "expires_at": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
        "status": SUBSCRIPTION_STATUS_TRIAL,
    }


async def ensure_trainer_welcome_trial(session: AsyncSession, trainer_id: int) -> None:
    """
    After first Telegram link: create trial with full modules if missing.

    If trial already exists, normalize row(s): canonical CRM tier + all modules (online, analytics, groups).
    """
    created = await create_trial_subscription(session, trainer_id)
    if created is not None:
        return
    now = datetime.now(timezone.utc)
    await session.execute(
        text("""
            UPDATE trainer_subscriptions AS ts
            SET tier = :tier, modules = CAST(:mods AS jsonb)
            FROM subscription_plans sp
            WHERE ts.trainer_id = :tid
              AND ts.plan_id = sp.id
              AND sp.is_trial = true
              AND ts.status IN (:s1, :s2)
              AND ts.expires_at > :now
        """),
        {
            "tid": trainer_id,
            "tier": SUBSCRIPTION_TIER_CRM,
            "mods": _TRIAL_MODULES_JSON,
            "s1": SUBSCRIPTION_STATUS_TRIAL,
            "s2": SUBSCRIPTION_STATUS_ACTIVE,
            "now": now,
        },
    )
    await session.commit()


async def expire_subscriptions_to_past_due(session: AsyncSession) -> int:
    """Set status to past_due for subscriptions with expires_at < now() and status in (trial, active). Returns count updated."""
    now = datetime.now(timezone.utc)
    r = await session.execute(
        text("""
            UPDATE trainer_subscriptions
            SET status = :past_due
            WHERE expires_at < :now
              AND status IN (:s1, :s2)
            RETURNING id
        """),
        {
            "past_due": SUBSCRIPTION_STATUS_PAST_DUE,
            "now": now,
            "s1": SUBSCRIPTION_STATUS_TRIAL,
            "s2": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    ids = r.fetchall()
    if ids:
        await session.commit()
    return len(ids)


async def get_subscriptions_reminder_due(session: AsyncSession, days_ahead: int = 3) -> list[dict]:
    """Subscriptions expiring in the next days_ahead days, status in (trial, active), reminder_sent_at is null. Returns list with id, trainer_id, expires_at, trainer_telegram_id."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days_ahead)
    r = await session.execute(
        text("""
            SELECT ts.id, ts.trainer_id, ts.expires_at, t.telegram_id, ts.status
            FROM trainer_subscriptions ts
            JOIN trainers t ON t.id = ts.trainer_id
            WHERE ts.expires_at > :now
              AND ts.expires_at <= :end
              AND ts.status IN (:s1, :s2)
              AND ts.reminder_sent_at IS NULL
            ORDER BY ts.expires_at
        """),
        {
            "now": now,
            "end": end,
            "s1": SUBSCRIPTION_STATUS_TRIAL,
            "s2": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "trainer_id": row[1],
            "expires_at": row[2],
            "trainer_telegram_id": row[3],
            "status": row[4],
        }
        for row in rows
    ]


async def mark_subscription_reminder_sent(session: AsyncSession, subscription_id: int) -> None:
    """Set reminder_sent_at = now() for the subscription."""
    now = datetime.now(timezone.utc)
    await session.execute(
        text("""
            UPDATE trainer_subscriptions
            SET reminder_sent_at = :now
            WHERE id = :id
        """),
        {"id": subscription_id, "now": now},
    )
    await session.commit()


async def get_paid_plan_id(session: AsyncSession) -> int | None:
    """First non-trial plan by sort_order (e.g. «Месяц»). Used when no plan chosen."""
    r = await session.execute(
        text("""
            SELECT id FROM subscription_plans
            WHERE is_trial = false
            ORDER BY sort_order ASC
            LIMIT 1
        """)
    )
    row = r.fetchone()
    return row[0] if row else None


async def list_paid_subscription_plans(session: AsyncSession) -> list[dict]:
    """All non-trial plans for trainer to choose. Ordered by sort_order."""
    r = await session.execute(
        text("""
            SELECT id, name, price_cents, period_days, sort_order
            FROM subscription_plans
            WHERE is_trial = false
            ORDER BY sort_order ASC
        """)
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "name": row[1],
            "price_cents": row[2],
            "period_days": row[3],
            "sort_order": row[4],
        }
        for row in rows
    ]


async def create_subscription_invoice(
    session: AsyncSession,
    trainer_id: int,
    plan_id: int,
) -> dict | None:
    """
    Create trainer_invoices row for paid plan (not trial). Period: from now or from current
    subscription expires_at if present. Returns invoice info or None if plan is trial / not found.
    """
    r = await session.execute(
        text("""
            SELECT id, name, price_cents, period_days, is_trial
            FROM subscription_plans WHERE id = :pid
        """),
        {"pid": plan_id},
    )
    row = r.fetchone()
    if not row or row[4]:  # is_trial
        return None
    plan_name, amount_cents, period_days = row[1], row[2], row[3]
    now = datetime.now(timezone.utc)
    # Period start: end of current active subscription if any, else now
    r2 = await session.execute(
        text("""
            SELECT expires_at FROM trainer_subscriptions
            WHERE trainer_id = :tid AND status IN (:s1, :s2)
            ORDER BY expires_at DESC LIMIT 1
        """),
        {"tid": trainer_id, "s1": SUBSCRIPTION_STATUS_TRIAL, "s2": SUBSCRIPTION_STATUS_ACTIVE},
    )
    row2 = r2.fetchone()
    period_start = row2[0] if row2 and row2[0] and row2[0] > now else now
    period_end = period_start + timedelta(days=period_days)
    due_date = period_end
    r3 = await session.execute(
        text("""
            INSERT INTO trainer_invoices
            (trainer_id, subscription_plan_id, amount_cents, period_start, period_end, due_date, status)
            VALUES (:tid, :pid, :amount, :period_start, :period_end, :due_date, :status)
            RETURNING id, amount_cents, period_start, period_end
        """),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "amount": amount_cents,
            "period_start": period_start,
            "period_end": period_end,
            "due_date": due_date,
            "status": INVOICE_STATUS_SENT,
        },
    )
    row3 = r3.fetchone()
    await session.commit()
    return {
        "invoice_id": row3[0],
        "amount_cents": row3[1],
        "period_start": row3[2],
        "period_end": row3[3],
        "plan_name": plan_name,
    }


async def get_pending_subscription_invoice(session: AsyncSession, trainer_id: int) -> dict | None:
    """Latest unpaid invoice (status sent or overdue) for trainer. Includes plan_name for display."""
    r = await session.execute(
        text("""
            SELECT ti.id, ti.subscription_plan_id, ti.amount_cents, ti.period_start, ti.period_end, ti.status,
                   sp.name AS plan_name
            FROM trainer_invoices ti
            JOIN subscription_plans sp ON sp.id = ti.subscription_plan_id
            WHERE ti.trainer_id = :tid AND ti.status IN ('sent', 'overdue')
            ORDER BY ti.id DESC
            LIMIT 1
        """),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "invoice_id": row[0],
        "subscription_plan_id": row[1],
        "amount_cents": row[2],
        "period_start": row[3],
        "period_end": row[4],
        "status": row[5],
        "plan_name": row[6],
    }


async def cancel_pending_catalog_subscription_invoices(session: AsyncSession, trainer_id: int) -> None:
    """Invalidate unpaid catalog (tier/constructor) invoices before issuing a new request."""
    await session.execute(
        text("""
            UPDATE trainer_invoices SET status = :cancelled
            WHERE trainer_id = :tid AND status IN (:sent, :overdue)
              AND checkout_modules IS NOT NULL AND checkout_billing_period_months IS NOT NULL
        """),
        {
            "cancelled": INVOICE_STATUS_CANCELLED,
            "tid": trainer_id,
            "sent": INVOICE_STATUS_SENT,
            "overdue": INVOICE_STATUS_OVERDUE,
        },
    )


async def create_catalog_subscription_invoice_for_trainer(
    session: AsyncSession,
    trainer_id: int,
    *,
    tier: str | None,
    modules: dict | None,
    period_months: int,
) -> dict | None:
    """
    Unpaid invoice for Mini App catalog selection (tier bundle or CRM+modules constructor).
    Payment via ERIP / manual: ops confirm with confirm_subscription_invoice_after_payment.
    """
    if period_months not in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
        return None
    bundle_tier: str | None = None
    mods = default_modules_dict()
    if tier is not None:
        if tier not in SUBSCRIPTION_TIERS:
            return None
        bundle_tier = tier
        if tier == SUBSCRIPTION_TIER_ONLINE:
            mods[SUBSCRIPTION_MODULE_ONLINE] = True
        elif tier == SUBSCRIPTION_TIER_ANALYTICS:
            mods[SUBSCRIPTION_MODULE_ONLINE] = True
            mods[SUBSCRIPTION_MODULE_ANALYTICS] = True
    elif modules is not None:
        mods = normalize_modules_dict(modules)
    else:
        return None

    if bundle_tier is not None:
        tp = await get_tier_period_pricing(session, bundle_tier, period_months)  # type: ignore[arg-type]
        if not tp:
            return None
        total_cents = int(tp["price_cents"])
        period_days = int(tp["period_days"])
        plan_label = str(tp.get("name_ru") or bundle_tier)
    else:
        base = await get_tier_period_pricing(session, SUBSCRIPTION_TIER_CRM, period_months)
        if not base:
            return None
        total_cents = int(base["price_cents"])
        period_days = int(base["period_days"])
        for key in SUBSCRIPTION_MODULES:
            if not mods.get(key):
                continue
            mp = await get_module_period_pricing(session, key, period_months)
            if not mp:
                return None
            total_cents += int(mp["price_cents"])
        plan_label = "Конструктор подписки"

    now = datetime.now(timezone.utc)
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
    period_start = row[0] if row and row[0] and row[0] > now else now
    period_end = period_start + timedelta(days=period_days)
    due_date = period_end

    plan_result = await session.execute(
        text("SELECT id, name FROM subscription_plans WHERE is_trial = false ORDER BY sort_order LIMIT 1")
    )
    plan_row = plan_result.fetchone()
    if not plan_row:
        return None
    plan_id, plan_name_fallback = plan_row[0], plan_row[1]

    mods_json = json.dumps(mods, ensure_ascii=False)
    await cancel_pending_catalog_subscription_invoices(session, trainer_id)

    r3 = await session.execute(
        text("""
            INSERT INTO trainer_invoices
            (trainer_id, subscription_plan_id, amount_cents, period_start, period_end, due_date, status,
             checkout_modules, checkout_billing_period_months, checkout_bundle_tier)
            VALUES (:tid, :pid, :amount, :period_start, :period_end, :due_date, :status,
                    CAST(:mods AS jsonb), :bpm, :bundle)
            RETURNING id, amount_cents, period_start, period_end
        """),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "amount": total_cents,
            "period_start": period_start,
            "period_end": period_end,
            "due_date": due_date,
            "status": INVOICE_STATUS_SENT,
            "mods": mods_json,
            "bpm": period_months,
            "bundle": bundle_tier,
        },
    )
    row3 = r3.fetchone()
    await session.commit()
    return {
        "invoice_id": row3[0],
        "amount_cents": row3[1],
        "period_start": row3[2],
        "period_end": row3[3],
        "plan_name": plan_label or plan_name_fallback,
        "checkout_modules": mods,
        "checkout_billing_period_months": period_months,
        "checkout_bundle_tier": bundle_tier,
    }


async def list_pending_catalog_subscription_invoices(
    session: AsyncSession,
    *,
    limit: int = 40,
) -> list[dict]:
    """
    Catalog (tier/constructor) invoices awaiting payment: status sent/overdue, checkout snapshot set.
    Newest first. For admin bot / ops.
    """
    lim = max(1, min(int(limit), 80))
    r = await session.execute(
        text("""
            SELECT ti.id, ti.trainer_id, ti.amount_cents, ti.period_start, ti.period_end, ti.status,
                   ti.checkout_bundle_tier, ti.checkout_billing_period_months, ti.checkout_modules,
                   sp.name AS plan_row_name,
                   t.telegram_id, t.telegram_username, tp.first_name, tp.last_name
            FROM trainer_invoices ti
            INNER JOIN trainers t ON t.id = ti.trainer_id
            INNER JOIN subscription_plans sp ON sp.id = ti.subscription_plan_id
            LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
            WHERE ti.checkout_modules IS NOT NULL
              AND ti.checkout_billing_period_months IS NOT NULL
              AND ti.status IN (:sent, :overdue)
            ORDER BY ti.id DESC
            LIMIT :lim
        """),
        {"sent": INVOICE_STATUS_SENT, "overdue": INVOICE_STATUS_OVERDUE, "lim": lim},
    )
    out: list[dict] = []
    for row in r.fetchall():
        out.append(
            {
                "invoice_id": row[0],
                "trainer_id": row[1],
                "amount_cents": row[2],
                "period_start": row[3],
                "period_end": row[4],
                "status": row[5],
                "checkout_bundle_tier": row[6],
                "checkout_billing_period_months": row[7],
                "checkout_modules": row[8],
                "plan_row_name": row[9],
                "telegram_id": int(row[10]) if row[10] is not None else None,
                "telegram_username": row[11],
                "first_name": row[12],
                "last_name": row[13],
            }
        )
    return out


async def confirm_subscription_invoice_after_payment(
    session: AsyncSession,
    invoice_id: int,
    payment_external_id: str,
) -> bool:
    """
    On gateway success for subscription: mark invoice paid, create trainer_subscriptions
    (active) for the period. Idempotent: if invoice already paid, return True without duplicate.

    Catalog invoices (checkout_modules set): insert row with tier=crm + modules JSON + billing period.
    Legacy invoices: same entitlement shape (CRM base + default modules).

    Also triggers referral credit grant if this is the trainer's first paid subscription.
    """
    r = await session.execute(
        text("""
            SELECT trainer_id, subscription_plan_id, amount_cents, period_start, period_end, status,
                   checkout_modules, checkout_billing_period_months, checkout_bundle_tier
            FROM trainer_invoices WHERE id = :iid
        """),
        {"iid": invoice_id},
    )
    row = r.fetchone()
    if not row:
        return False
    (
        tid,
        plan_id,
        _amount,
        period_start,
        period_end,
        status,
        checkout_modules,
        checkout_billing_period_months,
        _checkout_bundle_tier,
    ) = row
    if status == INVOICE_STATUS_PAID:
        return True
    if status not in (INVOICE_STATUS_SENT, INVOICE_STATUS_OVERDUE):
        return False
    catalog_checkout = (
        checkout_modules is not None and checkout_billing_period_months is not None
    )
    mods_for_insert = (
        normalize_modules_dict(checkout_modules) if checkout_modules is not None else None
    )
    bpm = checkout_billing_period_months if checkout_billing_period_months is not None else None
    # Check if this is the trainer's first paid subscription (for referral credit)
    r_first = await session.execute(
        text("""
            SELECT 1 FROM trainer_subscriptions
            WHERE trainer_id = :tid AND status = :active
            LIMIT 1
        """),
        {"tid": tid, "active": SUBSCRIPTION_STATUS_ACTIVE},
    )
    is_first_paid = r_first.fetchone() is None
    now = datetime.now(timezone.utc)
    await session.execute(
        text("""
            UPDATE trainer_invoices
            SET status = :paid, paid_at = :now, payment_external_id = :ext_id
            WHERE id = :iid
        """),
        {"paid": INVOICE_STATUS_PAID, "now": now, "ext_id": payment_external_id[:256], "iid": invoice_id},
    )
    if catalog_checkout and mods_for_insert is not None and bpm is not None:
        mods_json = json.dumps(mods_for_insert, ensure_ascii=False)
        await session.execute(
            text("""
                INSERT INTO trainer_subscriptions
                    (trainer_id, plan_id, tier, modules, billing_period_months, started_at, expires_at, status)
                VALUES
                    (:tid, :pid, :tier, CAST(:mods AS jsonb), :bpm, :started_at, :expires_at, :status)
            """),
            {
                "tid": tid,
                "pid": plan_id,
                "tier": SUBSCRIPTION_TIER_CRM,
                "mods": mods_json,
                "bpm": int(bpm),
                "started_at": period_start,
                "expires_at": period_end,
                "status": SUBSCRIPTION_STATUS_ACTIVE,
            },
        )
    else:
        await session.execute(
            text("""
                INSERT INTO trainer_subscriptions
                    (trainer_id, plan_id, tier, modules, billing_period_months, started_at, expires_at, status)
                VALUES
                    (:tid, :pid, :tier, CAST(:mods AS jsonb), NULL, :started_at, :expires_at, :status)
            """),
            {
                "tid": tid,
                "pid": plan_id,
                "tier": SUBSCRIPTION_TIER_CRM,
                "mods": _DEFAULT_PAID_MODULES_JSON,
                "started_at": period_start,
                "expires_at": period_end,
                "status": SUBSCRIPTION_STATUS_ACTIVE,
            },
        )
    await session.commit()
    # Referral credit: grant to referrer if this is first paid subscription
    if is_first_paid:
        from src.application.referral_use_cases import grant_referral_credit_if_eligible

        await grant_referral_credit_if_eligible(session, tid)
    return True


async def admin_grant_subscription_for_invoice(
    session: AsyncSession,
    invoice_id: int,
    *,
    modules: dict[str, bool] | None = None,
    period_months: int | None = None,
    admin_id: int,
) -> dict | None:
    """
    Admin path: confirm a pending invoice as paid (no money transfer required).

    If modules and/or period_months are provided, the invoice is rewritten in place first
    (modules JSON, billing period, recomputed amount, recomputed period_end). Then we go
    through the normal confirm_subscription_invoice_after_payment flow so trainer
    entitlements / referral credits / status all update via the same code path as ERIP.

    Returns a dict describing the activated subscription (trainer_id, modules, period_end,
    period_months, amount_cents, label) or None on failure.
    """
    r = await session.execute(
        text("""
            SELECT trainer_id, status, period_start, period_end, amount_cents,
                   checkout_modules, checkout_billing_period_months
            FROM trainer_invoices WHERE id = :iid
        """),
        {"iid": invoice_id},
    )
    row = r.fetchone()
    if not row:
        return None
    (
        tid,
        status,
        period_start,
        period_end,
        amount_cents,
        existing_modules,
        existing_pm,
    ) = row
    if status not in (INVOICE_STATUS_SENT, INVOICE_STATUS_OVERDUE, INVOICE_STATUS_PAID):
        return None

    final_modules = (
        normalize_modules_dict(modules) if modules is not None else normalize_modules_dict(existing_modules)
    )
    final_pm = int(period_months) if period_months is not None else (int(existing_pm) if existing_pm else None)

    # Rewrite invoice if anything changed (and it's still unpaid) so the audit trail matches reality.
    if status in (INVOICE_STATUS_SENT, INVOICE_STATUS_OVERDUE) and final_pm is not None:
        if final_pm not in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
            return None
        base = await get_tier_period_pricing(session, SUBSCRIPTION_TIER_CRM, final_pm)
        if not base:
            return None
        new_total = int(base["price_cents"])
        new_period_days = int(base["period_days"])
        for key in SUBSCRIPTION_MODULES:
            if not final_modules.get(key):
                continue
            mp = await get_module_period_pricing(session, key, final_pm)
            if not mp:
                return None
            new_total += int(mp["price_cents"])
        new_period_end = period_start + timedelta(days=new_period_days)
        await session.execute(
            text("""
                UPDATE trainer_invoices
                SET checkout_modules = CAST(:mods AS jsonb),
                    checkout_billing_period_months = :pm,
                    amount_cents = :amt,
                    period_end = :pe,
                    due_date = :pe
                WHERE id = :iid
            """),
            {
                "mods": json.dumps(final_modules, ensure_ascii=False),
                "pm": int(final_pm),
                "amt": int(new_total),
                "pe": new_period_end,
                "iid": invoice_id,
            },
        )
        await session.commit()
        amount_cents = new_total
        period_end = new_period_end

    if status != INVOICE_STATUS_PAID:
        ext_id = f"admin_grant:{int(admin_id)}"
        ok = await confirm_subscription_invoice_after_payment(session, invoice_id, ext_id)
        if not ok:
            return None

    return {
        "invoice_id": int(invoice_id),
        "trainer_id": int(tid),
        "modules": final_modules,
        "period_months": final_pm,
        "amount_cents": int(amount_cents) if amount_cents is not None else None,
        "period_end": period_end,
    }


async def get_active_paid_subscription_for_merge(
    session: AsyncSession,
    trainer_id: int,
) -> dict | None:
    """
    Return trainer's current paid (non-trial) subscription that covers NOW, for admin
    merge flow. Used to offer "add modules to existing plan" instead of stacking a new one.

    Returns None if trainer has no active paid plan (only trial, or nothing at all) —
    in that case admin should use the regular stack flow.
    """
    now = datetime.now(timezone.utc)
    r = await session.execute(
        text("""
            SELECT id, tier, modules, started_at, expires_at, billing_period_months
            FROM trainer_subscriptions
            WHERE trainer_id = :tid
              AND started_at <= :now
              AND expires_at > :now
              AND status = :active
              AND tier IS NOT NULL
            ORDER BY expires_at DESC
            LIMIT 1
        """),
        {"tid": int(trainer_id), "now": now, "active": SUBSCRIPTION_STATUS_ACTIVE},
    )
    row = r.fetchone()
    if not row:
        return None
    sub_id, tier, mods, started_at, expires_at, pm = row
    remaining_seconds = max(0.0, (expires_at - now).total_seconds())
    remaining_days = int(remaining_seconds // 86400)
    return {
        "subscription_id": int(sub_id),
        "tier": tier,
        "modules": normalize_modules_dict(mods),
        "started_at": started_at,
        "expires_at": expires_at,
        "billing_period_months": int(pm) if pm is not None else None,
        "remaining_days": remaining_days,
    }


async def compute_prorated_module_addon_cost_cents(
    session: AsyncSession,
    modules_to_add: list[str],
    remaining_days: int,
) -> int | None:
    """
    Cost of adding `modules_to_add` to an already-paid subscription for `remaining_days` only.

    Pro-rated against the 1-month catalog price: we divide monthly price by 30 and charge
    the remaining days. Returns cents. Returns None if a module has no catalog pricing.
    """
    if remaining_days <= 0 or not modules_to_add:
        return 0
    total = 0
    for code in modules_to_add:
        mp = await get_module_period_pricing(session, code, 1)
        if not mp:
            return None
        monthly_cents = int(mp["price_cents"])
        prorated = int(round(monthly_cents * (remaining_days / 30.0)))
        total += prorated
    return total


async def admin_merge_modules_into_current_subscription(
    session: AsyncSession,
    invoice_id: int,
    *,
    add_modules: dict[str, bool],
    admin_id: int,
) -> dict | None:
    """
    Admin path: extend the trainer's CURRENT active paid subscription with extra modules,
    without creating a new subscription row.

    Use case: trainer paid for CRM/year, later asks for 'add groups'. Instead of stacking
    a new row after the year, we OR the new module flags into the current row and charge
    a pro-rated delta for the remaining days. Invoice is rewritten to describe the delta
    (modules = what we added, amount = pro-rated price, period_end = current sub's
    expires_at) and then marked paid.

    Returns activation summary (trainer_id, modules = final UNION, period_end, amount_cents,
    period_months = 0 sentinel "add-on", invoice_id) or None on failure.
    """
    now = datetime.now(timezone.utc)
    r = await session.execute(
        text("""
            SELECT trainer_id, status FROM trainer_invoices WHERE id = :iid
        """),
        {"iid": int(invoice_id)},
    )
    inv_row = r.fetchone()
    if not inv_row:
        return None
    tid, inv_status = int(inv_row[0]), inv_row[1]
    if inv_status not in (INVOICE_STATUS_SENT, INVOICE_STATUS_OVERDUE):
        return None

    current = await get_active_paid_subscription_for_merge(session, tid)
    if not current:
        # No active paid subscription to merge into.
        return None

    add = normalize_modules_dict(add_modules)
    new_modules_to_add = [k for k in SUBSCRIPTION_MODULES if add.get(k) and not current["modules"].get(k)]
    if not new_modules_to_add:
        # Nothing to add — every requested module is already active. Treat as a no-op success.
        return {
            "invoice_id": int(invoice_id),
            "trainer_id": tid,
            "modules": current["modules"],
            "period_end": current["expires_at"],
            "amount_cents": 0,
            "period_months": 0,
            "merged": True,
            "remaining_days": current["remaining_days"],
        }

    cost_cents = await compute_prorated_module_addon_cost_cents(
        session, new_modules_to_add, current["remaining_days"]
    )
    if cost_cents is None:
        return None

    union_modules = dict(current["modules"])
    for k in new_modules_to_add:
        union_modules[k] = True

    # 1. Extend the existing subscription row's modules (no expires_at change).
    await session.execute(
        text("""
            UPDATE trainer_subscriptions
            SET modules = CAST(:mods AS jsonb)
            WHERE id = :sid
        """),
        {
            "mods": json.dumps(union_modules, ensure_ascii=False),
            "sid": int(current["subscription_id"]),
        },
    )

    # 2. Rewrite the invoice to describe the add-on: modules = delta, period_end = sub's
    #    end, amount = pro-rated cents, period_months = 0 sentinel (not a full cycle).
    delta_mods_dict = {k: (k in new_modules_to_add) for k in SUBSCRIPTION_MODULES}
    await session.execute(
        text("""
            UPDATE trainer_invoices
            SET checkout_modules = CAST(:mods AS jsonb),
                checkout_billing_period_months = 0,
                amount_cents = :amt,
                period_start = :ps,
                period_end = :pe,
                due_date = :pe,
                status = :paid,
                paid_at = :now,
                external_payment_id = :ext
            WHERE id = :iid
        """),
        {
            "mods": json.dumps(delta_mods_dict, ensure_ascii=False),
            "amt": int(cost_cents),
            "ps": now,
            "pe": current["expires_at"],
            "paid": INVOICE_STATUS_PAID,
            "now": now,
            "ext": f"admin_merge:{int(admin_id)}",
            "iid": int(invoice_id),
        },
    )
    await session.commit()

    return {
        "invoice_id": int(invoice_id),
        "trainer_id": tid,
        # Final state: union of what the trainer has after the merge.
        "modules": union_modules,
        # Which modules were actually added in this call — handy for trainer-facing message.
        "added_modules": new_modules_to_add,
        "period_end": current["expires_at"],
        "amount_cents": int(cost_cents),
        # 0 signals "add-on, not a period renewal" to callers.
        "period_months": 0,
        "merged": True,
        "remaining_days": current["remaining_days"],
    }


async def admin_cancel_pending_subscription_invoice(
    session: AsyncSession,
    invoice_id: int,
) -> dict | None:
    """Admin declines a trainer's invoice request. Marks invoice cancelled. Idempotent for already-cancelled."""
    r = await session.execute(
        text("""
            SELECT trainer_id, status FROM trainer_invoices WHERE id = :iid
        """),
        {"iid": invoice_id},
    )
    row = r.fetchone()
    if not row:
        return None
    tid, status = int(row[0]), row[1]
    if status not in (INVOICE_STATUS_SENT, INVOICE_STATUS_OVERDUE, INVOICE_STATUS_CANCELLED):
        return None
    if status != INVOICE_STATUS_CANCELLED:
        await session.execute(
            text("UPDATE trainer_invoices SET status = :c WHERE id = :iid"),
            {"c": INVOICE_STATUS_CANCELLED, "iid": invoice_id},
        )
        await session.commit()
    return {"invoice_id": int(invoice_id), "trainer_id": tid, "status": INVOICE_STATUS_CANCELLED}
