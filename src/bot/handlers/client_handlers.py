"""
Client bot handlers: /start and catalog. Public entry; no auth.
"""
import asyncio
import logging

from aiogram import Bot, Router
from aiogram.enums import ChatAction
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.bot import messages as msg
from src.bot.client_api import build_photo_url, fetch_active_trainers, fetch_photo_bytes

logger = logging.getLogger(__name__)
router = Router(name="client")
CATALOG_CALLBACK = "catalog"


def _trainer_caption(trainer: dict) -> str:
    """Format trainer card caption from profile (name, age, experience, description)."""
    profile = trainer.get("profile") or {}
    name = (profile.get("first_name") or "") + " " + (profile.get("last_name") or "")
    name = name.strip() or "Тренер"
    age = profile.get("age")
    age_str = str(age) if age is not None else "—"
    exp = profile.get("experience_years")
    exp_str = f"{exp} лет" if exp is not None else msg.CLIENT_TRAINER_CARD_NO_EXPERIENCE
    desc = (profile.get("description") or "").strip() or "—"
    return msg.CLIENT_TRAINER_CARD.format(
        name=name,
        age=age_str,
        experience=exp_str,
        description=desc,
    )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Welcome and catalog button."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Каталог тренеров", callback_data=CATALOG_CALLBACK)],
    ])
    await message.answer(msg.CLIENT_START_WELCOME, reply_markup=keyboard)


async def _send_trainer_card(bot: Bot, chat_id: int, trainer: dict) -> None:
    """Send one trainer card: fetch photo from API, send as file (works with localhost)."""
    photos = trainer.get("photos") or []
    first_photo = photos[0] if photos else None
    file_key = first_photo.get("file_key") if first_photo else None
    photo_url = build_photo_url(file_key) if file_key else None
    caption = _trainer_caption(trainer)
    if photo_url:
        body = await fetch_photo_bytes(photo_url)
        if body:
            try:
                photo_file = BufferedInputFile(body, filename="photo.jpg")
                await bot.send_photo(chat_id=chat_id, photo=photo_file, caption=caption)
            except Exception as e:
                logger.warning("Failed to send photo for trainer %s: %s", trainer.get("id"), e)
                await bot.send_message(chat_id=chat_id, text=caption)
        else:
            await bot.send_message(chat_id=chat_id, text=caption)
    else:
        await bot.send_message(chat_id=chat_id, text=caption)


@router.callback_query(lambda c: c.data == CATALOG_CALLBACK)
async def show_catalog(callback: CallbackQuery, bot: Bot) -> None:
    """Show active trainers: loader, then header, then cards with photos in parallel."""
    await callback.answer()
    chat_id = callback.message.chat.id
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    sent = await callback.message.answer(msg.CLIENT_CATALOG_LOADING)
    trainers = await fetch_active_trainers()
    if not trainers:
        await sent.edit_text(msg.CLIENT_CATALOG_EMPTY)
        return
    await sent.edit_text(msg.CLIENT_CATALOG_HEADER)
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    await asyncio.gather(*[
        _send_trainer_card(bot, chat_id, trainer) for trainer in trainers
    ])


@router.message()
async def fallback(message: Message) -> None:
    """Any other message: hint to use /start or catalog."""
    await message.answer(msg.CLIENT_FALLBACK)
