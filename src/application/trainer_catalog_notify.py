"""
Telegram pushes for catalog card state changes (TASK-140).

The whole point of the state machine is that a card cannot leave the catalog silently, so this
module is the other half of ``set_catalog_state``: every transition the trainer did **not**
initiate gets a push naming the reason and offering the one action that fixes it.

Which transitions speak, and why the rest stay quiet:

* ``→ paused`` — the trainer broke it by accident (stored phone erased, last arena removed).
  This is the push the whole task exists for.
* ``paused → published`` — the card came back on its own; without this the trainer would have
  to go and check.
* ``paused → pending_review`` — came back, but name/photo changed so it needs a look. Says so.
* ``published`` with a revision just approved — «новое фото доехало», previously silent.
* ``→ hidden`` / ``→ pending_review`` / ``→ draft`` — the trainer pressed the button a second
  ago and is looking at the screen. A push there is noise.
* ``pending_review → published`` / ``→ needs_revision`` — already covered by the moderator
  pushes in the admin bot; duplicating them would double-notify.

Quiet hours apply: none of this is urgent enough to wake anyone
(``is_trainer_push_allowed_now``). A push suppressed by quiet hours is dropped rather than
queued — the state and its reason are on the screen either way, and the daily digest picks up
a card that is still paused.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_notification_prefs import is_trainer_push_allowed_now
from src.bot import messages as msg
from src.infrastructure.db.models import (
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_PUBLISHED,
)
from src.shared.config import Settings

logger = logging.getLogger(__name__)

__all__ = [
    "notify_catalog_approved_again",
    "notify_catalog_revision_published",
    "notify_catalog_state_change",
]


def _catalog_keyboard() -> InlineKeyboardMarkup | None:
    """One button into the catalog section — the screen that shows state, reason and action."""
    base = (Settings().webapp_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_CATALOG_BTN_MINI_APP,
                    web_app=WebAppInfo(url=f"{base}/webapp/trainer-catalog"),
                )
            ]
        ]
    )


async def _trainer_telegram_id(session: AsyncSession, trainer_id: int) -> int | None:
    result = await session.execute(
        text("SELECT telegram_id FROM trainers WHERE id = :tid"), {"tid": int(trainer_id)}
    )
    row = result.fetchone()
    if not row or row[0] is None:
        return None
    return int(row[0])


async def _send(session: AsyncSession, trainer_id: int, html_body: str) -> bool:
    """Send to the trainer bot, respecting quiet hours. Returns whether it went out."""
    settings = Settings()
    if not settings.telegram_bot_token_trainer:
        return False
    telegram_id = await _trainer_telegram_id(session, trainer_id)
    if telegram_id is None:
        return False
    if not await is_trainer_push_allowed_now(session, trainer_id):
        logger.info("catalog push suppressed by quiet hours trainer_id=%s", trainer_id)
        return False
    bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await bot.send_message(
            chat_id=telegram_id, text=html_body, reply_markup=_catalog_keyboard()
        )
        return True
    except Exception:  # noqa: BLE001 — a dead chat must not fail the transition
        logger.exception("catalog push send failed trainer_id=%s", trainer_id)
        return False
    finally:
        await bot.session.close()


async def notify_catalog_state_change(
    session: AsyncSession,
    trainer_id: int,
    *,
    from_state: str | None,
    to_state: str,
    reason: str | None = None,
    reason_detail: str | None = None,
) -> bool:
    """
    Push for one transition. Returns whether a message went out.

    Called from ``set_catalog_state``; never call it directly, or the journal and the push can
    disagree about what happened.
    """
    if to_state == CATALOG_STATE_PAUSED:
        body = msg.TRAINER_CATALOG_PAUSED_PUSH.format(
            reason=(reason_detail or "Карточка больше не отвечает требованиям каталога.")
        )
        return await _send(session, trainer_id, body)

    if from_state == CATALOG_STATE_PAUSED and to_state == CATALOG_STATE_PUBLISHED:
        return await _send(session, trainer_id, msg.TRAINER_CATALOG_RESTORED_PUSH)

    if from_state == CATALOG_STATE_PAUSED and to_state == CATALOG_STATE_PENDING_REVIEW:
        return await _send(session, trainer_id, msg.TRAINER_CATALOG_RESTORED_PENDING_PUSH)

    return False


async def notify_catalog_approved_again(session: AsyncSession, trainer_id: int) -> bool:
    """
    Карточка вернулась в каталог после правок (``needs_revision`` → ``published``).

    Решение о пуше принималось по статусу аккаунта: «первая активация → поздравляем, иначе
    молчим». С TASK-140 ``status = active`` — липкая веха, поэтому у давно активного тренера,
    чью карточку модератор снял на правки и потом вернул, не срабатывала ни одна ветка: карточка
    публиковалась, а тренеру не приходило ничего.
    """
    return await _send(session, trainer_id, msg.TRAINER_CATALOG_APPROVED_AGAIN_PUSH)


async def notify_catalog_revision_published(session: AsyncSession, trainer_id: int) -> bool:
    """
    «Новое фото доехало» — a moderator approved an active trainer's pending revision.

    Not a state change (the card stayed ``published`` the whole time), so it does not travel
    through ``notify_catalog_state_change``. Re-approval used to be deliberately silent, which
    left the trainer unable to tell whether their new photo had reached clients.
    """
    return await _send(session, trainer_id, msg.TRAINER_CATALOG_REVISION_PUBLISHED_PUSH)
