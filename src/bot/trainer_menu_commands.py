"""
Trainer bot: command list depends on subscription tier.

- CRM+: schedule, requests, clients, passes (and /bookings legacy).
- Analytics: /stats in addition.
- No paid tier: guide, profile, subscription only.
- NOT_LINKED telegram: no commands, no Web App menu button (per-chat lockdown).
"""
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, MenuButtonCommands, MenuButtonWebApp, WebAppInfo
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.subscription_tier_use_cases import (
    get_effective_subscription_tier,
    trainer_has_analytics_access,
    trainer_has_crm_access,
)
from src.bot import messages as msg
from src.shared.config import Settings
from src.shared.mini_app_https import mini_app_https_base


def trainer_command_list(*, include_crm_features: bool, include_stats: bool) -> list[BotCommand]:
    """Commands shown in Telegram menu (left of input)."""
    cmds: list[BotCommand] = [
        BotCommand(command="guide", description="Помощь"),
        BotCommand(command="home", description="Обзор"),
        BotCommand(command="profile", description="Профиль"),
    ]
    if include_crm_features:
        cmds.extend(
            [
                BotCommand(command="editor", description="Расписание"),
                BotCommand(command="requests", description="Заявки клиентов"),
                BotCommand(command="clients", description="Мои клиенты"),
                BotCommand(command="passes", description="Абонементы/Сертификаты"),
            ]
        )
    cmds.append(BotCommand(command="subscription", description="Подписки"))
    if include_stats:
        cmds.append(BotCommand(command="stats", description="Статистика"))
    return cmds


async def trainer_menu_signature(session: AsyncSession, trainer_id: int) -> str:
    """
    Stable string for current menu (CRM block + stats). Used to detect tier changes and sync immediately.
    """
    tier = await get_effective_subscription_tier(session, trainer_id)
    include_crm = await trainer_has_crm_access(session, trainer_id)
    include_stats = await trainer_has_analytics_access(session, trainer_id)
    return f"{tier}|{int(include_crm)}|{int(include_stats)}"


async def sync_trainer_menu_commands(bot: Bot, chat_id: int, trainer_id: int, session: AsyncSession) -> None:
    """Set per-chat command list from effective subscription tier."""
    include_crm = await trainer_has_crm_access(session, trainer_id)
    include_stats = await trainer_has_analytics_access(session, trainer_id)
    await bot.set_my_commands(
        trainer_command_list(include_crm_features=include_crm, include_stats=include_stats),
        scope=BotCommandScopeChat(chat_id=chat_id),
    )


async def set_default_trainer_commands_without_stats(bot: Bot) -> None:
    """Default scope before per-chat sync: no commands until trainer is linked in this chat."""
    await bot.set_my_commands([], scope=BotCommandScopeDefault())


async def reset_trainer_menu_to_minimal(bot: Bot, chat_id: int) -> None:
    """Reset per-chat menu to minimal (onboarding) commands when trainer loses active status."""
    await bot.set_my_commands(
        trainer_command_list(include_crm_features=False, include_stats=False),
        scope=BotCommandScopeChat(chat_id=chat_id),
    )


async def reset_trainer_menu_for_unlinked(bot: Bot, chat_id: int) -> None:
    """Per-chat lockdown: no slash commands and no hub Web App button for strangers."""
    await bot.set_my_commands([], scope=BotCommandScopeChat(chat_id=chat_id))
    await bot.set_chat_menu_button(chat_id=chat_id, menu_button=MenuButtonCommands())


async def sync_trainer_hub_menu_button(bot: Bot, chat_id: int) -> None:
    """Per-chat hub button for linked trainers; commands-only fallback without HTTPS."""
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
