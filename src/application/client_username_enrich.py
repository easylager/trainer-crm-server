"""
Fill missing `clients.telegram_username` via Telegram getChat (client bot).

Used by trainer mini-app list/detail so the UI can use https://t.me/username — required for
Telegram Web (`tg://user?id=` is not supported; WebApp.openTelegramLink logs «protocol is not supported»).

Lists never wait for Telegram: one getChat per client without @username used to run on every
hub, schedule and clients request, in series (up to 32), and most people simply have no
username — so the same empty answer was fetched again each time. Now a list schedules a
background refresh that writes found usernames to the DB (the next request reads them from
there), and an empty or failed answer is remembered for ``_RECHECK_SECONDS``. A single card
still asks inline — one call, same memory.
"""
import asyncio
import logging
import time
from collections.abc import Iterable, Sequence

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.config import Settings

logger = logging.getLogger(__name__)

_MAX_GET_CHAT = 32
_RECHECK_SECONDS = 6 * 3600

# telegram_id -> monotonic time of the last answer without a username (per process).
_checked_without_username: dict[int, float] = {}
_in_flight: set[int] = set()
_background_tasks: set[asyncio.Task] = set()


def _recently_checked(uid: int) -> bool:
    at = _checked_without_username.get(uid)
    return at is not None and time.monotonic() - at < _RECHECK_SECONDS


def _remember_no_username(uid: int) -> None:
    _checked_without_username[uid] = time.monotonic()


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
    if settings.disable_client_telegram_username_enrich:
        return
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


def _client_bot() -> Bot | None:
    settings = Settings()
    if settings.disable_client_telegram_username_enrich:
        return None
    token = (settings.telegram_bot_token_client or "").strip()
    if not token:
        return None
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


async def _fetch_usernames(bot: Bot, uids: Iterable[int]) -> dict[int, str]:
    """getChat for each uid; remembers the ones without a username. Returns found usernames."""
    found: dict[int, str] = {}
    for uid in uids:
        try:
            chat = await bot.get_chat(uid)
        except Exception as e:
            logger.debug("enrich: getChat(%s) failed: %s", uid, e)
            _remember_no_username(uid)
            continue
        username = str(getattr(chat, "username", None) or "").strip()[:64]
        if username:
            found[uid] = username
        else:
            _remember_no_username(uid)
    return found


async def _refresh_in_background(uids: list[int]) -> None:
    from src.infrastructure.db.session import async_session_factory

    bot = _client_bot()
    if bot is None:
        return
    try:
        found = await _fetch_usernames(bot, uids)
        if found:
            async with async_session_factory() as session:
                for uid, username in found.items():
                    await persist_client_telegram_username_if_missing(session, uid, username)
                await session.commit()
    except Exception as e:
        logger.debug("enrich: background refresh failed: %s", e)
    finally:
        _in_flight.difference_update(uids)
        await bot.session.close()


async def enrich_booking_dicts_with_client_telegram_usernames(
    session: AsyncSession,
    bookings: Sequence[dict],
) -> None:
    """
    Rows with client_telegram_id but no username: a single row asks Telegram inline and is
    updated in place; a list schedules a background refresh and returns at once.
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
        if (b.get("client_telegram_username") or "").strip():
            continue
        if _recently_checked(tid_int) or tid_int in _in_flight:
            continue
        by_tid.setdefault(tid_int, []).append(b)  # type: ignore[index]
    if not by_tid:
        return

    if len(bookings) > 1:
        uids = list(by_tid)[:_MAX_GET_CHAT]
        if _client_bot_configured():
            _in_flight.update(uids)
            task = asyncio.create_task(_refresh_in_background(uids))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
        return

    bot = _client_bot()
    if bot is None:
        return
    try:
        found = await _fetch_usernames(bot, list(by_tid))
        for uid, username in found.items():
            await persist_client_telegram_username_if_missing(session, uid, username)
            for row in by_tid[uid]:
                row["client_telegram_username"] = username
    finally:
        await bot.session.close()


def _client_bot_configured() -> bool:
    settings = Settings()
    return not settings.disable_client_telegram_username_enrich and bool(
        (settings.telegram_bot_token_client or "").strip()
    )
