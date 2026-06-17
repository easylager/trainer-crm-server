"""
Push to trainer bot when a client requests a center session booking (ADR-003 §4.1).

Lane-only visits → studio admins (owner + admin), not duty coaches.
Coach modes → assigned fulfillment coach only.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import get_trainer_telegram_id
from src.application.collective_session_use_cases import (
    COACH_ATTENDANCE_MODES,
    LANE_ATTENDANCE_MODES,
    BOOKING_STATUS_PENDING,
    _attendance_mode_label_ru,
)
from src.application.collective_use_cases import MEMBER_STATUS_ACTIVE
from src.bot import messages as msg
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings

logger = logging.getLogger(__name__)


async def resolve_collective_session_booking_notify_trainer_ids(
    session: AsyncSession,
    *,
    collective_id: int,
    attendance_mode: str,
    center_coach_id: int | None,
    fulfillment_trainer_id: int,
) -> list[int]:
    """Return trainer_ids that should receive a pending booking push."""
    mode = (attendance_mode or "").strip()
    if mode in COACH_ATTENDANCE_MODES and center_coach_id is not None:
        return [int(center_coach_id)]

    if mode in LANE_ATTENDANCE_MODES or center_coach_id is None:
        r = await session.execute(
            text(
                """
                SELECT DISTINCT cm.trainer_id
                FROM collective_members cm
                WHERE cm.collective_id = :cid
                  AND cm.status = :active
                  AND cm.role IN ('owner', 'admin')
                """
            ),
            {
                "cid": int(collective_id),
                "active": MEMBER_STATUS_ACTIVE,
            },
        )
        admin_ids = [int(row[0]) for row in r.fetchall() if row[0] is not None]
        if admin_ids:
            return admin_ids

    return [int(fulfillment_trainer_id)]


async def _load_pending_booking_notify_row(
    session: AsyncSession,
    booking_id: int,
) -> dict[str, Any] | None:
    r = await session.execute(
        text(
            """
            SELECT b.id, b.collective_id, b.attendance_mode, b.center_coach_id, b.trainer_id,
                   b.status, b.guest_count, b.booking_price_cents,
                   cs.slot_date, cs.start_time, cs.end_time,
                   c.display_name, c.slug,
                   cl.first_name, cl.last_name, cl.id
            FROM collective_session_bookings b
            INNER JOIN collective_sessions cs ON cs.id = b.collective_session_id
            INNER JOIN collectives c ON c.id = b.collective_id
            INNER JOIN clients cl ON cl.id = b.client_id
            WHERE b.id = :bid
            """
        ),
        {"bid": int(booking_id)},
    )
    row = r.fetchone()
    if row is None:
        return None
    first = (row[13] or "").strip()
    last = (row[14] or "").strip()
    client_name = " ".join(filter(None, [first, last])).strip() or f"Клиент #{int(row[15])}"
    return {
        "booking_id": int(row[0]),
        "collective_id": int(row[1]),
        "attendance_mode": str(row[2]),
        "center_coach_id": int(row[3]) if row[3] is not None else None,
        "fulfillment_trainer_id": int(row[4]),
        "status": str(row[5]),
        "guest_count": int(row[6] or 0),
        "booking_price_cents": int(row[7] or 0),
        "slot_date": str(row[8]),
        "start_time": str(row[9])[:5] if row[9] else "",
        "end_time": str(row[10])[:5] if row[10] else "",
        "collective_name": str(row[11] or row[12] or "Центр"),
        "collective_slug": str(row[12] or ""),
        "client_name": client_name,
    }


async def notify_trainers_pending_collective_session_booking(booking_id: int) -> None:
    """Fire-and-forget trainer pushes for a new pending center session booking."""
    settings = Settings()
    if not settings.telegram_bot_token_trainer:
        return

    async with async_session_factory() as session:
        row = await _load_pending_booking_notify_row(session, int(booking_id))
        if not row or row["status"] != BOOKING_STATUS_PENDING:
            return

        trainer_ids = await resolve_collective_session_booking_notify_trainer_ids(
            session,
            collective_id=int(row["collective_id"]),
            attendance_mode=str(row["attendance_mode"]),
            center_coach_id=row.get("center_coach_id"),
            fulfillment_trainer_id=int(row["fulfillment_trainer_id"]),
        )

        chat_ids: list[int] = []
        for tid in trainer_ids:
            tg_id = await get_trainer_telegram_id(session, int(tid))
            if tg_id:
                chat_ids.append(int(tg_id))
        chat_ids = list(dict.fromkeys(chat_ids))
        if not chat_ids:
            return

        mode_label = _attendance_mode_label_ru(str(row["attendance_mode"]))
        when = f"{row['slot_date']} {row['start_time']}–{row['end_time']}"
        body = msg.TRAINER_COLLECTIVE_SESSION_BOOKING_PENDING.format(
            collective_name=html.escape(row["collective_name"]),
            client_name=html.escape(row["client_name"]),
            when=html.escape(when),
            mode=html.escape(mode_label),
        )

    bot = Bot(token=settings.telegram_bot_token_trainer, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=body)
            except Exception:
                logger.exception(
                    "collective session booking notify failed chat_id=%s booking_id=%s",
                    chat_id,
                    booking_id,
                )
    finally:
        await bot.session.close()
