"""Старт сезона и превью «Лёд на выходные».

  python scripts/send_ice_forecast.py --campaign season_start --dry-run
  python scripts/send_ice_forecast.py --campaign weekly --dry-run
  python scripts/send_ice_forecast.py --campaign weekly --to 123456

Ничего не шлёт в Telegram при --dry-run. Без флага пишет в клиентский бот.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.application.ice_forecast import (
    MINSK_TZ,
    format_dry_run,
    send_ice_forecast,
)
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Рассылка старта сезона или прогноза льда")
    parser.add_argument("--campaign", choices=("season_start", "weekly"), required=True)
    parser.add_argument("--dry-run", action="store_true", help="Текст, кнопки и размер аудитории, без отправки")
    parser.add_argument("--to", type=int, default=None, dest="telegram_id", help="Превью одному telegram id")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    settings = Settings()
    today = datetime.now(MINSK_TZ).date()
    bot: Bot | None = None
    if not args.dry_run:
        token = (settings.telegram_bot_token_client or "").strip()
        if not token:
            print("ERROR: TELEGRAM_BOT_TOKEN_CLIENT not set", file=sys.stderr)
            raise SystemExit(1)
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        async with async_session_factory() as session:
            message = await send_ice_forecast(
                session,
                bot,
                args.campaign,
                settings=settings,
                on=today,
                dry_run=args.dry_run,
                only_telegram_id=args.telegram_id,
            )
            if not args.dry_run:
                await session.commit()
    finally:
        if bot is not None:
            await bot.session.close()
    if args.dry_run:
        print(format_dry_run(message, kind=args.campaign, on=today))
    elif message is None:
        print("skip: нет людных часов на выходных, сообщение не отправляется")
    else:
        who = args.telegram_id if args.telegram_id is not None else "audience"
        print(f"sent campaign={message.campaign_key} to={who} audience={message.audience_size}")


if __name__ == "__main__":
    asyncio.run(main())
