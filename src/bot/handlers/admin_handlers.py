"""
Admin bot: moderation of trainers (approve / reject).
Shows trainer card (profile + photo) and lets admins set Trainer.status.
"""
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.application.trainer_use_cases import (
    get_trainer,
    list_trainers,
    set_trainer_moderation_feedback,
    update_trainer_status,
)
from src.bot import messages as msg
from src.bot.client_api import build_photo_url, fetch_photo_bytes
from src.infrastructure.db import async_session_factory
from src.infrastructure.db.models import TRAINER_STATUS_ACTIVE, TRAINER_STATUS_DEACTIVATED, TRAINER_STATUS_PENDING_PROFILE
from src.shared.config import Settings


router = Router(name="admin")

ADMIN_APPROVE_PREFIX = "admin:approve:"
ADMIN_REJECT_PREFIX = "admin:reject:"
ADMIN_NEEDS_EDIT_PREFIX = "admin:needs_edit:"

# In-memory state: admin user_id -> trainer_id (awaiting moderation feedback text)
_admin_awaiting_feedback: dict[int, int] = {}


def _is_admin(user_id: int | None) -> bool:
    if not user_id:
        return False
    settings = Settings()
    ids = settings.admin_telegram_ids or []
    return user_id in ids


def _format_admin_trainer_caption(trainer: dict) -> str:
    profile = trainer.get("profile") or {}
    name = ((profile.get("first_name") or "") + " " + (profile.get("last_name") or "")).strip() or "—"
    age = profile.get("age")
    age_str = str(age) if age is not None else "—"
    exp = profile.get("experience_years")
    exp_str = f"{exp} лет" if exp is not None else "не указан"
    desc = (profile.get("description") or "").strip() or "—"
    return msg.ADMIN_TRAINER_CARD.format(
        id=trainer["id"],
        name=name,
        age=age_str,
        experience=exp_str,
        description=desc,
    )


async def _send_trainer_for_moderation(message: Message, trainer_id: int) -> None:
    async with async_session_factory() as session:
        trainer = await get_trainer(session, trainer_id)
    if not trainer:
        await message.answer(f"Тренер #{trainer_id} не найден.")
        return
    caption = _format_admin_trainer_caption(trainer)
    photos = trainer.get("photos") or []
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=msg.ADMIN_BUTTON_APPROVE,
                callback_data=f"{ADMIN_APPROVE_PREFIX}{trainer_id}",
            ),
            InlineKeyboardButton(
                text=msg.ADMIN_BUTTON_REJECT,
                callback_data=f"{ADMIN_REJECT_PREFIX}{trainer_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text=msg.ADMIN_BUTTON_NEEDS_EDIT,
                callback_data=f"{ADMIN_NEEDS_EDIT_PREFIX}{trainer_id}",
            ),
        ],
    ])

    # Trainer has at most one photo (new upload replaces previous)
    file_key = photos[0]["file_key"] if photos else None
    if file_key:
        url = build_photo_url(file_key)
        if url:
            body = await fetch_photo_bytes(url)
            if body:
                try:
                    await message.answer_photo(
                        BufferedInputFile(body, filename="photo.jpg"),
                        caption=caption,
                        reply_markup=keyboard,
                    )
                    return
                except Exception:
                    pass
    await message.answer(caption, reply_markup=keyboard)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    await message.answer(msg.ADMIN_START)


@router.message(Command("pending"))
async def cmd_pending(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    async with async_session_factory() as session:
        trainers = await list_trainers(session, limit=20, offset=0, status=TRAINER_STATUS_PENDING_PROFILE)
        print(trainers)
    if not trainers:
        await message.answer(msg.ADMIN_PENDING_EMPTY)
        return
    for t in trainers:
        await _send_trainer_for_moderation(message, t["id"])


@router.callback_query(lambda c: c.data and c.data.startswith(ADMIN_APPROVE_PREFIX))
async def on_approve(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    if not _is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    trainer_id = int(callback.data[len(ADMIN_APPROVE_PREFIX) :])
    async with async_session_factory() as session:
        await set_trainer_moderation_feedback(session, trainer_id, None)
        ok = await update_trainer_status(session, trainer_id, TRAINER_STATUS_ACTIVE)
    if ok:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(msg.ADMIN_APPROVED)
    else:
        await callback.message.answer(f"Не удалось одобрить тренера #{trainer_id}.")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith(ADMIN_REJECT_PREFIX))
async def on_reject(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    if not _is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    trainer_id = int(callback.data[len(ADMIN_REJECT_PREFIX) :])
    async with async_session_factory() as session:
        ok = await update_trainer_status(session, trainer_id, TRAINER_STATUS_DEACTIVATED)
    if ok:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(msg.ADMIN_REJECTED)
    else:
        await callback.message.answer(f"Не удалось отклонить тренера #{trainer_id}.")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith(ADMIN_NEEDS_EDIT_PREFIX))
async def on_needs_edit(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    if not _is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    trainer_id = int(callback.data[len(ADMIN_NEEDS_EDIT_PREFIX) :])
    _admin_awaiting_feedback[user_id] = trainer_id
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(msg.ADMIN_NEEDS_EDIT_PROMPT)
    await callback.answer()


@router.message()
async def on_admin_message(message: Message) -> None:
    """Handle next message when admin is in 'awaiting feedback' state (plain text = feedback)."""
    user_id = message.from_user.id if message.from_user else 0
    trainer_id = _admin_awaiting_feedback.pop(user_id, None)
    if trainer_id is None:
        return
    if not _is_admin(user_id):
        return
    text = (message.text or "").strip()
    if text.lower() in ("/cancel", "отмена", "отменить"):
        await message.answer(msg.ADMIN_NEEDS_EDIT_CANCELLED)
        return
    async with async_session_factory() as session:
        await set_trainer_moderation_feedback(session, trainer_id, text or None)
        await update_trainer_status(session, trainer_id, TRAINER_STATUS_PENDING_PROFILE)
    await message.answer(msg.ADMIN_NEEDS_EDIT_DONE)

