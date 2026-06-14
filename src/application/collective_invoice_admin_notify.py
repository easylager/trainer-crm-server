"""
Push to admin Telegram bot when a studio owner requests a collective pool invoice (ERIP / manual).
"""
from __future__ import annotations

import html
import logging
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.collective_use_cases import format_collective_modules_list_ru
from src.bot import messages as msg
from src.infrastructure.db import async_session_factory
from src.shared.byr_currency_display import BYR_SIGN
from src.shared.config import Settings

logger = logging.getLogger(__name__)


def _trainer_display_name(first: str | None, last: str | None, trainer_id: int) -> str:
    n = " ".join([(first or "").strip(), (last or "").strip()]).strip()
    return n if n else f"trainer_id={trainer_id}"


async def _load_collective_invoice_notify_row(
    session: AsyncSession,
    invoice_id: int,
) -> dict[str, Any] | None:
    r = await session.execute(
        text(
            """
            SELECT ci.id, ci.collective_id, ci.requested_by_trainer_id, ci.amount_cents,
                   ci.period_months, ci.modules, ci.seat_limit, ci.period_start, ci.period_end,
                   ci.status, c.slug, c.display_name,
                   t.telegram_id, t.telegram_username, tp.first_name, tp.last_name
            FROM collective_invoices ci
            INNER JOIN collectives c ON c.id = ci.collective_id
            INNER JOIN trainers t ON t.id = ci.requested_by_trainer_id
            LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
            WHERE ci.id = :iid
            """
        ),
        {"iid": int(invoice_id)},
    )
    row = r.fetchone()
    if row is None:
        return None
    return {
        "invoice_id": int(row[0]),
        "collective_id": int(row[1]),
        "requested_by_trainer_id": int(row[2]),
        "amount_cents": int(row[3]),
        "period_months": int(row[4]),
        "modules": row[5],
        "seat_limit": int(row[6]),
        "period_start": row[7],
        "period_end": row[8],
        "status": str(row[9]),
        "slug": str(row[10]),
        "display_name": str(row[11]),
        "telegram_id": int(row[12]) if row[12] is not None else None,
        "telegram_username": row[13],
        "first_name": row[14],
        "last_name": row[15],
    }


def build_admin_collective_invoice_keyboard(invoice_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Активировать pool-подписку",
                    callback_data=f"cs:act:{invoice_id}",
                ),
            ],
        ]
    )


async def notify_admins_new_collective_subscription_invoice(invoice_id: int) -> None:
    settings = Settings()
    token = settings.telegram_bot_token_admin
    admin_ids = list(dict.fromkeys(settings.admin_telegram_ids or []))
    if not token or not admin_ids:
        return
    async with async_session_factory() as session:
        row = await _load_collective_invoice_notify_row(session, invoice_id)
    if not row:
        logger.warning("collective invoice notify: invoice %s not found", invoice_id)
        return

    amount_byn = int(row["amount_cents"]) / 100
    ps = row["period_start"]
    pe = row["period_end"]
    ps_s = ps.strftime("%d.%m.%Y") if hasattr(ps, "strftime") else str(ps)[:10]
    pe_s = pe.strftime("%d.%m.%Y") if hasattr(pe, "strftime") else str(pe)[:10]
    mods_label = ", ".join(format_collective_modules_list_ru(row.get("modules")))
    owner_name = _trainer_display_name(row.get("first_name"), row.get("last_name"), row["requested_by_trainer_id"])

    body = msg.ADMIN_COLLECTIVE_INVOICE_NOTIFY.format(
        invoice_id=invoice_id,
        slug=html.escape(row["slug"]),
        display_name=html.escape(row["display_name"]),
        owner_name=html.escape(owner_name),
        seats=row["seat_limit"],
        months=row["period_months"],
        modules_label=html.escape(mods_label),
        amount_byn=int(amount_byn) if amount_byn == int(amount_byn) else round(amount_byn, 2),
        period_start=html.escape(ps_s),
        period_end=html.escape(pe_s),
        byr_sign=BYR_SIGN,
    )
    keyboard = build_admin_collective_invoice_keyboard(int(invoice_id))
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        for chat_id in admin_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=body, reply_markup=keyboard)
            except Exception:
                logger.exception(
                    "collective invoice notify failed chat_id=%s invoice_id=%s",
                    chat_id,
                    invoice_id,
                )
    finally:
        await bot.session.close()
