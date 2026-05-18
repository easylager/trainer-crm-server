"""Support messages: create from client/trainer, list and reply from admin."""
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import (
    SUPPORT_FROM_CLIENT,
    SUPPORT_FROM_TRAINER,
    SUPPORT_STATUS_NEW,
    SUPPORT_STATUS_REPLIED,
)

logger = logging.getLogger(__name__)


async def create_support_message(
    session: AsyncSession,
    from_telegram_id: int,
    from_role: str,
    message_text: str,
    *,
    admin_notify_source_tag: str | None = None,
) -> dict:
    """Create one support ticket. from_role must be client or trainer.

    When ``admin_notify_source_tag`` is set, admins receive a Telegram card (best-effort).
    """
    if from_role not in (SUPPORT_FROM_CLIENT, SUPPORT_FROM_TRAINER):
        from_role = SUPPORT_FROM_CLIENT
    text_clean = (message_text or "").strip()[: 4000]
    if not text_clean:
        return {"id": None, "ok": False}
    r = await session.execute(
        text("""
            INSERT INTO support_messages (from_telegram_id, from_role, message_text, status)
            VALUES (:tid, :role, :msg, :status)
            RETURNING id, created_at
        """),
        {"tid": from_telegram_id, "role": from_role, "msg": text_clean, "status": SUPPORT_STATUS_NEW},
    )
    row = r.fetchone()
    await session.commit()
    sid = int(row[0])
    if admin_notify_source_tag:
        try:
            from src.application.support_admin_notify import notify_admins_new_support_ticket

            await notify_admins_new_support_ticket(sid, source_tag=admin_notify_source_tag)
        except Exception:
            logger.exception("support ticket admin notify failed support_id=%s", sid)
    return {"id": sid, "created_at": row[1].isoformat() if row[1] else None, "ok": True}


async def list_support_messages(
    session: AsyncSession,
    limit: int = 50,
    status: str | None = None,
) -> list[dict]:
    """List support tickets for admin. Newest first."""
    status_filter = ""
    params = {"lim": limit}
    if status:
        status_filter = " AND status = :status"
        params["status"] = status
    r = await session.execute(
        text(f"""
            SELECT id, from_telegram_id, from_role, message_text, created_at, status,
                   admin_reply_text, admin_replied_at
            FROM support_messages
            WHERE 1=1 {status_filter}
            ORDER BY created_at DESC
            LIMIT :lim
        """),
        params,
    )
    return [
        {
            "id": row[0],
            "from_telegram_id": row[1],
            "from_role": row[2],
            "message_text": row[3],
            "created_at": row[4].isoformat() if row[4] else None,
            "status": row[5],
            "admin_reply_text": row[6],
            "admin_replied_at": row[7].isoformat() if row[7] else None,
        }
        for row in r.fetchall()
    ]


async def reply_support_message(
    session: AsyncSession,
    support_id: int,
    admin_telegram_id: int,
    reply_text: str,
) -> bool:
    """Set admin reply and status=replied. Returns True if updated."""
    reply_clean = (reply_text or "").strip()[: 2000]
    if not reply_clean:
        return False
    r = await session.execute(
        text("""
            UPDATE support_messages
            SET admin_reply_text = :reply, admin_replied_at = CURRENT_TIMESTAMP,
                admin_telegram_id = :admin_tid, status = :status
            WHERE id = :id
            RETURNING id
        """),
        {
            "id": support_id,
            "reply": reply_clean,
            "admin_tid": admin_telegram_id,
            "status": SUPPORT_STATUS_REPLIED,
        },
    )
    if r.fetchone():
        await session.commit()
        return True
    return False


async def get_support_message(session: AsyncSession, support_id: int) -> dict | None:
    """Get one ticket by id (for admin)."""
    r = await session.execute(
        text("""
            SELECT id, from_telegram_id, from_role, message_text, created_at, status,
                   admin_reply_text, admin_replied_at
            FROM support_messages WHERE id = :id
        """),
        {"id": support_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "from_telegram_id": row[1],
        "from_role": row[2],
        "message_text": row[3],
        "created_at": row[4].isoformat() if row[4] else None,
        "status": row[5],
        "admin_reply_text": row[6],
        "admin_replied_at": row[7].isoformat() if row[7] else None,
    }
