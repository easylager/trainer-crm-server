"""Карточка компании: callback, inline-запрос, chosen_inline_result.

Бот в чат не добавляется. Правка inline-сообщения — по inline_message_id.
[ПРОВЕРИТЬ] на живом боте: inline в группах и правка по inline_message_id.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.types import (
    CallbackQuery,
    ChosenInlineResult,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultPhoto,
    InputTextMessageContent,
    InlineKeyboardMarkup,
)
from src.application.ice_company.copy import (
    MATCH_KIND,
    TOAST_CLOSED,
    card_text,
    toast_for,
)
from src.application.ice_company.delivery import AiogramSender
from src.application.ice_company.keyboard import inline_button
from src.application.ice_company.lifecycle import (
    ACTION_STATUS,
    _edit_dirty,
    button_rows,
    buttons_for,
    calendar_url_for,
    parse_callback,
    remember_inline_card,
    render_hash,
)
from src.application.ice_company.safety import TextRejected, clean_free_text
from src.application.ice_company.avatars import cache_telegram_avatar
from src.application.ice_company.codes import tg_participant_key
from src.application.ice_company.service import (
    CompanyRejected,
    actor_for_telegram,
    respond,
    snap_from,
    _load,
    _responses,
)
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings

logger = logging.getLogger(__name__)
router = Router(name="ice_company")


def _telegram_name(raw: str | None) -> str:
    try:
        return clean_free_text(raw, max_len=20, required=False, field="Имя")
    except TextRejected:
        return ""


@router.callback_query(F.data.startswith("ic:"))
async def on_company_callback(query: CallbackQuery) -> None:
    parsed = parse_callback(query.data or "")
    if parsed is None or query.from_user is None:
        await query.answer()
        return
    code, action = parsed
    user_id = int(query.from_user.id)
    name = _telegram_name(query.from_user.first_name) or _telegram_name(query.from_user.username)
    async with async_session_factory() as session:
        try:
            await respond(
                session,
                code=code,
                status=ACTION_STATUS.get(action, "going"),
                display_name=name or None,
                participant_key=f"tg:{user_id}",
                source="tg",
                consent=True,
                actor_hash=actor_for_telegram(user_id, None, None),
            )
        except CompanyRejected as exc:
            toast = TOAST_CLOSED if exc.status_code == 409 else str(exc.detail or "Не получилось")
            await query.answer(toast[:200], show_alert=False)
            logger.info("ice_company callback rejected status=%s", exc.status_code)
            return
        company = await _load(session, code)
        if company is not None and action == "g":
            await cache_telegram_avatar(
                session,
                query.bot,
                company_id=int(company["id"]),
                participant_key=tg_participant_key(user_id),
                telegram_user_id=user_id,
            )
            await session.commit()
        inline_id = (query.inline_message_id or "").strip()
        if inline_id:
            if company is not None:
                await remember_inline_card(
                    session,
                    company_id=int(company["id"]),
                    inline_message_id=inline_id,
                )
        else:
            logger.info("ice_company callback has no inline_message_id code=%s", code)
        kind = str(company["event_kind"]) if company is not None else ""
        await query.answer(toast_for(kind, action))
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
        from src.application.ice_company.service import ice_slot_url

        page = ice_slot_url(company, settings)
        body = card_text(snap)
        is_match = snap.kind == MATCH_KIND
        markup_buttons = buttons_for(
            company,
            snap,
            page,
            calendar_url=calendar_url_for(settings, code),
        )
    from src.application.ice_company.og import card_photo_url

    rows = []
    for group in button_rows(markup_buttons):
        row = []
        for button in group:
            row.append(inline_button(button))
        if row:
            rows.append(row)
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    # У матча карточка текстовая, как и при правке: плакат с катком ему не подходит.
    photo = None if is_match else card_photo_url(settings.webapp_base_url, code, render_hash(body, markup_buttons))
    title = "Звать на матч" if is_match else "Компания на лёд"
    if photo:
        result = InlineQueryResultPhoto(
            id=f"k{code}",
            photo_url=photo,
            thumbnail_url=photo,
            photo_width=1080,
            photo_height=1080,
            title=title,
            description=body.split("\n", 1)[0][:80],
            caption=body,
            reply_markup=markup,
        )
    else:
        result = InlineQueryResultArticle(
            id=f"k{code}",
            title=title,
            description=body.split("\n", 1)[0][:80],
            input_message_content=InputTextMessageContent(message_text=body),
            reply_markup=markup,
        )
    await query.answer([result], cache_time=1, is_personal=True)


@router.chosen_inline_result(F.result_id.regexp(r"^k?[23456789abcdefghjkmnpqrstuvwxyz]{8}$"))
async def on_company_chosen(result: ChosenInlineResult, bot: Bot) -> None:
    inline_id = (result.inline_message_id or "").strip()
    raw = result.result_id or ""
    code = raw[1:] if raw.startswith("k") else raw
    if not inline_id:
        logger.info("ice_company chosen without inline_message_id code=%s", code)
        return
    async with async_session_factory() as session:
        company = await _load(session, code)
        if company is None:
            return
        await remember_inline_card(session, company_id=int(company["id"]), inline_message_id=inline_id)
        sender = AiogramSender(bot, Settings())
        await _edit_dirty(
            session,
            sender,
            settings=Settings(),
            debounce_sec=0,
            now=datetime.now(timezone.utc),
        )
