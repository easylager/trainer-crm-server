"""Карточка компании: callback, inline-запрос, chosen_inline_result.

Бот в чат не добавляется. Правка inline-сообщения — по inline_message_id.
[ПРОВЕРИТЬ] на живом боте: inline в группах и правка по inline_message_id.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    ChosenInlineResult,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from sqlalchemy import text

from src.application.ice_company.copy import (
    TOAST_ATTENDED,
    TOAST_CANT,
    TOAST_CLOSED,
    TOAST_DEPARTING,
    TOAST_GOING,
    TOAST_MAYBE,
    TOAST_QUIET,
    card_text,
)
from src.application.ice_company.delivery import AiogramSender
from src.application.ice_company.lifecycle import (
    ACTION_STATUS,
    _edit_dirty,
    buttons_for,
    parse_callback,
)
from src.application.ice_company.safety import TextRejected, clean_free_text
from src.application.ice_company.service import (
    CompanyRejected,
    actor_for_telegram,
    repeat_company,
    respond,
    snap_from,
    _load,
    _responses,
)
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings

logger = logging.getLogger(__name__)
router = Router(name="ice_company")

_TOAST = {
    "g": TOAST_GOING,
    "m": TOAST_MAYBE,
    "x": TOAST_CANT,
    "q": TOAST_QUIET,
    "e": TOAST_DEPARTING,
    "a": TOAST_ATTENDED,
    "b": TOAST_ATTENDED,
    "r": "Собираем ещё раз",
}


@router.callback_query(F.data.startswith("ic:"))
async def on_company_callback(query: CallbackQuery) -> None:
    parsed = parse_callback(query.data or "")
    if parsed is None or query.from_user is None:
        await query.answer()
        return
    code, action = parsed
    toast = _TOAST.get(action, TOAST_ATTENDED)
    await query.answer(toast)
    user_id = int(query.from_user.id)
    try:
        name = clean_free_text(query.from_user.first_name, max_len=20, required=False, field="Имя") or "Участник"
    except TextRejected:
        name = "Участник"
    async with async_session_factory() as session:
        try:
            if action == "r":
                await repeat_company(session, code=code, telegram_user_id=user_id, session_id=None)
            else:
                status_action = {
                    "q": "quiet",
                    "e": "depart",
                    "a": "attended",
                    "b": "missed",
                }.get(action, "status")
                await respond(
                    session,
                    code=code,
                    status=ACTION_STATUS.get(action, "going"),
                    display_name=name,
                    participant_key=f"tg:{user_id}",
                    source="tg",
                    consent=True,
                    action=status_action,
                    actor_hash=actor_for_telegram(user_id, None, None),
                )
        except CompanyRejected as exc:
            if exc.status_code == 409:
                await query.answer(TOAST_CLOSED, show_alert=False)
            logger.info("ice_company callback rejected status=%s", exc.status_code)
            return
        sender = AiogramSender(query.bot, Settings())
        await _edit_dirty(
            session,
            sender,
            settings=Settings(),
            debounce_sec=0,
            now=datetime.now(timezone.utc),
        )


@router.inline_query(F.query.startswith("k:"))
async def on_company_inline(query: InlineQuery) -> None:
    code = (query.query or "")[2:10]
    async with async_session_factory() as session:
        company = await _load(session, code)
        if company is None:
            await query.answer([], cache_time=1, is_personal=True)
            return
        responses = await _responses(session, int(company["id"]))
        snap = snap_from(company, responses)
        settings = Settings()
        from src.application.ice_company.service import _page_url

        page = _page_url(settings, code)
        body = card_text(snap)
        markup_buttons = buttons_for(company, snap, page)
    row = []
    for button in markup_buttons:
        if button.get("url"):
            row.append(InlineKeyboardButton(text=button["text"], url=button["url"]))
        elif button.get("data"):
            row.append(InlineKeyboardButton(text=button["text"], callback_data=button["data"]))
    await query.answer(
        [
            InlineQueryResultArticle(
                id=f"k{code}",
                title="Компания на лёд",
                description=body.split("\n", 1)[0][:80],
                input_message_content=InputTextMessageContent(message_text=body),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[row]),
            )
        ],
        cache_time=1,
        is_personal=True,
    )


@router.chosen_inline_result(F.result_id.regexp(r"^k[23456789abcdefghjkmnpqrstuvwxyz]{8}$"))
async def on_company_chosen(result: ChosenInlineResult) -> None:
    inline_id = result.inline_message_id
    code = (result.result_id or "")[1:]
    if not inline_id:
        return
    async with async_session_factory() as session:
        company = await _load(session, code)
        if company is None:
            return
        await session.execute(
            text(
                """
                INSERT INTO ice_company_messages (company_id, inline_message_id, is_group)
                SELECT :company_id, :inline_id, false
                WHERE NOT EXISTS (
                    SELECT 1 FROM ice_company_messages
                    WHERE company_id = :company_id AND inline_message_id = :inline_id
                )
                """
            ),
            {"company_id": company["id"], "inline_id": inline_id},
        )
        await session.execute(
            text("UPDATE ice_companies SET card_dirty = true WHERE id = :id"),
            {"id": company["id"]},
        )
        await session.commit()
