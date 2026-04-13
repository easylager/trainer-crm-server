"""
Telegram notifications after trainer saves PASS/CERT «Клиент не пришёл» (booking_client_no_show).
Client-first copy: return vs no deduction vs keep charge — aligned with messages.py voice.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_no_show_use_cases import RESOLUTION_REDEEM, RESOLUTION_SKIP
from src.application.booking_use_cases import get_trainer_telegram_id
from src.bot import messages as msg
from src.shared.config import Settings

logger = logging.getLogger(__name__)


async def load_booking_client_no_show_notify_payload(
    session: AsyncSession,
    booking_id: int,
) -> dict[str, Any] | None:
    """Row in booking_client_no_show + slot/client for both bots."""
    r = await session.execute(
        text(
            """
            SELECT cns.deduct_resolution, cns.completed_at_submit, cns.payment_class,
                   b.trainer_id,
                   s.slot_date, s.start_time, s.end_time,
                   COALESCE(c.telegram_id, 0) AS client_telegram_id,
                   TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                   COALESCE(srv.name, '—') AS service_name
            FROM booking_client_no_show cns
            JOIN bookings b ON b.id = cns.booking_id
            JOIN slots s ON s.id = b.slot_id
            JOIN clients c ON c.id = b.client_id
            LEFT JOIN services srv ON srv.id = b.service_id
            WHERE cns.booking_id = :bid
            LIMIT 1
            """
        ),
        {"bid": booking_id},
    )
    row = r.fetchone()
    if not row:
        return None
    dr = (row[0] or "").strip().lower()
    completed_submit = bool(row[1])
    pclass = (row[2] or "").strip()
    trainer_id = int(row[3])
    trainer_tid = await get_trainer_telegram_id(session, trainer_id)
    return {
        "booking_id": booking_id,
        "trainer_id": trainer_id,
        "trainer_telegram_id": trainer_tid,
        "deduct_resolution": dr,
        "completed_at_submit": completed_submit,
        "payment_class": pclass,
        "slot_date": row[4],
        "start_time": row[5],
        "end_time": row[6],
        "client_telegram_id": int(row[7]) if row[7] else None,
        "client_name": ((row[8] or "").strip() or "Клиент"),
        "service_name": ((row[9] or "—").strip()),
    }


def _client_notice_variant(deduct_resolution: str, completed_at_submit: bool) -> str:
    if deduct_resolution == RESOLUTION_SKIP and not completed_at_submit:
        return "skip_before"
    if deduct_resolution == RESOLUTION_SKIP and completed_at_submit:
        return "skip_after"
    if deduct_resolution == RESOLUTION_REDEEM and not completed_at_submit:
        return "redeem_before"
    if deduct_resolution == RESOLUTION_REDEEM and completed_at_submit:
        return "redeem_after"
    return "redeem_before"


def _trainer_outcome_line_ru(deduct_resolution: str, completed_at_submit: bool) -> str:
    if deduct_resolution == RESOLUTION_SKIP and not completed_at_submit:
        return "Клиент получит уведомление: по записи не будет списания с абонемента или сертификата."
    if deduct_resolution == RESOLUTION_SKIP and completed_at_submit:
        return "Клиент получит уведомление: занятие возвращено на абонемент или средства — на сертификат."
    if deduct_resolution == RESOLUTION_REDEEM and not completed_at_submit:
        return "Клиент получит уведомление: при закрытии записи спишется занятие, как если клиента не было на тренировке."
    return "Клиент получит уведомление: списание по записи оставлено в учёте."


async def send_booking_client_no_show_telegram_notifications(
    session: AsyncSession,
    booking_id: int,
) -> None:
    """Best-effort trainer + client messages; logs failures; does not raise."""
    payload = await load_booking_client_no_show_notify_payload(session, booking_id)
    if not payload:
        logger.warning("client_no_show notify: no payload for booking_id=%s", booking_id)
        return

    settings = Settings()
    base = (settings.webapp_base_url or "").rstrip("/")
    webapp_https = base.startswith("https://")

    slot_date = payload.get("slot_date")
    start_time = payload.get("start_time")
    ds = (
        slot_date.strftime("%d.%m")
        if slot_date and hasattr(slot_date, "strftime")
        else "—"
    )
    dy = (
        msg.TRAINER_DAYS[slot_date.weekday()]
        if slot_date and hasattr(slot_date, "weekday")
        else ""
    )
    ts = (
        start_time.strftime("%H:%M")
        if start_time and hasattr(start_time, "strftime")
        else "—"
    )

    dr = str(payload.get("deduct_resolution") or "")
    completed = bool(payload.get("completed_at_submit"))
    outcome_line = _trainer_outcome_line_ru(dr, completed)
    pc = str(payload.get("payment_class") or "")

    # --- Trainer ---
    trainer_tid = payload.get("trainer_telegram_id")
    if trainer_tid:
        text_html = msg.format_trainer_client_no_show_ack_html(
            client_name=payload["client_name"],
            outcome_line_ru=outcome_line,
            payment_class=pc,
            date=ds,
            day=dy,
            time=ts,
            service_name=payload.get("service_name"),
        )
        rows: list[list[InlineKeyboardButton]] = []
        if webapp_https:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=msg.TRAINER_BUTTON_OPEN_SCHEDULE_PROBLEM,
                        web_app=WebAppInfo(
                            url=f"{base}/webapp/schedule-editor?open_booking={booking_id}"
                        ),
                    ),
                ]
            )
        kb = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
        trainer_bot = Bot(
            token=settings.telegram_bot_token_trainer,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            await trainer_bot.send_message(
                chat_id=int(trainer_tid),
                text=text_html,
                reply_markup=kb,
            )
        except Exception as e:
            logger.warning(
                "client_no_show notify trainer tid=%s booking=%s: %s",
                trainer_tid,
                booking_id,
                e,
            )
        finally:
            await trainer_bot.session.close()
    else:
        logger.info(
            "client_no_show notify: no trainer telegram for booking_id=%s",
            booking_id,
        )

    # --- Client ---
    client_tid = payload.get("client_telegram_id")
    if not client_tid:
        logger.info("client_no_show notify: no client telegram for booking_id=%s", booking_id)
        return

    variant = _client_notice_variant(dr, completed)
    text_client = msg.format_client_booking_no_show_notice_html(
        variant=variant,
        payment_class=pc,
        date=ds,
        day=dy,
        time=ts,
        service_name=payload.get("service_name"),
    )
    client_rows: list[list[InlineKeyboardButton]] = []
    if webapp_https:
        client_rows.append(
            [
                InlineKeyboardButton(
                    text=msg.CLIENT_BUTTON_MY_BOOKINGS,
                    web_app=WebAppInfo(
                        url=f"{base}/webapp/client-bookings?open_booking={booking_id}"
                    ),
                ),
            ]
        )
    kb_c = InlineKeyboardMarkup(inline_keyboard=client_rows) if client_rows else None
    client_bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await client_bot.send_message(
            chat_id=int(client_tid),
            text=text_client,
            reply_markup=kb_c,
        )
    except Exception as e:
        logger.warning(
            "client_no_show notify client tid=%s booking=%s: %s",
            client_tid,
            booking_id,
            e,
        )
    finally:
        await client_bot.session.close()
