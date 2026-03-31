"""
Trainer bot: command list depends on subscription tier.

- CRM+: schedule, requests, clients, passes (and /bookings legacy).
- Analytics: /stats in addition.
- No paid tier: guide, profile, subscription only.
"""
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.subscription_tier_use_cases import (
    get_effective_subscription_tier,
    tier_satisfies,
)
from src.infrastructure.db.models import SUBSCRIPTION_TIER_ANALYTICS, SUBSCRIPTION_TIER_CRM


def trainer_command_list(*, include_crm_features: bool, include_stats: bool) -> list[BotCommand]:
    """Commands shown in Telegram menu (left of input)."""
    cmds: list[BotCommand] = [
        BotCommand(command="guide", description="Помощь"),
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
    include_crm = tier_satisfies(tier, SUBSCRIPTION_TIER_CRM)
    include_stats = tier_satisfies(tier, SUBSCRIPTION_TIER_ANALYTICS)
    return f"{tier}|{int(include_crm)}|{int(include_stats)}"


async def sync_trainer_menu_commands(bot: Bot, chat_id: int, trainer_id: int, session: AsyncSession) -> None:
    """Set per-chat command list from effective subscription tier."""
    tier = await get_effective_subscription_tier(session, trainer_id)
    include_crm = tier_satisfies(tier, SUBSCRIPTION_TIER_CRM)
    include_stats = tier_satisfies(tier, SUBSCRIPTION_TIER_ANALYTICS)
    await bot.set_my_commands(
        trainer_command_list(include_crm_features=include_crm, include_stats=include_stats),
        scope=BotCommandScopeChat(chat_id=chat_id),
    )


async def set_default_trainer_commands_without_stats(bot: Bot) -> None:
    """Default scope before per-chat sync: minimal commands (no CRM features, no /stats)."""
    await bot.set_my_commands(
        trainer_command_list(include_crm_features=False, include_stats=False),
        scope=BotCommandScopeDefault(),
    )
