"""
One-off founder welcome after catalog listing (same copy as notification loop).

Prod (from repo root, Railway linked):
  bash scripts/run_ice_ingest_prod_local.sh scripts/send_founder_welcome_push.py --chat-id 1304982166

Local trainer bot (.env):
  PYTHONPATH=. python scripts/send_founder_welcome_push.py --chat-id 123
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import text

from src.application.trainer_catalog_listed_invite_push_use_cases import (
    mark_catalog_listed_invite_push_sent,
)
from src.bot.trainer_catalog_listed_invite_delivery import send_trainer_catalog_listed_invite_push
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings


async def _trainer_id_for_telegram(telegram_id: int) -> int | None:
    async with async_session_factory() as session:
        r = await session.execute(
            text("SELECT id FROM trainers WHERE telegram_id = :tg"),
            {"tg": telegram_id},
        )
        row = r.fetchone()
        return int(row[0]) if row else None


async def main() -> None:
    parser = argparse.ArgumentParser(description="Send catalog-listed invite push via trainer bot")
    parser.add_argument("--chat-id", type=int, required=True, help="Telegram chat id (trainer)")
    parser.add_argument(
        "--trainer-id",
        type=int,
        default=None,
        help="Override trainer id for invite link (default: lookup by chat telegram id)",
    )
    parser.add_argument(
        "--mark-sent",
        action="store_true",
        help="Set catalog_listed_invite_push_sent_at so the loop will not duplicate",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    token = (settings.telegram_bot_token_trainer or "").strip()
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN_TRAINER not set", file=sys.stderr)
        raise SystemExit(1)

    trainer_id = args.trainer_id
    if trainer_id is None:
        trainer_id = await _trainer_id_for_telegram(args.chat_id)
    if not trainer_id:
        print("ERROR: no trainers row for this chat-id; pass --trainer-id", file=sys.stderr)
        raise SystemExit(1)

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    print(f"bot=@{me.username} trainer_id={trainer_id} chat_id={args.chat_id}")
    if args.dry_run:
        print("dry-run; not sending")
        await bot.session.close()
        return

    err = await send_trainer_catalog_listed_invite_push(
        bot, chat_id=args.chat_id, trainer_id=int(trainer_id)
    )
    if err:
        print(f"ERROR: send failed: {err}", file=sys.stderr)
        await bot.session.close()
        raise SystemExit(1)
    if args.mark_sent:
        async with async_session_factory() as session:
            await mark_catalog_listed_invite_push_sent(session, int(trainer_id))
    print("sent ok")
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
