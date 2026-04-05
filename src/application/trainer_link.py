"""
Trainer–Telegram binding: consume one-time link token and resolve trainer by telegram_id.
All DB access via raw SQL.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.trainer_status import normalize_trainer_status_value


@dataclass(frozen=True, slots=True)
class ConsumeLinkTokenResult:
    """Outcome of consume_link_token: either linked trainer_id or a failure reason."""

    trainer_id: int | None = None
    error: Literal["invalid_token", "telegram_other_trainer"] | None = None


async def consume_link_token(
    session: AsyncSession,
    token: str,
    telegram_id: int,
    *,
    telegram_username: str | None = None,
) -> ConsumeLinkTokenResult:
    """
    Find valid token, set trainer.telegram_id and telegram_username, mark token used.

    If this Telegram is already linked to the same trainer (repeat welcome link), refreshes username
    and consumes the token without touching telegram_id (idempotent).

    If Telegram is already linked to another trainer row, returns telegram_other_trainer (no
    partial updates; token may remain unused for support to reissue).
    """
    now = datetime.now(timezone.utc)
    r = await session.execute(
        text("""
            SELECT trainer_id FROM trainer_link_tokens
            WHERE token = :token AND used_at IS NULL AND expires_at > :now
        """),
        {"token": token, "now": now},
    )
    row = r.fetchone()
    if not row:
        return ConsumeLinkTokenResult(error="invalid_token")
    trainer_id = int(row[0])
    username_val = (telegram_username or "").strip()[:64] or None

    r_existing = await session.execute(
        text("SELECT id FROM trainers WHERE telegram_id = :tid LIMIT 1"),
        {"tid": telegram_id},
    )
    existing = r_existing.scalar()
    if existing is not None:
        if int(existing) == trainer_id:
            # Same profile: repeat link — only refresh username and burn token.
            await session.execute(
                text("UPDATE trainers SET telegram_username = :tuname WHERE id = :id"),
                {"tuname": username_val, "id": trainer_id},
            )
            await session.execute(
                text("UPDATE trainer_link_tokens SET used_at = :now WHERE token = :token"),
                {"now": now, "token": token},
            )
            await session.commit()
            return ConsumeLinkTokenResult(trainer_id=trainer_id)
        await session.rollback()
        return ConsumeLinkTokenResult(error="telegram_other_trainer")

    try:
        await session.execute(
            text("UPDATE trainers SET telegram_id = :tid, telegram_username = :tuname WHERE id = :id"),
            {"tid": telegram_id, "tuname": username_val, "id": trainer_id},
        )
        await session.execute(
            text("UPDATE trainer_link_tokens SET used_at = :now WHERE token = :token"),
            {"now": now, "token": token},
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return ConsumeLinkTokenResult(error="telegram_other_trainer")
    return ConsumeLinkTokenResult(trainer_id=trainer_id)


async def get_trainer_row_by_telegram_id(session: AsyncSession, telegram_id: int) -> dict | None:
    """Linked trainer row (any status). Used for onboarding / gate before active."""
    r = await session.execute(
        text(
            """
            SELECT id, status, moderation_feedback
            FROM trainers
            WHERE telegram_id = :tid
            LIMIT 1
            """
        ),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "status": normalize_trainer_status_value(row[1]),
        "moderation_feedback": row[2],
    }


async def get_trainer_by_telegram_id(session: AsyncSession, telegram_id: int) -> bool:
    """True if this telegram_id is linked to an active trainer (bot access allowed)."""
    r = await session.execute(
        text("SELECT 1 FROM trainers WHERE telegram_id = :tid AND status = 'active' LIMIT 1"),
        {"tid": telegram_id},
    )
    return r.fetchone() is not None


async def get_trainer_id_by_telegram_id(session: AsyncSession, telegram_id: int) -> int | None:
    """Return trainer id if linked and status=active (bot access allowed), else None."""
    r = await session.execute(
        text("SELECT id FROM trainers WHERE telegram_id = :tid AND status = 'active' LIMIT 1"),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    return row[0] if row else None


async def get_trainer_id_linked_any_status(session: AsyncSession, telegram_id: int) -> int | None:
    """Trainer id for linked Telegram user regardless of status (onboarding Mini App, etc.)."""
    r = await session.execute(
        text("SELECT id FROM trainers WHERE telegram_id = :tid LIMIT 1"),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    return row[0] if row else None
