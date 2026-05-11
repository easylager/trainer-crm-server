"""
Отправить в клиентский бот превью всех «пушевых» клиентских уведомлений с моковыми данными.

Цель — проверить HTML, длину текста и клавиатуры (как в проде: ParseMode.HTML).

Usage:
  python -m scripts.send_client_notifications_preview
  python -m scripts.send_client_notifications_preview --chat-id 123456789

Env (.env):
  TELEGRAM_BOT_TOKEN_CLIENT
  NOTIFY_TELEGRAM_ID  (если не передан --chat-id)
  WEBAPP_BASE_URL     (опционально, https://… — тогда WebApp-кнопки как в API)
"""
from __future__ import annotations

import argparse
import asyncio
import html as html_lib
import sys
from datetime import date, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from src.bot import messages as msg
from src.shared.config import Settings

# --- Mock slot / names (визуальный превью) ---
MOCK_DATE_STR = "20.04"
MOCK_DAY = msg.TRAINER_DAYS[date(2026, 4, 20).weekday()]
MOCK_TIME = "18:30"
MOCK_DURATION = 60
MOCK_SERVICE = "Горные лыжи · индивидуально"
MOCK_ARENA = "Снежная арена «Боровляны»"
MOCK_ADDRESS = "Минский р-н, Боровляны, ул. Спортивная, 1"
MOCK_TRAINER_NAME = "Алексей Снежный"
MOCK_TRAINER_TG = 100000000  # кнопка «написать» ведёт на тестовый id — замените при необходимости
MOCK_MAP_URL = "https://yandex.by/maps/?ll=27.5590%2C53.9006&z=11"
MOCK_BOOKING_ID = 999001
MOCK_REQUEST_ID = 999002
MOCK_GROUP_NAME = "Группа выходного дня"
MOCK_PRICE_CENTS = 85_00  # 85.00 BYN
MOCK_TIER_LABEL = "Стандарт"
MOCK_RESPONDER = "Мария Лыжная"
MOCK_COMMENT = "Могу взять вас в Сб 11:00 или Вс 10:00 — напишите, что удобнее."
MOCK_DECLINE_REASON = "Перенёс личные дела, к сожалению не смогу провести этот слот."
MOCK_CLIENT_NAME = "Новиков Артём"
MOCK_CLIENT_PHONE = "+375 33 765-43-21"


def _preview_title(title: str) -> str:
    return f"<b>[Превью]</b> <i>{title}</i>"


def _client_bookings_markup(settings: Settings) -> InlineKeyboardMarkup | None:
    base = (settings.webapp_base_url or "").rstrip("/")
    if base.startswith("https://"):
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=msg.CLIENT_BOOKING_CONFIRMED_BTN_DETAILS,
                        web_app=WebAppInfo(url=f"{base}/webapp/client-bookings?open_booking={MOCK_BOOKING_ID}"),
                    ),
                ],
            ],
        )
    return None


async def _send(bot: Bot, chat_id: int, title: str, text: str, reply_markup=None) -> None:
    body = f"{_preview_title(title)}\n\n{text}"
    await bot.send_message(chat_id=chat_id, text=body, reply_markup=reply_markup)
    await asyncio.sleep(0.35)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Отправить превью клиентских уведомлений в Telegram")
    parser.add_argument(
        "--chat-id",
        type=int,
        default=None,
        help="Telegram user id (по умолчанию NOTIFY_TELEGRAM_ID из .env)",
    )
    args = parser.parse_args()

    settings = Settings()
    chat_id = args.chat_id if args.chat_id is not None else settings.notify_telegram_id
    if chat_id is None:
        print("Укажите --chat-id или задайте NOTIFY_TELEGRAM_ID в .env.")
        sys.exit(1)

    bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "<b>[Превью]</b> Пакет клиентских уведомлений (моковые данные). "
                "Ниже — типы пушей из notification_service, API и связанных модулей."
            ),
        )
        await asyncio.sleep(0.35)

        # 1–2. Напоминания (актуальный формат — format_client_booking_reminder_text)
        rem24 = msg.format_client_booking_reminder_text(
            is_soon=False,
            date=MOCK_DATE_STR,
            day=MOCK_DAY,
            time=MOCK_TIME,
            duration=MOCK_DURATION,
            service_name=MOCK_SERVICE,
            booking_price_cents=MOCK_PRICE_CENTS,
            arena_name=MOCK_ARENA,
            arena_address=MOCK_ADDRESS,
        )
        row_rem = [
            [
                InlineKeyboardButton(
                    text=msg.CLIENT_REMINDER_BTN_WRITE_TRAINER,
                    url=f"tg://user?id={MOCK_TRAINER_TG}",
                ),
            ],
            [InlineKeyboardButton(text=msg.CLIENT_REMINDER_BTN_SHOW_ON_MAP, url=MOCK_MAP_URL)],
        ]
        await _send(
            bot,
            chat_id,
            "Напоминание (~за сутки / не «скоро»)",
            rem24,
            InlineKeyboardMarkup(inline_keyboard=row_rem),
        )

        rem2h = msg.format_client_booking_reminder_text(
            is_soon=True,
            date=MOCK_DATE_STR,
            day=MOCK_DAY,
            time=MOCK_TIME,
            duration=MOCK_DURATION,
            service_name=MOCK_SERVICE,
            booking_price_cents=None,
            arena_name=MOCK_ARENA,
            arena_address=MOCK_ADDRESS,
        )
        row_rem_2h = [
            InlineKeyboardButton(
                text=msg.CLIENT_REMINDER_BTN_WRITE_TRAINER,
                url=f"tg://user?id={MOCK_TRAINER_TG}",
            ),
        ]
        await _send(bot, chat_id, "Напоминание («скоро» / ~2ч)", rem2h, InlineKeyboardMarkup(inline_keyboard=[row_rem_2h]))

        # 3. Групповое RSVP
        rsvp_text = msg.CLIENT_GROUP_RSVP_INVITE.format(
            group=MOCK_GROUP_NAME,
            date=MOCK_DATE_STR,
            day=MOCK_DAY,
            time=MOCK_TIME,
            duration=MOCK_DURATION,
        )
        await _send(
            bot,
            chat_id,
            "Группа: приглашение подтвердить приход",
            rsvp_text,
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.GROUP_RSVP_BUTTON_YES,
                            callback_data=f"RSY:0:preview",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text=msg.GROUP_RSVP_BUTTON_NO,
                            callback_data=f"RSN:0:preview",
                        ),
                    ],
                ],
            ),
        )

        # 4. Занятие завершено (+ кнопки как в цикле при «слот свободен на +7д»)
        completed = msg.format_client_booking_completed_notice_html(
            date=MOCK_DATE_STR,
            day=MOCK_DAY,
            time=MOCK_TIME,
            duration_minutes=MOCK_DURATION,
            trainer_name=MOCK_TRAINER_NAME,
            service_name=MOCK_SERVICE,
        )
        kb_completed = msg.build_client_booking_completed_inline_keyboard(
            webapp_base_url=(settings.webapp_base_url or ""),
            trainer_id=1,
            booking_id=MOCK_BOOKING_ID,
            trainer_telegram_id=MOCK_TRAINER_TG,
            show_repeat_row=True,
        )
        await _send(bot, chat_id, "Занятие завершено", completed, kb_completed)

        # 5–6. Отмены
        await _send(
            bot,
            chat_id,
            "Отмена тренером",
            msg.CLIENT_BOOKING_CANCELLED_BY_TRAINER.format(
                date=MOCK_DATE_STR, day=MOCK_DAY, time=MOCK_TIME
            ),
        )
        cancel_self_kb = msg.build_client_rebook_catalog_keyboard(webapp_base_url=settings.webapp_base_url)
        await _send(
            bot,
            chat_id,
            "Отмена клиентом (Mini App)",
            msg.CLIENT_BOOKING_CANCELLED_BY_SELF.format(
                date=MOCK_DATE_STR, day=MOCK_DAY, time=MOCK_TIME
            ),
            cancel_self_kb,
        )

        # 7–8. Отклики по заявке
        base = (settings.webapp_base_url or "").rstrip("/")
        if base.startswith("https://"):
            kb_resp = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.CLIENT_RESPONSE_BUTTON_VIEW,
                            web_app=WebAppInfo(url=f"{base}/webapp/client-requests?request_id={MOCK_REQUEST_ID}"),
                        ),
                    ],
                ],
            )
        else:
            kb_resp = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.CLIENT_RESPONSE_BUTTON_VIEW,
                            callback_data=f"my_request:{MOCK_REQUEST_ID}",
                        ),
                    ],
                ],
            )
        await _send(bot, chat_id, "Отклик (без комментария)", msg.CLIENT_RESPONSE_NOTIFICATION, kb_resp)
        await _send(
            bot,
            chat_id,
            "Отклик (с комментарием)",
            msg.CLIENT_RESPONSE_NOTIFICATION_WITH_COMMENT.format(
                responder_name=MOCK_RESPONDER,
                comment=MOCK_COMMENT,
            ),
            kb_resp,
        )

        # 9. Напоминание «пока без откликов»
        nr_kb = msg.build_client_no_response_catalog_keyboard(webapp_base_url=settings.webapp_base_url)
        await _send(bot, chat_id, "Заявка: без откликов (напоминание)", msg.CLIENT_NO_RESPONSE_REMINDER, nr_kb)

        # 10. Тренер записал клиента
        await _send(
            bot,
            chat_id,
            "Вас записали на занятие",
            msg.CLIENT_TRAINER_BOOKED_YOU.format(
                name=MOCK_TRAINER_NAME,
                date=MOCK_DATE_STR,
                day=MOCK_DAY,
                time=MOCK_TIME,
            ),
        )

        # 11–13. Неактивность
        base_prev = (settings.webapp_base_url or "").rstrip("/")
        if base_prev.lower().startswith("https://"):
            kb_cat = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.CLIENT_INACTIVE_BTN_BOOK_NOW,
                            web_app=WebAppInfo(url=f"{base_prev}/webapp/catalog"),
                        ),
                    ],
                ],
            )
        else:
            kb_cat = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=msg.CLIENT_BUTTON_BOOK, callback_data="catalog")]],
            )
        await _send(
            bot,
            chat_id,
            "Неактивность 10 дней (без имени)",
            msg.CLIENT_INACTIVE_10_DAYS.format(name=""),
            kb_cat,
        )
        await _send(
            bot,
            chat_id,
            "Неактивность 10 дней (с именем)",
            msg.CLIENT_INACTIVE_10_DAYS.format(name=", Иван"),
            kb_cat,
        )
        await _send(
            bot,
            chat_id,
            "Неактивность 30 дней",
            msg.CLIENT_INACTIVE_30_DAYS.format(name=""),
            kb_cat,
        )

        # 14–15. Подтверждение записи
        confirmed_plain = msg.format_client_booking_confirmed_by_trainer_text(
            date=MOCK_DATE_STR,
            day=MOCK_DAY,
            time=MOCK_TIME,
            trainer_name=MOCK_TRAINER_NAME,
            service_name=MOCK_SERVICE,
            booking_price_cents=MOCK_PRICE_CENTS,
            price_tier_label=MOCK_TIER_LABEL,
            arena_name=MOCK_ARENA,
            arena_address=MOCK_ADDRESS,
            trainer_first_booking_milestone=False,
            client_display_name=MOCK_CLIENT_NAME,
            client_phone=MOCK_CLIENT_PHONE,
            duration_minutes=MOCK_DURATION,
        )
        kb_conf = msg.build_client_booking_confirmed_inline_keyboard(
            map_url=MOCK_MAP_URL,
            trainer_telegram_id=MOCK_TRAINER_TG,
            booking_id=MOCK_BOOKING_ID,
            webapp_base_url=settings.webapp_base_url,
        )
        await _send(bot, chat_id, "Запись подтверждена", confirmed_plain, kb_conf)

        confirmed_first = msg.format_client_booking_confirmed_by_trainer_text(
            date=MOCK_DATE_STR,
            day=MOCK_DAY,
            time=MOCK_TIME,
            trainer_name=MOCK_TRAINER_NAME,
            service_name=MOCK_SERVICE,
            booking_price_cents=7500,
            price_tier_label=None,
            arena_name=None,
            arena_address=None,
            trainer_first_booking_milestone=True,
            client_display_name=MOCK_CLIENT_NAME,
            client_phone=None,
            duration_minutes=MOCK_DURATION,
        )
        await _send(
            bot,
            chat_id,
            "Подтверждение + «первая запись тренера» (без телефона в тексте)",
            confirmed_first,
            kb_conf,
        )

        # 16. Отклонение записи
        decl_kb_prev = msg.build_client_declined_booking_catalog_keyboard(
            webapp_base_url=settings.webapp_base_url,
        )
        await _send(
            bot,
            chat_id,
            "Запись отклонена тренером",
            msg.format_client_booking_declined_by_trainer_html(
                date=MOCK_DATE_STR,
                day=MOCK_DAY,
                time=MOCK_TIME,
                reason=MOCK_DECLINE_REASON,
            ),
            decl_kb_prev,
        )

        # 17–18. Абонемент выдан
        pass_kb_base = (settings.api_base_url or settings.webapp_base_url or "").rstrip("/")
        pass_kb = None
        if pass_kb_base.startswith("https://"):
            pass_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.CLIENT_BUTTON_BOOK,
                            web_app=WebAppInfo(url=f"{pass_kb_base}/webapp/catalog"),
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text=msg.CLIENT_BUTTON_MY_PASSES_AND_CERTIFICATES,
                            web_app=WebAppInfo(url=f"{pass_kb_base}/webapp/client-passes-certificates"),
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text=msg.CLIENT_PASS_ISSUED_BTN_TERMS,
                            web_app=WebAppInfo(url=f"{pass_kb_base}/webapp/client-passes-certificates"),
                        ),
                    ],
                ],
            )
        pass_with_svc = msg.format_client_pass_issued_html(
            product_name="Пакет «Старт»",
            sessions_total=8,
            sessions_remaining=8,
            trainer_name=MOCK_TRAINER_NAME,
            service_names=[MOCK_SERVICE],
        )
        await _send(bot, chat_id, "Абонемент выдан (на услугу)", pass_with_svc, pass_kb)
        pass_all = msg.format_client_pass_issued_html(
            product_name="Пакет «Всё включено»",
            sessions_total=5,
            sessions_remaining=3,
            trainer_name=MOCK_TRAINER_NAME,
            service_names=[],
        )
        pass_multi = msg.format_client_pass_issued_html(
            product_name="Пакет «Комби»",
            sessions_total=10,
            sessions_remaining=10,
            trainer_name=MOCK_TRAINER_NAME,
            service_names=["Йога", "Пилатес"],
        )
        await _send(bot, chat_id, "Абонемент выдан (на все услуги)", pass_all, pass_kb)
        await _send(bot, chat_id, "Абонемент выдан (несколько услуг)", pass_multi, pass_kb)

        # 19. Отчёт о проблеме (клиент)
        problem = msg.format_client_booking_problem_notice_html(
            date=MOCK_DATE_STR,
            day=MOCK_DAY,
            time=MOCK_TIME,
        )
        await _send(
            bot,
            chat_id,
            "Тренер обновил запись (важное изменение)",
            problem,
            _client_bookings_markup(settings),
        )

        # 20–27. «Клиент не пришёл» — все варианты текста
        for variant in ("skip_before", "skip_after", "redeem_before", "redeem_after"):
            for pc in ("PASS", "CERT"):
                no_show = msg.format_client_booking_no_show_notice_html(
                    variant=variant,
                    payment_class=pc,
                    date=MOCK_DATE_STR,
                    day=MOCK_DAY,
                    time=MOCK_TIME,
                    service_name=MOCK_SERVICE,
                )
                await _send(
                    bot,
                    chat_id,
                    f"Не пришёл: {variant} / {pc}",
                    no_show,
                    _client_bookings_markup(settings),
                )

        # 28. Серия группы — расписание обновлено
        rules = [
            {"day_of_week": 5, "start_time": time(10, 0), "duration_minutes": 90},
            {"day_of_week": 6, "start_time": time(9, 0), "duration_minutes": 90},
        ]
        series = msg.format_client_group_series_schedule_updated_html(
            trainer_name=MOCK_TRAINER_NAME,
            group_name=MOCK_GROUP_NAME,
            service_name=MOCK_SERVICE,
            arena_name=MOCK_ARENA,
            season_start_date="03.05.2026",
            rules=rules,
        )
        await _send(bot, chat_id, "Групповой поток: обновлено расписание", series)

        # 29. Свободное окно (ожидание слота)
        slot_free = msg.CLIENT_SLOT_AVAILABLE.format(
            date=MOCK_DATE_STR,
            day=MOCK_DAY,
            time=MOCK_TIME,
            trainer_name=MOCK_TRAINER_NAME,
        )
        await _send(
            bot,
            chat_id,
            "Свободное окно (уведомление о слоте)",
            slot_free,
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.CLIENT_BUTTON_BOOK_THIS_SLOT,
                            callback_data="book_available_slot:0",
                        ),
                    ],
                ],
            ),
        )

        # 30–33. Шаблоны из воронки / welcome (часто видит клиент)
        await _send(
            bot,
            chat_id,
            "Сертификат выдан (шаблон)",
            msg.CLIENT_CERTIFICATE_ISSUED.format(
                amount_display="150 BYN",
                code="MOCK-CERT-001",
                trainer_name=MOCK_TRAINER_NAME,
            ),
        )
        cert_bound_preview = msg.format_client_certificate_bound_html(
            amount_display="150 BYN",
            code="MOCK-CERT-001",
            trainer_name=MOCK_TRAINER_NAME,
        )
        await _send(bot, chat_id, "Сертификат привязан (deep link)", cert_bound_preview)
        welcome_cta = msg.CLIENT_WELCOME_INVITE_CTA_WEBAPP
        await _send(
            bot,
            chat_id,
            "Приглашение по ссылке тренера",
            msg.CLIENT_WELCOME_INVITE.format(name=html_lib.escape(MOCK_TRAINER_NAME), cta=welcome_cta),
        )
        await _send(
            bot,
            chat_id,
            "Приглашение (абонемент / welcome)",
            msg.CLIENT_PASS_WELCOME.format(name=html_lib.escape(MOCK_TRAINER_NAME)),
        )
        book_ok = (
            f"{msg.CLIENT_BOOK_SUCCESS.format(date=MOCK_DATE_STR, day=MOCK_DAY, time=MOCK_TIME, duration=MOCK_DURATION)}\n\n"
            f"{msg.CLIENT_BOOK_WHAT_NEXT}\n\n{msg.CLIENT_BOOK_SUCCESS_HINT}"
        )
        await _send(bot, chat_id, "Успешная запись из каталога (цепочка)", book_ok)

        await bot.send_message(
            chat_id=chat_id,
            text="<b>[Превью]</b> Готово. Если чего-то не хватает — добавьте кейс в <code>scripts/send_client_notifications_preview.py</code>.",
        )
        print(f"Отправлено в chat_id={chat_id}.")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
