"""
Trainer bot: command list depends on subscription tier (Analytics unlocks /stats in menu).
"""
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.subscription_tier_use_cases import (
    get_effective_subscription_tier,
    tier_satisfies,
)
from src.infrastructure.db.models import SUBSCRIPTION_TIER_ANALYTICS


def trainer_command_list(include_stats: bool) -> list[BotCommand]:
    """Commands shown in Telegram menu (left of input). Stats only for Analytics tier."""
    cmds: list[BotCommand] = [
        BotCommand(command="guide", description="Помощь"),
        BotCommand(command="invite", description="Пригласить клиента"),
        BotCommand(command="profile", description="Профиль"),
        BotCommand(command="editor", description="Расписание"),
        BotCommand(command="requests", description="Заявки клиентов"),
        BotCommand(command="clients", description="Мои клиенты"),
        BotCommand(command="passes", description="Абонементы/Сертификаты"),
        BotCommand(command="subscription", description="Подписка — конструктор тарифа"),
    ]
    if include_stats:
        cmds.append(BotCommand(command="stats", description="Статистика"))
    return cmds


async def sync_trainer_menu_commands(bot: Bot, chat_id: int, trainer_id: int, session: AsyncSession) -> None:
    """Set per-chat command list: /stats only when effective tier includes Analytics."""
    tier = await get_effective_subscription_tier(session, trainer_id)
    include_stats = tier_satisfies(tier, SUBSCRIPTION_TIER_ANALYTICS)
    await bot.set_my_commands(
        trainer_command_list(include_stats),
        scope=BotCommandScopeChat(chat_id=chat_id),
    )


async def set_default_trainer_commands_without_stats(bot: Bot) -> None:
    """Default scope for chats that never received chat-specific commands (no /stats)."""
    await bot.set_my_commands(
        trainer_command_list(include_stats=False),
        scope=BotCommandScopeDefault(),
    )
