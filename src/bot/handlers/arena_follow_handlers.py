"""Deep link ``/start follow_<arena_id>``, «Не следить» и «Следить дальше» (TASK-213).

Роутер подключается раньше общего клиентского: чужие ``/start`` сюда не попадают.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import BaseFilter, Command, CommandStart
from aiogram.types import CallbackQuery, Message

from src.application.arena_follows import (
    CB_KEEP_PREFIX,
    CB_UNFOLLOW_PREFIX,
    keep_following,
    looks_like_follow_start,
    open_follow_from_start,
    parse_follow_callback_arena_id,
    unfollow_arena,
    unfollow_command,
)
from src.bot.arena_follow_keyboards import follow_reply_markup
from src.infrastructure.db.session import async_session_factory
from src.shared.config import Settings

router = Router(name="arena_follow")


class _FollowStart(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        parts = (message.text or "").strip().split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""
        return looks_like_follow_start(payload)


def _payload(message: Message) -> str:
    parts = (message.text or "").strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _telegram_id(message: Message | CallbackQuery) -> int:
    user = message.from_user
    return int(user.id) if user is not None else 0


async def _send(message: Message, text: str, buttons) -> None:
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=follow_reply_markup(buttons))


@router.message(CommandStart(), _FollowStart())
async def cmd_follow_start(message: Message) -> None:
    telegram_id = _telegram_id(message)
    if telegram_id <= 0:
        await message.answer("Не получилось понять, кто написал. Откройте ссылку ещё раз.")
        return
    async with async_session_factory() as session:
        reply = await open_follow_from_start(
            session,
            telegram_id=telegram_id,
            payload=_payload(message),
            webapp_base_url=Settings().webapp_base_url,
        )
    await _send(message, reply.text, reply.buttons)


@router.message(Command("unfollow"))
async def cmd_unfollow(message: Message) -> None:
    telegram_id = _telegram_id(message)
    if telegram_id <= 0:
        return
    async with async_session_factory() as session:
        reply = await unfollow_command(session, telegram_id=telegram_id)
    await _send(message, reply.text, reply.buttons)


@router.callback_query(F.data.startswith(CB_UNFOLLOW_PREFIX))
async def cb_unfollow(callback: CallbackQuery) -> None:
    arena_id = parse_follow_callback_arena_id(callback.data, CB_UNFOLLOW_PREFIX)
    telegram_id = _telegram_id(callback)
    if arena_id is None or telegram_id <= 0:
        await callback.answer("Не получилось отписаться.")
        return
    async with async_session_factory() as session:
        reply = await unfollow_arena(session, telegram_id=telegram_id, arena_id=arena_id, via="button")
    await callback.answer("Готово")
    if callback.message is not None:
        await callback.message.answer(reply.text, parse_mode=ParseMode.HTML)


@router.callback_query(F.data.startswith(CB_KEEP_PREFIX))
async def cb_keep(callback: CallbackQuery) -> None:
    arena_id = parse_follow_callback_arena_id(callback.data, CB_KEEP_PREFIX)
    telegram_id = _telegram_id(callback)
    if arena_id is None or telegram_id <= 0:
        await callback.answer("Не получилось.")
        return
    async with async_session_factory() as session:
        reply = await keep_following(
            session,
            telegram_id=telegram_id,
            arena_id=arena_id,
            webapp_base_url=Settings().webapp_base_url,
        )
    await callback.answer("Следим дальше")
    if callback.message is not None:
        await callback.message.answer(
            reply.text,
            parse_mode=ParseMode.HTML,
            reply_markup=follow_reply_markup(reply.buttons),
        )
