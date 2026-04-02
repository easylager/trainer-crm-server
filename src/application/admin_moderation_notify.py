"""
Notify admins (Telegram admin bot) when a trainer queues for profile moderation.
Same card shape as /pending in admin_handlers; failures are logged, never raised to callers.
"""
from __future__ import annotations

import logging
import time

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import messages as msg
from src.bot.admin_moderation_card import (
    fetch_city_name,
    format_admin_trainer_moderation_caption,
    split_photo_caption_if_needed,
)
from src.application.trainer_profile_pending import merge_profile_pending_for_editor, trainer_photo_file_key_for_moderation_ui
from src.bot.client_api import resolve_trainer_photo_bytes
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings

logger = logging.getLogger(__name__)

ADMIN_APPROVE_PREFIX = "admin:approve:"
ADMIN_REJECT_PREFIX = "admin:reject:"
ADMIN_NEEDS_EDIT_PREFIX = "admin:needs_edit:"

# Same queue stamp → skip second notify (double PATCH/submit in one flow or overlapping workers).
_dedupe_by_trainer_and_sub_at: set[tuple[int, str]] = set()
_DEDUPE_MAX_KEYS = 4096
# Fallback when moderation_submitted_at is missing (should be rare after mark_queued).
_last_notify_monotonic_by_trainer: dict[int, float] = {}
_NOTIFY_COOLDOWN_SEC = 3.5


def _moderation_submitted_at_key(sub_at: object | None) -> str:
    if sub_at is None:
        return "none"
    if hasattr(sub_at, "isoformat"):
        return sub_at.isoformat()  # type: ignore[no-any-return]
    return str(sub_at)


def _should_skip_duplicate_notify(trainer_id: int, sub_at: object | None) -> bool:
    if sub_at is not None:
        key = (trainer_id, _moderation_submitted_at_key(sub_at))
        if key in _dedupe_by_trainer_and_sub_at:
            return True
        _dedupe_by_trainer_and_sub_at.add(key)
        if len(_dedupe_by_trainer_and_sub_at) > _DEDUPE_MAX_KEYS:
            _dedupe_by_trainer_and_sub_at.clear()
        return False
    now = time.monotonic()
    last = _last_notify_monotonic_by_trainer.get(trainer_id)
    if last is not None and (now - last) < _NOTIFY_COOLDOWN_SEC:
        return True
    _last_notify_monotonic_by_trainer[trainer_id] = now
    return False


def _moderation_keyboard(trainer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
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
        ]
    )


async def notify_admins_trainer_queued_for_moderation(trainer_id: int) -> None:
    """
    Push one moderation card to each configured admin (same UX as /pending).
    Called only when try_submit_trainer_for_moderation_review actually queues (not noop duplicate).
    """
    # Lazy import avoids circular import with trainer_use_cases.
    from src.application.trainer_use_cases import get_trainer, list_trainer_education

    settings = Settings()
    token = settings.telegram_bot_token_admin
    admin_ids = list(dict.fromkeys(settings.admin_telegram_ids or []))
    if not token or not admin_ids:
        return
    async with async_session_factory() as session:
        trainer = await get_trainer(session, trainer_id)
        education_items = await list_trainer_education(session, trainer_id, public_only=False)
        city_name = None
        if trainer:
            city_name = await fetch_city_name(session, (trainer.get("profile") or {}).get("city_id"))
    if not trainer:
        return
    sub_at = trainer.get("moderation_submitted_at")
    if _should_skip_duplicate_notify(trainer_id, sub_at):
        logger.info(
            "skip duplicate moderation notify trainer_id=%s moderation_submitted_at=%s",
            trainer_id,
            _moderation_submitted_at_key(sub_at),
        )
        return
    base_caption = format_admin_trainer_moderation_caption(trainer, education_items or [], city_name=city_name)
    caption = msg.ADMIN_NOTIFY_NEW_MODERATION_PREFIX + base_caption
    profile = merge_profile_pending_for_editor(
        trainer.get("profile") if isinstance(trainer.get("profile"), dict) else {},
        trainer.get("profile_pending") if isinstance(trainer.get("profile_pending"), dict) else None,
    ) or {}
    name_plain = ((profile.get("first_name") or "") + " " + (profile.get("last_name") or "")).strip() or "—"
    file_key = trainer_photo_file_key_for_moderation_ui(trainer)
    body: bytes | None = await resolve_trainer_photo_bytes(file_key) if file_key else None
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    kb = _moderation_keyboard(trainer_id)
    photo_caption, continuation = split_photo_caption_if_needed(
        caption, trainer_id=trainer_id, name_plain=name_plain
    )
    try:
        for chat_id in admin_ids:
            try:
                if body:
                    if continuation:
                        await bot.send_photo(
                            chat_id=chat_id,
                            photo=BufferedInputFile(body, filename="photo.jpg"),
                            caption=photo_caption,
                        )
                        await bot.send_message(chat_id=chat_id, text=continuation, reply_markup=kb)
                    else:
                        await bot.send_photo(
                            chat_id=chat_id,
                            photo=BufferedInputFile(body, filename="photo.jpg"),
                            caption=photo_caption,
                            reply_markup=kb,
                        )
                else:
                    text_out = caption
                    if len(text_out) > 4090:
                        text_out = text_out[:4070] + "\n\n<i>…сообщение обрезано (лимит Telegram)</i>"
                    await bot.send_message(chat_id=chat_id, text=text_out, reply_markup=kb)
            except Exception:  # noqa: BLE001
                logger.exception("admin moderation notify failed chat_id=%s trainer_id=%s", chat_id, trainer_id)
    finally:
        await bot.session.close()
