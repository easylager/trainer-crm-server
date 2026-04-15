"""
Отправить в Telegram превью уведомлений «первая запись» + подсказка про ссылку (как в тренерском боте).

Использует тот же токен, что и тренерский бот, и ParseMode.HTML — формат как у
`_send_first_booking_milestone_followups` в trainer_handlers.

Usage:
  python -m scripts.send_first_booking_milestone_preview
  python -m scripts.send_first_booking_milestone_preview --chat-id 123456789
  python -m scripts.send_first_booking_milestone_preview --all-variants

Env (.env):
  TELEGRAM_BOT_TOKEN_TRAINER
  NOTIFY_TELEGRAM_ID  (если не передан --chat-id)
"""
from __future__ import annotations

import argparse
import asyncio
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.bot import messages as msg
from src.shared.config import Settings

# Моковые URL только для визуального превью (не рабочие deep link / каталог).
MOCK_DEEP_LINK = "https://t.me/your_client_bot?start=mock_city_1_service_2_trainer_42"
MOCK_CATALOG_URL = "https://your-api.example/webapp/catalog"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Preview first-booking milestone messages in Telegram")
    parser.add_argument(
        "--chat-id",
        type=int,
        default=None,
        help="Telegram user id (defaults to NOTIFY_TELEGRAM_ID from .env)",
    )
    parser.add_argument(
        "--all-variants",
        action="store_true",
        help="Also send deep-only, no-bot, and profile-incomplete fallback texts",
    )
    args = parser.parse_args()

    settings = Settings()
    chat_id = args.chat_id if args.chat_id is not None else settings.notify_telegram_id
    if chat_id is None:
        print("Укажите --chat-id или задайте NOTIFY_TELEGRAM_ID в .env (ваш Telegram user id).")
        sys.exit(1)

    bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    await bot.send_message(
        chat_id=chat_id,
        text=(
            "<i>Превью (мок): первая подтверждённая запись — как в боте после записи/подтверждения.</i>"
        ),
    )

    rich = msg.format_trainer_first_booking_milestone_rich_html(
        client_name="Иванов Иван Иванович",
        client_phone="+375 29 123-45-67",
        date_str="18.05",
        day_label="Вс",
        time_str="10:00",
        arena_name="Зал «Олимп»",
        arena_address="г. Минск, пр. Независимости, 95",
        service_name="Персональная тренировка",
        price_tier_label="Взрослый",
        booking_price_cents=5000,
    )
    await bot.send_message(chat_id=chat_id, text=rich)

    deep_esc = html.escape(MOCK_DEEP_LINK)
    cat_esc = html.escape(MOCK_CATALOG_URL)
    tip_both = msg.TRAINER_SHARE_CATALOG_TIP_BOTH_HTML.format(deep_link=deep_esc, catalog_url=cat_esc)
    await bot.send_message(chat_id=chat_id, text=tip_both)

    if args.all_variants:
        tip_deep = msg.TRAINER_SHARE_CATALOG_TIP_DEEP_ONLY_HTML.format(deep_link=deep_esc)
        await bot.send_message(
            chat_id=chat_id,
            text="<i>--- вариант: только deep link (нет HTTPS каталога) ---</i>\n\n" + tip_deep,
        )
        await bot.send_message(
            chat_id=chat_id,
            text="<i>--- fallback: нет CLIENT_BOT_USERNAME ---</i>\n\n" + msg.TRAINER_SHARE_CATALOG_TIP_NO_CLIENT_BOT,
        )
        await bot.send_message(
            chat_id=chat_id,
            text="<i>--- fallback: нет города/услуги в профиле ---</i>\n\n" + msg.TRAINER_SHARE_CATALOG_TIP_PROFILE_INCOMPLETE,
        )

    await bot.session.close()
    print("Отправлено в чат", chat_id, "(тренерский бот).")


if __name__ == "__main__":
    asyncio.run(main())
