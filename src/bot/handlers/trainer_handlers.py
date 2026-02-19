"""
Trainer bot: entry only via paid link from site (t.me/bot?start=link_<token>).
No other path: unlinked users get "only for trainers via site".
"""
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.application.trainer_link import consume_link_token, get_trainer_by_telegram_id
from src.bot import messages as msg
from src.infrastructure.db import async_session_factory

router = Router(name="trainer")

START_LINK_PREFIX = "link_"


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0  # type: ignore[union-attr]
    print(f"User id: {user_id}")
    print(f"Message text: {message}")
    text = message.text or ""
    args = text.split(maxsplit=1)
    async with async_session_factory() as session:
        if len(args) > 1 and args[1].startswith(START_LINK_PREFIX):
            token = args[1].removeprefix(START_LINK_PREFIX)
            ok = await consume_link_token(session, token, user_id)
            if ok:
                await message.answer(msg.TRAINER_LINK_SUCCESS)
            else:
                await message.answer(msg.TRAINER_LINK_INVALID)
            return
        is_trainer = await get_trainer_by_telegram_id(session, user_id)
        if is_trainer:
            await message.answer(msg.TRAINER_START_WELCOME)
        else:
            await message.answer(msg.TRAINER_ONLY_VIA_SITE)


@router.message()
async def fallback(message: Message) -> None:
    await message.answer(msg.TRAINER_ONLY_VIA_SITE)
