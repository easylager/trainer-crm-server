"""
Trainer–Telegram binding: consume one-time link token and resolve trainer by telegram_id.
All DB access via raw SQL.
"""
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def consume_link_token(
    session: AsyncSession,
    token: str,
    telegram_id: int,
    *,
    telegram_username: str | None = None,
) -> int | None:
    """
    Find valid token, set trainer.telegram_id and telegram_username, mark token used.
    Returns trainer_id if linked, else None.
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
        return None
    trainer_id = row[0]
    username_val = (telegram_username or "").strip()[:64] or None
    await session.execute(
        text("UPDATE trainers SET telegram_id = :tid, telegram_username = :tuname WHERE id = :id"),
        {"tid": telegram_id, "tuname": username_val, "id": trainer_id},
    )
    await session.execute(
        text("UPDATE trainer_link_tokens SET used_at = :now WHERE token = :token"),
        {"now": now, "token": token},
    )
    await session.commit()
    return trainer_id


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
