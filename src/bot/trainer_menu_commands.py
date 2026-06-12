"""
Trainer bot: no slash command menu — only per-chat «Обзор» Web App button to hub.

- Linked trainers: MenuButtonWebApp «Обзор» → trainer-home (requires HTTPS).
- NOT_LINKED: empty commands, commands-style menu button without hub until welcome link.
"""
from aiogram import Bot
from aiogram.types import BotCommandScopeChat, BotCommandScopeDefault, MenuButtonCommands, MenuButtonWebApp, WebAppInfo

from src.bot import messages as msg
from src.shared.config import Settings
from src.shared.mini_app_https import mini_app_https_base


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
