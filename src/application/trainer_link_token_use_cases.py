"""Issue one-time trainer-bot deep-link tokens (admin / site automation)."""
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import TRAINER_STATUS_PENDING_PROFILE
from src.shared.config import Settings

# Default token lifetime when admin omits days (aligned with scripts/create_trainer_link.py spirit).
DEFAULT_TRAINER_LINK_EXPIRE_DAYS = 14

WELCOME_GRANT_KIND_TRIAL = "trial"
WELCOME_GRANT_KIND_PAID = "paid"


async def issue_trainer_welcome_link_token(
    session: AsyncSession,
    trainer_id: int,
    *,
    expire_days: int = DEFAULT_TRAINER_LINK_EXPIRE_DAYS,
    welcome_grant_kind: str | None = None,
    welcome_grant_modules: dict[str, bool] | None = None,
    welcome_grant_period_months: int | None = None,
    welcome_grant_admin_id: int | None = None,
) -> dict | None:
    """
    Insert a new unused token row. Returns None if trainer_id does not exist.

    Deep link: https://t.me/<trainer_bot_username>?start=link_<token>

    Optional welcome_grant_* fields describe the entitlement to apply when the trainer
    first opens the link (trial vs prepaid paid subscription). Period for paid grants
    starts at open time, not at issue time.
    """
    check = await session.execute(
        text("SELECT 1 FROM trainers WHERE id = :id"),
        {"id": trainer_id},
    )
    if check.fetchone() is None:
        return None

    days = max(1, min(int(expire_days), 365))
    raw = secrets.token_urlsafe(32)
    token = raw[:64] if len(raw) > 64 else raw
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=days)

    kind = (welcome_grant_kind or "").strip().lower() or None
    if kind not in (None, WELCOME_GRANT_KIND_TRIAL, WELCOME_GRANT_KIND_PAID):
        kind = WELCOME_GRANT_KIND_TRIAL
    mods_json = json.dumps(welcome_grant_modules) if welcome_grant_modules is not None else None
    period_months = int(welcome_grant_period_months) if welcome_grant_period_months is not None else None

    await session.execute(
        text(
            """
            INSERT INTO trainer_link_tokens (
                token, trainer_id, expires_at,
                welcome_grant_kind, welcome_grant_modules, welcome_grant_period_months,
                welcome_grant_admin_id
            )
            VALUES (
                :token, :tid, :exp,
                :gkind, CAST(:gmods AS jsonb), :gmonths,
                :gadmin
            )
            """
        ),
        {
            "token": token,
            "tid": trainer_id,
            "exp": expires_at,
            "gkind": kind,
            "gmods": mods_json,
            "gmonths": period_months,
            "gadmin": welcome_grant_admin_id,
        },
    )
    await session.commit()

    settings = Settings()
    uname = (settings.trainer_bot_username or "").strip().lstrip("@")
    if uname:
        deep_link = f"https://t.me/{uname}?start=link_{token}"
    else:
        deep_link = ""

    return {
        "trainer_id": trainer_id,
        "token": token,
        "start_payload": f"link_{token}",
        "expires_at": expires_at,
        "deep_link": deep_link or None,
        "trainer_bot_username_configured": bool(uname),
        "welcome_grant_kind": kind or WELCOME_GRANT_KIND_TRIAL,
        "welcome_grant_period_months": period_months,
        "welcome_grant_modules": welcome_grant_modules,
    }


async def issue_landing_trainer_link_token(
    session: AsyncSession,
    *,
    expire_days: int = DEFAULT_TRAINER_LINK_EXPIRE_DAYS,
) -> dict:
    """
    Public landing CTA: issue a one-time bot token without creating a trainer row.

    The trainer profile is created lazily in consume_link_token when Telegram opens the link.
    """
    days = max(1, min(int(expire_days), 365))
    raw = secrets.token_urlsafe(32)
    token = raw[:64] if len(raw) > 64 else raw
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=days)

    await session.execute(
        text(
            """
            INSERT INTO trainer_link_tokens (token, trainer_id, expires_at, welcome_grant_kind)
            VALUES (:token, NULL, :exp, :gkind)
            """
        ),
        {"token": token, "exp": expires_at, "gkind": WELCOME_GRANT_KIND_TRIAL},
    )
    await session.commit()

    settings = Settings()
    uname = (settings.trainer_bot_username or "").strip().lstrip("@")
    deep_link = f"https://t.me/{uname}?start=link_{token}" if uname else ""

    return {
        "trainer_id": None,
        "token": token,
        "start_payload": f"link_{token}",
        "expires_at": expires_at,
        "deep_link": deep_link or None,
        "trainer_bot_username_configured": bool(uname),
        "created_new_trainer": False,
        "welcome_grant_kind": WELCOME_GRANT_KIND_TRIAL,
    }


async def create_trainer_and_issue_welcome_link_token(
    session: AsyncSession,
    *,
    expire_days: int = DEFAULT_TRAINER_LINK_EXPIRE_DAYS,
    welcome_grant_kind: str | None = None,
    welcome_grant_modules: dict[str, bool] | None = None,
    welcome_grant_period_months: int | None = None,
    welcome_grant_admin_id: int | None = None,
) -> dict:
    """
    Create a new trainer row (pending_profile) and attach a one-time link token.

    Use when inviting a new person: no id required — id appears in the reply for your records.
    """
    r = await session.execute(
        text(
            """
            INSERT INTO trainers (status)
            VALUES (:st)
            RETURNING id
            """
        ),
        {"st": TRAINER_STATUS_PENDING_PROFILE},
    )
    row = r.fetchone()
    assert row is not None
    trainer_id = int(row[0])
    await session.commit()

    issued = await issue_trainer_welcome_link_token(
        session,
        trainer_id,
        expire_days=expire_days,
        welcome_grant_kind=welcome_grant_kind,
        welcome_grant_modules=welcome_grant_modules,
        welcome_grant_period_months=welcome_grant_period_months,
        welcome_grant_admin_id=welcome_grant_admin_id,
    )
    assert issued is not None
    issued["created_new_trainer"] = True
    return issued


async def apply_pending_welcome_grant_for_token(
    session: AsyncSession,
    token: str,
    trainer_id: int,
) -> dict[str, Any]:
    """
    Apply a prepaid welcome grant stored on the token, once.

    Returns {"kind": "trial"|"paid"|"none", ...}. For paid grants the paid subscription
    is activated here so the period starts at first open. For trial / legacy tokens the
    caller should still run ensure_trainer_welcome_trial.
    """
    now = datetime.now(timezone.utc)
    r = await session.execute(
        text(
            """
            SELECT welcome_grant_kind, welcome_grant_modules, welcome_grant_period_months,
                   welcome_grant_admin_id, welcome_grant_applied_at
            FROM trainer_link_tokens
            WHERE token = :token
            """
        ),
        {"token": token},
    )
    row = r.fetchone()
    if not row:
        return {"kind": "none"}

    kind = (row[0] or "").strip().lower() or WELCOME_GRANT_KIND_TRIAL
    modules = row[1]
    period_months = row[2]
    admin_id = int(row[3]) if row[3] is not None else 0
    applied_at = row[4]

    if applied_at is not None:
        return {"kind": kind, "already_applied": True}

    if kind != WELCOME_GRANT_KIND_PAID:
        # Trial (or legacy): entitlement is created by ensure_trainer_welcome_trial.
        await session.execute(
            text(
                """
                UPDATE trainer_link_tokens
                SET welcome_grant_applied_at = :now
                WHERE token = :token AND welcome_grant_applied_at IS NULL
                """
            ),
            {"now": now, "token": token},
        )
        await session.commit()
        return {"kind": WELCOME_GRANT_KIND_TRIAL}

    from src.application.subscription_tier_use_cases import (
        SUBSCRIPTION_BILLING_PERIOD_MONTHS,
        default_modules_dict,
        normalize_modules_dict,
    )
    from src.application.subscription_use_cases import (
        admin_grant_subscription_for_invoice,
        create_catalog_subscription_invoice_for_trainer,
    )

    final_modules = normalize_modules_dict(modules) if modules else default_modules_dict()
    months = int(period_months) if period_months is not None else 1
    if months not in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
        months = SUBSCRIPTION_BILLING_PERIOD_MONTHS[0]

    draft = await create_catalog_subscription_invoice_for_trainer(
        session,
        int(trainer_id),
        tier=None,
        modules=final_modules,
        period_months=months,
    )
    if not draft:
        return {"kind": WELCOME_GRANT_KIND_PAID, "error": "draft_failed"}

    result = await admin_grant_subscription_for_invoice(
        session,
        int(draft["invoice_id"]),
        modules=final_modules,
        period_months=months,
        admin_id=admin_id,
    )
    if not result:
        return {"kind": WELCOME_GRANT_KIND_PAID, "error": "grant_failed"}

    await session.execute(
        text(
            """
            UPDATE trainer_link_tokens
            SET welcome_grant_applied_at = :now
            WHERE token = :token AND welcome_grant_applied_at IS NULL
            """
        ),
        {"now": now, "token": token},
    )
    await session.commit()
    out = dict(result)
    out["kind"] = WELCOME_GRANT_KIND_PAID
    return out
