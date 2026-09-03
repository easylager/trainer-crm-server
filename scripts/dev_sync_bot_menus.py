#!/usr/bin/env python3
"""Push current WEBAPP_BASE_URL to Telegram menu buttons (client + linked trainers)."""
from __future__ import annotations

import asyncio
import sys

from aiogram import Bot
from aiogram.types import MenuButtonWebApp, WebAppInfo
from sqlalchemy import text

from src.bot import messages as msg
from src.bot.trainer_menu_commands import sync_trainer_linked_chat_menu
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings
from src.shared.mini_app_https import mini_app_https_base


async def sync_client_menu(bot: Bot, base: str) -> None:
    hub_url = f"{base.rstrip('/')}/webapp/client-home"
    await bot.set_my_commands([])
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text=msg.CLIENT_MENU_BUTTON_HUB,
            web_app=WebAppInfo(url=hub_url),
        ),
    )
    print(f"client menu -> {hub_url}")


async def sync_trainer_menus(bot: Bot) -> None:
    async with async_session_factory() as session:
        rows = await session.execute(
            text(
                """
                SELECT DISTINCT telegram_id
                FROM trainers
                WHERE telegram_id IS NOT NULL
                ORDER BY telegram_id
                """
            )
        )
        chat_ids = [int(r[0]) for r in rows.fetchall() if r[0] is not None]

    settings = Settings()
    base, _src = mini_app_https_base(settings)
    hub = f"{base}/webapp/trainer-home" if base else None

    for chat_id in chat_ids:
        await sync_trainer_linked_chat_menu(bot, chat_id)
        print(f"trainer menu chat {chat_id} -> {hub or '(no HTTPS)'}")


async def main() -> int:
    settings = Settings()
    base, src = mini_app_https_base(settings)
    if not base:
        print(f"No HTTPS base in Settings [{src}]", file=sys.stderr)
        return 1

    client_bot = Bot(token=settings.telegram_bot_token_client)
    trainer_bot = Bot(token=settings.telegram_bot_token_trainer)
    try:
        await sync_client_menu(client_bot, base)
        await sync_trainer_menus(trainer_bot)
    finally:
        await client_bot.session.close()
        await trainer_bot.session.close()

    print(f"done [{src}] base={base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
