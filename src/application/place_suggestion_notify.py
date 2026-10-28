"""
Push a card to admins the moment someone suggests a place (PDEC-028).

Mirrors ``admin_arena_notify.notify_admins_new_trainer_arena``: one HTML message per admin,
failures logged, never raised. «Открыть» opens the suggestion in the admin Mini App;
«Одобрить как есть» appears only when there is nothing to compare against — no likely
duplicate in our city (or the city is new) — so a one-tap approve never doubles a place.
"""
from __future__ import annotations

import html
import logging
from typing import Any, Mapping

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db import async_session_factory
from src.shared.config import Settings
from src.shared.place_suggestion import PLACE_SUGGEST_APPROVE_PREFIX
from src.shared.venue_types import venue_type_noun

logger = logging.getLogger(__name__)

_PRICE_KEYS = ("price_adult", "price_child", "price_rental")


def format_place_suggestion_notice(row: Mapping[str, Any]) -> str:
    """«Новая заявка №12 · Каток · Уфа (новый город) · есть цены, есть контакт» (HTML-safe)."""
    is_new_city = bool(row.get("new_city_name")) and not row.get("city_name")
    city = row.get("city_name") or row.get("new_city_name") or "—"
    parts = [
        f"Новая заявка №{int(row['id'])}",
        html.escape(venue_type_noun(row.get("kind"))),
        html.escape(str(city)) + (" (новый город)" if is_new_city else ""),
    ]
    details = row.get("details") or {}
    signals = []
    if any(details.get(k) for k in _PRICE_KEYS):
        signals.append("есть цены")
    if row.get("contact") or row.get("author_telegram_id"):
        signals.append("есть контакт")
    if signals:
        parts.append(", ".join(signals))
    return " · ".join(parts)


def place_suggestion_keyboard(suggestion_id: int, *, base_url: str, can_approve: bool) -> InlineKeyboardMarkup:
    base = (base_url or "").rstrip("/")
    row = [
        InlineKeyboardButton(
            text="Открыть",
            web_app=WebAppInfo(url=f"{base}/webapp/admin-place-suggestions?id={int(suggestion_id)}"),
        )
    ]
    if can_approve:
        row.append(
            InlineKeyboardButton(
                text="Одобрить как есть",
                callback_data=f"{PLACE_SUGGEST_APPROVE_PREFIX}{int(suggestion_id)}",
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=[row])


async def load_place_suggestion_notice_row(session: AsyncSession, suggestion_id: int) -> dict[str, Any] | None:
    r = await session.execute(
        text(
            """
            SELECT s.id, s.kind, s.city_id, c.name, s.new_city_name, s.name, s.details,
                   s.contact, s.author_telegram_id, s.latitude, s.longitude
            FROM place_suggestions s
            LEFT JOIN cities c ON c.id = s.city_id
            WHERE s.id = :id
            """
        ),
        {"id": int(suggestion_id)},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": int(row[0]),
        "kind": row[1],
        "city_id": int(row[2]) if row[2] is not None else None,
        "city_name": row[3],
        "new_city_name": row[4],
        "name": row[5],
        "details": row[6] or {},
        "contact": row[7],
        "author_telegram_id": row[8],
        "latitude": row[9],
        "longitude": row[10],
    }


async def _can_approve_as_is(session: AsyncSession, row: Mapping[str, Any]) -> bool:
    if not (row.get("name") or "").strip():
        return False
    if row.get("city_id") is None:
        return True  # новый город — сравнивать не с чем
    from src.application.trainer_arena_create_use_cases import find_possible_duplicate_arenas

    dups = await find_possible_duplicate_arenas(
        session,
        int(row["city_id"]),
        name=row["name"],
        latitude=row.get("latitude"),
        longitude=row.get("longitude"),
    )
    return not dups


async def notify_admins_new_place_suggestion(suggestion_id: int) -> None:
    """Deliver one card per admin right after ``create_place_suggestion`` commits."""
    settings = Settings()
    token = settings.telegram_bot_token_admin
    admin_ids = list(dict.fromkeys(settings.admin_telegram_ids or []))
    if not token or not admin_ids:
        return
    async with async_session_factory() as session:
        row = await load_place_suggestion_notice_row(session, suggestion_id)
        if not row:
            logger.warning("place suggestion notify: suggestion %s missing", suggestion_id)
            return
        can_approve = await _can_approve_as_is(session, row)
    caption = format_place_suggestion_notice(row)
    kb = place_suggestion_keyboard(suggestion_id, base_url=settings.webapp_base_url or "", can_approve=can_approve)
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        for chat_id in admin_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=caption, reply_markup=kb)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "place suggestion admin notify failed chat_id=%s suggestion_id=%s", chat_id, suggestion_id
                )
    finally:
        await bot.session.close()


_REPLY_PREVIEW_MAX = 3500


def format_place_suggestion_reply(suggestion_id: int, body: str) -> str:
    """«Ответ по заявке №12: …» (HTML-safe, длинный ответ обрезан до лимита Telegram)."""
    text_body = str(body or "").strip()
    if len(text_body) > _REPLY_PREVIEW_MAX:
        text_body = text_body[:_REPLY_PREVIEW_MAX].rstrip() + "…"
    return f"Ответ по заявке №{int(suggestion_id)}: {html.escape(text_body)}"


async def notify_admins_place_suggestion_reply(suggestion_id: int, body: str) -> None:
    """Автор ответил в клиентском боте — карточка с «Открыть» каждому админу; ошибки только в лог."""
    settings = Settings()
    token = settings.telegram_bot_token_admin
    admin_ids = list(dict.fromkeys(settings.admin_telegram_ids or []))
    if not token or not admin_ids:
        return
    caption = format_place_suggestion_reply(suggestion_id, body)
    kb = place_suggestion_keyboard(suggestion_id, base_url=settings.webapp_base_url or "", can_approve=False)
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        for chat_id in admin_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=caption, reply_markup=kb)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "place suggestion reply notify failed chat_id=%s suggestion_id=%s", chat_id, suggestion_id
                )
    finally:
        await bot.session.close()
