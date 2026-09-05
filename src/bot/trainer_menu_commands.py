"""
Trainer bot: no slash command menu — only per-chat «Обзор» Web App button to hub.

- Linked trainers: MenuButtonWebApp «Обзор» → trainer-home (requires HTTPS).
- NOT_LINKED: empty commands, commands-style menu button without hub until welcome link.
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.types import BotCommandScopeChat, BotCommandScopeDefault, MenuButtonCommands, MenuButtonWebApp, WebAppInfo

from src.application.trainer_link import (
    get_trainer_id_for_webapp_trainer_operations,
    list_linked_trainer_telegram_ids_for_hub_menu,
)
from src.bot import messages as msg
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings
from src.shared.mini_app_https import mini_app_https_base

logger = logging.getLogger(__name__)

_RESTORE_DELAY_SEC = 0.05


async def set_default_trainer_commands_without_stats(bot: Bot) -> None:
    """Default scope before per-chat sync: no commands until trainer is linked in this chat."""
    await bot.set_my_commands([], scope=BotCommandScopeDefault())


async def reset_trainer_menu_for_unlinked(bot: Bot, chat_id: int) -> None:
    """Per-chat lockdown: no slash commands and no hub Web App button for strangers."""
    await bot.set_my_commands([], scope=BotCommandScopeChat(chat_id=chat_id))
    await bot.set_chat_menu_button(chat_id=chat_id, menu_button=MenuButtonCommands())


async def sync_trainer_hub_menu_button(bot: Bot, chat_id: int) -> None:
    """Per-chat hub button for linked trainers; empty commands menu fallback without HTTPS."""
    settings = Settings()
    base, _src = mini_app_https_base(settings)
    if base:
        hub_url = f"{base.rstrip('/')}/webapp/trainer-home"
        await bot.set_chat_menu_button(
            chat_id=chat_id,
            menu_button=MenuButtonWebApp(
                text=msg.TRAINER_MENU_BUTTON_HUB,
                web_app=WebAppInfo(url=hub_url),
            ),
        )
    else:
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=MenuButtonCommands())


async def sync_trainer_linked_chat_menu(bot: Bot, chat_id: int) -> None:
    """Linked trainer chat: hide slash menu, show only «Обзор» hub Web App button."""
    await bot.set_my_commands([], scope=BotCommandScopeChat(chat_id=chat_id))
    await sync_trainer_hub_menu_button(bot, chat_id)


async def ensure_trainer_hub_menu_button(bot: Bot, chat_id: int) -> None:
    """
    Re-apply per-chat «Обзор» when Telegram drops MenuButtonWebApp (e.g. after Mini App close).

    Use after outbound trainer pushes so the hub entry returns without waiting for the next
    inbound message. chat_id for private chats equals the trainer telegram user id.
    """
    async with async_session_factory() as session:
        tid = await get_trainer_id_for_webapp_trainer_operations(session, chat_id)
    if tid:
        await sync_trainer_linked_chat_menu(bot, chat_id)


async def restore_all_linked_trainer_hub_menu_buttons(bot: Bot) -> None:
    """
    On startup after deploy: re-apply «Обзор» for every linked non-deactivated trainer.

    Telegram does not notify clients when MenuButtonWebApp is dropped; this restores hub
    access without asking trainers to message the bot or run /home.
    """
    base, src = mini_app_https_base(Settings())
    if not base:
        logger.warning("trainer_hub_menu_restore: skipped — no HTTPS mini-app base [%s]", src)
        return

    async with async_session_factory() as session:
        chat_ids = await list_linked_trainer_telegram_ids_for_hub_menu(session)

    if not chat_ids:
        logger.info("trainer_hub_menu_restore: no linked trainers")
        return

    logger.info("trainer_hub_menu_restore: restoring «Обзор» for %s linked trainers", len(chat_ids))
    ok = 0
    failed = 0
    for i, chat_id in enumerate(chat_ids):
        try:
            await sync_trainer_linked_chat_menu(bot, chat_id)
            ok += 1
        except Exception:
            failed += 1
            logger.warning("trainer_hub_menu_restore: failed chat_id=%s", chat_id, exc_info=True)
        if i + 1 < len(chat_ids):
            await asyncio.sleep(_RESTORE_DELAY_SEC)

    logger.info(
        "trainer_hub_menu_restore: done ok=%s failed=%s total=%s",
        ok,
        failed,
        len(chat_ids),
    )
