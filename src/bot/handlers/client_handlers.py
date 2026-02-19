"""
Client bot: public entry. Anyone who writes /start is a client.
"""
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.bot import messages as msg

router = Router(name="client")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(msg.CLIENT_START_WELCOME)


@router.message()
async def fallback(message: Message) -> None:
    await message.answer(msg.CLIENT_FALLBACK)
