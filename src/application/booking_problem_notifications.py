"""
E5: immediate Telegram notifications after a trainer submits a booking problem report.

Trainer: acknowledgment + outcome summary (distinct from «завершено»).
Client: neutral notice — session not counted as successful completion (FR-12).
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

from src.application.booking_use_cases import get_trainer_telegram_id
from src.bot import messages as msg
from src.shared.config import Settings

logger = logging.getLogger(__name__)

# Align with booking_problem_use_cases preset ids (short labels for push)
_PRESET_SHORT_LABEL_RU = {
    "A1": "не пришёл",
    "A2": "оплата под вопросом",
    "B1": "не пришёл (абонемент/сертификат)",
    "B2": "оплата (абонемент/сертификат)",
}


async def load_booking_problem_notify_payload(
    session: AsyncSession,
    booking_id: int,
) -> dict[str, Any] | None:
    """One row after report exists: preset, slot, names for both bots."""
    r = await session.execute(
        text(
            """
            SELECT pr.preset_id, pr.payment_class,
                   b.id, b.trainer_id,
                   s.slot_date, s.start_time, s.end_time,
                   COALESCE(c.telegram_id, 0) AS client_telegram_id,
                   TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                   COALESCE(srv.name, '—') AS service_name
            FROM booking_problem_reports pr
            JOIN bookings b ON b.id = pr.booking_id
            JOIN slots s ON s.id = b.slot_id
            JOIN clients c ON c.id = b.client_id
            LEFT JOIN services srv ON srv.id = b.service_id
            WHERE pr.booking_id = :bid
            LIMIT 1
            """
        ),
        {"bid": booking_id},
    )
    row = r.fetchone()
    if not row:
        return None
    preset_id = (row[0] or "").strip()
    trainer_id = int(row[3])
    client_tg = int(row[7]) if row[7] else 0
    client_name = ((row[8] or "").strip() or "Клиент")
    service_name = ((row[9] or "—").strip())
    trainer_tid = await get_trainer_telegram_id(session, trainer_id)
    return {
        "booking_id": booking_id,
        "trainer_id": trainer_id,
        "trainer_telegram_id": trainer_tid,
        "preset_id": preset_id,
        "payment_class": (row[1] or "").strip(),
        "slot_date": row[4],
        "start_time": row[5],
        "end_time": row[6],
        "client_telegram_id": client_tg or None,
        "client_name": client_name,
        "service_name": service_name,
        "preset_short_label_ru": _PRESET_SHORT_LABEL_RU.get(preset_id, preset_id),
    }


async def send_booking_problem_telegram_notifications(
    session: AsyncSession,
    booking_id: int,
) -> None:
    """
    Best-effort: send trainer + client messages. Logs failures; does not raise (API already succeeded).
    """
    payload = await load_booking_problem_notify_payload(session, booking_id)
    if not payload:
        logger.warning("booking_problem notify: no payload for booking_id=%s", booking_id)
        return
    settings = Settings()
    base = (settings.webapp_base_url or "").rstrip("/")
    webapp_https = base.startswith("https://")

    # --- Trainer (trainer bot): acknowledgment ---
    trainer_tid = payload.get("trainer_telegram_id")
    if trainer_tid:
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
        text_html = msg.format_trainer_booking_problem_ack_html(
            client_name=payload["client_name"],
            preset_summary_ru=payload["preset_short_label_ru"],
            payment_class=payload.get("payment_class") or "",
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
                "booking_problem notify trainer tid=%s booking=%s: %s",
                trainer_tid,
                booking_id,
                e,
            )
        finally:
            await trainer_bot.session.close()
    else:
        logger.info(
            "booking_problem notify: no trainer telegram for booking_id=%s",
            booking_id,
        )

    # --- Client (client bot): not happy-path completion ---
    client_tid = payload.get("client_telegram_id")
    if client_tid:
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
        text_client = msg.format_client_booking_problem_notice_html(
            date=ds,
            day=dy,
            time=ts,
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
                "booking_problem notify client tid=%s booking=%s: %s",
                client_tid,
                booking_id,
                e,
            )
        finally:
            await client_bot.session.close()
