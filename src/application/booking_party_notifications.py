"""
Outbox for booking lifecycle Telegram notifications (client ↔ trainer).

Business mutations commit first; delivery is best-effort immediate + guaranteed retry via notification_service loop.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_outbox_available: bool | None = None

KIND_CLIENT_CANCEL_TRAINER = "client_cancel_trainer"
KIND_CLIENT_CANCEL_CONFIRM = "client_cancel_confirm"
KIND_TRAINER_DECLINE_CLIENT = "trainer_decline_client"

ROLE_TRAINER = "trainer"
ROLE_CLIENT = "client"


def _json_dumps(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


async def enqueue_trainer_decline_client_notification(
    session: AsyncSession,
    *,
    booking_id: int,
    client_telegram_id: int,
    date_str: str,
    day_label: str,
    time_str: str,
    reason: str | None,
) -> None:
    await enqueue_booking_party_notification(
        session,
        booking_id=int(booking_id),
        kind=KIND_TRAINER_DECLINE_CLIENT,
        recipient_role=ROLE_CLIENT,
        recipient_telegram_id=int(client_telegram_id),
        payload={
            "date_str": date_str,
            "day_label": day_label,
            "time_str": time_str,
            "reason": (reason or "").strip() or None,
        },
    )


async def enqueue_booking_party_notification(
    session: AsyncSession,
    *,
    booking_id: int,
    kind: str,
    recipient_role: str,
    recipient_telegram_id: int,
    payload: dict[str, Any],
    do_commit: bool = False,
) -> int | None:
    """Insert one outbox row; idempotent per (booking_id, kind)."""
    if not await booking_party_outbox_available(session):
        return None
    try:
        r = await session.execute(
        text(
            """
            INSERT INTO booking_party_notifications (
                booking_id, kind, recipient_role, recipient_telegram_id, payload
            )
            VALUES (
                :booking_id, :kind, :recipient_role, :recipient_telegram_id,
                CAST(:payload AS jsonb)
            )
            ON CONFLICT (booking_id, kind) DO NOTHING
            RETURNING id
            """
        ),
        {
            "booking_id": int(booking_id),
            "kind": kind[:32],
            "recipient_role": recipient_role[:16],
            "recipient_telegram_id": int(recipient_telegram_id),
            "payload": _json_dumps(payload),
        },
    )
        row = r.fetchone()
    except ProgrammingError:
        await session.rollback()
        global _outbox_available
        _outbox_available = False
        logger.warning("booking_party_notifications insert failed; outbox disabled for process")
        return None
    if do_commit:
        await session.commit()
    return int(row[0]) if row else None


async def list_pending_booking_party_notifications(
    session: AsyncSession, *, limit: int = 50
) -> list[dict[str, Any]]:
    if not await booking_party_outbox_available(session):
        return []
    r = await session.execute(
        text(
            """
            SELECT id, booking_id, kind, recipient_role, recipient_telegram_id, payload, attempt_count
            FROM booking_party_notifications
            WHERE sent_at IS NULL
            ORDER BY id ASC
            LIMIT :lim
            """
        ),
        {"lim": max(1, min(limit, 200))},
    )
    out: list[dict[str, Any]] = []
    for row in r.fetchall():
        pl = row[5] if isinstance(row[5], dict) else {}
        out.append(
            {
                "id": int(row[0]),
                "booking_id": int(row[1]),
                "kind": str(row[2]),
                "recipient_role": str(row[3]),
                "recipient_telegram_id": int(row[4]),
                "payload": pl,
                "attempt_count": int(row[6] or 0),
            }
        )
    return out


async def list_pending_booking_party_notifications_for_booking(
    session: AsyncSession, booking_id: int
) -> list[dict[str, Any]]:
    if not await booking_party_outbox_available(session):
        return []
    r = await session.execute(
        text(
            """
            SELECT id, booking_id, kind, recipient_role, recipient_telegram_id, payload, attempt_count
            FROM booking_party_notifications
            WHERE booking_id = :bid AND sent_at IS NULL
            ORDER BY id ASC
            """
        ),
        {"bid": int(booking_id)},
    )
    out: list[dict[str, Any]] = []
    for row in r.fetchall():
        pl = row[5] if isinstance(row[5], dict) else {}
        out.append(
            {
                "id": int(row[0]),
                "booking_id": int(row[1]),
                "kind": str(row[2]),
                "recipient_role": str(row[3]),
                "recipient_telegram_id": int(row[4]),
                "payload": pl,
                "attempt_count": int(row[6] or 0),
            }
        )
    return out


async def mark_booking_party_notification_attempt(
    session: AsyncSession, notification_id: int, *, error: str | None = None
) -> None:
    await session.execute(
        text(
            """
            UPDATE booking_party_notifications
            SET attempt_count = attempt_count + 1,
                last_error = :err
            WHERE id = :id
            """
        ),
        {"id": int(notification_id), "err": (error or "")[:2000] or None},
    )


async def mark_booking_party_notification_sent(session: AsyncSession, notification_id: int) -> None:
    await session.execute(
        text(
            """
            UPDATE booking_party_notifications
            SET sent_at = CURRENT_TIMESTAMP,
                last_error = NULL
            WHERE id = :id
            """
        ),
        {"id": int(notification_id)},
    )
    await session.commit()


def delivery_status_label(*, sent: bool, queued: bool, skipped: bool = False) -> str:
    if skipped:
        return "skipped"
    if sent:
        return "sent"
    if queued:
        return "queued"
    return "failed"


async def booking_party_outbox_available(session: AsyncSession) -> bool:
    """Probe once per process; missing migration disables outbox without breaking cancel/decline."""
    global _outbox_available
    if _outbox_available is False:
        return False
    if _outbox_available is True:
        return True
    try:
        await session.execute(text("SELECT 1 FROM booking_party_notifications LIMIT 1"))
        _outbox_available = True
        return True
    except ProgrammingError:
        await session.rollback()
        _outbox_available = False
        logger.warning(
            "booking_party_notifications table missing — run migration 0173; outbox delivery disabled"
        )
        return False
