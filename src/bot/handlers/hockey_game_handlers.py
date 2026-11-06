"""«Кто кого» в чате клиентского бота: ход кнопкой, «Следующий ход», отключение типа, выход из лиги (TASK-334 S6).

Ход — тот же ``make_pick``, что у Mini App (``hockey_notices.chat_pick``): срок закрытия проверяет сервер,
так что нажатие на старое сообщение во 2-м периоде честно отвечает «ходы закрыты».
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from src.application.hockey_leagues import leave_league
from src.application.hockey_notices import (
    CB_LEAVE,
    CB_NEXT,
    CB_OFF,
    CB_PICK,
    TYPE_CODES,
    TYPE_TITLES,
    chat_pick,
    clear_blocked,
    next_move,
    picked_buttons,
    set_type,
)
from src.infrastructure.db import async_session_factory

logger = logging.getLogger(__name__)

router = Router(name="hockey_game")

TOAST_CLOSED = "Ходы на этот матч уже закрыты"
TOAST_MISSING = "Матча уже нет"


def _markup(rows: list[list[dict]]) -> InlineKeyboardMarkup | None:
    return (
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(**b) for b in row] for row in rows])
        if rows
        else None
    )


def _current_rows(cb: CallbackQuery) -> list[list[dict]]:
    markup = getattr(cb.message, "reply_markup", None)
    if markup is None:
        return []
    return [[b.model_dump(exclude_none=True) for b in row] for row in markup.inline_keyboard]


def _is_pick(button: dict, match_id: int) -> bool:
    return str(button.get("callback_data", "")).startswith(f"{CB_PICK}:{match_id}:")


def strip_picks(rows: list[list[dict]], match_id: int) -> list[list[dict]]:
    """Без кнопок хода на этот матч — остальные (таблица, «отключить») остаются."""
    kept = [[b for b in row if not _is_pick(b, match_id)] for row in rows]
    return [row for row in kept if row]


def _without(rows: list[list[dict]], prefix: str) -> list[list[dict]]:
    kept = [[b for b in row if not str(b.get("callback_data", "")).startswith(prefix)] for row in rows]
    return [row for row in kept if row]


def mark_pick(rows: list[list[dict]], match_id: int, home: str, away: str, side: str) -> list[list[dict]]:
    out, done = [], False
    for row in rows:
        if any(_is_pick(b, match_id) for b in row):
            if not done:
                out.extend(picked_buttons(match_id, home, away, side))
                done = True
            continue
        out.append(row)
    return out


async def _edit_markup(cb: CallbackQuery, rows: list[list[dict]]) -> None:
    if cb.message is None:
        return
    try:
        await cb.message.edit_reply_markup(reply_markup=_markup(rows))
    except TelegramBadRequest:  # «message is not modified» и подобное — не ошибка для игрока
        logger.debug("kk edit_reply_markup skipped", exc_info=True)


def _display_name(cb: CallbackQuery) -> str:
    user = cb.from_user
    return (user.first_name or user.full_name or "Игрок")[:40]


@router.callback_query(F.data.startswith(f"{CB_PICK}:"))
async def on_pick(cb: CallbackQuery) -> None:
    try:
        _, _, raw_id, side = (cb.data or "").split(":")
        match_id = int(raw_id)
        if side not in ("h", "a"):
            raise ValueError(side)
    except ValueError:
        await cb.answer()
        return
    async with async_session_factory() as session:
        got = await chat_pick(
            session,
            player_key=cb.from_user.id,
            display_name=_display_name(cb),
            match_id=match_id,
            side=side,
            now=datetime.now(timezone.utc),
        )
        await session.commit()
    rows = _current_rows(cb)
    if got.status == "ok":
        team = got.home if got.side == "home" else got.away
        await cb.answer(f"Ход принят: {team}")
        await _edit_markup(cb, mark_pick(rows, match_id, got.home, got.away, got.side))
    elif got.status == "closed":
        await cb.answer(TOAST_CLOSED, show_alert=True)
        await _edit_markup(cb, strip_picks(rows, match_id))
    else:
        await cb.answer(TOAST_MISSING, show_alert=True)
        await _edit_markup(cb, strip_picks(rows, match_id))


@router.callback_query(F.data == CB_NEXT)
async def on_next(cb: CallbackQuery) -> None:
    async with async_session_factory() as session:
        await clear_blocked(session, cb.from_user.id)
        notice = await next_move(session, player_key=cb.from_user.id, now=datetime.now(timezone.utc))
        await session.commit()
    if notice is None:
        await cb.answer("Открытых матчей пока нет — загляни позже", show_alert=True)
        return
    await cb.answer()
    if cb.message is not None:
        await cb.message.answer(notice.text, reply_markup=_markup(notice.buttons))


@router.callback_query(F.data.startswith(f"{CB_OFF}:"))
async def on_off(cb: CallbackQuery) -> None:
    kind = TYPE_CODES.get((cb.data or "").rsplit(":", 1)[-1])
    if kind is None:
        await cb.answer()
        return
    async with async_session_factory() as session:
        await set_type(session, cb.from_user.id, kind, False)
        await session.commit()
    await cb.answer(f"Отключено: {TYPE_TITLES[kind]}. Остальные сообщения игры продолжат приходить.", show_alert=True)
    await _edit_markup(cb, _without(_current_rows(cb), f"{CB_OFF}:"))


@router.callback_query(F.data.startswith(f"{CB_LEAVE}:"))
async def on_leave(cb: CallbackQuery) -> None:
    try:
        league_id = int((cb.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await cb.answer()
        return
    async with async_session_factory() as session:
        try:
            await leave_league(session, league_id=league_id, player_key=cb.from_user.id)
            await session.commit()
            toast = "Готово: тебя нет в лиге"
        except (LookupError, PermissionError):
            toast = "Тебя уже нет в этой лиге"
    await cb.answer(toast, show_alert=True)
    await _edit_markup(cb, _without(_current_rows(cb), f"{CB_LEAVE}:"))
