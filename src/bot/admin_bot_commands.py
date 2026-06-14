"""Admin bot Telegram menu commands — single source for startup and /start refresh."""
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, MenuButtonCommands

ADMIN_BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="pending", description="Тренеры на модерацию"),
    BotCommand(command="trainer_welcome_link", description="Ссылка новому тренеру"),
    BotCommand(command="stats", description="Статистика платформы"),
    BotCommand(command="support", description="Обращения в поддержку"),
    BotCommand(command="dicts", description="Города и арены"),
    BotCommand(command="subscription_tiers", description="Тарифы подписки тренеров"),
    BotCommand(command="subscription_invoices", description="Счета по подписке (ERIP)"),
    BotCommand(command="grant_subscription", description="Выдать подписку тренеру"),
    BotCommand(command="collective_draft", description="Студия: черновик + claim"),
    BotCommand(command="collective_sub", description="Студия: подписка pool"),
    BotCommand(command="version", description="Версия деплоя и health API"),
    BotCommand(command="problem_reports", description="Аудит отчётов о проблемах (E6)"),
]


async def register_admin_bot_commands(bot: Bot) -> None:
    """Push command list to Telegram (default private chats + menu button)."""
    await bot.set_my_commands(ADMIN_BOT_COMMANDS, scope=BotCommandScopeAllPrivateChats())
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
