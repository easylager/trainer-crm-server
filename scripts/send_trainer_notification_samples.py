"""
Разово отправляет в Telegram превью тренерских пушей (как в notification_service, webapp, admin).

Моковые данные; callback/web_app URL — только для проверки внешнего вида кнопок.

Usage:
  python -m scripts.send_trainer_notification_samples
  python -m scripts.send_trainer_notification_samples --chat-id 123456789
  python -m scripts.send_trainer_notification_samples --dry-run
  python -m scripts.send_trainer_notification_samples --lead-mode-recovery-only --chat-id 123456789

Env (.env):
  TELEGRAM_BOT_TOKEN_TRAINER
  NOTIFY_TELEGRAM_ID  (если не передан --chat-id)
  WEBAPP_BASE_URL     (для кнопок WebApp и ссылки «Оплатить подписку»; для WebApp-кнопки нужен https)
"""
from __future__ import annotations

import argparse
import asyncio
import html
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from src.application.booking_client_no_show_notifications import _trainer_outcome_line_ru
from src.application.booking_no_show_use_cases import RESOLUTION_REDEEM, RESOLUTION_SKIP
from src.bot import messages as msg
from src.bot.handlers.trainer_handlers import (
    CONFIRM_BOOKING_PREFIX,
    DECLINE_BOOKING_PREFIX,
    FEEDBACK_BOOKING_TRAINER_PREFIX,
    REQUEST_DECLINE_PREFIX,
    REQUEST_RESPOND_PREFIX,
    TRAINER_REPEAT_WEEK_PREFIX,
    _trainer_moderation_profile_approved_reply_markup,
    _trainer_profile_footer_hint,
    _trainer_profile_keyboard,
)
from src.bot.notification_loops import _render_recovery_text
from src.bot.schedule_notifications import REQUESTS_CALLBACK
from src.application.demand_signals_use_cases import SignalsRecap
from src.application.lead_mode_recovery_use_cases import DueRecoveryNudge
from src.infrastructure.db.models import (
    RECOVERY_STEP_D0,
    RECOVERY_STEP_D3,
    RECOVERY_STEP_D14,
    RECOVERY_STEP_D30,
)
from src.shared.config import Settings

MOCK_BOOKING_ID = 900001
MOCK_REQUEST_ID = 800001
MOCK_CLIENT_TELEGRAM_ID = 123456789


def _sample_signals(
    profile_views: int,
    contact_clicks: int,
    booking_attempts_blocked: int = 0,
    *,
    catalog_favorites: int = 0,
) -> SignalsRecap:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=14)
    return SignalsRecap(
        trainer_id=1,
        window_days=14,
        since=since,
        until=now,
        profile_views=profile_views,
        contact_clicks=contact_clicks,
        booking_attempts_blocked=booking_attempts_blocked,
        catalog_favorites=catalog_favorites,
    )


def _sample_recovery_nudge(
    *,
    step: str,
    days_in_lead_mode: int,
    signals: SignalsRecap,
) -> DueRecoveryNudge:
    now = datetime.now(timezone.utc)
    last_exp = now - timedelta(days=days_in_lead_mode)
    offset = {RECOVERY_STEP_D0: 0, RECOVERY_STEP_D3: 3, RECOVERY_STEP_D14: 14, RECOVERY_STEP_D30: 30}[
        step
    ]
    return DueRecoveryNudge(
        trainer_id=1,
        trainer_telegram_id=0,
        step=step,
        days_offset=offset,
        days_in_lead_mode=days_in_lead_mode,
        last_expires_at=last_exp,
        signals=signals,
    )


async def _send_lead_mode_recovery_samples(
    bot: Bot,
    chat_id: int,
    *,
    base: str,
    webapp_https: bool,
) -> None:
    """Same rendering as run_lead_mode_recovery_loop (HTML + optional subscription WebApp button)."""
    subscription_webapp_url = (
        base + "/webapp/trainer-subscription?v=20260509" if base else None
    )
    sub_kb: InlineKeyboardMarkup | None = None
    if webapp_https and subscription_webapp_url:
        sub_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=msg.TRAINER_SUBSCRIPTION_PUSH_BTN_WEBAPP,
                        web_app=WebAppInfo(url=subscription_webapp_url),
                    ),
                ],
            ],
        )

    await bot.send_message(
        chat_id=chat_id,
        text=(
            "<b>Превью: Lead Mode recovery</b> (серия D+0 / D+3 / D+14 / D+30, как в "
            "<code>run_lead_mode_recovery_loop</code>)."
        ),
    )
    await _section(bot, chat_id, "Recovery D+0 — после trial")
    await bot.send_message(
        chat_id=chat_id,
        text=_render_recovery_text(
            _sample_recovery_nudge(
                step=RECOVERY_STEP_D0,
                days_in_lead_mode=0,
                signals=_sample_signals(0, 0),
            ),
            was_trial=True,
        ),
        reply_markup=sub_kb,
    )
    await _section(bot, chat_id, "Recovery D+0 — после оплаченного периода")
    await bot.send_message(
        chat_id=chat_id,
        text=_render_recovery_text(
            _sample_recovery_nudge(
                step=RECOVERY_STEP_D0,
                days_in_lead_mode=0,
                signals=_sample_signals(0, 0),
            ),
            was_trial=False,
        ),
        reply_markup=sub_kb,
    )

    await _section(bot, chat_id, "Recovery D+3 — есть просмотры и клики в Telegram")
    await bot.send_message(
        chat_id=chat_id,
        text=_render_recovery_text(
            _sample_recovery_nudge(
                step=RECOVERY_STEP_D3,
                days_in_lead_mode=5,
                signals=_sample_signals(23, 6),
            ),
            was_trial=False,
        ),
        reply_markup=sub_kb,
    )
    await _section(bot, chat_id, "Recovery D+3 — только просмотры (без кликов)")
    await bot.send_message(
        chat_id=chat_id,
        text=_render_recovery_text(
            _sample_recovery_nudge(
                step=RECOVERY_STEP_D3,
                days_in_lead_mode=4,
                signals=_sample_signals(12, 0),
            ),
            was_trial=False,
        ),
        reply_markup=sub_kb,
    )
    await _section(bot, chat_id, "Recovery D+3 — без сигналов (честно, без фейковых нулей)")
    await bot.send_message(
        chat_id=chat_id,
        text=_render_recovery_text(
            _sample_recovery_nudge(
                step=RECOVERY_STEP_D3,
                days_in_lead_mode=3,
                signals=_sample_signals(0, 0),
            ),
            was_trial=False,
        ),
        reply_markup=sub_kb,
    )

    await _section(bot, chat_id, "Recovery D+14 — усиленный loss framing")
    await bot.send_message(
        chat_id=chat_id,
        text=_render_recovery_text(
            _sample_recovery_nudge(
                step=RECOVERY_STEP_D14,
                days_in_lead_mode=15,
                signals=_sample_signals(41, 9, booking_attempts_blocked=2),
            ),
            was_trial=False,
        ),
        reply_markup=sub_kb,
    )

    await _section(bot, chat_id, "Recovery D+30 — последнее напоминание + сигналы")
    await bot.send_message(
        chat_id=chat_id,
        text=_render_recovery_text(
            _sample_recovery_nudge(
                step=RECOVERY_STEP_D30,
                days_in_lead_mode=31,
                signals=_sample_signals(88, 19),
            ),
            was_trial=False,
        ),
        reply_markup=sub_kb,
    )
    await _section(bot, chat_id, "Recovery D+30 — без сигналов")
    await bot.send_message(
        chat_id=chat_id,
        text=_render_recovery_text(
            _sample_recovery_nudge(
                step=RECOVERY_STEP_D30,
                days_in_lead_mode=30,
                signals=_sample_signals(0, 0),
            ),
            was_trial=False,
        ),
        reply_markup=sub_kb,
    )


def _requests_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "заявка"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "заявки"
    return "заявок"


def _section(bot: Bot, chat_id: int, title: str) -> Any:
    return bot.send_message(
        chat_id=chat_id,
        text=f"<b>━━ {html.escape(title)} ━━</b>",
    )


async def _send_profile_moderation_html(
    bot: Bot, chat_id: int, html_body: str
) -> None:
    """Same composition as admin_handlers._trainer_bot_send_html_with_profile_button."""
    kb = _trainer_profile_keyboard()
    if kb is None:
        html_body = html_body + _trainer_profile_footer_hint()
    await bot.send_message(chat_id=chat_id, text=html_body, reply_markup=kb)


async def _send_moderation_profile_approved_html(bot: Bot, chat_id: int, html_body: str) -> None:
    """Catalog approval: «Профиль» + «Статистика» (same as admin_handlers._trainer_bot_send_moderation_profile_approved)."""
    kb = _trainer_moderation_profile_approved_reply_markup()
    if kb is None:
        html_body = html_body + _trainer_profile_footer_hint()
    await bot.send_message(chat_id=chat_id, text=html_body, reply_markup=kb)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send sample trainer-bot notifications (mock data) for copy QA"
    )
    parser.add_argument(
        "--chat-id",
        type=int,
        default=None,
        help="Telegram user id (defaults to NOTIFY_TELEGRAM_ID from .env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned samples only, do not call Telegram",
    )
    parser.add_argument(
        "--lead-mode-recovery-only",
        action="store_true",
        help="Send only Lead Mode recovery nudges (D+0/D+3/D+14/D+30), not the full sample pack",
    )
    args = parser.parse_args()

    settings = Settings()
    chat_id = args.chat_id if args.chat_id is not None else settings.notify_telegram_id
    if chat_id is None:
        print("Укажите --chat-id или задайте NOTIFY_TELEGRAM_ID в .env.")
        sys.exit(1)

    base = (settings.webapp_base_url or "").rstrip("/")
    webapp_https = base.lower().startswith("https://")
    subscription_webapp_url = base + "/webapp/trainer-subscription?v=20260450" if base else None

    if args.lead_mode_recovery_only:
        planned = [
            "Lead Mode recovery: D+0 trial / D+0 paid",
            "D+3: views+clicks / views only / no signals",
            "D+14: strong loss framing",
            "D+30: last call with / without signals",
        ]
    else:
        planned = [
        "Секции-заголовки в чате",
        "Новая заявка (с комментарием / без) + клавиатура отклика",
        "Ежедневное напоминание по заявкам",
        "Новая запись + клавиатура / вариант без комментария",
        "Напоминание подтвердить запись + клавиатура",
        "Занятие завершено (HTML) + отзыв / повтор / карточка клиента",
        "Закрыто без списания абонемента",
        "Появились слоты → заявки ждут записи",
        "Подписка / триал + кнопка WebApp «Тарифы и оплата»",
        "Клиент отменил запись (с причиной / без)",
        "Отчёт о проблеме (PASS / CERT / NONE) + опционально WebApp",
        "«Клиент не пришёл» — 4 исхода + опционально WebApp",
        "Модерация образования (без ParseMode, как в админке)",
        "Модерация профиля (HTML + кнопки Профиль и Статистика)",
        "Запись подтверждена (эхо после confirm)",
        "Первая запись — rich card",
        "Подсказки «поделиться каталогом» (все варианты HTML)",
    ]
    if args.dry_run:
        for i, line in enumerate(planned, 1):
            print(f"{i:2}. {line}")
        return

    bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        if args.lead_mode_recovery_only:
            await _send_lead_mode_recovery_samples(
                bot, chat_id, base=base, webapp_https=webapp_https
            )
            await bot.send_message(
                chat_id=chat_id,
                text="<b>Готово.</b> Это все варианты серии Lead Mode recovery.",
            )
            print(f"Sent Lead Mode recovery previews to chat_id={chat_id}")
            return

        await bot.send_message(
            chat_id=chat_id,
            text=(
                "<b>Превью тренерских уведомлений</b> (мок-данные, "
                "<code>python -m scripts.send_trainer_notification_samples</code>)."
            ),
        )

        await _section(bot, chat_id, "Заявки клиентов")
        text_r = msg.TRAINER_REQUEST_NOTIFICATION.format(
            city="Минск",
            service="Персональная тренировка",
            comment="Удобно вечером после 19:00, зал у метро «Спортивная».",
        )
        await bot.send_message(
            chat_id=chat_id,
            text=text_r,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.TRAINER_BUTTON_RESPOND,
                            callback_data=f"{REQUEST_RESPOND_PREFIX}{MOCK_REQUEST_ID}",
                        ),
                        InlineKeyboardButton(
                            text=msg.TRAINER_BUTTON_DECLINE,
                            callback_data=f"{REQUEST_DECLINE_PREFIX}{MOCK_REQUEST_ID}",
                        ),
                    ],
                ]
            ),
        )
        text_rnc = msg.TRAINER_REQUEST_NOTIFICATION_NO_COMMENT.format(
            city="Гродно",
            service="Функциональный тренинг",
        )
        await bot.send_message(
            chat_id=chat_id,
            text=text_rnc,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.TRAINER_BUTTON_RESPOND,
                            callback_data=f"{REQUEST_RESPOND_PREFIX}{MOCK_REQUEST_ID + 1}",
                        ),
                        InlineKeyboardButton(
                            text=msg.TRAINER_BUTTON_DECLINE,
                            callback_data=f"{REQUEST_DECLINE_PREFIX}{MOCK_REQUEST_ID + 1}",
                        ),
                    ],
                ]
            ),
        )

        await _section(bot, chat_id, "Утренний ритуал — ежедневный обзор")
        from datetime import date, time, timedelta
        from src.bot.trainer_digest_format import (
            format_morning_digest,
            format_weekly_digest,
        )

        morning_sample = {
            "sessions": [
                {
                    "start_time": time(9, 0),
                    "end_time": time(10, 0),
                    "client_name": "Олег Петров",
                    "arena_name": "Минск-Арена",
                    "is_first_time": False,
                    "status": "confirmed",
                },
                {
                    "start_time": time(10, 30),
                    "end_time": time(11, 30),
                    "client_name": "Ирина Ковалёва",
                    "arena_name": "Минск-Арена",
                    "is_first_time": True,
                    "status": "confirmed",
                },
                {
                    "start_time": time(18, 0),
                    "end_time": time(19, 0),
                    "client_name": "Катя Смирнова",
                    "arena_name": "FootballPark",
                    "is_first_time": False,
                    "status": "pending",
                },
            ],
            "sessions_count": 3,
            "gaps": [
                {
                    "from_time": time(11, 30),
                    "to_time": time(18, 0),
                    "duration_minutes": 390,
                }
            ],
            "first_timers_count": 1,
            "pending_confirmations_count": 1,
            "pending_requests_count": 2,
            "catalog_pulse": {
                "favorites": 2,
                "contact_clicks": 4,
                "profile_views_total": 120,
            },
        }
        await bot.send_message(
            chat_id=chat_id,
            text=format_morning_digest(morning_sample),
        )

        await _section(bot, chat_id, "Воскресный обзор недели")
        today_preview = date.today()
        weekly_sample = {
            "past_week": {
                "completed_count": 8,
                "cash_cents": 24000,
                "pass_sessions_count": 3,
                "cert_cents": 5000,
            },
            "upcoming_week": {
                "sessions_count": 6,
                "empty_days": [today_preview + timedelta(days=4)],
                "heaviest_day": {"date": today_preview + timedelta(days=2), "count": 3},
                "new_clients": [
                    {"client_name": "Павел Сидоров"},
                    {"client_name": "Настя Иванова"},
                ],
            },
            "drought": {"triggered": False},
            "catalog_pulse": {
                "favorites": 5,
                "contact_clicks": 3,
                "profile_views_total": 200,
            },
        }
        await bot.send_message(
            chat_id=chat_id,
            text=format_weekly_digest(weekly_sample),
        )

        await _section(bot, chat_id, "Новая запись / напоминание подтвердить")
        kb_booking = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=msg.TRAINER_BOOKINGS_BUTTON_CONFIRM,
                        callback_data=f"{CONFIRM_BOOKING_PREFIX}{MOCK_BOOKING_ID}",
                    ),
                    InlineKeyboardButton(
                        text=msg.TRAINER_BOOKINGS_BUTTON_DECLINE,
                        callback_data=f"{DECLINE_BOOKING_PREFIX}{MOCK_BOOKING_ID}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=msg.TRAINER_BOOKINGS_BUTTON_WRITE,
                        url=f"tg://user?id={MOCK_CLIENT_TELEGRAM_ID}",
                    )
                ],
            ]
        )
        await bot.send_message(
            chat_id=chat_id,
            text=msg.TRAINER_BOOKING_NOTIFICATION.format(
                date="22.04",
                day=msg.TRAINER_DAYS[1],
                time="10:00–11:00",
                duration=60,
                client_name="Петров Пётр",
                phone="+375 29 999-88-77",
                service="Йога-стретч",
                city="Минск",
                arenas="Arena West, зал 2",
                comment="Первый раз, нужны коврики.",
            ),
            reply_markup=kb_booking,
        )
        await bot.send_message(
            chat_id=chat_id,
            text=msg.TRAINER_BOOKING_NOTIFICATION_NO_COMMENT.format(
                date="23.04",
                day=msg.TRAINER_DAYS[2],
                time="18:30–19:30",
                duration=60,
                client_name="Сидорова Анна",
                phone="—",
                service="Силовая",
                city="Минск",
                arenas="Домашняя площадка",
            ),
            reply_markup=kb_booking,
        )

        kb_rem = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=msg.TRAINER_BOOKINGS_BUTTON_CONFIRM,
                        callback_data=f"{CONFIRM_BOOKING_PREFIX}{MOCK_BOOKING_ID + 1}",
                    ),
                    InlineKeyboardButton(
                        text=msg.TRAINER_BOOKINGS_BUTTON_DECLINE,
                        callback_data=f"{DECLINE_BOOKING_PREFIX}{MOCK_BOOKING_ID + 1}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=msg.TRAINER_BOOKING_CONFIRMED_BTN_WRITE,
                        url=f"tg://user?id={MOCK_CLIENT_TELEGRAM_ID}",
                    ),
                ],
            ]
        )
        await bot.send_message(
            chat_id=chat_id,
            text=msg.TRAINER_BOOKING_CONFIRM_REMINDER.format(
                client_display="Иванов Иван (+375 29 111-22-33)",
                date="24.04",
                day=msg.TRAINER_DAYS[3],
                time="12:00",
            ),
            reply_markup=kb_rem,
        )

        await _section(bot, chat_id, "Занятие завершено (петля completed_feedback)")
        text_done = msg.format_trainer_booking_completed_html(
            client_name="Козлов Дмитрий",
            date="15.04",
            day=msg.TRAINER_DAYS[1],
            time="09:00",
            duration_minutes=60,
            service_name="Беговая подготовка",
            price_tier_label="Разовое занятие",
            arena_display="Стадион «Динамо»",
            include_quick_rebook_line=webapp_https,
        )
        rows: list[list[InlineKeyboardButton]] = []
        if webapp_https:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=msg.TRAINER_BUTTON_BOOK_AGAIN,
                        web_app=WebAppInfo(
                            url=f"{base}/webapp/schedule-editor?flow=book&client_id=1"
                        ),
                    ),
                ],
            )
        rows += [
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BUTTON_BOOK_SAME_TIME_NEXT_WEEK,
                    callback_data=f"{TRAINER_REPEAT_WEEK_PREFIX}{MOCK_BOOKING_ID}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BUTTON_LEAVE_FEEDBACK,
                    callback_data=f"{FEEDBACK_BOOKING_TRAINER_PREFIX}{MOCK_BOOKING_ID}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BOOKING_CONFIRMED_BTN_WRITE,
                    url=f"tg://user?id={MOCK_CLIENT_TELEGRAM_ID}",
                ),
            ],
        ]
        if webapp_https:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=msg.TRAINER_BUTTON_CLIENT_CARD_WEBAPP,
                        web_app=WebAppInfo(url=f"{base}/webapp/trainer-clients?client_id=1"),
                    ),
                ],
            )
        await bot.send_message(
            chat_id=chat_id,
            text=text_done,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )

        await _section(
            bot,
            chat_id,
            "То же сообщение, если абонемент не списан (хвост в конце, без второго пуша)",
        )
        text_done_no_pass = msg.format_trainer_booking_completed_html(
            client_name="Козлов Дмитрий",
            date="15.04",
            day=msg.TRAINER_DAYS[1],
            time="09:00",
            duration_minutes=60,
            service_name="Беговая подготовка",
            price_tier_label="Разовое занятие",
            arena_display="Стадион «Динамо»",
            include_quick_rebook_line=webapp_https,
            append_no_pass_notice=True,
        )
        await bot.send_message(
            chat_id=chat_id,
            text=text_done_no_pass,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )

        await _section(bot, chat_id, "Слоты появились → заявки ждут записи")
        await bot.send_message(
            chat_id=chat_id,
            text=msg.TRAINER_PENDING_BOOKING_REMINDER.format(
                count=2,
                requests_word=_requests_word(2),
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=msg.TRAINER_BUTTON_REQUESTS, callback_data=REQUESTS_CALLBACK)],
                ]
            ),
        )

        await _section(bot, chat_id, "Подписка / пробный период")
        sub_kb = None
        if webapp_https and subscription_webapp_url:
            sub_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.TRAINER_SUBSCRIPTION_PUSH_BTN_WEBAPP,
                            web_app=WebAppInfo(url=subscription_webapp_url),
                        ),
                    ],
                ]
            )
        await bot.send_message(
            chat_id=chat_id,
            text=msg.TRAINER_SUBSCRIPTION_REMINDER.format(expires_date="30.04.2026"),
            reply_markup=sub_kb,
        )
        sub_kb_trial = None
        if webapp_https and subscription_webapp_url:
            sub_kb_trial = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.TRAINER_SUBSCRIPTION_PUSH_BTN_WEBAPP,
                            web_app=WebAppInfo(url=subscription_webapp_url),
                        ),
                    ],
                ]
            )
        await bot.send_message(
            chat_id=chat_id,
            text=msg.TRAINER_SUBSCRIPTION_REMINDER_TRIAL.format(expires_date="02.05.2026"),
            reply_markup=sub_kb_trial,
        )

        await _section(bot, chat_id, "Клиент отменил запись")
        await bot.send_message(
            chat_id=chat_id,
            text=msg.TRAINER_BOOKING_CANCELLED_BY_CLIENT.format(
                client_name=html.escape("Иванов Иван"),
                date="20.04",
                day=msg.TRAINER_DAYS[6],
                time="11:00",
                reason=html.escape("Перенос на следующую неделю по работе."),
            ),
        )
        await bot.send_message(
            chat_id=chat_id,
            text=msg.TRAINER_BOOKING_CANCELLED_BY_CLIENT_NO_REASON.format(
                client_name=html.escape("Смирнова Елена"),
                date="21.04",
                day=msg.TRAINER_DAYS[0],
                time="08:00",
            ),
        )

        await _section(bot, chat_id, "Отчёт о проблеме (E5) — тренеру")
        for pc, label in (
            ("PASS", "абонемент"),
            ("CERT", "сертификат"),
            ("NONE", "без абонемента"),
        ):
            prob_text = msg.format_trainer_booking_problem_ack_html(
                client_name="Непришедший Клиент",
                preset_summary_ru="не пришёл",
                payment_class=pc,
                date="17.04",
                day=msg.TRAINER_DAYS[4],
                time="19:00",
                service_name="Групповой кроссфит",
            )
            prob_rows: list[list[InlineKeyboardButton]] = []
            if webapp_https:
                prob_rows.append(
                    [
                        InlineKeyboardButton(
                            text=msg.TRAINER_BUTTON_OPEN_SCHEDULE_PROBLEM,
                            web_app=WebAppInfo(
                                url=f"{base}/webapp/schedule-editor?open_booking={MOCK_BOOKING_ID}"
                            ),
                        ),
                    ]
                )
            prob_kb = InlineKeyboardMarkup(inline_keyboard=prob_rows) if prob_rows else None
            await bot.send_message(
                chat_id=chat_id,
                text=f"<i>Вариант: {html.escape(label)}</i>\n\n{prob_text}",
                reply_markup=prob_kb,
            )

        await _section(bot, chat_id, "Клиент не пришёл (PASS/CERT) — тренеру")
        for dr, completed, tag in (
            (RESOLUTION_SKIP, False, "skip_before"),
            (RESOLUTION_SKIP, True, "skip_after"),
            (RESOLUTION_REDEEM, False, "redeem_before"),
            (RESOLUTION_REDEEM, True, "redeem_after"),
        ):
            outcome = _trainer_outcome_line_ru(dr, completed)
            ns_text = msg.format_trainer_client_no_show_ack_html(
                client_name="Абонементный Клиент",
                outcome_line_ru=outcome,
                payment_class="PASS",
                date="18.04",
                day=msg.TRAINER_DAYS[5],
                time="07:30",
                service_name="Тренажёрный зал",
                variant=tag,
            )
            ns_rows: list[list[InlineKeyboardButton]] = []
            if webapp_https:
                ns_rows.append(
                    [
                        InlineKeyboardButton(
                            text=msg.TRAINER_BUTTON_OPEN_SCHEDULE_PROBLEM,
                            web_app=WebAppInfo(
                                url=f"{base}/webapp/schedule-editor?open_booking={MOCK_BOOKING_ID + 2}"
                            ),
                        ),
                    ]
                )
            ns_kb = InlineKeyboardMarkup(inline_keyboard=ns_rows) if ns_rows else None
            await bot.send_message(
                chat_id=chat_id,
                text=f"<i>{html.escape(tag)}</i>\n\n{ns_text}",
                reply_markup=ns_kb,
            )

        await _section(bot, chat_id, "Модерация образования (ParseMode.HTML, как в админке)")
        edu_bot = Bot(
            token=settings.telegram_bot_token_trainer,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            await edu_bot.send_message(chat_id=chat_id, text=msg.TRAINER_EDUCATION_MODERATION_APPROVED)
            await edu_bot.send_message(
                chat_id=chat_id,
                text=msg.TRAINER_EDUCATION_MODERATION_REJECTED.format(
                    reason=html.escape("Фото диплома нечитаемое — загрузите чёткое изображение.")
                ),
            )
        finally:
            await edu_bot.session.close()

        await _section(bot, chat_id, "Модерация профиля")
        fb = msg.TRAINER_PROFILE_MODERATION_FEEDBACK_PUSH.format(
            feedback=html.escape("Уточните город в профиле и добавьте фото сертификата.")
        )
        fb += msg.TRAINER_PROFILE_MODERATION_FEEDBACK_PUSH_FOOTER
        await _send_profile_moderation_html(bot, chat_id, fb)
        await _send_moderation_profile_approved_html(bot, chat_id, msg.TRAINER_MODERATION_PROFILE_APPROVED)
        await _send_profile_moderation_html(bot, chat_id, msg.TRAINER_MODERATION_PROFILE_REJECTED)

        await _section(bot, chat_id, "Подтверждение записи (ответ в чат после confirm)")
        echo1 = msg.format_trainer_booking_confirmed_echo_html(
            client_name="Новиков Артём",
            client_phone="+375 33 765-43-21",
            date="25.04",
            day=msg.TRAINER_DAYS[5],
            time="16:00",
            duration_minutes=60,
            service_name="Горные лыжи · индивидуально",
            booking_price_cents=8500,
            price_tier_label="Стандарт",
            arena_name="Снежная арена «Боровляны»",
            arena_address="Минский р-н, ул. Спортивная, 1",
        )
        echo_kb1 = msg.build_trainer_booking_confirmed_echo_reply_markup(
            webapp_base=base,
            booking_id=MOCK_BOOKING_ID,
            client_telegram_id=MOCK_CLIENT_TELEGRAM_ID,
        )
        await bot.send_message(chat_id=chat_id, text=echo1, reply_markup=echo_kb1)
        echo2 = msg.format_trainer_booking_confirmed_echo_html(
            client_name="Безтелефонный Клиент",
            client_phone=None,
            date="26.04",
            day=msg.TRAINER_DAYS[6],
            time="10:30",
            duration_minutes=45,
            service_name="Силовая",
            booking_price_cents=None,
            price_tier_label=None,
            arena_name=None,
            arena_address=None,
        )
        echo_kb2 = msg.build_trainer_booking_confirmed_echo_reply_markup(
            webapp_base=base,
            booking_id=MOCK_BOOKING_ID + 5,
            client_telegram_id=None,
        )
        await bot.send_message(chat_id=chat_id, text=echo2, reply_markup=echo_kb2)

        await _section(bot, chat_id, "Первая запись + подсказки каталога")
        rich = msg.format_trainer_first_booking_milestone_rich_html(
            client_name="Первый Клиент",
            client_phone="+375 29 000-00-01",
            date_str="27.04",
            day_label=msg.TRAINER_DAYS[0],
            time_str="12:15",
            arena_name="Фитнес-клуб «Мок»",
            arena_address="ул. Примерная, 1",
            service_name="Индивидуальная консультация",
            price_tier_label="Стандарт",
            booking_price_cents=4500,
            arena_city_name="Минск",
            duration_minutes=45,
            map_link="https://yandex.ru/maps/?text=mock",
            client_has_telegram=False,
        )
        await bot.send_message(chat_id=chat_id, text=rich)
        deep_esc = html.escape("https://t.me/mock_client_bot?start=mock")
        cat_esc = html.escape(f"{base}/webapp/catalog" if base else "https://example.com/catalog")
        await bot.send_message(
            chat_id=chat_id,
            text=msg.TRAINER_SHARE_CATALOG_TIP_BOTH_HTML.format(
                deep_link=deep_esc,
                catalog_url=cat_esc,
            ),
        )
        await bot.send_message(
            chat_id=chat_id,
            text=msg.TRAINER_SHARE_CATALOG_TIP_DEEP_ONLY_HTML.format(deep_link=deep_esc),
        )
        await bot.send_message(
            chat_id=chat_id,
            text=msg.TRAINER_SHARE_CATALOG_TIP_NO_CLIENT_BOT,
        )
        await bot.send_message(
            chat_id=chat_id,
            text=msg.TRAINER_SHARE_CATALOG_TIP_PROFILE_INCOMPLETE,
        )

        await bot.send_message(chat_id=chat_id, text="<b>Готово.</b> Проверьте формат и кнопки выше.")
        print(f"Sent trainer notification samples to chat_id={chat_id}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
