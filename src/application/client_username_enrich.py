"""
Fill missing `clients.telegram_username` via Telegram getChat (client bot).

Used by trainer mini-app list/detail so the UI can use https://t.me/username — required for
Telegram Web (`tg://user?id=` is not supported; WebApp.openTelegramLink logs «protocol is not supported»).
"""
import logging
from collections.abc import Sequence

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.config import Settings

logger = logging.getLogger(__name__)

_MAX_GET_CHAT = 32


async def persist_client_telegram_username_if_missing(
    session: AsyncSession,
    telegram_user_id: int,
    username: str | None,
) -> None:
    """Write username when Telegram exposes one and DB row still lacks it."""
    if not username or not str(username).strip():
        return
    u = str(username).strip()[:64]
    try:
        await session.execute(
            text(
                "UPDATE clients SET telegram_username = :u, updated_at = now() "
                "WHERE telegram_id = :tid "
                "AND (telegram_username IS NULL OR trim(telegram_username) = '')"
            ),
            {"u": u, "tid": telegram_user_id},
        )
    except Exception as e:
        logger.debug("persist telegram_username: update failed for tid=%s: %s", telegram_user_id, e)


async def sync_client_telegram_username_from_client_bot(
    session: AsyncSession,
    telegram_user_id: int,
) -> None:
    """
    Single-user getChat + DB backfill after bind flows.

    Client may omit `Message.from_user.username` while still having a public @handle visible via bot API.
    """
    settings = Settings()
    token = (settings.telegram_bot_token_client or "").strip()
    if not token:
        return
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        try:
            chat = await bot.get_chat(telegram_user_id)
        except Exception as e:
            logger.debug("sync username: getChat(%s) failed: %s", telegram_user_id, e)
            return
        await persist_client_telegram_username_if_missing(
            session, telegram_user_id, getattr(chat, "username", None)
        )
    finally:
        await bot.session.close()


async def enrich_booking_dicts_with_client_telegram_usernames(
    session: AsyncSession,
    bookings: Sequence[dict],
) -> None:
    """
    For rows with client_telegram_id but empty username: call getChat (client bot), update DB, mutate dicts.
    """
    if not bookings:
        return
    by_tid: dict[int, list[dict]] = {}
    for b in bookings:
        tid = b.get("client_telegram_id")
        if tid is None:
            continue
        try:
            tid_int = int(tid)
        except (TypeError, ValueError):
            continue
        un = (b.get("client_telegram_username") or "").strip()
        if un:
            continue
        by_tid.setdefault(tid_int, []).append(b)  # type: ignore[index]
    if not by_tid:
        return
    settings = Settings()
    token = (settings.telegram_bot_token_client or "").strip()
    if not token:
        return
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        n = 0
        for uid in list(by_tid.keys()):
            if n >= _MAX_GET_CHAT:
                break
            rows = by_tid[uid]
            try:
                chat = await bot.get_chat(uid)
            except Exception as e:
                logger.debug("enrich: getChat(%s) failed: %s", uid, e)
                continue
            n += 1
            username = getattr(chat, "username", None)
            if not username or not str(username).strip():
                continue
            u = str(username).strip()[:64]
            await persist_client_telegram_username_if_missing(session, uid, username)
            for row in rows:
                row["client_telegram_username"] = u
    finally:
        await bot.session.close()
