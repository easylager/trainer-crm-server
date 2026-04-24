"""
Push to admin Telegram bot when a trainer requests a subscription invoice (ERIP / manual flow).
Failures are logged only; never raised to API callers.
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

from src.application.subscription_tier_use_cases import format_subscription_label
from src.bot import messages as msg
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings

logger = logging.getLogger(__name__)


def _trainer_display_name(first: str | None, last: str | None, trainer_id: int) -> str:
    n = " ".join([(first or "").strip(), (last or "").strip()]).strip()
    return n if n else f"trainer_id={trainer_id}"


def trainer_contact_url(telegram_id: int | None, telegram_username: str | None) -> str | None:
    if telegram_username:
        u = str(telegram_username).strip().lstrip("@")
        if u:
            return f"https://t.me/{u}"
    if telegram_id is not None:
        return f"tg://user?id={int(telegram_id)}"
    return None


def trainer_contact_link_html(telegram_id: int | None, telegram_username: str | None) -> str:
    """Single-line HTML link for admin lists / push."""
    url = trainer_contact_url(telegram_id, telegram_username)
    if not url:
        return "<i>нет @username / id</i>"
    return f'<a href="{html.escape(url)}">контакт</a>'


def format_catalog_modules_short(mods: dict[str, Any] | None) -> str:
    """Single-line label for an invoice's module set; matches the unified plan-naming rules."""
    if not isinstance(mods, dict):
        return "—"
    return format_subscription_label(mods, has_base_crm=True, is_trial=False)


async def load_subscription_invoice_admin_view(session: AsyncSession, invoice_id: int) -> dict[str, Any] | None:
    """Public alias used by admin handlers; same row shape as the notification loader."""
    return await _load_invoice_notify_row(session, invoice_id)


async def _load_invoice_notify_row(session: AsyncSession, invoice_id: int) -> dict[str, Any] | None:
    r = await session.execute(
        text("""
            SELECT ti.id, ti.trainer_id, ti.amount_cents, ti.period_start, ti.period_end, ti.status,
                   ti.checkout_bundle_tier, ti.checkout_billing_period_months, ti.checkout_modules,
                   t.telegram_id, t.telegram_username, tp.first_name, tp.last_name
            FROM trainer_invoices ti
            INNER JOIN trainers t ON t.id = ti.trainer_id
            LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
            WHERE ti.id = :iid
              AND ti.checkout_modules IS NOT NULL
              AND ti.checkout_billing_period_months IS NOT NULL
        """),
        {"iid": invoice_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "invoice_id": row[0],
        "trainer_id": row[1],
        "amount_cents": row[2],
        "period_start": row[3],
        "period_end": row[4],
        "status": row[5],
        "checkout_bundle_tier": row[6],
        "checkout_billing_period_months": row[7],
        "checkout_modules": row[8],
        "telegram_id": int(row[9]) if row[9] is not None else None,
        "telegram_username": row[10],
        "first_name": row[11],
        "last_name": row[12],
    }


async def notify_admins_new_catalog_subscription_invoice(invoice_id: int) -> None:
    """Send one HTML message per admin (admin bot)."""
    settings = Settings()
    token = settings.telegram_bot_token_admin
    admin_ids = list(dict.fromkeys(settings.admin_telegram_ids or []))
    if not token or not admin_ids:
        return
    async with async_session_factory() as session:
        row = await _load_invoice_notify_row(session, invoice_id)
    if not row:
        logger.warning("subscription invoice notify: invoice %s not found or not catalog checkout", invoice_id)
        return
    tid = int(row["trainer_id"])
    name_plain = _trainer_display_name(row.get("first_name"), row.get("last_name"), tid)
    amount_byn = int(row["amount_cents"]) / 100
    ps = row["period_start"]
    pe = row["period_end"]
    ps_s = ps.strftime("%d.%m.%Y") if hasattr(ps, "strftime") else str(ps)[:10]
    pe_s = pe.strftime("%d.%m.%Y") if hasattr(pe, "strftime") else str(pe)[:10]
    bpm = row.get("checkout_billing_period_months")
    bundle = row.get("checkout_bundle_tier")
    plan_line = (
        f"Пакет: <b>{html.escape(str(bundle))}</b> · период <b>{bpm}</b> мес."
        if bundle
        else f"Конструктор · период <b>{bpm}</b> мес. · {format_catalog_modules_short(row.get('checkout_modules'))}"
    )
    contact_url = trainer_contact_url(row.get("telegram_id"), row.get("telegram_username"))
    link_line = (
        f'<a href="{html.escape(contact_url)}">Открыть контакт тренера в Telegram</a>'
        if contact_url
        else "<i>Нет telegram_id / username — ищите по internal id.</i>"
    )
    body = msg.ADMIN_SUBSCRIPTION_INVOICE_NOTIFY.format(
        invoice_id=invoice_id,
        trainer_id=tid,
        trainer_name=html.escape(name_plain),
        amount_byn=int(amount_byn) if amount_byn == int(amount_byn) else round(amount_byn, 2),
        period_start=html.escape(ps_s),
        period_end=html.escape(pe_s),
        plan_line=plan_line,
        trainer_contact_block=link_line,
    )
    keyboard = build_admin_subscription_invoice_keyboard(int(invoice_id))
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        for chat_id in admin_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=body, reply_markup=keyboard)
            except Exception:
                logger.exception(
                    "subscription invoice notify failed chat_id=%s invoice_id=%s",
                    chat_id,
                    invoice_id,
                )
    finally:
        await bot.session.close()


def build_admin_subscription_invoice_keyboard(invoice_id: int) -> InlineKeyboardMarkup:
    """Three-button action keyboard attached to every admin invoice card."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Активировать как заказано",
                    callback_data=f"as:act:{invoice_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Изменить состав",
                    callback_data=f"as:edit:{invoice_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"as:cancel:{invoice_id}",
                ),
            ],
        ]
    )
