"""Issue one-time trainer-bot deep-link tokens (admin / site automation)."""
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import TRAINER_STATUS_PENDING_PROFILE
from src.shared.config import Settings

# Default token lifetime when admin omits days (aligned with scripts/create_trainer_link.py spirit).
DEFAULT_TRAINER_LINK_EXPIRE_DAYS = 14


async def issue_trainer_welcome_link_token(
    session: AsyncSession,
    trainer_id: int,
    *,
    expire_days: int = DEFAULT_TRAINER_LINK_EXPIRE_DAYS,
) -> dict | None:
    """
    Insert a new unused token row. Returns None if trainer_id does not exist.

    Deep link: https://t.me/<trainer_bot_username>?start=link_<token>
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

    await session.execute(
        text(
            """
            INSERT INTO trainer_link_tokens (token, trainer_id, expires_at)
            VALUES (:token, :tid, :exp)
            """
        ),
        {"token": token, "tid": trainer_id, "exp": expires_at},
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
    }


async def create_trainer_and_issue_welcome_link_token(
    session: AsyncSession,
    *,
    expire_days: int = DEFAULT_TRAINER_LINK_EXPIRE_DAYS,
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

    issued = await issue_trainer_welcome_link_token(session, trainer_id, expire_days=expire_days)
    assert issued is not None
    issued["created_new_trainer"] = True
    return issued
