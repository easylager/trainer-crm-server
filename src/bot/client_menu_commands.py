"""
Client bot hub menu button: single Web App button, no per-user link state (unlike the
trainer bot, every client sees the same hub).

Telegram silently drops a chat's MenuButtonWebApp back to a non-functional state after
Mini App use and never notifies the bot — see trainer_menu_commands.py, which already
defends against this for the trainer bot. This ports the same defense here.
"""
import logging

from aiogram import Bot
from aiogram.types import MenuButtonCommands, MenuButtonWebApp, WebAppInfo

from src.bot import messages as msg
from src.shared.config import Settings
from src.shared.mini_app_https import mini_app_https_base

logger = logging.getLogger(__name__)


async def sync_client_hub_menu_button(bot: Bot, chat_id: int | None = None) -> None:
    """
    Set the client bot's hub Web App menu button.

    chat_id=None (startup): sets the bot-wide default for every chat.
    chat_id=<id>: re-applies it for one chat — use on every inbound message so a chat
    where Telegram dropped the button silently recovers without waiting for a restart.
    """
    settings = Settings()
    base, src = mini_app_https_base(settings)
    if base:
        hub_url = f"{base}/webapp/client-home"
        await bot.set_chat_menu_button(
            chat_id=chat_id,
            menu_button=MenuButtonWebApp(
                text=msg.CLIENT_MENU_BUTTON_HUB,
                web_app=WebAppInfo(url=hub_url),
            ),
        )
    else:
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=MenuButtonCommands())
        logger.warning(
            "Client bot: no HTTPS — menu button = commands (empty) chat_id=%s [%s]",
            chat_id,
            src,
        )
