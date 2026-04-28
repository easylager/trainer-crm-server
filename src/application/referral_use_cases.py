"""
Referral program use cases: B2B trainer-to-trainer.

- Attribution: record who referred whom (on first /start with ref code)
- Milestone accruals for referrer: TTV minimal onboarding (+2d), first confirmed/completed booking (+3d),
  first paid subscription (+14d)
- Credit balance: sum of ledger for trainer
- Credit redemption: apply credit when trainer pays subscription (extend period)
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import (
    REFERRAL_CREDIT_REASON_ACCRUAL,
    REFERRAL_CREDIT_REASON_ACCRUAL_FIRST_BOOKING,
    REFERRAL_CREDIT_REASON_ACCRUAL_ONBOARDING,
    REFERRAL_CREDIT_REASON_ACCRUAL_PAYMENT,
    REFERRAL_CREDIT_REASON_ADMIN,
    REFERRAL_CREDIT_REASON_REDEMPTION,
    REFERRAL_PROGRAM_ACCRUAL_REASONS,
)

# Attribution window: referred trainer must pay first subscription within this many days for payment bonus
REFERRAL_ATTRIBUTION_WINDOW_DAYS = 60

REFERRAL_BONUS_ONBOARDING_DAYS = 2
REFERRAL_BONUS_FIRST_BOOKING_DAYS = 3
REFERRAL_BONUS_PAYMENT_DAYS = 14

# Max referral-program accruals (sum of positive milestone rows) per referrer, lifetime
REFERRAL_MAX_ACCRUAL_LIFETIME_DAYS = 60

# Back-compat export for API field names
REFERRAL_CREDIT_DAYS_PER_REFERRAL = REFERRAL_BONUS_PAYMENT_DAYS


def generate_referral_code() -> str:
    """Generate a short, URL-safe referral code (8 chars)."""
    return secrets.token_urlsafe(6)[:8].upper()


def _accrual_reasons_sql_tuple() -> str:
    return ", ".join(f"'{r}'" for r in REFERRAL_PROGRAM_ACCRUAL_REASONS)


async def _lifetime_referral_accrual_sum(session: AsyncSession, referrer_id: int) -> int:
    reasons = _accrual_reasons_sql_tuple()
    r = await session.execute(
        text(f"""
            SELECT COALESCE(SUM(amount_days), 0)
            FROM trainer_referral_credits
            WHERE trainer_id = :tid
              AND amount_days > 0
              AND reason IN ({reasons})
        """),
        {"tid": referrer_id},
    )
    return int(r.scalar() or 0)


async def _referral_accrual_headroom(session: AsyncSession, referrer_id: int) -> int:
    used = await _lifetime_referral_accrual_sum(session, referrer_id)
    return max(0, REFERRAL_MAX_ACCRUAL_LIFETIME_DAYS - used)


async def ensure_trainer_referral_code(session: AsyncSession, trainer_id: int) -> str | None:
    """
    Get or create a stable referral code for trainer.
    Returns None if trainer does not exist.
    """
    r = await session.execute(
        text("SELECT referral_code FROM trainers WHERE id = :id"),
        {"id": trainer_id},
    )
    row = r.fetchone()
    if row is None:
        return None
    if row[0]:
        return str(row[0])
    # Generate new code, retry on collision (unlikely)
    for _ in range(5):
        code = generate_referral_code()
        try:
            await session.execute(
                text("UPDATE trainers SET referral_code = :code WHERE id = :id AND referral_code IS NULL"),
                {"code": code, "id": trainer_id},
            )
            await session.commit()
            # Re-fetch to confirm (handles race)
            r2 = await session.execute(
                text("SELECT referral_code FROM trainers WHERE id = :id"),
                {"id": trainer_id},
            )
            row2 = r2.fetchone()
            if row2 and row2[0]:
                return str(row2[0])
        except Exception:
            await session.rollback()
    return None


async def get_trainer_id_by_referral_code(session: AsyncSession, code: str) -> int | None:
    """Resolve referral code to trainer_id. Returns None if not found."""
    r = await session.execute(
        text("SELECT id FROM trainers WHERE referral_code = :code"),
        {"code": code.upper().strip()},
    )
    row = r.fetchone()
    return int(row[0]) if row else None


async def record_referral_attribution(
    session: AsyncSession,
    referrer_id: int,
    referred_id: int,
    *,
    attribution_window_days: int = REFERRAL_ATTRIBUTION_WINDOW_DAYS,
) -> bool:
    """
    Record that referrer_id referred referred_id.
    Returns False if referred_id already has a referrer or if self-referral.
    """
    if referrer_id == referred_id:
        return False
    # Check if already attributed
    r = await session.execute(
        text("SELECT 1 FROM trainer_referrals WHERE referred_id = :rid LIMIT 1"),
        {"rid": referred_id},
    )
    if r.fetchone():
        return False
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=attribution_window_days)
    ins = await session.execute(
        text("""
            INSERT INTO trainer_referrals (referrer_id, referred_id, created_at, attribution_expires_at)
            VALUES (:referrer_id, :referred_id, :now, :expires)
            ON CONFLICT (referred_id) DO NOTHING
            RETURNING id
        """),
        {"referrer_id": referrer_id, "referred_id": referred_id, "now": now, "expires": expires},
    )
    inserted = ins.fetchone() is not None
    await session.commit()
    if inserted:
        # Referred may already satisfy milestones before link was stored (rare); catch up.
        await maybe_grant_referral_onboarding_bonus(referred_id)
        await maybe_grant_referral_first_booking_bonus(referred_id)
    return inserted


async def get_referral_attribution(session: AsyncSession, referred_id: int) -> dict[str, Any] | None:
    """Get referral attribution for a trainer (if any)."""
    r = await session.execute(
        text("""
            SELECT id, referrer_id, created_at, attribution_expires_at, credit_granted_at,
                   onboarding_bonus_granted_at, first_booking_bonus_granted_at
            FROM trainer_referrals WHERE referred_id = :rid
        """),
        {"rid": referred_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "referrer_id": row[1],
        "referred_id": referred_id,
        "created_at": row[2],
        "attribution_expires_at": row[3],
        "credit_granted_at": row[4],
        "onboarding_bonus_granted_at": row[5],
        "first_booking_bonus_granted_at": row[6],
    }


async def maybe_grant_referral_onboarding_bonus(trainer_id: int) -> None:
    """Referrer +2d when referred trainer completes TTV minimal profile (7-field gate)."""
    from src.application.trainer_use_cases import get_trainer_moderation_readiness
    from src.infrastructure.db import async_session_factory

    async with async_session_factory() as session:
        r = await session.execute(
            text("""
                SELECT id, referrer_id, onboarding_bonus_granted_at
                FROM trainer_referrals
                WHERE referred_id = :tid
                FOR UPDATE
            """),
            {"tid": trainer_id},
        )
        row = r.fetchone()
        if not row:
            return
        ref_id, referrer_id, ob_at = int(row[0]), int(row[1]), row[2]
        if ob_at is not None:
            return
        readiness = await get_trainer_moderation_readiness(session, trainer_id)
        if not readiness or not readiness.get("tt_minimal_complete"):
            return
        now = datetime.now(timezone.utc)
        headroom = await _referral_accrual_headroom(session, referrer_id)
        grant_days = min(REFERRAL_BONUS_ONBOARDING_DAYS, headroom)
        await session.execute(
            text("UPDATE trainer_referrals SET onboarding_bonus_granted_at = :now WHERE id = :id"),
            {"now": now, "id": ref_id},
        )
        if grant_days > 0:
            await session.execute(
                text("""
                    INSERT INTO trainer_referral_credits (trainer_id, amount_days, reason, referral_id, created_at)
                    VALUES (:tid, :days, :reason, :ref_id, :now)
                """),
                {
                    "tid": referrer_id,
                    "days": grant_days,
                    "reason": REFERRAL_CREDIT_REASON_ACCRUAL_ONBOARDING,
                    "ref_id": ref_id,
                    "now": now,
                },
            )
        await session.commit()


async def maybe_grant_referral_first_booking_bonus(trainer_id: int) -> None:
    """Referrer +3d when referred trainer has at least one confirmed or completed booking."""
    from src.infrastructure.db import async_session_factory

    async with async_session_factory() as session:
        r = await session.execute(
            text("""
                SELECT id, referrer_id, first_booking_bonus_granted_at
                FROM trainer_referrals
                WHERE referred_id = :tid
                FOR UPDATE
            """),
            {"tid": trainer_id},
        )
        row = r.fetchone()
        if not row:
            return
        ref_id, referrer_id, fb_at = int(row[0]), int(row[1]), row[2]
        if fb_at is not None:
            return
        r_cnt = await session.execute(
            text("""
                SELECT COUNT(*)::int FROM bookings
                WHERE trainer_id = :tid AND status IN ('confirmed', 'completed')
                  AND NOT is_sandbox
            """),
            {"tid": trainer_id},
        )
        cnt_row = r_cnt.fetchone()
        if not cnt_row or int(cnt_row[0] or 0) < 1:
            return
        now = datetime.now(timezone.utc)
        headroom = await _referral_accrual_headroom(session, referrer_id)
        grant_days = min(REFERRAL_BONUS_FIRST_BOOKING_DAYS, headroom)
        await session.execute(
            text("UPDATE trainer_referrals SET first_booking_bonus_granted_at = :now WHERE id = :id"),
            {"now": now, "id": ref_id},
        )
        if grant_days > 0:
            await session.execute(
                text("""
                    INSERT INTO trainer_referral_credits (trainer_id, amount_days, reason, referral_id, created_at)
                    VALUES (:tid, :days, :reason, :ref_id, :now)
                """),
                {
                    "tid": referrer_id,
                    "days": grant_days,
                    "reason": REFERRAL_CREDIT_REASON_ACCRUAL_FIRST_BOOKING,
                    "ref_id": ref_id,
                    "now": now,
                },
            )
        await session.commit()


async def grant_referral_credit_if_eligible(
    session: AsyncSession,
    referred_trainer_id: int,
    *,
    credit_days: int = REFERRAL_BONUS_PAYMENT_DAYS,
) -> int | None:
    """
    Called after referred trainer's first subscription payment.
    Grants payment bonus to referrer if within attribution window and not already granted.
    Returns referrer_id if milestone processed (credit may be 0 if lifetime cap exhausted), None otherwise.

    ``session`` is accepted for call-site compatibility; referral updates use an isolated session.
    """
    _ = session
    from src.infrastructure.db import async_session_factory

    async with async_session_factory() as session2:
        now = datetime.now(timezone.utc)
        r = await session2.execute(
            text("""
                SELECT id, referrer_id, attribution_expires_at, credit_granted_at
                FROM trainer_referrals
                WHERE referred_id = :rid
                FOR UPDATE
            """),
            {"rid": referred_trainer_id},
        )
        row = r.fetchone()
        if not row:
            return None
        ref_id, referrer_id, expires_at, granted_at = row
        if granted_at is not None:
            return None
        if expires_at < now:
            return None
        headroom = await _referral_accrual_headroom(session2, referrer_id)
        grant_days = min(credit_days, headroom)
        await session2.execute(
            text("UPDATE trainer_referrals SET credit_granted_at = :now WHERE id = :id"),
            {"now": now, "id": ref_id},
        )
        if grant_days > 0:
            await session2.execute(
                text("""
                    INSERT INTO trainer_referral_credits (trainer_id, amount_days, reason, referral_id, created_at)
                    VALUES (:tid, :days, :reason, :ref_id, :now)
                """),
                {
                    "tid": referrer_id,
                    "days": grant_days,
                    "reason": REFERRAL_CREDIT_REASON_ACCRUAL_PAYMENT,
                    "ref_id": ref_id,
                    "now": now,
                },
            )
        await session2.commit()
        return referrer_id


async def get_referral_credit_balance(session: AsyncSession, trainer_id: int) -> int:
    """Get current referral credit balance in days for trainer."""
    r = await session.execute(
        text("SELECT COALESCE(SUM(amount_days), 0) FROM trainer_referral_credits WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    return int(r.scalar() or 0)


async def redeem_referral_credit(
    session: AsyncSession,
    trainer_id: int,
    days_to_redeem: int,
    subscription_id: int | None = None,
    *,
    do_commit: bool = True,
) -> int:
    """
    Redeem (deduct) referral credit when trainer pays subscription.
    Returns actual days redeemed (may be less if balance insufficient).
    """
    balance = await get_referral_credit_balance(session, trainer_id)
    actual = min(days_to_redeem, balance)
    if actual <= 0:
        return 0
    now = datetime.now(timezone.utc)
    await session.execute(
        text("""
            INSERT INTO trainer_referral_credits (trainer_id, amount_days, reason, subscription_id, created_at)
            VALUES (:tid, :days, :reason, :sub_id, :now)
        """),
        {
            "tid": trainer_id,
            "days": -actual,
            "reason": REFERRAL_CREDIT_REASON_REDEMPTION,
            "sub_id": subscription_id,
            "now": now,
        },
    )
    if do_commit:
        await session.commit()
    return actual


async def admin_adjust_referral_credit(
    session: AsyncSession,
    trainer_id: int,
    amount_days: int,
    admin_telegram_id: int,
    note: str | None = None,
) -> int:
    """Admin manually adjusts referral credit (positive or negative). Returns new balance."""
    now = datetime.now(timezone.utc)
    await session.execute(
        text("""
            INSERT INTO trainer_referral_credits (trainer_id, amount_days, reason, note, created_at, created_by_admin_id)
            VALUES (:tid, :days, :reason, :note, :now, :admin_id)
        """),
        {
            "tid": trainer_id,
            "days": amount_days,
            "reason": REFERRAL_CREDIT_REASON_ADMIN,
            "note": note,
            "now": now,
            "admin_id": admin_telegram_id,
        },
    )
    await session.commit()
    return await get_referral_credit_balance(session, trainer_id)


async def get_referral_stats_for_trainer(session: AsyncSession, trainer_id: int) -> dict[str, Any]:
    """Get referral statistics for trainer (for UI)."""
    reasons = _accrual_reasons_sql_tuple()
    r_count = await session.execute(
        text("SELECT COUNT(*) FROM trainer_referrals WHERE referrer_id = :tid"),
        {"tid": trainer_id},
    )
    total_referred = int(r_count.scalar() or 0)
    r_credited = await session.execute(
        text("SELECT COUNT(*) FROM trainer_referrals WHERE referrer_id = :tid AND credit_granted_at IS NOT NULL"),
        {"tid": trainer_id},
    )
    credited_count = int(r_credited.scalar() or 0)
    balance = await get_referral_credit_balance(session, trainer_id)
    r_earned = await session.execute(
        text(f"""
            SELECT COALESCE(SUM(amount_days), 0)
            FROM trainer_referral_credits
            WHERE trainer_id = :tid AND reason IN ({reasons})
        """),
        {"tid": trainer_id},
    )
    total_earned = int(r_earned.scalar() or 0)
    lifetime_accrual = await _lifetime_referral_accrual_sum(session, trainer_id)
    return {
        "total_referred": total_referred,
        "credited_count": credited_count,
        "balance_days": balance,
        "total_earned_days": total_earned,
        "referral_accrual_lifetime_days": lifetime_accrual,
        "referral_accrual_cap_days": REFERRAL_MAX_ACCRUAL_LIFETIME_DAYS,
        "bonus_onboarding_days": REFERRAL_BONUS_ONBOARDING_DAYS,
        "bonus_first_booking_days": REFERRAL_BONUS_FIRST_BOOKING_DAYS,
        "bonus_payment_days": REFERRAL_BONUS_PAYMENT_DAYS,
    }


async def list_referred_trainers(
    session: AsyncSession,
    referrer_id: int,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List trainers referred by this referrer (for UI)."""
    r = await session.execute(
        text("""
            SELECT tr.id, tr.referred_id, tr.created_at, tr.credit_granted_at,
                   tr.onboarding_bonus_granted_at, tr.first_booking_bonus_granted_at,
                   t.telegram_username, tp.first_name, tp.last_name
            FROM trainer_referrals tr
            JOIN trainers t ON t.id = tr.referred_id
            LEFT JOIN trainer_profiles tp ON tp.trainer_id = tr.referred_id
            WHERE tr.referrer_id = :rid
            ORDER BY tr.created_at DESC
            LIMIT :lim
        """),
        {"rid": referrer_id, "lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "referral_id": row[0],
            "referred_trainer_id": row[1],
            "created_at": row[2],
            "credit_granted_at": row[3],
            "onboarding_bonus_granted_at": row[4],
            "first_booking_bonus_granted_at": row[5],
            "telegram_username": row[6],
            "first_name": row[7],
            "last_name": row[8],
        }
        for row in rows
    ]
