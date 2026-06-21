"""
Deliver booking party outbox rows via Telegram bots (immediate + retry loop).
"""
from __future__ import annotations

import html
import logging
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_party_notifications import (
    KIND_CLIENT_CANCEL_CONFIRM,
    KIND_CLIENT_CANCEL_TRAINER,
    KIND_TRAINER_DECLINE_CLIENT,
    delivery_status_label,
    list_pending_booking_party_notifications_for_booking,
    mark_booking_party_notification_attempt,
    mark_booking_party_notification_sent,
)
from src.bot import messages as msg
from src.shared.config import Settings

logger = logging.getLogger(__name__)


async def _send_client_cancel_trainer(bot: Bot, row: dict[str, Any]) -> None:
    pl = row.get("payload") or {}
    client_name = html.escape(str(pl.get("client_name") or "Клиент"))
    date_str = html.escape(str(pl.get("date_str") or "—"))
    day_label = html.escape(str(pl.get("day_label") or ""))
    time_str = html.escape(str(pl.get("time_str") or "—"))
    reason = pl.get("reason")
    if reason:
        text = msg.TRAINER_BOOKING_CANCELLED_BY_CLIENT.format(
            client_name=client_name,
            date=date_str,
            day=day_label,
            time=time_str,
            reason=html.escape(str(reason)),
        )
    else:
        text = msg.TRAINER_BOOKING_CANCELLED_BY_CLIENT_NO_REASON.format(
            client_name=client_name,
            date=date_str,
            day=day_label,
            time=time_str,
        )
    reply_markup = None
    slot_id = pl.get("slot_id")
    exclude_client_id = pl.get("client_id")
    client_tid = pl.get("client_telegram_id")
    if slot_id is not None and exclude_client_id is not None:
        reply_markup = msg.build_trainer_client_cancel_notification_keyboard(
            webapp_base_url=Settings().webapp_base_url,
            slot_id=int(slot_id),
            exclude_client_id=int(exclude_client_id),
            client_telegram_id=int(client_tid) if client_tid else None,
        )
    await bot.send_message(
        chat_id=int(row["recipient_telegram_id"]),
        text=text,
        reply_markup=reply_markup,
    )


async def _send_client_cancel_confirm(bot: Bot, row: dict[str, Any]) -> None:
    pl = row.get("payload") or {}
    date_str = str(pl.get("date_str") or "—")
    day_label = str(pl.get("day_label") or "")
    time_str = str(pl.get("time_str") or "—")
    settings = Settings()
    reply_markup = msg.build_client_rebook_catalog_keyboard(
        webapp_base_url=settings.webapp_base_url,
        trainer_id=pl.get("trainer_id"),
        service_id=pl.get("service_id"),
    )
    cancel_tpl = (
        msg.CLIENT_BOOKING_CANCELLED_BY_SELF
        if reply_markup is not None
        else msg.CLIENT_BOOKING_CANCELLED_BY_SELF_MENU
    )
    text = cancel_tpl.format(date=date_str, day=day_label, time=time_str)
    await bot.send_message(
        chat_id=int(row["recipient_telegram_id"]),
        text=text,
        reply_markup=reply_markup,
    )


async def _send_trainer_decline_client(bot: Bot, row: dict[str, Any]) -> None:
    pl = row.get("payload") or {}
    text = msg.format_client_booking_declined_by_trainer_html(
        date=str(pl.get("date_str") or "—"),
        day=str(pl.get("day_label") or ""),
        time=str(pl.get("time_str") or "—"),
        reason=str(pl.get("reason") or ""),
    )
    decl_kb = msg.build_client_declined_booking_catalog_keyboard(
        webapp_base_url=Settings().webapp_base_url,
    )
    await bot.send_message(
        chat_id=int(row["recipient_telegram_id"]),
        text=text,
        reply_markup=decl_kb,
    )


async def deliver_booking_party_notification_row(
    session: AsyncSession,
    row: dict[str, Any],
    *,
    trainer_bot: Bot | None = None,
    client_bot: Bot | None = None,
) -> bool:
    """Send one outbox row; update attempt_count / sent_at. Returns True when delivered."""
    kind = str(row.get("kind") or "")
    nid = int(row["id"])
    try:
        if kind == KIND_CLIENT_CANCEL_TRAINER:
            if trainer_bot is None:
                return False
            await _send_client_cancel_trainer(trainer_bot, row)
        elif kind == KIND_CLIENT_CANCEL_CONFIRM:
            if client_bot is None:
                return False
            await _send_client_cancel_confirm(client_bot, row)
        elif kind == KIND_TRAINER_DECLINE_CLIENT:
            if client_bot is None:
                return False
            await _send_trainer_decline_client(client_bot, row)
        else:
            logger.warning("booking_party_notify unknown kind=%s id=%s", kind, nid)
            await mark_booking_party_notification_attempt(
                session, nid, error=f"unknown kind {kind}"
            )
            await session.commit()
            return False
        await mark_booking_party_notification_sent(session, nid)
        logger.info(
            "booking_party_notify delivered kind=%s booking_id=%s notification_id=%s recipient=%s",
            kind,
            row.get("booking_id"),
            nid,
            row.get("recipient_telegram_id"),
        )
        return True
    except Exception as e:
        await mark_booking_party_notification_attempt(session, nid, error=str(e))
        await session.commit()
        logger.warning(
            "booking_party_notify failed kind=%s booking_id=%s notification_id=%s recipient=%s err=%s",
            kind,
            row.get("booking_id"),
            nid,
            row.get("recipient_telegram_id"),
            e,
        )
        return False


async def deliver_client_cancel_notifications_immediate(
    session: AsyncSession,
    booking_id: int,
    payload: dict[str, Any],
    *,
    trainer_bot: Bot,
    client_bot: Bot,
    client_telegram_id: int,
    send_client_confirm: bool,
) -> dict[str, str]:
    """Direct Telegram send (fallback when outbox table is unavailable). Never raises."""
    from src.application.booking_party_notifications import (
        KIND_CLIENT_CANCEL_CONFIRM,
        KIND_CLIENT_CANCEL_TRAINER,
        delivery_status_label,
    )

    results: dict[str, str] = {}
    trainer_tid = payload.get("trainer_telegram_id")
    if trainer_tid:
        row = {
            "recipient_telegram_id": int(trainer_tid),
            "payload": {
                "date_str": payload.get("date_str"),
                "day_label": payload.get("day_label"),
                "time_str": payload.get("time_str"),
                "client_name": payload.get("client_name"),
                "reason": payload.get("reason"),
                "slot_id": payload.get("slot_id"),
                "client_id": payload.get("client_id"),
                "client_telegram_id": payload.get("client_telegram_id"),
            },
        }
        try:
            await _send_client_cancel_trainer(trainer_bot, row)
            results[KIND_CLIENT_CANCEL_TRAINER] = delivery_status_label(sent=True, queued=False)
        except Exception as e:
            logger.warning(
                "client_cancel_trainer immediate failed booking_id=%s err=%s",
                booking_id,
                e,
            )
            results[KIND_CLIENT_CANCEL_TRAINER] = delivery_status_label(sent=False, queued=False)
    else:
        results[KIND_CLIENT_CANCEL_TRAINER] = delivery_status_label(skipped=True, sent=False, queued=False)

    if send_client_confirm:
        row = {
            "recipient_telegram_id": int(client_telegram_id),
            "payload": {
                "date_str": payload.get("date_str"),
                "day_label": payload.get("day_label"),
                "time_str": payload.get("time_str"),
                "trainer_id": payload.get("trainer_id"),
                "service_id": payload.get("service_id"),
            },
        }
        try:
            await _send_client_cancel_confirm(client_bot, row)
            results[KIND_CLIENT_CANCEL_CONFIRM] = delivery_status_label(sent=True, queued=False)
        except Exception as e:
            logger.warning(
                "client_cancel_confirm immediate failed booking_id=%s err=%s",
                booking_id,
                e,
            )
            results[KIND_CLIENT_CANCEL_CONFIRM] = delivery_status_label(sent=False, queued=False)
    else:
        results[KIND_CLIENT_CANCEL_CONFIRM] = delivery_status_label(skipped=True, sent=False, queued=False)
    return results


async def try_deliver_booking_party_notifications_for_booking(
    session: AsyncSession,
    booking_id: int,
    *,
    trainer_bot: Bot | None = None,
    client_bot: Bot | None = None,
) -> dict[str, str]:
    """Immediate delivery pass for all pending rows of one booking; returns per-kind status labels."""
    rows = await list_pending_booking_party_notifications_for_booking(session, int(booking_id))
    by_kind: dict[str, str] = {}
    for row in rows:
        kind = str(row.get("kind") or "")
        ok = await deliver_booking_party_notification_row(
            session, row, trainer_bot=trainer_bot, client_bot=client_bot
        )
        by_kind[kind] = delivery_status_label(sent=ok, queued=not ok)
    return by_kind


async def process_booking_party_notifications_batch(
    session: AsyncSession,
    *,
    trainer_bot: Bot,
    client_bot: Bot,
    limit: int = 50,
) -> int:
    from src.application.booking_party_notifications import list_pending_booking_party_notifications

    pending = await list_pending_booking_party_notifications(session, limit=limit)
    delivered = 0
    for row in pending:
        role = str(row.get("recipient_role") or "")
        if await deliver_booking_party_notification_row(
            session,
            row,
            trainer_bot=trainer_bot if role == "trainer" else None,
            client_bot=client_bot if role == "client" else None,
        ):
            delivered += 1
    return delivered
