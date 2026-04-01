"""
Trainer platform subscription: trial, paid plans, active check.
Single source for trainer_has_active_subscription used by catalog and payment flows.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.platform_settings_use_cases import (
    WELCOME_TRIAL_PERIOD_DAYS_KEY,
    get_platform_int,
)
from src.shared.config import Settings
from src.infrastructure.db.models import (
    INVOICE_STATUS_OVERDUE,
    INVOICE_STATUS_PAID,
    INVOICE_STATUS_SENT,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_TRIAL,
    SUBSCRIPTION_TIER_ANALYTICS,
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
            INSERT INTO trainer_subscriptions (trainer_id, plan_id, tier, started_at, expires_at, status)
            VALUES (:tid, :pid, :tier, :started_at, :expires_at, :status)
            RETURNING id, started_at, expires_at
        """),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "tier": SUBSCRIPTION_TIER_ANALYTICS,
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
    After first Telegram link: create max-tier trial if missing, or backfill tier on legacy trial rows.
    """
    created = await create_trial_subscription(session, trainer_id)
    if created is not None:
        return
    now = datetime.now(timezone.utc)
    await session.execute(
        text("""
            UPDATE trainer_subscriptions AS ts
            SET tier = :tier
            FROM subscription_plans sp
            WHERE ts.trainer_id = :tid
              AND ts.plan_id = sp.id
              AND sp.is_trial = true
              AND ts.tier IS NULL
              AND ts.status IN (:s1, :s2)
              AND ts.expires_at > :now
        """),
        {
            "tid": trainer_id,
            "tier": SUBSCRIPTION_TIER_ANALYTICS,
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


async def confirm_subscription_invoice_after_payment(
    session: AsyncSession,
    invoice_id: int,
    payment_external_id: str,
) -> bool:
    """
    On gateway success for subscription: mark invoice paid, create trainer_subscriptions
    (active) for the period. Idempotent: if invoice already paid, return True without duplicate.
    """
    r = await session.execute(
        text("""
            SELECT id, trainer_id, subscription_plan_id, amount_cents, period_start, period_end, status
            FROM trainer_invoices WHERE id = :iid
        """),
        {"iid": invoice_id},
    )
    row = r.fetchone()
    if not row:
        return False
    tid, plan_id, amount, period_start, period_end, status = row[1], row[2], row[3], row[4], row[5], row[6]
    if status == INVOICE_STATUS_PAID:
        return True
    if status not in (INVOICE_STATUS_SENT, INVOICE_STATUS_OVERDUE):
        return False
    now = datetime.now(timezone.utc)
    await session.execute(
        text("""
            UPDATE trainer_invoices
            SET status = :paid, paid_at = :now, payment_external_id = :ext_id
            WHERE id = :iid
        """),
        {"paid": INVOICE_STATUS_PAID, "now": now, "ext_id": payment_external_id[:256], "iid": invoice_id},
    )
    await session.execute(
        text("""
            INSERT INTO trainer_subscriptions (trainer_id, plan_id, started_at, expires_at, status)
            VALUES (:tid, :pid, :started_at, :expires_at, :status)
        """),
        {
            "tid": tid,
            "pid": plan_id,
            "started_at": period_start,
            "expires_at": period_end,
            "status": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    await session.commit()
    return True
