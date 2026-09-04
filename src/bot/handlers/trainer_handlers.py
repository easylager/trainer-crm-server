"""
Trainer bot: entry only via paid link from site (t.me/bot?start=link_<token>).
Schedule: by calendar week (this/next). Template for quick apply; add slots to a specific week.
"""
import asyncio
import html
import logging
from datetime import date, datetime, time, timedelta
from itertools import groupby

from aiogram.exceptions import TelegramBadRequest
from aiogram import Bot, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from src.application.booking_payment_notice import classify_booking_expected_payment_class
from src.application.booking_use_cases import (
    cancel_booking,
    confirm_booking,
    create_booking,
    decline_booking,
    format_trainer_reminder_plan_for_client_day,
    generate_reminders_for_booking,
    get_booking_for_trainer_feedback,
    get_booking_milestone_display_for_trainer,
    get_trainer_client_for_card,
    get_booking_with_slot,
    get_first_service_id_for_trainer,
    list_trainer_service_price_variants,
    get_trainer_booking_detail_payload,
    get_trainer_default_city_and_service,
    is_slot_end_in_past_local,
    list_bookings_for_trainer,
    list_trainer_clients,
    set_booking_trainer_review,
    trainer_has_access_to_client,
    trainer_repeat_booking_same_time_next_week,
)
from src.application.client_dossier_use_cases import add_client_entry_with_date
from src.application.trainer_client_invite_tracking import record_trainer_client_invite_link_first_copy
from src.application.trainer_invite_links import build_trainer_invite_links, build_trainer_universal_invite_link
from src.application.recurring_use_cases import (
    apply_recurring_bookings_for_week,
    cancel_recurring_client_slot,
    create_recurring_client_slot,
    get_active_recurring_for_booking,
    maintain_recurring_horizon,
)
from src.application.client_request_use_cases import (
    add_trainer_pending_request_booking,
    clear_trainer_pending_request_booking,
    create_request_decline,
    create_request_response,
    get_client_request_notification_payload_for_trainer,
    get_request_client_for_trainer_booking,
    list_requests_for_trainer,
)
from src.application.stats_use_cases import get_trainer_stats
from src.application.subscription_use_cases import ensure_trainer_welcome_trial
from src.application.subscription_tier_use_cases import (
    format_subscription_label,
    get_trainer_subscription_status,
    trainer_has_analytics_access,
    trainer_has_crm_access,
)
from src.application.trainer_access_state import (
    TrainerAccessState,
    get_trainer_access_state,
    trainer_may_use_bot_workflows,
)
from src.application.trainer_link import consume_link_token, get_trainer_id_for_webapp_trainer_operations
from src.application.referral_use_cases import (
    get_trainer_id_by_referral_code,
    record_referral_attribution,
)
from src.application.trainer_use_cases import get_trainer
from src.application.support_use_cases import create_support_message
from src.infrastructure.db.models import SUPPORT_FROM_TRAINER
from src.shared.audit import ACTOR_TRAINER_BOT, audit_log
from src.shared.byr_currency_display import format_rubles_byn_display
from src.shared.validation import MAX_COMMENT_LEN, MAX_REVIEW_LEN, safe_parse_id, truncate_text
from src.application.trainer_schedule_use_cases import (
    add_template,
    delete_slot,
    delete_template,
    get_slot,
    list_slots,
    list_templates,
    next_week_monday,
    replace_slots_for_day,
    replace_templates_for_day,
    replace_week_with_template,
    this_week_monday,
)
from src.application.trainer_client_relay_use_cases import (
    close_relay_session,
    open_relay_session,
    relay_session_context_for_id,
    sanitize_relay_body,
)
from src.application.trainer_relay_delivery import send_client_plain_notification, sweep_idle_relay_sessions_and_notify
from src.bot.handlers.relay_handlers import deliver_trainer_pending_relay_reply
from src.bot import messages as msg
from src.bot.trainer_cancel_client_notify import send_trainer_cancel_notification_for_booking_now
from src.bot.trainer_bot_state import (
    clear_trainer_relay_reply_pending,
    peek_trainer_relay_reply_pending,
    set_trainer_relay_reply_pending,
    trainer_booking_decline_awaiting,
    trainer_booking_note_awaiting,
    trainer_support_awaiting,
)
from src.bot.trainer_gate_text import trainer_first_link_onboarding_html, trainer_gate_message
from src.bot.trainer_menu_commands import sync_trainer_linked_chat_menu
from src.bot.share_catalog_tip import send_trainer_share_catalog_tip_to_chat
from src.shared.config import Settings
from src.shared.notification_hours import NOTIFICATION_TZ

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]
from src.bot.schedule_notifications import run_after_schedule_changed
from src.infrastructure.db import async_session_factory

# Модульный логгер: использовался в этом файле, но нигде не определялся —
# любая ветка с logger.warning падала бы с NameError.
logger = logging.getLogger(__name__)

router = Router(name="trainer")

# Telegram: remove stale reply keyboard (cannot combine with InlineKeyboardMarkup in one message).
_REPLY_KEYBOARD_CLEAR = "\u200b"


def _format_trainer_client_row_display_name(client_row: dict | None) -> str:
    """CRM-style full label: имя, отчество, фамилия (пропуски убираются)."""
    if not client_row:
        return "Клиент"
    parts = [
        (client_row.get("first_name") or "").strip(),
        (client_row.get("middle_name") or "").strip(),
        (client_row.get("last_name") or "").strip(),
    ]
    name = " ".join(p for p in parts if p)
    return name or "Клиент"


def _format_expires_ru_from_iso(iso_dt: str | None) -> str:
    """DD.MM.YYYY for subscription API timestamps (UTC ISO)."""
    if not iso_dt or not str(iso_dt).strip():
        return "—"
    s = str(iso_dt).strip()
    day = s[:10]
    try:
        y, m, d = day.split("-")
        return f"{d}.{m}.{y}"
    except Exception:
        return day


def _trial_welcome_labels(sub_st: dict) -> tuple[str, str] | None:
    """Tier label + expiry for welcome trial message, or None if trial should not be announced."""
    if not (
        sub_st.get("is_active")
        and sub_st.get("is_trial")
        and (sub_st.get("effective_tier") or "none") != "none"
    ):
        return None
    tier_label = (sub_st.get("tier_name_ru") or "Полный доступ").strip() or "Полный доступ"
    exp_fmt = _format_expires_ru_from_iso(sub_st.get("expires_at"))
    return tier_label, exp_fmt


async def _trainer_has_crm_subscription(session, trainer_id: int) -> bool:
    """True if trainer has an active paid tier at least CRM (schedule, clients, passes)."""
    return await trainer_has_crm_access(session, trainer_id)


START_LINK_PREFIX = "link_"
START_REF_PREFIX = "ref_"  # Referral code payload: t.me/bot?start=ref_ABC123
START_JOIN_PAYLOAD = "join"  # Self-serve registration: t.me/bot?start=join
SCHEDULE_CALLBACK = "schedule"
SCHEDULE_ADD = "schedule:add"
SCHEDULE_ADD_TEMPLATE = "schedule:template"
SCHEDULE_WEEK_PREFIX = "schedule:week:"
SCHEDULE_DAY_PREFIX = "schedule:day:"
SCHEDULE_TIME_PREFIX = "schedule:time:"
SCHEDULE_TIME_LOCKED_PREFIX = "schedule:time_locked:"
SCHEDULE_DONE_PREFIX = "schedule:done:"
SCHEDULE_CANCEL_ADD = "schedule:cancel_add"
SCHEDULE_CREATE_BOOKING = "schedule:create_booking"
SCHEDULE_CREATE_BOOKING_SLOT_PREFIX = "schedule:create_booking_slot:"
SCHEDULE_CREATE_BOOKING_CLIENT_PREFIX = "schedule:create_booking_client:"
SCHEDULE_CREATE_BOOKING_TARIFF_PREFIX = "schedule:create_booking_tariff:"
SCHEDULE_GEN_THIS = "schedule:gen:this"
SCHEDULE_GEN_NEXT = "schedule:gen:next"
BOOKING_INVITE_CLIENT_PREFIX = "booking_invite_client:"
SCHEDULE_CONFIRM_THIS = "schedule:confirm:this"
SCHEDULE_CONFIRM_NEXT = "schedule:confirm:next"
SCHEDULE_DELETE_PREFIX = "schedule:del:"
SLOT_DELETE_PREFIX = "slot:del:"
SLOTS_CALLBACK = "slots"
BOOKINGS_CALLBACK = "bookings"
BOOKING_DETAIL_PREFIX = "booking_detail:"
BOOKINGS_PAGE_PREFIX = "bookings_page:"
WRITE_BOOKING_PREFIX = "write_booking:"
CANCEL_BOOKING_PREFIX = "cancel_booking:"
CANCEL_BOOKING_CONFIRM_PREFIX = "cancel_booking_confirm:"
CONFIRM_BOOKING_PREFIX = "confirm_booking:"
DECLINE_BOOKING_PREFIX = "decline_booking:"
DECLINE_BOOKING_SKIP_PREFIX = "decline_booking_skip:"
MAKE_RECURRING_TRAINER_PREFIX = "make_recurring_trainer:"
REMOVE_RECURRING_PREFIX = "remove_recurring:"
REQUESTS_CALLBACK = "requests"
REQUEST_DETAIL_PREFIX = "request_detail:"
REQUESTS_PAGE_PREFIX = "requests_page:"
REQUESTS_PER_PAGE = 8  # within one group (city+service); pagination if 100+ requests
REQUEST_RESPOND_PREFIX = "request_respond:"
REQUEST_RESPOND_SKIP_PREFIX = "request_respond_skip:"
REQUEST_DECLINE_PREFIX = "request_decline:"
REQUEST_BOOK_CLIENT_PREFIX = "request_book:"
REQUEST_REMIND_SLOTS_PREFIX = "request_remind_slots:"
REQUEST_BOOK_SLOT_PREFIX = "request_book_slot:"
FEEDBACK_BOOKING_TRAINER_PREFIX = "feedback_booking_trainer:"
TRAINER_REPEAT_WEEK_PREFIX = "trainer_repeat_week:"
BOOKING_ADD_NOTE_PREFIX = "booking_add_note:"
BOOKING_NOTIFY_RELAY_WRITE_PREFIX = "bkrly:"
GUIDE_CALLBACK = "guide"
TRAINER_SUPPORT_CALLBACK = "trainer:support"
TRAINER_FAQ_CALLBACK = "trainer:faq"
TRAINER_INVITE_CALLBACK = "trainer:invite"

# Human-readable trainer.status (aligned with admin TRAINER_STATUS_LABELS)
_TRAINER_STATUS_LABELS = {
    "pending_profile": "На модерации / черновик",
    "pending_contract": "Ожидает договор",
    "pending_payment": "Ожидает оплату",
    "active": "Активен",
    "deactivated": "Деактивирован",
}


def _trainer_profile_webapp_url() -> str | None:
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.lower().startswith("https://"):
        return f"{base}/webapp/trainer-profile"
    return None


def _trainer_stats_webapp_url() -> str | None:
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.lower().startswith("https://"):
        return f"{base}/webapp/trainer-stats"
    return None


def _trainer_moderation_profile_approved_reply_markup() -> InlineKeyboardMarkup | None:
    """After catalog moderation: open profile or stats mini apps (same row)."""
    profile = _trainer_profile_webapp_url()
    stats = _trainer_stats_webapp_url()
    if not profile or not stats:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=msg.TRAINER_PROFILE_BTN_MINI_APP, web_app=WebAppInfo(url=profile)),
                InlineKeyboardButton(text=msg.TRAINER_STATS_BTN_MINI_APP, web_app=WebAppInfo(url=stats)),
            ],
        ]
    )


def _trainer_faq_webapp_url() -> str | None:
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.lower().startswith("https://"):
        return f"{base}/webapp/trainer-faq"
    return None


def _trainer_profile_keyboard() -> InlineKeyboardMarkup | None:
    url = _trainer_profile_webapp_url()
    if not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=msg.TRAINER_PROFILE_BTN_MINI_APP, web_app=WebAppInfo(url=url))],
        ]
    )


async def _seed_trainer_avatar_bg(bot, trainer_id: int, telegram_user_id: int) -> None:
    """Fire-and-forget avatar copy; owns its session so /start's transaction is unaffected."""
    from src.application.trainer_quick_setup_use_cases import seed_trainer_photo_from_telegram

    try:
        async with async_session_factory() as s:
            await seed_trainer_photo_from_telegram(bot, s, trainer_id, telegram_user_id)
    except Exception:
        logger.info("avatar seed task failed trainer_id=%s", trainer_id, exc_info=True)


def _onboarding_start_keyboard() -> InlineKeyboardMarkup | None:
    """
    One button under the first message: «Начать» → the quick-setup screen.

    Not «Обзор». The hub is a place with many things in it; at second zero the trainer needs a
    single door, and behind it a screen that asks two questions they can answer without thinking.
    """
    base = (Settings().webapp_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_ONBOARDING_START_BUTTON,
                    web_app=WebAppInfo(url=f"{base}/webapp/trainer-onboarding"),
                )
            ]
        ]
    )


def _post_welcome_link_keyboard(*, for_active_menu: bool) -> InlineKeyboardMarkup:
    """
    After /start with link_: Обзор (HTTPS onboarding hub) only — no inline Profile (avoid duplicate entry;
    profile is reachable from trainer-home + left menu). Subscription when menu fully active.
    """
    rows: list[list[InlineKeyboardButton]] = []
    base = (Settings().webapp_base_url or "").rstrip("/")
    # Always offer Обзор when Mini App is available — welcome flow must not skip onboarding (trainer-home).
    if base.lower().startswith("https://"):
        rows.append(
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_MENU_BUTTON_HUB,
                    web_app=WebAppInfo(url=f"{base}/webapp/trainer-home"),
                )
            ]
        )
    if for_active_menu and base.lower().startswith("https://"):
        rows.append(
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BUTTON_SUBSCRIPTION_CONSTRUCTOR,
                    web_app=WebAppInfo(url=f"{base}/webapp/trainer-subscription?v=20260450"),
                )
            ]
        )
    # Guide: /guide — не дублируем кнопкой на первом шаге онбординга.
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _trainer_profile_footer_hint() -> str:
    """Extra copy under status card: HTTPS Mini App hint, or HTTPS missing + optional site URL."""
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.lower().startswith("https://"):
        return "\n\n" + msg.TRAINER_PROFILE_MINI_APP_HINT
    lines = ["\n\n" + msg.TRAINER_PROFILE_HTTPS_REQUIRED]
    if base:
        lines.append("\n" + msg.TRAINER_PROFILE_SITE_HINT.format(url=base))
    return "".join(lines)


# Add state: telegram_id -> { week_start?: str (YYYY-MM-DD), day: int, hours: set[int] }. No week_start = template.
_schedule_add_state: dict[int, dict] = {}
# Trainer feedback after completed booking: telegram_id -> { booking_id, trainer_id }
_trainer_feedback_state: dict[int, dict] = {}
# Trainer responding to request: telegram_id -> request_id (awaiting optional comment)
_request_respond_state: dict[int, int] = {}
# Trainer declining booking: telegram_id -> booking_id (awaiting optional comment)
_booking_decline_state: dict[int, int] = {}
# Trainer quick note after booking: telegram_id -> booking context for dated timeline entry.
_trainer_booking_note_state: dict[int, dict] = {}


def _clear_booking_decline_state(telegram_id: int) -> None:
    _booking_decline_state.pop(telegram_id, None)
    trainer_booking_decline_awaiting.discard(telegram_id)


def _set_booking_decline_state(telegram_id: int, booking_id: int) -> None:
    _booking_decline_state[telegram_id] = booking_id
    trainer_booking_decline_awaiting.add(telegram_id)


def _booking_decline_blocked_message(status: str) -> str:
    st = (status or "").strip().lower()
    if st == "confirmed":
        return msg.TRAINER_BOOKING_DECLINE_ALREADY_CONFIRMED
    if st in ("declined", "cancelled", "trainer_removed", "completed", "no_show"):
        return msg.TRAINER_BOOKING_DECLINE_ALREADY_HANDLED
    return msg.TRAINER_ERROR_BOOKING_NOT_FOUND


async def _complete_trainer_booking_decline(
    *,
    telegram_id: int,
    booking_id: int,
    comment: str | None,
    reply: Message,
) -> bool:
    """Decline pending booking and notify client. Returns True on success."""
    try:
        async with async_session_factory() as session:
            trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await reply.answer(msg.TRAINER_ONLY_VIA_SITE)
            return False
        async with async_session_factory() as session:
            booking = await get_booking_with_slot(session, booking_id, trainer_id)
        if not booking:
            await reply.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
            return False
        status = (booking.get("status") or "").strip().lower()
        if status != "pending":
            await reply.answer(_booking_decline_blocked_message(status))
            return False
        async with async_session_factory() as session:
            info = await decline_booking(session, booking_id, trainer_id)
        if not info:
            async with async_session_factory() as session:
                booking = await get_booking_with_slot(session, booking_id, trainer_id)
            if booking:
                await reply.answer(_booking_decline_blocked_message(str(booking.get("status") or "")))
            else:
                await reply.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
            return False

        audit_log(
            "booking.declined",
            ACTOR_TRAINER_BOT,
            telegram_id,
            {"booking_id": booking_id, "trainer_id": trainer_id, "has_comment": bool((comment or "").strip())},
        )
        d = info["slot_date"]
        date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
        dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
        start_time = info["start_time"]
        time_str = _format_time(start_time)
        await reply.answer(msg.TRAINER_BOOKING_DECLINED_DONE)
        client_tid = info.get("client_telegram_id")
        if client_tid:
            from src.application.booking_party_notifications import enqueue_trainer_decline_client_notification
            from src.bot.booking_party_notify import try_deliver_booking_party_notifications_for_booking

            async with async_session_factory() as session:
                await enqueue_trainer_decline_client_notification(
                    session,
                    booking_id=int(booking_id),
                    client_telegram_id=int(client_tid),
                    date_str=date_str,
                    day_label=dow,
                    time_str=time_str,
                    reason=(comment or "").strip() or None,
                )
                await session.commit()
            settings = Settings()
            client_bot = Bot(
                token=settings.telegram_bot_token_client,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            try:
                async with async_session_factory() as session:
                    await try_deliver_booking_party_notifications_for_booking(
                        session,
                        int(booking_id),
                        client_bot=client_bot,
                    )
            finally:
                await client_bot.session.close()
        return True
    finally:
        _clear_booking_decline_state(telegram_id)


async def _trainer_typing(bot: Bot, chat_id: int) -> None:
    """Typing indicator while DB or heavy work runs (constitution § VII)."""
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)


def _format_time(t) -> str:
    if hasattr(t, "strftime"):
        return t.strftime("%H:%M")
    s = str(t)
    return s[:5] if len(s) >= 5 else s


def _slot_duration_minutes(slot_date, start_time, end_time) -> int | None:
    """Length of slot in minutes for notification copy; None if not computable."""
    if slot_date is None or start_time is None or end_time is None:
        return None
    try:
        d = slot_date.date() if hasattr(slot_date, "date") else slot_date
        if not hasattr(d, "year"):
            return None
        a = datetime.combine(d, start_time)
        b = datetime.combine(d, end_time)
        sec = (b - a).total_seconds()
        if sec <= 0:
            return None
        return max(1, int(sec // 60))
    except Exception:
        return None


def _week_range(week_start: date | str) -> tuple[str, str]:
    """(start, end) as dd.mm for a week (week_start = Monday)."""
    if isinstance(week_start, str):
        week_start = date.fromisoformat(week_start)
    end = week_start + timedelta(days=6)
    fmt = msg.TRAINER_DATE_FMT
    return week_start.strftime(fmt), end.strftime(fmt)


async def _schedule_keyboard(trainer_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Build schedule screen: template list + Add slots + Apply to this/next week."""
    async with async_session_factory() as session:
        templates = await list_templates(session, trainer_id)
    lines = []
    prev_day: int | None = None
    for t in templates:
        dow = t["day_of_week"]
        if prev_day is not None and dow != prev_day:
            lines.append("")
        prev_day = dow
        day_name = msg.TRAINER_DAYS[dow] if dow < 7 else "?"
        time_str = _format_time(t["start_time"])
        cap = int(t.get("capacity") or 1)
        if cap > 1:
            time_str = f"{time_str} (×{cap})"
        lines.append(msg.TRAINER_SCHEDULE_ROW.format(
            day=day_name,
            time=time_str,
            duration=t["duration_minutes"],
        ))
    text = msg.TRAINER_SCHEDULE_TITLE + "\n\n"
    if not lines:
        text += msg.TRAINER_SCHEDULE_EMPTY + "\n"
    else:
        text += "\n".join(lines) + "\n"
    this_m = this_week_monday()
    next_m = next_week_monday()

    base = (Settings().webapp_base_url or "").rstrip("/")
    if base and base.lower().startswith("https://"):
        schedule_row = [InlineKeyboardButton(text=msg.TRAINER_BUTTON_MY_SLOTS, web_app=WebAppInfo(url=f"{base}/webapp/schedule-editor"))]
    else:
        schedule_row = [InlineKeyboardButton(text=msg.TRAINER_BUTTON_MY_SLOTS, callback_data=SLOTS_CALLBACK)]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        schedule_row,
        [InlineKeyboardButton(text=msg.TRAINER_BUTTON_CREATE_BOOKING, callback_data=SCHEDULE_CREATE_BOOKING)],
        [InlineKeyboardButton(text=msg.TRAINER_BUTTON_ADD_SLOT, callback_data=SCHEDULE_ADD)],
        [InlineKeyboardButton(text=f"{msg.TRAINER_BUTTON_APPLY_THIS_WEEK}", callback_data=SCHEDULE_GEN_THIS)],
        [InlineKeyboardButton(text=f"{msg.TRAINER_BUTTON_APPLY_NEXT_WEEK}", callback_data=SCHEDULE_GEN_NEXT)],
    ])
    return text, keyboard


async def _cmd_collective_claim(message: Message, session, token: str) -> None:
    """Activate studio draft when owner opens col_claim_* deep link."""
    from src.application.collective_use_cases import (
        consume_collective_claim_token,
        ensure_trainer_id_for_collective_bot_user,
    )
    from src.application.subscription_use_cases import ensure_trainer_welcome_trial

    user_id = message.from_user.id if message.from_user else 0
    username = (message.from_user.username if message.from_user else None) or None
    trainer_id, link_err = await ensure_trainer_id_for_collective_bot_user(
        session, user_id, telegram_username=username
    )
    if trainer_id is None:
        if link_err == "telegram_other_trainer":
            await message.answer(msg.TRAINER_LINK_TELEGRAM_CONFLICT, parse_mode=ParseMode.HTML)
        else:
            await message.answer(msg.TRAINER_COLLECTIVE_CLAIM_NEED_LINK, parse_mode=ParseMode.HTML)
        return
    await ensure_trainer_welcome_trial(session, trainer_id)
    outcome = await consume_collective_claim_token(session, token, trainer_id)
    if outcome.error == "invalid_token":
        await message.answer(msg.TRAINER_COLLECTIVE_CLAIM_INVALID, parse_mode=ParseMode.HTML)
        return
    if outcome.error == "already_in_collective":
        await message.answer(msg.TRAINER_COLLECTIVE_CLAIM_ALREADY, parse_mode=ParseMode.HTML)
        return
    if outcome.error or outcome.collective_id is None:
        await message.answer(msg.TRAINER_COLLECTIVE_CLAIM_INVALID, parse_mode=ParseMode.HTML)
        return
    name = html.escape((outcome.display_name or outcome.slug or "Студия").strip())
    await message.answer(
        msg.TRAINER_COLLECTIVE_CLAIM_SUCCESS.format(name=name),
        parse_mode=ParseMode.HTML,
    )


async def _cmd_collective_invite(message: Message, session, token: str) -> None:
    """Join studio as member when trainer opens col_inv_* deep link."""
    from src.application.collective_use_cases import (
        consume_collective_invite_token,
        ensure_trainer_id_for_collective_bot_user,
    )
    from src.application.subscription_use_cases import ensure_trainer_welcome_trial

    user_id = message.from_user.id if message.from_user else 0
    username = (message.from_user.username if message.from_user else None) or None
    trainer_id, link_err = await ensure_trainer_id_for_collective_bot_user(
        session, user_id, telegram_username=username
    )
    if trainer_id is None:
        if link_err == "telegram_other_trainer":
            await message.answer(msg.TRAINER_LINK_TELEGRAM_CONFLICT, parse_mode=ParseMode.HTML)
        else:
            await message.answer(msg.TRAINER_COLLECTIVE_INVITE_INVALID, parse_mode=ParseMode.HTML)
        return
    await ensure_trainer_welcome_trial(session, trainer_id)
    outcome = await consume_collective_invite_token(session, token, trainer_id)
    if outcome.error == "invalid_token":
        await message.answer(msg.TRAINER_COLLECTIVE_INVITE_INVALID, parse_mode=ParseMode.HTML)
        return
    if outcome.error == "already_in_collective":
        await message.answer(msg.TRAINER_COLLECTIVE_INVITE_ALREADY, parse_mode=ParseMode.HTML)
        return
    if outcome.error == "seats_full":
        await message.answer(msg.TRAINER_COLLECTIVE_INVITE_SEATS_FULL, parse_mode=ParseMode.HTML)
        return
    if outcome.error or outcome.collective_id is None:
        await message.answer(msg.TRAINER_COLLECTIVE_INVITE_INVALID, parse_mode=ParseMode.HTML)
        return
    name = html.escape((outcome.display_name or outcome.slug or "Студия").strip())
    await message.answer(
        msg.TRAINER_COLLECTIVE_INVITE_SUCCESS.format(name=name),
        parse_mode=ParseMode.HTML,
    )


async def _respond_to_not_linked_trainer(message: Message) -> None:
    """Respond to trainer who is NOT_LINKED. If registration is enabled, offer join button."""
    if not Settings().landing_trainer_registration_enabled:
        await message.answer(msg.TRAINER_REGISTRATION_UNAVAILABLE)
        return
    from src.application.landing_trainer_start_use_cases import build_trainer_bot_join_deep_link

    join_link = build_trainer_bot_join_deep_link()
    if join_link:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Зарегистрироваться", url=join_link)]
            ]
        )
        await message.answer(msg.TRAINER_ONLY_VIA_SITE, reply_markup=kb)
    else:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await _trainer_typing(message.bot, message.chat.id)
    user_id = message.from_user.id if message.from_user else 0
    text = message.text or ""
    args = text.split(maxsplit=1)
    pending_referrer_id: int | None = None  # Referral code to attribute after link
    async with async_session_factory() as session:
        if len(args) > 1:
            from src.application.trainer_start_payload import TrainerStartKind, parse_trainer_start_payload

            parsed_start = parse_trainer_start_payload(args[1])
            if parsed_start.kind == TrainerStartKind.COLLECTIVE_CLAIM:
                await _cmd_collective_claim(message, session, parsed_start.collective_token or "")
                return
            if parsed_start.kind == TrainerStartKind.COLLECTIVE_INVITE:
                await _cmd_collective_invite(message, session, parsed_start.collective_token or "")
                return
            if parsed_start.kind == TrainerStartKind.JOIN:
                if not Settings().landing_trainer_registration_enabled:
                    await message.answer(msg.TRAINER_REGISTRATION_UNAVAILABLE)
                    return
                join_state, _join_trainer = await get_trainer_access_state(session, user_id)
                if join_state == TrainerAccessState.NOT_LINKED:
                    if parsed_start.ref_code:
                        pending_referrer_id = await get_trainer_id_by_referral_code(
                            session, parsed_start.ref_code
                        )
                    from src.application.trainer_link_token_use_cases import issue_landing_trainer_link_token

                    issued = await issue_landing_trainer_link_token(session)
                    args[1] = START_LINK_PREFIX + str(issued["token"])
        # Parse referral code from payload (ref_<CODE> or link_<token>_ref_<CODE>)
        if len(args) > 1:
            payload = args[1]
            # Check for standalone referral code: ref_ABC123
            if payload.startswith(START_REF_PREFIX) and not payload.startswith(START_LINK_PREFIX):
                ref_code = payload.removeprefix(START_REF_PREFIX).split("_")[0]
                pending_referrer_id = await get_trainer_id_by_referral_code(session, ref_code)
                # Referral-only link: user must already be linked or will link later
                state, trainer = await get_trainer_access_state(session, user_id)
                if state != TrainerAccessState.NOT_LINKED and trainer:
                    # Already linked: record attribution if not yet set
                    tid = trainer.get("id")
                    if tid and pending_referrer_id:
                        await record_referral_attribution(session, pending_referrer_id, tid)
                    if state == TrainerAccessState.ACTIVE:
                        await message.answer(msg.TRAINER_START_WELCOME, reply_markup=ReplyKeyboardRemove())
                        await sync_trainer_linked_chat_menu(message.bot, message.chat.id)
                    else:
                        await message.answer(trainer_gate_message(state, trainer))
                    return
                else:
                    # Not linked yet: issue landing token for referral flow
                    if not Settings().landing_trainer_registration_enabled:
                        await message.answer(msg.TRAINER_REGISTRATION_UNAVAILABLE)
                        return
                    from src.application.trainer_link_token_use_cases import issue_landing_trainer_link_token

                    issued = await issue_landing_trainer_link_token(session)
                    args[1] = START_LINK_PREFIX + str(issued["token"])
                    # Fall through to link token processing below
            # Check for combined payload: link_<token>_ref_<CODE>
            if "_ref_" in payload and payload.startswith(START_LINK_PREFIX):
                parts = payload.split("_ref_", 1)
                token_part = parts[0].removeprefix(START_LINK_PREFIX)
                ref_code = parts[1].split("_")[0] if len(parts) > 1 else ""
                if ref_code:
                    pending_referrer_id = await get_trainer_id_by_referral_code(session, ref_code)
                # Continue with link token processing below
                args[1] = START_LINK_PREFIX + token_part
        if len(args) > 1 and args[1].startswith(START_LINK_PREFIX):
            token = args[1].removeprefix(START_LINK_PREFIX)
            username = (message.from_user.username if message.from_user else None) or None
            link_out = await consume_link_token(session, token, user_id, telegram_username=username)
            trainer_id = link_out.trainer_id
            if trainer_id is not None:
                audit_log("trainer.linked", ACTOR_TRAINER_BOT, user_id, {"trainer_id": trainer_id})
                # Notify admins about first login
                if link_out.first_login:
                    from src.application.trainer_events_notify import notify_admins_trainer_first_login
                    trainer = await get_trainer(session, trainer_id)
                    if trainer:
                        await notify_admins_trainer_first_login(trainer_id, trainer)
                # Record referral attribution if referrer was in payload
                if pending_referrer_id:
                    await record_referral_attribution(session, pending_referrer_id, trainer_id)
                state, trainer = await get_trainer_access_state(session, user_id)
                grant_kind = "trial"
                grant_result: dict | None = None
                paid_ok = False
                async with async_session_factory() as s2:
                    from src.application.trainer_link_token_use_cases import (
                        WELCOME_GRANT_KIND_PAID,
                        apply_pending_welcome_grant_for_token,
                    )

                    grant_result = await apply_pending_welcome_grant_for_token(s2, token, trainer_id)
                    grant_kind = str(grant_result.get("kind") or "trial")
                    paid_ok = grant_kind == WELCOME_GRANT_KIND_PAID and not grant_result.get("error")
                    if not paid_ok:
                        await ensure_trainer_welcome_trial(s2, trainer_id)
                async with async_session_factory() as s2:
                    sub_st = await get_trainer_subscription_status(s2, trainer_id)
                trial_welcome = _trial_welcome_labels(sub_st) if not paid_ok else None
                kb_active = _post_welcome_link_keyboard(for_active_menu=True)
                kb_onboarding = _post_welcome_link_keyboard(for_active_menu=False)

                # Onboarding v2: the fork is «has this trainer set up a week yet», not «did a
                # moderator approve them». A first-timer gets one offer and one button; everyone
                # else gets the normal welcome-back with the hub and their subscription state.
                from src.application.trainer_quick_setup_use_cases import (
                    seed_trainer_identity_from_telegram,
                    seed_trainer_photo_from_telegram,
                    trainer_has_weekly_template,
                )

                tg_user = message.from_user
                await seed_trainer_identity_from_telegram(
                    session,
                    trainer_id,
                    first_name=getattr(tg_user, "first_name", None),
                    last_name=getattr(tg_user, "last_name", None),
                )
                # Avatar in the background: it improves the client's booking screen, but the
                # trainer must never wait on Telegram's CDN to see their first message.
                asyncio.create_task(
                    _seed_trainer_avatar_bg(message.bot, trainer_id, int(user_id))
                )
                is_first_run = (
                    state != TrainerAccessState.DEACTIVATED
                    and not await trainer_has_weekly_template(session, trainer_id)
                )
                if is_first_run:
                    kb_start = _onboarding_start_keyboard()
                    await message.answer(
                        msg.TRAINER_AFTER_LINK_HERO,
                        parse_mode=ParseMode.HTML,
                        reply_markup=kb_start if kb_start else kb_onboarding,
                    )
                    await sync_trainer_linked_chat_menu(message.bot, message.chat.id)
                    return

                if state == TrainerAccessState.ACTIVE:
                    if paid_ok:
                        label = html.escape(
                            format_subscription_label(
                                grant_result.get("modules") or {},
                                has_base_crm=True,
                                is_trial=False,
                            )
                        )
                        exp_fmt = _format_expires_ru_from_iso(
                            grant_result.get("period_end").isoformat()
                            if hasattr(grant_result.get("period_end"), "isoformat")
                            else (grant_result.get("period_end") or sub_st.get("expires_at"))
                        )
                        await message.answer(
                            msg.TRAINER_WELCOME_PAID_GRANT_ACTIVATED.format(
                                label=label,
                                expires_date=html.escape(exp_fmt),
                            ),
                            parse_mode=ParseMode.HTML,
                            reply_markup=kb_active,
                        )
                    elif trial_welcome:
                        tier_label, exp_fmt = trial_welcome
                        await message.answer(
                            msg.TRAINER_WELCOME_TRIAL_ACTIVATED.format(
                                tier_name=html.escape(tier_label),
                                expires_date=html.escape(exp_fmt),
                            ),
                            parse_mode=ParseMode.HTML,
                            reply_markup=kb_active,
                        )
                    else:
                        await message.answer(
                            msg.TRAINER_LINK_SUCCESS_ACTIVE,
                            parse_mode=ParseMode.HTML,
                            reply_markup=kb_active,
                        )
                else:
                    if trial_welcome:
                        tier_label, exp_fmt = trial_welcome
                        await message.answer(
                            msg.TRAINER_WELCOME_TRIAL_ACTIVATED.format(
                                tier_name=html.escape(tier_label),
                                expires_date=html.escape(exp_fmt),
                            ),
                            parse_mode=ParseMode.HTML,
                            reply_markup=kb_onboarding,
                        )
                    await message.answer(
                        trainer_first_link_onboarding_html(state, trainer),
                        parse_mode=ParseMode.HTML,
                        reply_markup=kb_onboarding,
                    )
                await sync_trainer_linked_chat_menu(message.bot, message.chat.id)
            elif link_out.error == "telegram_other_trainer":
                await message.answer(
                    msg.TRAINER_LINK_TELEGRAM_CONFLICT,
                    parse_mode=ParseMode.HTML,
                )
            else:
                await message.answer(msg.TRAINER_LINK_INVALID)
            return
        state, trainer = await get_trainer_access_state(session, user_id)
    if state == TrainerAccessState.NOT_LINKED:
        await _respond_to_not_linked_trainer(message)
        return
    if state == TrainerAccessState.ACTIVE:
        await message.answer(msg.TRAINER_START_WELCOME, reply_markup=ReplyKeyboardRemove())
        await sync_trainer_linked_chat_menu(message.bot, message.chat.id)
        return
    await sync_trainer_linked_chat_menu(message.bot, message.chat.id)
    base = (Settings().webapp_base_url or "").rstrip("/")
    welcome_kb = (
        _post_welcome_link_keyboard(for_active_menu=False)
        if base.lower().startswith("https://")
        else None
    )
    await message.answer(
        trainer_gate_message(state, trainer),
        parse_mode=ParseMode.HTML,
        reply_markup=welcome_kb,
    )


def _trainer_guide_keyboard() -> InlineKeyboardMarkup:
    """Support + FAQ Mini App (HTTPS); без HTTPS — callback-заглушка."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="💬 Написать в поддержку", callback_data=TRAINER_SUPPORT_CALLBACK)],
    ]
    faq_url = _trainer_faq_webapp_url()
    if faq_url:
        rows.append([InlineKeyboardButton(text="FAQ", web_app=WebAppInfo(url=faq_url))])
    else:
        rows.append([InlineKeyboardButton(text="FAQ", callback_data=TRAINER_FAQ_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("guide"))
async def cmd_guide(message: Message) -> None:
    """Show help (Помощь) and support button."""
    await _trainer_typing(message.bot, message.chat.id)
    uid = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        state, _ = await get_trainer_access_state(session, uid)
    if state == TrainerAccessState.NOT_LINKED:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    await sync_trainer_linked_chat_menu(message.bot, message.chat.id)
    await message.answer(
        msg.TRAINER_GUIDE,
        parse_mode=ParseMode.HTML,
        reply_markup=_trainer_guide_keyboard(),
    )


async def _send_trainer_invite_package(chat_message: Message, telegram_id: int) -> None:
    """Two messages: HTML intro + plain text block the trainer can forward to clients."""
    settings = Settings()
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await chat_message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        city_id, service_id = await get_trainer_default_city_and_service(session, trainer_id)
    links, err = build_trainer_invite_links(
        webapp_base_url=settings.webapp_base_url,
        client_bot_username=settings.client_bot_username,
        city_id=city_id,
        service_id=service_id,
        trainer_id=trainer_id,
    )
    if err == "missing_username":
        await chat_message.answer(msg.TRAINER_INVITE_ERR_NO_CLIENT_BOT_USERNAME)
        return
    if err == "missing_city_or_service":
        await chat_message.answer(msg.TRAINER_INVITE_ERR_PROFILE_INCOMPLETE)
        return
    assert links is not None
    # Одна ссылка независимо от того, доступна ли страница каталога: ученик идёт к конкретному
    # тренеру, а второй адрес рядом с первым только заставляет выбирать.
    plain = msg.TRAINER_INVITE_PLAIN_CLIENT.format(deep_link=links.client_bot_deep_link)
    await chat_message.answer(msg.TRAINER_INVITE_INTRO_HTML)
    await chat_message.answer(plain, parse_mode=None)
    async with async_session_factory() as session:
        await record_trainer_client_invite_link_first_copy(session, trainer_id)


async def _send_first_booking_milestone_followups(
    chat_message: Message,
    trainer_id: int,
    *,
    milestone: bool,
    share_tip: bool,
    milestone_booking_info: dict | None = None,
    milestone_booking_id: int | None = None,
    skip_milestone_card: bool = False,
    created_by_trainer: bool = True,
) -> None:
    """One-time celebration + share-link tip (DB flags already set in booking use case)."""
    if not milestone and not share_tip:
        return
    if milestone and not skip_milestone_card:
        info_for_card = milestone_booking_info
        if info_for_card is None and milestone_booking_id is not None:
            async with async_session_factory() as session:
                info_for_card = await get_booking_milestone_display_for_trainer(
                    session, milestone_booking_id, trainer_id
                )
        if info_for_card:
            card_html = msg.format_trainer_first_booking_milestone_from_booking_row(info_for_card, created_by_trainer=created_by_trainer)
        else:
            if created_by_trainer:
                card_html = (
                    "✅ <b>Запись создана.</b>\n\n"
                    + msg.TRAINER_FIRST_BOOKING_MILESTONE_FOOTER_SUBDUED_HTML
                )
            else:
                card_html = (
                    "🎉 <b>Первая настоящая запись!</b>\n\n"
                    "Клиент нашёл вас и записался сам — без вашего участия.\n\n"
                    + msg.TRAINER_FIRST_BOOKING_MILESTONE_FOOTER_HTML
                )
        await chat_message.answer(card_html, parse_mode=ParseMode.HTML)
    if not share_tip:
        return
    await send_trainer_share_catalog_tip_to_chat(
        bot=chat_message.bot,
        chat_id=chat_message.chat.id,
        trainer_id=trainer_id,
    )


@router.message(Command("home"))
async def cmd_home(message: Message) -> None:
    """Trainer hub Mini App: upcoming bookings + links to schedule, clients, etc."""
    await _trainer_typing(message.bot, message.chat.id)
    uid = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        state, trainer = await get_trainer_access_state(session, uid)
    if state == TrainerAccessState.NOT_LINKED or not trainer:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    base = (Settings().webapp_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        await message.answer(msg.TRAINER_HOME_HTTPS_REQUIRED)
        return
    await sync_trainer_linked_chat_menu(message.bot, message.chat.id)
    url = f"{base}/webapp/trainer-home"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=msg.TRAINER_MENU_BUTTON_HUB, web_app=WebAppInfo(url=url))],
        ]
    )
    await message.answer(
        msg.TRAINER_HOME_OPEN_WEBAPP,
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    """Status card + single Web App entry to trainer-profile Mini App (HTTPS)."""
    await _trainer_typing(message.bot, message.chat.id)
    uid = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        state, trainer = await get_trainer_access_state(session, uid)
    if state == TrainerAccessState.NOT_LINKED or not trainer:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    tid = trainer["id"]
    raw_status = (trainer.get("status") or "").strip()
    status_label = _TRAINER_STATUS_LABELS.get(raw_status, raw_status or "—")
    if state == TrainerAccessState.ACTIVE:
        gate_hint = msg.TRAINER_PROFILE_ACTIVE_HINT
    else:
        gate_hint = trainer_gate_message(state, trainer)
    text = msg.TRAINER_PROFILE_CARD.format(
        trainer_id=tid,
        status_label=status_label,
        gate_hint=gate_hint + _trainer_profile_footer_hint(),
    )
    await message.answer(text, reply_markup=_trainer_profile_keyboard())


@router.message(Command("myprofile"))
async def cmd_myprofile(message: Message) -> None:
    """Alias for profile entry: Mini App button (no FSM wizard)."""
    await _trainer_typing(message.bot, message.chat.id)
    uid = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        state, trainer = await get_trainer_access_state(session, uid)
    if state == TrainerAccessState.NOT_LINKED or not trainer:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    kb = _trainer_profile_keyboard()
    if kb:
        await message.answer(msg.TRAINER_MYPROFILE_INTRO, reply_markup=kb)
        return
    base = (Settings().webapp_base_url or "").rstrip("/")
    extra = "\n\n" + msg.TRAINER_PROFILE_SITE_HINT.format(url=base) if base else ""
    await message.answer(msg.TRAINER_PROFILE_HTTPS_REQUIRED + extra)


@router.callback_query(F.data.startswith("profwiz:"))
async def on_profwiz_deprecated(callback: CallbackQuery) -> None:
    """Legacy inline buttons from old chat wizard → point to Mini App."""
    await callback.answer()
    if not callback.message:
        return
    await _trainer_typing(callback.bot, callback.message.chat.id)
    kb = _trainer_profile_keyboard()
    if kb:
        await callback.message.answer(msg.TRAINER_PROFILE_WIZARD_DEPRECATED, reply_markup=kb)
    else:
        await callback.message.answer(msg.TRAINER_PROFILE_HTTPS_REQUIRED)


def _format_slot_time(st, et) -> str:
    if hasattr(st, "strftime"):
        st_str = st.strftime("%H:%M")
    else:
        st_str = str(st)[:5] if len(str(st)) >= 5 else str(st)
    if hasattr(et, "strftime"):
        et_str = et.strftime("%H:%M")
    else:
        et_str = str(et)[:5] if len(str(et)) >= 5 else str(et)
    return f"{st_str}–{et_str}"


def _slot_status_label(status: str) -> str:
    if status == "available":
        return msg.TRAINER_SLOTS_STATUS_AVAILABLE
    if status == "booked":
        return msg.TRAINER_SLOTS_STATUS_BOOKED
    return msg.TRAINER_SLOTS_STATUS_CANCELLED


def _schedule_webapp_keyboard(
    include_back: bool = False,
    include_create_booking: bool = False,
) -> InlineKeyboardMarkup:
    """Keyboard with Web App 'Open schedule' button; optionally Create booking and Back rows. Web App only if HTTPS (Telegram requirement)."""
    base = (Settings().webapp_base_url or "").rstrip("/")
    url = f"{base}/webapp/schedule-editor" if base else ""
    rows = []
    if url and base.lower().startswith("https://"):
        rows.append([
            InlineKeyboardButton(
                text=msg.TRAINER_BUTTON_OPEN_SCHEDULE_WEBAPP,
                web_app=WebAppInfo(url=url),
            )
        ])
    if include_create_booking:
        rows.append([InlineKeyboardButton(text=msg.TRAINER_BUTTON_CREATE_BOOKING, callback_data=SCHEDULE_CREATE_BOOKING)])
    if include_back:
        rows.append([InlineKeyboardButton(text=msg.TRAINER_BUTTON_BACK_TO_SCHEDULE, callback_data=SCHEDULE_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _slot_is_future(slot_date: date, start_time: time, now_date: date, now_time: time) -> bool:
    """True if slot (date + start_time) is strictly after (now_date, now_time)."""
    if slot_date > now_date:
        return True
    if slot_date < now_date:
        return False
    return start_time > now_time


async def _slots_content(trainer_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    """Build applied schedule screen: text only (this week / next week), no delete buttons. Past slots hidden. Always returns (text, None)."""
    this_m = this_week_monday()
    next_m = next_week_monday()
    to_date = next_m + timedelta(days=6)
    async with async_session_factory() as session:
        slots = await list_slots(session, trainer_id, this_m, to_date)
    now_minsk = datetime.now(ZoneInfo(NOTIFICATION_TZ))
    now_date = now_minsk.date()
    now_time = now_minsk.time()
    slots = [s for s in slots if _slot_is_future(s["slot_date"], s["start_time"], now_date, now_time)]
    if not slots:
        return msg.TRAINER_SLOTS_TITLE + "\n\n" + msg.TRAINER_SLOTS_EMPTY, None
    s1, e1 = _week_range(this_m)
    s2, e2 = _week_range(next_m)
    this_week_end = this_m + timedelta(days=6)
    lines = [msg.TRAINER_SLOTS_TITLE]
    # This week: one blank line between days
    lines.append(msg.TRAINER_SLOTS_THIS_WEEK_HEADER.format(start=s1, end=e1))
    prev_d = None
    for s in slots:
        d = s["slot_date"]
        if d > this_week_end:
            break
        if prev_d is not None and d != prev_d:
            lines.append("")
        prev_d = d
        date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
        dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
        time_range = _format_slot_time(s["start_time"], s["end_time"])
        status_label = _slot_status_label(s.get("status") or "available")
        lines.append(f"• {date_str} ({dow}) {time_range} — {status_label}")
    # Next week: one blank line between days
    lines.append(msg.TRAINER_SLOTS_NEXT_WEEK_HEADER.format(start=s2, end=e2))
    prev_d = None
    for s in slots:
        d = s["slot_date"]
        if d <= this_week_end:
            continue
        if prev_d is not None and d != prev_d:
            lines.append("")
        prev_d = d
        date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
        dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
        time_range = _format_slot_time(s["start_time"], s["end_time"])
        status_label = _slot_status_label(s.get("status") or "available")
        lines.append(f"• {date_str} ({dow}) {time_range} — {status_label}")
    return "\n".join(lines), None


@router.message(Command("editor"))
async def cmd_editor(message: Message) -> None:
    """Open schedule editor: Mini App (HTTPS) or chat keyboard with template + add/apply."""
    await _trainer_typing(message.bot, message.chat.id)
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if not await _trainer_has_crm_subscription(session, trainer_id):
            await message.answer(
                msg.TRAINER_TIER_REQUIRED_CRM + "\n\n" + msg.TRAINER_TIER_CTA,
                parse_mode=ParseMode.HTML,
            )
            return
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.startswith("https://"):
        await message.answer(
            msg.TRAINER_EDITOR_OPEN_HINT,
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    # Drop legacy reply keyboard (e.g. old "Расписание" bar); cannot mix Remove with inline keys.
    await message.answer(_REPLY_KEYBOARD_CLEAR, reply_markup=ReplyKeyboardRemove())
    text, keyboard = await _schedule_keyboard(trainer_id)
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("schedule"))
async def cmd_schedule(message: Message) -> None:
    """Same as /editor: open schedule (editor) Mini App or chat keyboard. Kept for backwards compatibility."""
    await cmd_editor(message)


def _booking_button_label(b: dict) -> str:
    """Short label for list=buttons: date, day, time, client (Telegram button limit ~64 bytes)."""
    d = b["slot_date"]
    date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
    dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
    start_str = _format_time(b["start_time"])
    first = (b.get("client_first_name") or "").strip()
    last = (b.get("client_last_name") or "").strip()
    client = f"{first} {last}".strip() or (b.get("client_phone") or "Клиент")
    return f"{date_str} {dow} {start_str} — {client}"[:64]


def _booking_detail_text(b: dict) -> str:
    """Detail screen: date/time, client, meta (service, arena, N-th), optional comment. Clear blocks."""
    d = b["slot_date"]
    date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
    dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
    time_range = _format_slot_time(b["start_time"], b["end_time"])
    first = (b.get("client_first_name") or "").strip()
    last = (b.get("client_last_name") or "").strip()
    client_display = f"{first} {last}".strip() or (b.get("client_phone") or "Клиент")
    services = b.get("services_str") or "—"
    arenas = b.get("arenas_str") or "—"
    session_num = b.get("session_num") or 1
    session_label = msg.TRAINER_BOOKINGS_SESSION_NTH.format(n=session_num)
    lines = [
        msg.TRAINER_BOOKINGS_DETAIL_HEAD.format(date=date_str, day=dow, time=time_range),
        msg.TRAINER_BOOKINGS_DETAIL_CLIENT.format(client_display=client_display),
        "",
        msg.TRAINER_BOOKINGS_DETAIL_META.format(services=services, arenas=arenas, session_label=session_label),
    ]
    comment = (b.get("client_comment") or "").strip()
    if comment:
        lines.append("")
        lines.append(msg.TRAINER_BOOKINGS_DETAIL_COMMENT.format(comment=comment))
    return "\n".join(lines)


async def _bookings_content(trainer_id: int, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    """List = one page per day. First page = today, then next days (no past days)."""
    async with async_session_factory() as session:
        bookings = await list_bookings_for_trainer(session, trainer_id)
    today = date.today()
    if not bookings:
        text = msg.TRAINER_BOOKINGS_TITLE + "\n\n" + msg.TRAINER_BOOKINGS_EMPTY
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        return text, keyboard

    # Group by slot_date (list is sorted slot_date ASC, so days = [today, tomorrow, ...])
    days = [(d, list(g)) for d, g in groupby(bookings, key=lambda b: b["slot_date"])]
    if days[0][0] > today:
        days.insert(0, (today, []))  # first tab = always today; may have no bookings
    total_days = len(days)
    page = max(0, min(page, total_days - 1))
    day_date, day_bookings = days[page]

    date_str = day_date.strftime("%d.%m") if hasattr(day_date, "strftime") else str(day_date)
    dow = msg.TRAINER_DAYS[day_date.weekday()] if hasattr(day_date, "weekday") else ""
    day_header = msg.TRAINER_BOOKINGS_DAY_HEADER.format(date=date_str, day=dow).strip()

    text = (
        msg.TRAINER_BOOKINGS_TITLE
        + "\n\n"
        + msg.TRAINER_BOOKINGS_LIST_HINT
        + "\n\n"
        + day_header
    )
    if not day_bookings:
        text += "\n\n" + msg.TRAINER_BOOKINGS_DAY_EMPTY
    button_rows = []
    for b in day_bookings:
        button_rows.append([InlineKeyboardButton(
            text=_booking_button_label(b),
            callback_data=f"{BOOKING_DETAIL_PREFIX}{b['id']}",
        )])
    if total_days > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_PAGE_BACK, callback_data=f"{BOOKINGS_PAGE_PREFIX}{page - 1}"))
        if page < total_days - 1:
            nav.append(InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_PAGE_NEXT, callback_data=f"{BOOKINGS_PAGE_PREFIX}{page + 1}"))
        if nav:
            button_rows.append(nav)
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, keyboard


def _request_button_label(req: dict, *, in_progress: bool) -> str:
    """Short label: prefix (🆕/✓) + city · service — client or comment preview. 64 bytes max."""
    city = (req.get("city_name") or "").strip() or "—"
    service = (req.get("service_name") or "").strip() or "—"
    comment = (req.get("comment") or "").strip().replace("\n", " ").strip()
    first = (req.get("client_first_name") or "").strip()
    last = (req.get("client_last_name") or "").strip()
    if last:
        client = f"{first} {last[0]}." if first else f"{last[0]}."
    else:
        client = first or "Клиент"
    preview = comment if comment else client
    prefix = "✓ " if in_progress else "🆕 "
    raw_full = f"{prefix}{city} · {service} — {preview}"
    max_bytes = 60
    if len(raw_full.encode("utf-8")) <= max_bytes:
        return raw_full
    for n in range(len(preview), 0, -1):
        raw = f"{prefix}{city} · {service} — {preview[:n]}…"
        if len(raw.encode("utf-8")) <= max_bytes:
            return raw
    return f"{prefix}{city} · {service}"


def _request_detail_text(req: dict) -> str:
    """Detail screen: city, service, optional comment. Clear blocks."""
    city = (req.get("city_name") or "").strip() or "—"
    service = (req.get("service_name") or "").strip() or "—"
    lines = [msg.TRAINER_REQUEST_DETAIL_HEAD.format(city=city, service=service)]
    comment = (req.get("comment") or "").strip()
    if comment:
        lines.append("")
        lines.append(msg.TRAINER_REQUEST_DETAIL_COMMENT.format(comment=comment))
    if req.get("has_responded"):
        lines.append("")
        lines.append(msg.TRAINER_REQUEST_DETAIL_RESPONDED_HINT)
    return "\n".join(lines)


async def _requests_content(
    trainer_id: int, offset: int = 0
) -> tuple[str, InlineKeyboardMarkup]:
    """List: two sections (Новые / В работе), one combined list new first then in progress. Pagination by page."""
    async with async_session_factory() as session:
        requests_list = await list_requests_for_trainer(session, trainer_id)
    if not requests_list:
        text = msg.TRAINER_REQUESTS_TITLE + "\n\n" + msg.TRAINER_REQUESTS_EMPTY
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        return text, keyboard

    new_list = [r for r in requests_list if not r.get("has_responded")]
    in_progress_list = [r for r in requests_list if r.get("has_responded")]
    combined = new_list + in_progress_list
    total = len(combined)
    offset = max(0, min(offset, total))
    page_requests = combined[offset : offset + REQUESTS_PER_PAGE]

    lines = [
        msg.TRAINER_REQUESTS_TITLE,
        "",
        msg.TRAINER_REQUESTS_FILTER_LINE,
        "",
    ]
    if new_list:
        lines.append(msg.TRAINER_REQUESTS_SECTION_NEW)
    else:
        lines.append(msg.TRAINER_REQUESTS_SECTION_NEW_EMPTY)
    lines.append("")
    if in_progress_list:
        lines.append(msg.TRAINER_REQUESTS_SECTION_IN_PROGRESS)
    else:
        lines.append(msg.TRAINER_REQUESTS_SECTION_IN_PROGRESS_EMPTY)
    if total > REQUESTS_PER_PAGE:
        page_num = offset // REQUESTS_PER_PAGE + 1
        total_pages = (total + REQUESTS_PER_PAGE - 1) // REQUESTS_PER_PAGE
        lines.append(f"\nСтраница {page_num} из {total_pages} ({total} заявок)")
    text = "\n".join(lines)

    button_rows = []
    for req in page_requests:
        in_progress = bool(req.get("has_responded"))
        button_rows.append([InlineKeyboardButton(
            text=_request_button_label(req, in_progress=in_progress),
            callback_data=f"{REQUEST_DETAIL_PREFIX}{req['id']}",
        )])
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(
            text=msg.TRAINER_REQUESTS_PAGE_BACK,
            callback_data=f"{REQUESTS_PAGE_PREFIX}{offset - REQUESTS_PER_PAGE}",
        ))
    if offset + REQUESTS_PER_PAGE < total:
        nav.append(InlineKeyboardButton(
            text=msg.TRAINER_REQUESTS_PAGE_NEXT,
            callback_data=f"{REQUESTS_PAGE_PREFIX}{offset + REQUESTS_PER_PAGE}",
        ))
    if nav:
        button_rows.append(nav)
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, keyboard


@router.message(Command("bookings"))
async def cmd_bookings(message: Message) -> None:
    """Legacy /bookings: same Mini App as «Моё расписание» (HTTPS) or inline list without Web App."""
    await _trainer_typing(message.bot, message.chat.id)
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if not await _trainer_has_crm_subscription(session, trainer_id):
            await message.answer(
                msg.TRAINER_TIER_REQUIRED_CRM + "\n\n" + msg.TRAINER_TIER_CTA,
                parse_mode=ParseMode.HTML,
            )
            return
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.startswith("https://"):
        url = f"{base}/webapp/schedule-editor"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.TRAINER_BUTTON_MY_BOOKINGS, web_app=WebAppInfo(url=url))],
        ])
        await message.answer(msg.TRAINER_BOOKINGS_OPEN_WEBAPP, reply_markup=kb)
        return
    text, keyboard = await _bookings_content(trainer_id)
    await message.answer(
        msg.TRAINER_BOOKINGS_CHAT_MODE_INTRO + "\n\n" + text,
        reply_markup=keyboard,
    )


@router.message(Command("clients"))
async def cmd_clients(message: Message) -> None:
    """Open 'Мои клиенты' Mini App for trainer (HTTPS only)."""
    await _trainer_typing(message.bot, message.chat.id)
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if not await _trainer_has_crm_subscription(session, trainer_id):
            await message.answer(
                msg.TRAINER_TIER_REQUIRED_CRM + "\n\n" + msg.TRAINER_TIER_CTA,
                parse_mode=ParseMode.HTML,
            )
            return
    base = (Settings().webapp_base_url or "").rstrip("/")
    if not base or not base.startswith("https://"):
        await message.answer(msg.TRAINER_CLIENTS_HTTPS_REQUIRED)
        return
    url = f"{base}/webapp/trainer-clients"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=msg.TRAINER_BUTTON_CLIENTS, web_app=WebAppInfo(url=url))],
        ]
    )
    await message.answer(msg.TRAINER_CLIENTS_OPEN_WEBAPP, reply_markup=kb)


@router.message(Command("requests"))
async def cmd_requests(message: Message) -> None:
    """Open 'Заявки клиентов' from menu: Mini App (HTTPS) or chat list."""
    await _trainer_typing(message.bot, message.chat.id)
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if not await _trainer_has_crm_subscription(session, trainer_id):
            await message.answer(
                msg.TRAINER_TIER_REQUIRED_CRM + "\n\n" + msg.TRAINER_TIER_CTA,
                parse_mode=ParseMode.HTML,
            )
            return
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.startswith("https://"):
        url = f"{base}/webapp/trainer-requests"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.TRAINER_BUTTON_REQUESTS, web_app=WebAppInfo(url=url))],
        ])
        await message.answer(
            msg.TRAINER_REQUESTS_OPEN_WEBAPP,
            reply_markup=kb,
        )
        return
    text, keyboard = await _requests_content(trainer_id)
    await message.answer(text, reply_markup=keyboard)


def _format_stats_date(d: date) -> str:
    return d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Open stats Mini App (HTTPS) or show text statistics."""
    await _trainer_typing(message.bot, message.chat.id)
    telegram_id = message.from_user.id if message.from_user else 0
    base = (Settings().webapp_base_url or "").rstrip("/")
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if not await trainer_has_analytics_access(session, trainer_id):
            await message.answer(
                msg.TRAINER_TIER_REQUIRED_ANALYTICS + "\n\n" + msg.TRAINER_TIER_CTA,
                parse_mode=ParseMode.HTML,
            )
            return
        if base.startswith("https://"):
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=msg.TRAINER_BUTTON_STATS_APP, web_app=WebAppInfo(url=f"{base}/webapp/trainer-stats"))],
            ])
            await message.answer(msg.TRAINER_STATS_OPEN_APP, reply_markup=kb)
            return
        s = await get_trainer_stats(session, trainer_id)
    parts = [msg.TRAINER_STATS_TITLE]
    parts.append(
        msg.TRAINER_STATS_WEEK.format(
            week_start=_format_stats_date(s["week_start"]),
            week_end=_format_stats_date(s["week_end"]),
            week_total=s["week_total"],
            week_completed=s["week_completed"],
            week_upcoming=s["week_upcoming"],
        )
    )
    parts.append(msg.TRAINER_STATS_MONTH.format(month_total=s["month_total"]))
    if s["week_slots_total"] and s["load_pct"] is not None:
        parts.append(
            msg.TRAINER_STATS_LOAD.format(
                week_slots_total=s["week_slots_total"],
                week_slots_booked=s["week_slots_booked"],
                load_pct=int(s["load_pct"]),
            )
        )
    else:
        parts.append(msg.TRAINER_STATS_LOAD_EMPTY)
    parts.append(msg.TRAINER_STATS_NEW_CLIENTS.format(new_clients_30d=s["new_clients_30d"]))
    if s["rating_avg"] is not None and s["rating_count"]:
        parts.append(
            msg.TRAINER_STATS_RATING.format(
                rating_avg=round(s["rating_avg"], 1),
                rating_count=s["rating_count"],
            )
        )
    else:
        parts.append(msg.TRAINER_STATS_RATING_NONE)
    parts.append(
        msg.TRAINER_STATS_PASSES.format(
            passes_active=s["passes_active"],
            passes_issued_30d=s["passes_issued_30d"],
        )
    )
    cert_balance_byn = (s.get("certificate_balance_cents") or 0) / 100
    parts.append(
        msg.TRAINER_STATS_CERTS.format(
            certificates_issued_total=s["certificates_issued_total"],
            certificates_with_balance=s["certificates_with_balance"],
            certificate_balance_byn=f"{cert_balance_byn:.0f}" if cert_balance_byn == int(cert_balance_byn) else f"{cert_balance_byn:.2f}",
            certificates_redeemed_30d=s["certificates_redeemed_30d"],
        )
    )
    await message.answer("\n".join(parts))


@router.message(Command("passes"))
async def cmd_passes(message: Message) -> None:
    """Open pass products Mini App (HTTPS) or hint to use app."""
    await _trainer_typing(message.bot, message.chat.id)
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if not await _trainer_has_crm_subscription(session, trainer_id):
            await message.answer(
                msg.TRAINER_TIER_REQUIRED_CRM + "\n\n" + msg.TRAINER_TIER_CTA,
                parse_mode=ParseMode.HTML,
            )
            return
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.startswith("https://"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.TRAINER_BUTTON_PASSES, web_app=WebAppInfo(url=f"{base}/webapp/trainer-pass-products"))],
        ])
        await message.answer(
            msg.TRAINER_PASSES_INTRO_WEBAPP,
            reply_markup=kb,
        )
        return
    await message.answer(msg.TRAINER_PASSES_HTTPS_REQUIRED)


def _subscription_label_from_status(status: dict) -> str:
    """Use the API-provided composite label; fall back to a reasonable default."""
    name = (status.get("tier_name_ru") or "").strip()
    if name:
        return name
    if status.get("is_trial"):
        return "Полный доступ"
    return "Подписка"


def _format_iso_date_ru(iso: str | None) -> str:
    if not iso or len(iso) < 10:
        return "—"
    y, m, d = iso[:10].split("-")
    return f"{d}.{m}.{y}"


@router.message(Command("subscription"))
async def cmd_subscription(message: Message) -> None:
    """Краткий статус подписки + мини-приложение тарифов."""
    await _trainer_typing(message.bot, message.chat.id)
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    base = (Settings().webapp_base_url or "").rstrip("/")
    constructor_url = f"{base}/webapp/trainer-subscription?v=20260450" if base and base.startswith("https://") else None
    async with async_session_factory() as session:
        tier_status = await get_trainer_subscription_status(session, trainer_id)
        eff = (tier_status.get("effective_tier") or "none").strip().lower()
        if eff != "none" and tier_status.get("is_active") and tier_status.get("expires_at"):
            expires_date = _format_iso_date_ru(tier_status.get("expires_at"))
            text = msg.TRAINER_SUBSCRIPTION_WITH_TIER.format(
                tier_name=_subscription_label_from_status(tier_status),
                expires_date=expires_date,
            )
            # Queued paid plan will kick in after current window — surface it so trainer
            # knows days/modules aren't lost when trial and paid overlap.
            nxt = tier_status.get("next_plan")
            if nxt and nxt.get("expires_at"):
                nxt_label = (nxt.get("tier_name_ru") or "Подписка").strip()
                nxt_expires = _format_iso_date_ru(nxt.get("expires_at"))
                text += (
                    "\n\nПосле окончания текущего периода автоматически начнётся "
                    f"<b>{nxt_label}</b> до <b>{nxt_expires}</b>. Дни не сгорят."
                )
        else:
            text = msg.TRAINER_SUBSCRIPTION_WITHOUT_TIER
        rows: list[list[InlineKeyboardButton]] = []
        if constructor_url:
            rows.append(
                [InlineKeyboardButton(text=msg.TRAINER_BUTTON_SUBSCRIPTION_CONSTRUCTOR, web_app=WebAppInfo(url=constructor_url))]
            )
        kb = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
        await sync_trainer_linked_chat_menu(message.bot, message.chat.id)
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@router.message(Command("referral"))
async def cmd_referral(message: Message) -> None:
    """Реферальная программа: ссылка для приглашения коллег."""
    await _trainer_typing(message.bot, message.chat.id)
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    from src.application.referral_use_cases import (
        ensure_trainer_referral_code,
        get_referral_credit_balance,
        get_referral_stats_for_trainer,
    )
    async with async_session_factory() as session:
        code = await ensure_trainer_referral_code(session, trainer_id)
        if not code:
            await message.answer("Не удалось создать реферальный код. Попробуйте позже.")
            return
        stats = await get_referral_stats_for_trainer(session, trainer_id)
    bot_username = Settings().trainer_bot_username or "trainer_bot"
    referral_link = f"https://t.me/{bot_username}?start=ref_{code}"
    balance = stats.get("balance_days", 0)
    credited = stats.get("credited_count", 0)
    text = (
        f"🎁 <b>Реферальная программа</b>\n\n"
        f"Пригласи коллегу: до <b>19 дней</b> подписки с одного тренера "
        f"(<b>+2</b> за базовый профиль, <b>+3</b> за первую запись, <b>+14</b> за оплату). "
        f"Всего не больше <b>60</b> бонусных дней с рефералок за всё время. "
        f"При оплате подписки бонусы уменьшают сумму счёта пропорционально дням.\n\n"
        f"Твоя ссылка:\n<code>{html.escape(referral_link)}</code>\n\n"
        f"📊 Баланс: <b>{balance}</b> дней\n"
        f"👥 Оплатили: <b>{credited}</b> тренеров"
    )
    base = (Settings().webapp_base_url or "").rstrip("/")
    referral_url = f"{base}/webapp/trainer-referral" if base and base.startswith("https://") else None
    rows: list[list[InlineKeyboardButton]] = []
    if referral_url:
        rows.append([InlineKeyboardButton(text="📊 Подробнее", web_app=WebAppInfo(url=referral_url))])
    kb = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@router.callback_query(lambda c: c.data == SCHEDULE_CALLBACK)
async def show_schedule(callback: CallbackQuery) -> None:
    await callback.answer()
    await _trainer_typing(callback.bot, callback.message.chat.id)
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if not await _trainer_has_crm_subscription(session, trainer_id):
            await callback.message.answer(
                msg.TRAINER_TIER_REQUIRED_CRM + "\n\n" + msg.TRAINER_TIER_CTA,
                parse_mode=ParseMode.HTML,
            )
            return
    text, keyboard = await _schedule_keyboard(trainer_id)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == SLOTS_CALLBACK)
async def show_slots_from_schedule(callback: CallbackQuery) -> None:
    """Open applied-slots view from schedule screen; add Back to schedule."""
    await callback.answer()
    await _trainer_typing(callback.bot, callback.message.chat.id)
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if not await _trainer_has_crm_subscription(session, trainer_id):
            await callback.message.answer(
                msg.TRAINER_TIER_REQUIRED_CRM + "\n\n" + msg.TRAINER_TIER_CTA,
                parse_mode=ParseMode.HTML,
            )
            return
    text, _ = await _slots_content(trainer_id)
    await callback.message.edit_text(
        text,
        reply_markup=_schedule_webapp_keyboard(include_back=True, include_create_booking=True),
    )


@router.callback_query(lambda c: c.data == SCHEDULE_CREATE_BOOKING)
async def schedule_create_booking_start(callback: CallbackQuery) -> None:
    """Trainer wants to create a booking from schedule: choose future free slot first."""
    await callback.answer()
    await _trainer_typing(callback.bot, callback.message.chat.id)
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if not await _trainer_has_crm_subscription(session, trainer_id):
            await callback.message.answer(
                msg.TRAINER_TIER_REQUIRED_CRM + "\n\n" + msg.TRAINER_TIER_CTA,
                parse_mode=ParseMode.HTML,
            )
            return
    now = datetime.now()
    cutoff = now + timedelta(hours=2)
    from_date = cutoff.date()
    to_date = from_date + timedelta(days=14)
    async with async_session_factory() as session:
        slots = await list_slots(session, trainer_id, from_date, to_date)
    free_slots: list[dict] = []
    for s in slots:
        status = (s.get("status") or "").strip()
        if status != "available":
            continue
        slot_date = s.get("slot_date")
        start_time = s.get("start_time")
        if not slot_date or not start_time:
            continue
        try:
            slot_dt = datetime.combine(slot_date, start_time)
        except Exception:
            continue
        if slot_dt < cutoff:
            continue
        free_slots.append(s)
    if not free_slots:
        await callback.message.answer(msg.TRAINER_CREATE_BOOKING_NO_SLOTS)
        return
    rows: list[list[InlineKeyboardButton]] = []
    for s in free_slots:
        d = s["slot_date"]
        date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
        dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
        time_range = _format_slot_time(s["start_time"], s["end_time"])
        label = f"{date_str} {dow} {time_range}"
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"{SCHEDULE_CREATE_BOOKING_SLOT_PREFIX}{s['id']}",
            )
        ])
    rows.append([InlineKeyboardButton(text=msg.TRAINER_BUTTON_BACK_TO_SCHEDULE, callback_data=SCHEDULE_CALLBACK)])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.edit_text(msg.TRAINER_CREATE_BOOKING_CHOOSE_SLOT, reply_markup=kb)


@router.callback_query(lambda c: c.data and c.data.startswith(SCHEDULE_CREATE_BOOKING_SLOT_PREFIX))
async def schedule_create_booking_choose_client(callback: CallbackQuery) -> None:
    """After slot chosen, ask trainer to pick one of their existing clients."""
    await callback.answer()
    raw = callback.data[len(SCHEDULE_CREATE_BOOKING_SLOT_PREFIX):]
    slot_id = safe_parse_id(raw)
    if slot_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    # Validate slot and load its date/time for caption
    async with async_session_factory() as session:
        slot = await get_slot(session, slot_id)
    if not slot or slot.get("trainer_id") != trainer_id or (slot.get("status") or "").strip() != "available":
        await callback.message.answer(msg.TRAINER_CREATE_BOOKING_SLOT_UNAVAILABLE)
        return
    async with async_session_factory() as session:
        clients = await list_trainer_clients(session, trainer_id, limit=50)
    if not clients:
        await callback.message.answer(msg.TRAINER_CREATE_BOOKING_NO_CLIENTS)
        return
    slot_date = slot.get("slot_date")
    start_time = slot.get("start_time")
    date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
    day_str = msg.TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
    time_str = _format_time(start_time)
    rows: list[list[InlineKeyboardButton]] = []
    for c in clients:
        name = _format_trainer_client_row_display_name(c)
        rows.append([
            InlineKeyboardButton(
                text=name,
                callback_data=f"{SCHEDULE_CREATE_BOOKING_CLIENT_PREFIX}{slot_id}:{c['id']}",
            )
        ])
    rows.append([InlineKeyboardButton(text=msg.TRAINER_BUTTON_BACK_TO_SCHEDULE, callback_data=SCHEDULE_CALLBACK)])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.edit_text(
        msg.TRAINER_CREATE_BOOKING_CHOOSE_CLIENT.format(date=date_str, day=day_str, time=time_str),
        reply_markup=kb,
    )


def _format_byn_amount(price_cents: int | None) -> str:
    if price_cents is None:
        return "цена не указана"
    return format_rubles_byn_display(price_cents / 100)


async def _complete_schedule_create_booking(
    callback: CallbackQuery,
    *,
    trainer_id: int,
    slot_id: int,
    client_id: int,
    service_price_variant_id: int | None,
) -> None:
    async with async_session_factory() as session:
        slot = await get_slot(session, slot_id)
    if not slot or slot.get("trainer_id") != trainer_id or (slot.get("status") or "").strip() != "available":
        await callback.message.answer(msg.TRAINER_CREATE_BOOKING_SLOT_UNAVAILABLE)
        return
    async with async_session_factory() as session:
        service_id = await get_first_service_id_for_trainer(session, trainer_id)
        if not service_id:
            await callback.message.answer(msg.TRAINER_ERROR_NO_SERVICES)
            return
        booking_id, booking_milestones = await create_booking(
            session,
            slot_id=slot_id,
            trainer_id=trainer_id,
            client_id=client_id,
            service_id=service_id,
            client_comment=None,
            client_request_id=None,
            created_by_trainer=True,
            service_price_variant_id=service_price_variant_id,
        )
    if not booking_id:
        await callback.message.answer(msg.TRAINER_CREATE_BOOKING_SLOT_UNAVAILABLE)
        return
    if not is_slot_end_in_past_local(slot.get("slot_date"), slot.get("end_time")):
        async with async_session_factory() as session:
            await generate_reminders_for_booking(session, booking_id)
    slot_date = slot.get("slot_date")
    start_time = slot.get("start_time")
    date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
    day_str = msg.TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
    time_str = _format_time(start_time)
    async with async_session_factory() as session:
        client_card = await get_trainer_client_for_card(session, trainer_id, client_id)
    client_name = _format_trainer_client_row_display_name(client_card)
    client_tg_id_raw = (client_card or {}).get("telegram_id")
    client_tg_id = int(client_tg_id_raw) if client_tg_id_raw else None

    client_is_sandbox = bool((client_card or {}).get("is_sandbox"))
    m_first, m_tip = booking_milestones
    settings_w = Settings()
    async with async_session_factory() as session:
        has_crm_sub = await _trainer_has_crm_subscription(session, trainer_id)
    if m_first:
        async with async_session_factory() as session:
            info_for_card = await get_booking_milestone_display_for_trainer(
                session, booking_id, trainer_id
            )
        if info_for_card:
            card_html = msg.format_trainer_first_booking_milestone_from_booking_row(info_for_card, created_by_trainer=True)
        else:
            card_html = (
                "✅ <b>Запись создана.</b>\n\n"
                + msg.TRAINER_FIRST_BOOKING_MILESTONE_FOOTER_SUBDUED_HTML
            )
        milestone_kb = msg.build_trainer_first_booking_milestone_reply_markup(
            webapp_base=settings_w.webapp_base_url or "",
            booking_id=booking_id,
            client_id=client_id,
            client_telegram_id=client_tg_id,
            trainer_has_crm=has_crm_sub,
            is_sandbox=client_is_sandbox,
        )
        await callback.message.answer(card_html, parse_mode=ParseMode.HTML, reply_markup=milestone_kb)
    else:
        keyboard_rows: list[list[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BUTTON_ADD_BOOKING_NOTE,
                    callback_data=f"{BOOKING_ADD_NOTE_PREFIX}{booking_id}",
                )
            ]
        ]
        if not client_tg_id:
            keyboard_rows.append(
                [
                    InlineKeyboardButton(
                        text=msg.TRAINER_BUTTON_INVITE_CLIENT_TO_BOT,
                        callback_data=f"{BOOKING_INVITE_CLIENT_PREFIX}{booking_id}",
                    )
                ]
            )
        async with async_session_factory() as session:
            reminder_plan = await format_trainer_reminder_plan_for_client_day(
                session,
                client_id=client_id,
                slot_date=slot_date,
                client_has_telegram=bool(client_tg_id),
            )
        client_confirmation = "не применимо: у клиента не привязан Telegram"
        if client_tg_id:
            client_confirmation = msg.TRAINER_CREATE_BOOKING_CLIENT_CONFIRMATION_QUEUED

        await callback.message.answer(
            msg.TRAINER_CREATE_BOOKING_DONE.format(
                client_name=html.escape(client_name),
                date=date_str,
                day=day_str,
                time=time_str,
                reminder_plan=html.escape(reminder_plan),
                client_confirmation=html.escape(client_confirmation),
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
        )
    await _send_first_booking_milestone_followups(
        callback.message,
        trainer_id,
        milestone=m_first,
        share_tip=m_tip,
        milestone_booking_id=booking_id,
        skip_milestone_card=m_first,
        created_by_trainer=True,
    )


@router.callback_query(lambda c: c.data and c.data.startswith(SCHEDULE_CREATE_BOOKING_CLIENT_PREFIX))
async def schedule_create_booking_choose_tariff(callback: CallbackQuery) -> None:
    """After client chosen, ask trainer to pick tariff (default is preselected first tier)."""
    await callback.answer()
    payload = (callback.data or "")[len(SCHEDULE_CREATE_BOOKING_CLIENT_PREFIX):]
    parts = payload.split(":")
    if len(parts) != 2:
        return
    slot_id = safe_parse_id(parts[0])
    client_id = safe_parse_id(parts[1])
    if slot_id is None or client_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        slot = await get_slot(session, slot_id)
    if not slot or slot.get("trainer_id") != trainer_id or (slot.get("status") or "").strip() != "available":
        await callback.message.answer(msg.TRAINER_CREATE_BOOKING_SLOT_UNAVAILABLE)
        return
    async with async_session_factory() as session:
        service_id = await get_first_service_id_for_trainer(session, trainer_id)
        if not service_id:
            await callback.message.answer(msg.TRAINER_ERROR_NO_SERVICES)
            return
        variants = await list_trainer_service_price_variants(session, trainer_id, service_id)
        client_card = await get_trainer_client_for_card(session, trainer_id, client_id)

    if not variants:
        await _complete_schedule_create_booking(
            callback,
            trainer_id=trainer_id,
            slot_id=slot_id,
            client_id=client_id,
            service_price_variant_id=None,
        )
        return

    slot_date = slot.get("slot_date")
    start_time = slot.get("start_time")
    date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
    day_str = msg.TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
    time_str = _format_time(start_time)
    client_name = _format_trainer_client_row_display_name(client_card)
    default_variant_id = int(variants[0]["id"])
    rows: list[list[InlineKeyboardButton]] = []
    for v in variants:
        variant_id = int(v["id"])
        is_default = variant_id == default_variant_id
        label = (v.get("label") or "Тариф").strip()
        price_text = _format_byn_amount(v.get("price_cents"))
        prefix = "✅ " if is_default else ""
        suffix = " (по умолчанию)" if is_default else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix}{label} · {price_text}{suffix}",
                    callback_data=f"{SCHEDULE_CREATE_BOOKING_TARIFF_PREFIX}{slot_id}:{client_id}:{variant_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text=msg.TRAINER_BUTTON_BACK_TO_SCHEDULE, callback_data=SCHEDULE_CALLBACK)])
    await callback.message.edit_text(
        msg.TRAINER_CREATE_BOOKING_CHOOSE_TARIFF.format(
            date=date_str,
            day=day_str,
            time=time_str,
            client_name=html.escape(client_name),
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(lambda c: c.data and c.data.startswith(SCHEDULE_CREATE_BOOKING_TARIFF_PREFIX))
async def schedule_create_booking_finalize(callback: CallbackQuery) -> None:
    """Create booking for chosen slot/client/tariff."""
    await callback.answer()
    payload = (callback.data or "")[len(SCHEDULE_CREATE_BOOKING_TARIFF_PREFIX):]
    parts = payload.split(":")
    if len(parts) != 3:
        return
    slot_id = safe_parse_id(parts[0])
    client_id = safe_parse_id(parts[1])
    service_price_variant_id = safe_parse_id(parts[2])
    if slot_id is None or client_id is None or service_price_variant_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    await _complete_schedule_create_booking(
        callback,
        trainer_id=trainer_id,
        slot_id=slot_id,
        client_id=client_id,
        service_price_variant_id=service_price_variant_id,
    )


@router.callback_query(lambda c: c.data == BOOKINGS_CALLBACK)
async def show_bookings(callback: CallbackQuery) -> None:
    """List = buttons: one per booking (page 0)."""
    await callback.answer()
    await _trainer_typing(callback.bot, callback.message.chat.id)
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if not await _trainer_has_crm_subscription(session, trainer_id):
            await callback.message.answer(
                msg.TRAINER_TIER_REQUIRED_CRM + "\n\n" + msg.TRAINER_TIER_CTA,
                parse_mode=ParseMode.HTML,
            )
            return
    text, keyboard = await _bookings_content(trainer_id, page=0)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(BOOKINGS_PAGE_PREFIX))
async def show_bookings_page(callback: CallbackQuery) -> None:
    """Pagination: show bookings list for given page."""
    await callback.answer()
    await _trainer_typing(callback.bot, callback.message.chat.id)
    page = safe_parse_id(callback.data[len(BOOKINGS_PAGE_PREFIX):])
    if page is None or page < 0:
        page = 0
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if not await _trainer_has_crm_subscription(session, trainer_id):
            await callback.message.answer(
                msg.TRAINER_TIER_REQUIRED_CRM + "\n\n" + msg.TRAINER_TIER_CTA,
                parse_mode=ParseMode.HTML,
            )
            return
    text, keyboard = await _bookings_content(trainer_id, page=page)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(BOOKING_DETAIL_PREFIX))
async def show_booking_detail(callback: CallbackQuery) -> None:
    """Tap-to-expand: one booking detail + Write / Cancel / Make regular or Remove regularity / Back."""
    await callback.answer()
    booking_id = safe_parse_id(callback.data[len(BOOKING_DETAIL_PREFIX):])
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        has_crm = await _trainer_has_crm_subscription(session, trainer_id)
        bookings = await list_bookings_for_trainer(session, trainer_id)
    b = next((x for x in bookings if x["id"] == booking_id), None)
    if not b:
        await callback.message.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
        return
    text = _booking_detail_text(b)
    async with async_session_factory() as session:
        booking = await get_booking_with_slot(session, booking_id, trainer_id)
        recurring = await get_active_recurring_for_booking(
            session, trainer_id, booking["client_id"],
            b["slot_date"].weekday(), b["start_time"],
        ) if booking else None
    base = (Settings().webapp_base_url or "").rstrip("/")
    https = base.startswith("https://")
    cid = int(booking["client_id"]) if booking and booking.get("client_id") is not None else None
    use_webapp_write = bool(booking and https and has_crm and cid is not None)
    write_btn = (
        InlineKeyboardButton(
            text=msg.TRAINER_BOOKINGS_BUTTON_WRITE,
            web_app=WebAppInfo(url=f"{base}/webapp/trainer-clients?client_id={cid}&open_write=1"),
        )
        if use_webapp_write
        else InlineKeyboardButton(
            text=msg.TRAINER_BOOKINGS_BUTTON_WRITE,
            callback_data=f"{WRITE_BOOKING_PREFIX}{booking_id}",
        )
    )
    rows = [
        [
            write_btn,
            InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_BUTTON_CANCEL, callback_data=f"{CANCEL_BOOKING_PREFIX}{booking_id}"),
        ],
    ]
    if recurring:
        rows.append([InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_BUTTON_REMOVE_REGULARITY, callback_data=f"{REMOVE_RECURRING_PREFIX}{recurring['id']}")])
    else:
        rows.append([InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_BUTTON_MAKE_REGULAR, callback_data=f"{MAKE_RECURRING_TRAINER_PREFIX}{booking_id}")])
    if (
        booking
        and https
        and booking.get("client_id") is not None
        and has_crm
    ):
        rows.insert(
            1,
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BUTTON_CLIENT_CARD_WEBAPP,
                    web_app=WebAppInfo(
                        url=f"{base}/webapp/trainer-clients?client_id={int(booking['client_id'])}"
                    ),
                ),
            ],
        )
    rows.append([InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_BUTTON_BACK_TO_LIST, callback_data=BOOKINGS_CALLBACK)])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(MAKE_RECURRING_TRAINER_PREFIX))
async def on_make_recurring_trainer(callback: CallbackQuery) -> None:
    """Create recurring slot from current booking (same weekday + time)."""
    await callback.answer()
    booking_id = safe_parse_id(callback.data[len(MAKE_RECURRING_TRAINER_PREFIX):])
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        booking = await get_booking_with_slot(session, booking_id, trainer_id)
    if not booking:
        await callback.message.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
        return
    client_id = booking["client_id"]
    day_of_week = booking["slot_date"].weekday()
    start_time = booking["start_time"]
    end_time = booking["end_time"]
    async with async_session_factory() as session:
        if not await get_first_service_id_for_trainer(session, trainer_id):
            await callback.message.answer(msg.TRAINER_RECURRING_NEEDS_SERVICE)
            return
        recurring_id = await create_recurring_client_slot(
            session, trainer_id, client_id, day_of_week, start_time, end_time
        )
        if recurring_id:
            hw = max(1, int(Settings().recurring_materialization_horizon_weeks))
            maintained = await maintain_recurring_horizon(
                session,
                trainer_id,
                horizon_weeks=hw,
                recurring_ids=[recurring_id],
            )
            materialized = int(maintained.get("created") or 0)
            if materialized <= 0:
                await cancel_recurring_client_slot(session, trainer_id, recurring_id)
                await callback.message.answer(msg.TRAINER_RECURRING_MATERIALIZE_INCOMPLETE)
                return
    await callback.message.answer(msg.TRAINER_RECURRING_DONE)


@router.callback_query(lambda c: c.data and c.data.startswith(REMOVE_RECURRING_PREFIX))
async def on_remove_recurring(callback: CallbackQuery) -> None:
    """Cancel recurring slot (status=cancelled)."""
    await callback.answer()
    recurring_id = safe_parse_id(callback.data[len(REMOVE_RECURRING_PREFIX):])
    if recurring_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        ok, _removed = await cancel_recurring_client_slot(session, trainer_id, recurring_id)
    if not ok:
        await callback.message.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
        return
    await callback.message.answer(msg.TRAINER_RECURRING_REMOVED)


@router.callback_query(lambda c: c.data and c.data.startswith(WRITE_BOOKING_PREFIX))
async def show_write_booking_link(callback: CallbackQuery) -> None:
    """Show single 'Write to client' link for chosen booking."""
    await callback.answer()
    booking_id = safe_parse_id(callback.data[len(WRITE_BOOKING_PREFIX):])
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        booking = await get_booking_with_slot(session, booking_id, trainer_id)
    if not booking:
        await callback.message.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
        return
    d = booking["slot_date"]
    date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
    start_time_str = _format_time(booking["start_time"])
    dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
    text = msg.TRAINER_BOOKINGS_WRITE_LINK.format(date=date_str, day=dow, time=start_time_str)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_BUTTON_WRITE_LINK, url=f"tg://user?id={booking['client_telegram_id']}")],
        [InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_BUTTON_BACK_TO_LIST, callback_data=BOOKINGS_CALLBACK)],
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(CONFIRM_BOOKING_PREFIX))
async def on_confirm_booking(callback: CallbackQuery) -> None:
    """Trainer tapped 'Подтвердить' for a booking: mark confirmed and notify both sides."""
    await callback.answer()
    booking_id = safe_parse_id(callback.data[len(CONFIRM_BOOKING_PREFIX) :])
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        info = await confirm_booking(session, booking_id, trainer_id)
    if not info:
        await callback.message.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
        return
    async with async_session_factory() as session:
        has_crm_sub = await _trainer_has_crm_subscription(session, trainer_id)
        expected_payment_class = await classify_booking_expected_payment_class(
            session, booking_id, trainer_id
        )
    d = info["slot_date"]
    date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
    dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
    start_time = info["start_time"]
    time_str = _format_time(start_time)
    client_name_raw = (info.get("client_name") or "").strip() or "Клиент"
    phone = (info.get("client_phone") or "").strip()
    m_first = bool(info.get("first_booking_milestone"))
    m_tip = bool(info.get("share_catalog_tip"))
    settings_echo = Settings()
    if not m_first:
        dur_min = _slot_duration_minutes(d, info.get("start_time"), info.get("end_time"))
        text_trainer = msg.format_trainer_booking_confirmed_echo_html(
            client_name=client_name_raw,
            client_phone=phone or None,
            date=date_str,
            day=dow,
            time=time_str,
            duration_minutes=dur_min,
            service_name=info.get("service_name"),
            booking_price_cents=info.get("booking_price_cents"),
            price_tier_label=info.get("price_tier_label"),
            arena_name=info.get("arena_name"),
            arena_address=info.get("arena_address"),
            expected_payment_class=expected_payment_class,
        )
        echo_kb = msg.build_trainer_booking_confirmed_echo_reply_markup(
            webapp_base=settings_echo.webapp_base_url or "",
            booking_id=booking_id,
            client_id=info.get("client_id"),
            client_telegram_id=info.get("client_telegram_id"),
            trainer_has_crm=has_crm_sub,
        )
        await callback.message.answer(
            text_trainer,
            parse_mode=ParseMode.HTML,
            reply_markup=echo_kb,
        )
    else:
        milestone_info = {**info, "expected_payment_class": expected_payment_class}
        card_html = msg.format_trainer_first_booking_milestone_from_booking_row(milestone_info, created_by_trainer=False)
        milestone_kb = msg.build_trainer_first_booking_milestone_reply_markup(
            webapp_base=settings_echo.webapp_base_url or "",
            booking_id=booking_id,
            client_id=info.get("client_id"),
            client_telegram_id=info.get("client_telegram_id"),
            trainer_has_crm=has_crm_sub,
            is_sandbox=bool(info.get("client_is_sandbox")),
        )
        await callback.message.answer(card_html, parse_mode=ParseMode.HTML, reply_markup=milestone_kb)
    # Notify client via client bot (separate token)
    client_tid = info.get("client_telegram_id")
    if client_tid:
        async with async_session_factory() as session:
            trainer_obj = await get_trainer(session, trainer_id)
        profile = (trainer_obj or {}).get("profile") or {}
        trainer_name = (
            ((profile.get("first_name") or "") + " " + (profile.get("last_name") or "")).strip()
            or "Тренер"
        )
        settings = Settings()
        client_bot = Bot(
            token=settings.telegram_bot_token_client,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        text_client = msg.format_client_booking_confirmed_by_trainer_text(
            date=date_str,
            day=dow,
            time=time_str,
            trainer_name=trainer_name,
            service_name=info.get("service_name"),
            booking_price_cents=info.get("booking_price_cents"),
            price_tier_label=info.get("price_tier_label"),
            arena_name=info.get("arena_name"),
            arena_address=info.get("arena_address"),
            trainer_first_booking_milestone=m_first,
            client_display_name=info.get("client_name"),
            client_phone=(info.get("client_phone") or "") or None,
            duration_minutes=info.get("duration_minutes"),
            expected_payment_class=expected_payment_class,
        )
        reply_markup = msg.build_client_booking_confirmed_inline_keyboard(
            map_url=info.get("map_link"),
            trainer_telegram_id=info.get("trainer_telegram_id"),
            booking_id=int(info["id"]),
            webapp_base_url=settings.webapp_base_url,
        )
        try:
            await client_bot.send_message(
                chat_id=client_tid,
                text=text_client,
                reply_markup=reply_markup,
            )
        finally:
            await client_bot.session.close()
    await _send_first_booking_milestone_followups(
        callback.message,
        trainer_id,
        milestone=m_first,
        share_tip=m_tip,
        milestone_booking_info=info,
        skip_milestone_card=m_first,
        created_by_trainer=False,
    )


@router.callback_query(lambda c: c.data and c.data.startswith(CANCEL_BOOKING_PREFIX))
async def show_cancel_booking_confirm(callback: CallbackQuery) -> None:
    """Show warning and confirm before cancelling a booking."""
    await callback.answer()
    booking_id = safe_parse_id(callback.data[len(CANCEL_BOOKING_PREFIX):])
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        booking = await get_booking_with_slot(session, booking_id, trainer_id)
    if not booking:
        await callback.message.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
        return
    d = booking["slot_date"]
    date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
    start_time_str = _format_time(booking["start_time"])
    dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
    text = msg.TRAINER_BOOKINGS_CANCEL_WARNING.format(date=date_str, day=dow, time=start_time_str)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_CANCEL_CONFIRM_YES, callback_data=f"{CANCEL_BOOKING_CONFIRM_PREFIX}{booking_id}")],
        [InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_CANCEL_CONFIRM_NO, callback_data=BOOKINGS_CALLBACK)],
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(CANCEL_BOOKING_CONFIRM_PREFIX))
async def on_cancel_booking_confirm(callback: CallbackQuery) -> None:
    """Cancel the booking and refresh the list."""
    await callback.answer()
    booking_id = safe_parse_id(callback.data[len(CANCEL_BOOKING_CONFIRM_PREFIX):])
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        ok = await cancel_booking(session, booking_id, trainer_id)
    if not ok:
        await callback.message.answer(msg.TRAINER_ERROR_CANCEL_FAILED)
        return
    settings = Settings()
    client_bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        async with async_session_factory() as session:
            await send_trainer_cancel_notification_for_booking_now(
                client_bot, session, booking_id
            )
    finally:
        await client_bot.session.close()
    audit_log("booking.cancelled", ACTOR_TRAINER_BOT, telegram_id, {"booking_id": booking_id, "trainer_id": trainer_id})
    text, keyboard = await _bookings_content(trainer_id)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.message.answer(msg.TRAINER_BOOKINGS_CANCELLED)


@router.callback_query(lambda c: c.data and c.data.startswith(DECLINE_BOOKING_PREFIX))
async def on_decline_booking_start(callback: CallbackQuery) -> None:
    """Trainer tapped 'Отклонить' in notification: optional comment, then decline."""
    await callback.answer()
    booking_id = safe_parse_id(callback.data[len(DECLINE_BOOKING_PREFIX) :])
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        booking = await get_booking_with_slot(session, booking_id, trainer_id)
    if not booking:
        await callback.message.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
        return
    status = (booking.get("status") or "").strip().lower()
    if status != "pending":
        await callback.message.answer(_booking_decline_blocked_message(status))
        return
    _set_booking_decline_state(telegram_id, booking_id)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BOOKING_DECLINE_SKIP,
                    callback_data=f"{DECLINE_BOOKING_SKIP_PREFIX}{booking_id}",
                )
            ],
        ]
    )
    await callback.message.answer(msg.TRAINER_BOOKING_DECLINE_PROMPT, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(DECLINE_BOOKING_SKIP_PREFIX))
async def on_decline_booking_skip(callback: CallbackQuery) -> None:
    """Trainer taps 'Отправить без комментария' on pending booking decline."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    booking_id = safe_parse_id(callback.data[len(DECLINE_BOOKING_SKIP_PREFIX) :])
    if booking_id is None or _booking_decline_state.get(telegram_id) != booking_id:
        _clear_booking_decline_state(telegram_id)
        return
    if not callback.message:
        return
    await _complete_trainer_booking_decline(
        telegram_id=telegram_id,
        booking_id=booking_id,
        comment=None,
        reply=callback.message,
    )


@router.callback_query(lambda c: c.data and c.data.startswith(BOOKING_INVITE_CLIENT_PREFIX))
async def on_booking_invite_client_to_bot(callback: CallbackQuery) -> None:
    """Trainer invites client to bot: same permanent welcome_ref link as hub paperclip."""
    await callback.answer("Ссылка...")
    booking_id = safe_parse_id((callback.data or "").replace(BOOKING_INVITE_CLIENT_PREFIX, "").strip())
    if booking_id is None:
        logger.warning("on_booking_invite_client_to_bot: invalid booking_id %s", callback.data)
        await callback.message.answer("Ошибка: неверный ID записи.")
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        booking = await get_booking_with_slot(session, booking_id, trainer_id)
    if not booking or booking.get("client_id") is None:
        logger.warning(
            "on_booking_invite_client_to_bot: booking %s not found for trainer %s or client missing",
            booking_id,
            trainer_id,
        )
        await callback.message.answer("Ошибка: запись не найдена или клиент не привязан.")
        return
    client_id = booking["client_id"]
    settings = Settings()
    deep_link, err = build_trainer_universal_invite_link(
        client_bot_username=settings.client_bot_username,
        trainer_id=int(trainer_id),
    )
    if err == "missing_username" or not deep_link:
        await callback.message.answer(
            "Ошибка: не настроено имя клиентского бота для ссылок. Свяжитесь с администратором."
        )
        return
    async with async_session_factory() as session:
        client_card = await get_trainer_client_for_card(session, trainer_id, client_id)
    await callback.message.answer(
        msg.TRAINER_CLIENT_INVITE_LINK_FOR_TRAINER.format(
            client_name=html.escape(_format_trainer_client_row_display_name(client_card)),
            deep_link=html.escape(deep_link),
        ),
        parse_mode=ParseMode.HTML,
    )
    async with async_session_factory() as session:
        await record_trainer_client_invite_link_first_copy(session, trainer_id)

@router.callback_query(lambda c: c.data and c.data.startswith(TRAINER_REPEAT_WEEK_PREFIX))
async def on_trainer_repeat_week(callback: CallbackQuery) -> None:
    """Book same client on the same interval one calendar week after the completed session (trainer push)."""
    await callback.answer()
    raw = (callback.data or "").replace(TRAINER_REPEAT_WEEK_PREFIX, "").strip()
    booking_id = safe_parse_id(raw)
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        out = await trainer_repeat_booking_same_time_next_week(session, booking_id, trainer_id)
    if not out.get("success"):
        err = out.get("error") or "create_failed"
        if err == "not_found":
            text = msg.TRAINER_REPEAT_BOOKING_NOT_FOUND
        elif err == "slot_booked":
            text = msg.TRAINER_REPEAT_BOOKING_SLOT_BOOKED
        elif err == "no_service":
            text = msg.TRAINER_REPEAT_BOOKING_NO_SERVICE
        elif err == "price_tier_required":
            text = msg.TRAINER_REPEAT_BOOKING_PRICE_TIER
        elif err == "schedule_error":
            detail = (out.get("message") or "—").strip()
            text = msg.TRAINER_REPEAT_BOOKING_SCHEDULE_ERROR.format(detail=html.escape(detail))
        else:
            text = msg.TRAINER_REPEAT_BOOKING_CREATE_FAILED
        await callback.message.answer(text)
        return
    sd = out.get("slot_date")
    tm = out.get("start_time")
    date_str = sd.strftime("%d.%m") if sd and hasattr(sd, "strftime") else "—"
    day_str = msg.TRAINER_DAYS[sd.weekday()] if sd and hasattr(sd, "weekday") else ""
    time_str = tm.strftime("%H:%M") if tm and hasattr(tm, "strftime") else "—"
    await callback.message.answer(
        msg.TRAINER_REPEAT_BOOKING_OK.format(date=date_str, day=day_str, time=time_str),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(lambda c: c.data and c.data.startswith(FEEDBACK_BOOKING_TRAINER_PREFIX))
async def on_feedback_booking_trainer(callback: CallbackQuery) -> None:
    """Trainer tapped 'Leave feedback' after session (wrap-up or completed): ask for optional review text."""
    await callback.answer()
    raw = (callback.data or "").replace(FEEDBACK_BOOKING_TRAINER_PREFIX, "").strip()
    booking_id = safe_parse_id(raw)
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        booking = await get_booking_for_trainer_feedback(session, booking_id, trainer_id)
    if not booking:
        await callback.message.answer(msg.TRAINER_ERROR_BOOKING_CLOSED_OR_NOT_FOUND)
        return
    _trainer_feedback_state[telegram_id] = {"booking_id": booking_id, "trainer_id": trainer_id}
    await callback.message.answer(msg.TRAINER_FEEDBACK_PROMPT)


@router.callback_query(lambda c: c.data and c.data.startswith(BOOKING_ADD_NOTE_PREFIX))
async def on_booking_add_note_start(callback: CallbackQuery) -> None:
    """Quick CTA after booking creation: ask trainer for a dated note to client timeline."""
    await callback.answer()
    raw = (callback.data or "").replace(BOOKING_ADD_NOTE_PREFIX, "").strip()
    booking_id = safe_parse_id(raw)
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        booking = await get_booking_with_slot(session, booking_id, trainer_id)
        detail = await get_trainer_booking_detail_payload(session, booking_id, trainer_id)
    if not booking:
        await callback.message.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
        return
    slot_date = booking.get("slot_date")
    start_time = booking.get("start_time")
    date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
    day_str = msg.TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
    time_str = _format_time(start_time)
    first = (detail or {}).get("client_first_name") or ""
    last = (detail or {}).get("client_last_name") or ""
    client_name = f"{first} {last}".strip() or (booking.get("client_phone") or "Клиент")
    _trainer_booking_note_state[telegram_id] = {
        "trainer_id": trainer_id,
        "client_id": int(booking["client_id"]),
        "slot_date": slot_date,
        "start_time": start_time,
    }
    trainer_booking_note_awaiting.add(telegram_id)
    clear_trainer_relay_reply_pending(telegram_id)
    await callback.message.answer(
        msg.TRAINER_ADD_BOOKING_NOTE_PROMPT.format(
            client_name=html.escape(client_name),
            date=date_str,
            day=day_str,
            time=time_str,
        ),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith(BOOKING_NOTIFY_RELAY_WRITE_PREFIX))
async def on_booking_notify_relay_write(callback: CallbackQuery) -> None:
    """Booking push «Написать»: relay when client telegram equals trainer (tg://user?id=self is invalid)."""
    if not Settings().trainer_booking_self_client_relay_button:
        await callback.answer(msg.TRAINER_BOOKING_RELAY_SELF_DISABLED, show_alert=True)
        return
    if not callback.message:
        await callback.answer()
        return
    tg_id = callback.from_user.id if callback.from_user else 0
    raw = (callback.data or "").replace(BOOKING_NOTIFY_RELAY_WRITE_PREFIX, "").strip()
    booking_id = safe_parse_id(raw)
    if not tg_id or booking_id is None:
        await callback.answer(msg.TRAINER_ERROR_REQUEST_BOOK_PAYLOAD_SHORT, show_alert=True)
        return
    await callback.answer()
    await sweep_idle_relay_sessions_and_notify()
    async with async_session_factory() as session:
        trainer_row_id = await get_trainer_id_for_webapp_trainer_operations(session, tg_id)
        if not trainer_row_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        booking = await get_booking_with_slot(session, booking_id, trainer_row_id)
        if not booking:
            await callback.message.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
            return
        ctg = booking.get("client_telegram_id")
        try:
            same_person = ctg is not None and int(ctg) == int(tg_id) and int(tg_id) > 0
        except (TypeError, ValueError):
            same_person = False
        if not same_person:
            await callback.message.answer(msg.TRAINER_BOOKING_RELAY_SELF_NOT_SELF_CLIENT)
            return
        cid = booking.get("client_id")
        if cid is None:
            await callback.message.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
            return
        if not await trainer_has_access_to_client(session, int(trainer_row_id), int(cid)):
            await callback.message.answer(msg.TRAINER_CERT_ORDER_RELAY_TRAINER_CANT_ACCESS_CLIENT)
            return
        sid = await open_relay_session(session, trainer_id=int(trainer_row_id), client_id=int(cid))
        await session.commit()

    set_trainer_relay_reply_pending(int(tg_id), int(sid))
    await callback.message.answer(msg.TRAINER_RELAY_REPLY_PROMPT)


@router.message(lambda m: m.from_user and m.from_user.id in _trainer_feedback_state)
async def on_trainer_feedback_message(message: Message) -> None:
    """Trainer sent review text for a booking (any stage where feedback CTA is shown)."""
    telegram_id = message.from_user.id if message.from_user else 0
    state = _trainer_feedback_state.pop(telegram_id, None)
    if not state:
        return
    text = (message.text or "").strip() or ""
    async with async_session_factory() as session:
        ok = await set_booking_trainer_review(
            session, state["booking_id"], state["trainer_id"], text
        )
    if ok:
        audit_log("trainer.review", ACTOR_TRAINER_BOT, telegram_id, {"booking_id": state["booking_id"], "trainer_id": state["trainer_id"]})
        await message.answer(msg.TRAINER_FEEDBACK_THANKS)
    else:
        await message.answer(msg.TRAINER_ERROR_FEEDBACK_SAVE_FAILED)


@router.message(lambda m: m.from_user and m.from_user.id in _trainer_booking_note_state)
async def on_booking_note_message(message: Message) -> None:
    """Save quick trainer note into client dossier timeline with lesson date/time."""
    telegram_id = message.from_user.id if message.from_user else 0
    state = _trainer_booking_note_state.get(telegram_id)
    if not state:
        return
    raw_text = (message.text or "").strip()
    if not raw_text:
        await message.answer(msg.TRAINER_ADD_BOOKING_NOTE_REQUIRED)
        return
    text = truncate_text(raw_text, 2000)
    slot_date = state.get("slot_date")
    start_time = state.get("start_time")
    # Keep timeline chronological by lesson datetime, not by message send time.
    if slot_date and start_time and hasattr(slot_date, "year") and hasattr(start_time, "hour"):
        entry_dt = datetime.combine(slot_date, start_time)
    else:
        entry_dt = datetime.now()
    async with async_session_factory() as session:
        await add_client_entry_with_date(
            session,
            trainer_id=int(state["trainer_id"]),
            client_id=int(state["client_id"]),
            content=text,
            entry_date=entry_dt,
        )
    _trainer_booking_note_state.pop(telegram_id, None)
    trainer_booking_note_awaiting.discard(telegram_id)
    await message.answer(msg.TRAINER_ADD_BOOKING_NOTE_SAVED)


@router.message(lambda m: m.from_user and m.from_user.id in _booking_decline_state)
async def on_decline_booking_comment(message: Message) -> None:
    """Trainer sent optional decline comment for pending booking."""
    telegram_id = message.from_user.id if message.from_user else 0
    booking_id = _booking_decline_state.get(telegram_id)
    if booking_id is None:
        return
    raw_comment = (message.text or "").strip()
    comment = truncate_text(raw_comment, MAX_COMMENT_LEN) if raw_comment else None
    ok = await _complete_trainer_booking_decline(
        telegram_id=telegram_id,
        booking_id=booking_id,
        comment=comment,
        reply=message,
    )


@router.message(lambda m: m.text and m.from_user and m.from_user.id in _request_respond_state)
async def on_request_respond_comment_message(message: Message) -> None:
    """Trainer sent comment text for their response to a request."""
    telegram_id = message.from_user.id if message.from_user else 0
    request_id = _request_respond_state.pop(telegram_id, None)
    if request_id is None:
        return
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    comment = truncate_text(message.text, MAX_COMMENT_LEN)
    async with async_session_factory() as session:
        resp_id = await create_request_response(session, request_id, trainer_id, trainer_comment=comment)
    if resp_id is None:
        await message.answer(msg.TRAINER_ERROR_RESPOND_FAILED)
        return
    audit_log("request_response.created", ACTOR_TRAINER_BOT, telegram_id, {"request_id": request_id, "trainer_id": trainer_id, "response_id": resp_id})
    await message.answer(msg.TRAINER_RESPOND_SUCCESS)
    text, keyboard = await _requests_content(trainer_id)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == REQUESTS_CALLBACK)
async def show_requests(callback: CallbackQuery) -> None:
    """Open requests list: Новые / В работе, page 0."""
    await callback.answer()
    await _trainer_typing(callback.bot, callback.message.chat.id)
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if not await _trainer_has_crm_subscription(session, trainer_id):
            await callback.message.answer(
                msg.TRAINER_TIER_REQUIRED_CRM + "\n\n" + msg.TRAINER_TIER_CTA,
                parse_mode=ParseMode.HTML,
            )
            return
    text, keyboard = await _requests_content(trainer_id)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(REQUESTS_PAGE_PREFIX))
async def show_requests_page(callback: CallbackQuery) -> None:
    """Pagination: callback_data = requests_page:offset."""
    await callback.answer()
    await _trainer_typing(callback.bot, callback.message.chat.id)
    suffix = callback.data[len(REQUESTS_PAGE_PREFIX):].strip()
    offset = safe_parse_id(suffix) if suffix else 0
    if offset is None or offset < 0:
        offset = 0
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if not await _trainer_has_crm_subscription(session, trainer_id):
            await callback.message.answer(
                msg.TRAINER_TIER_REQUIRED_CRM + "\n\n" + msg.TRAINER_TIER_CTA,
                parse_mode=ParseMode.HTML,
            )
            return
    text, keyboard = await _requests_content(trainer_id, offset=offset)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(REQUEST_DETAIL_PREFIX))
async def show_request_detail(callback: CallbackQuery) -> None:
    """Tap-to-expand: one request detail + Готов взять / Вы откликнулись + К списку."""
    await callback.answer()
    await _trainer_typing(callback.bot, callback.message.chat.id)
    raw = callback.data[len(REQUEST_DETAIL_PREFIX):]
    request_id = safe_parse_id(raw)
    if request_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        requests_list = await list_requests_for_trainer(session, trainer_id)
    req = next((r for r in requests_list if r["id"] == request_id), None)
    if not req:
        await callback.message.answer(msg.TRAINER_ERROR_REQUEST_GONE)
        return
    text = _request_detail_text(req)
    if req.get("has_responded"):
        request_id = req["id"]
        button_rows = [
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_REQUEST_BOOK_CLIENT,
                    callback_data=f"{REQUEST_BOOK_CLIENT_PREFIX}{request_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_REQUEST_REMIND_WHEN_SLOTS,
                    callback_data=f"{REQUEST_REMIND_SLOTS_PREFIX}{request_id}",
                ),
            ],
            [InlineKeyboardButton(text=msg.TRAINER_REQUESTS_BACK_TO_LIST, callback_data=REQUESTS_CALLBACK)],
        ]
    else:
        button_rows = [
            [InlineKeyboardButton(text=msg.TRAINER_BUTTON_RESPOND, callback_data=f"{REQUEST_RESPOND_PREFIX}{request_id}")],
            [InlineKeyboardButton(text=msg.TRAINER_REQUESTS_BACK_TO_LIST, callback_data=REQUESTS_CALLBACK)],
        ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    await callback.message.edit_text(text, reply_markup=keyboard)


async def _trainer_open_relay_chat_for_client_request(
    *,
    callback: CallbackQuery,
    trainer_telegram_id: int,
    request_id: int,
) -> None:
    """Shared: open relay after callback.answer() (avoids Telegram callback timeout)."""
    await sweep_idle_relay_sessions_and_notify()
    async with async_session_factory() as session:
        p = await get_client_request_notification_payload_for_trainer(
            session,
            trainer_telegram_id=trainer_telegram_id,
            request_id=request_id,
        )
        if not p:
            if callback.message:
                await callback.message.answer(msg.TRAINER_ERROR_REQUEST_GONE)
            return
        trainer_row_id = await get_trainer_id_for_webapp_trainer_operations(session, trainer_telegram_id)
        if not trainer_row_id:
            if callback.message:
                await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        cid = p.get("client_id")
        if cid is None:
            if callback.message:
                await callback.message.answer(msg.TRAINER_ERROR_REQUEST_GONE)
            return
        if p.get("client_telegram_id") is None:
            if callback.message:
                await callback.message.answer(msg.TRAINER_CERT_ORDER_RELAY_NO_CLIENT_TELEGRAM)
            return
        if not await trainer_has_access_to_client(session, int(trainer_row_id), int(cid)):
            if callback.message:
                await callback.message.answer(msg.TRAINER_CERT_ORDER_RELAY_TRAINER_CANT_ACCESS_CLIENT)
            return
        sid = await open_relay_session(session, trainer_id=int(trainer_row_id), client_id=int(cid))
        await session.commit()

    set_trainer_relay_reply_pending(int(trainer_telegram_id), int(sid))
    if callback.message:
        await callback.message.answer(msg.TRAINER_RELAY_REPLY_PROMPT)


def _client_request_relay_callback_request_id(data: str) -> int | None:
    """Parse request id from cq_rly: or legacy co_rly: callback_data."""
    if data.startswith(msg.CLIENT_REQUEST_RELAY_CHAT_PREFIX):
        return safe_parse_id(data[len(msg.CLIENT_REQUEST_RELAY_CHAT_PREFIX) :])
    if data.startswith(msg.CERT_ORDER_FALLBACK_RELAY_CALLBACK_PREFIX):
        return safe_parse_id(data[len(msg.CERT_ORDER_FALLBACK_RELAY_CALLBACK_PREFIX) :])
    return None


@router.callback_query(
    lambda c: c.data
    and (
        str(c.data).startswith(msg.CLIENT_REQUEST_RELAY_CHAT_PREFIX)
        or str(c.data).startswith(msg.CERT_ORDER_FALLBACK_RELAY_CALLBACK_PREFIX)
    )
)
async def on_client_request_relay_chat(callback: CallbackQuery) -> None:
    """«Написать клиенту» в пуше по заявке (абонемент/сертификат) или legacy co_rly: — relay в боте."""
    if not callback.message:
        await callback.answer()
        return
    tg_id = callback.from_user.id if callback.from_user else 0
    req_id = _client_request_relay_callback_request_id(str(callback.data or ""))
    if not tg_id or req_id is None:
        await callback.answer(msg.TRAINER_ERROR_REQUEST_BOOK_PAYLOAD_SHORT, show_alert=True)
        return
    await callback.answer()
    await _trainer_open_relay_chat_for_client_request(
        callback=callback,
        trainer_telegram_id=int(tg_id),
        request_id=int(req_id),
    )


@router.callback_query(F.data.startswith(msg.CERT_ORDER_FALLBACK_PROMPT_CALLBACK_PREFIX))
async def on_cert_order_fallback_followup_message(callback: CallbackQuery) -> None:
    """Legacy «Чат не открылся» — сразу открывает relay (старые уведомления с tg:// + этой кнопкой)."""
    if not callback.message:
        await callback.answer()
        return
    tg_id = callback.from_user.id if callback.from_user else 0
    raw = callback.data or ""
    req_id = safe_parse_id(raw[len(msg.CERT_ORDER_FALLBACK_PROMPT_CALLBACK_PREFIX) :])
    if not tg_id or req_id is None:
        await callback.answer(msg.TRAINER_ERROR_REQUEST_BOOK_PAYLOAD_SHORT, show_alert=True)
        return
    await callback.answer()
    await _trainer_open_relay_chat_for_client_request(
        callback=callback,
        trainer_telegram_id=int(tg_id),
        request_id=int(req_id),
    )


@router.callback_query(F.data.startswith(msg.CERT_ORDER_FALLBACK_DISMISS_CALLBACK_PREFIX))
async def on_cert_order_fallback_followup_dismiss(callback: CallbackQuery) -> None:
    """Remove buttons from the fallback follow-up message."""
    await callback.answer()
    if not callback.message:
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise


@router.callback_query(lambda c: c.data and c.data.startswith(REQUEST_RESPOND_PREFIX))
async def on_request_respond(callback: CallbackQuery) -> None:
    """Trainer taps 'Готов взять': ask optional comment, then create response."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    request_id = safe_parse_id(callback.data[len(REQUEST_RESPOND_PREFIX):])
    if request_id is None:
        return
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    _request_respond_state[telegram_id] = request_id
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.TRAINER_RESPOND_SKIP, callback_data=f"{REQUEST_RESPOND_SKIP_PREFIX}{request_id}")],
    ])
    await callback.message.edit_text(msg.TRAINER_RESPOND_PROMPT_COMMENT, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(REQUEST_RESPOND_SKIP_PREFIX))
async def on_request_respond_skip(callback: CallbackQuery) -> None:
    """Trainer taps 'Отправить без комментария': create response with no comment."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    request_id = safe_parse_id(callback.data[len(REQUEST_RESPOND_SKIP_PREFIX):])
    if request_id is None or _request_respond_state.get(telegram_id) != request_id:
        _request_respond_state.pop(telegram_id, None)
        return
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        _request_respond_state.pop(telegram_id, None)
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    _request_respond_state.pop(telegram_id, None)
    async with async_session_factory() as session:
        resp_id = await create_request_response(session, request_id, trainer_id, trainer_comment=None)
    if resp_id is None:
        await callback.message.answer(msg.TRAINER_ERROR_RESPOND_FAILED)
        return
    audit_log("request_response.created", ACTOR_TRAINER_BOT, telegram_id, {"request_id": request_id, "trainer_id": trainer_id, "response_id": resp_id})
    await callback.message.answer(msg.TRAINER_RESPOND_SUCCESS)
    text, keyboard = await _requests_content(trainer_id)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(REQUEST_DECLINE_PREFIX))
async def on_request_decline(callback: CallbackQuery) -> None:
    """Trainer taps 'Отклонить': record decline, hide from list; client is not notified."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    request_id = safe_parse_id(callback.data[len(REQUEST_DECLINE_PREFIX):])
    if request_id is None:
        return
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        ok = await create_request_decline(session, request_id, trainer_id)
    if not ok:
        await callback.answer(msg.TRAINER_ERROR_RESPOND_FAILED, show_alert=True)
        return
    await callback.answer(msg.TRAINER_REQUEST_DECLINED, show_alert=True)
    # Remove buttons from notification message so trainer sees confirmation
    await callback.message.edit_text(
        callback.message.text + "\n\n" + msg.TRAINER_REQUEST_DECLINED,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),
    )


@router.callback_query(lambda c: c.data and c.data.startswith(REQUEST_REMIND_SLOTS_PREFIX))
async def on_request_remind_slots(callback: CallbackQuery) -> None:
    """Trainer taps 'Напомнить когда появятся слоты': store pending, confirm."""
    await callback.answer()
    request_id = safe_parse_id(callback.data[len(REQUEST_REMIND_SLOTS_PREFIX):])
    if request_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        await add_trainer_pending_request_booking(session, trainer_id, request_id)
    await callback.message.answer(msg.TRAINER_REQUEST_REMIND_SLOTS_SET)


@router.callback_query(lambda c: c.data and c.data.startswith(REQUEST_BOOK_CLIENT_PREFIX))
async def on_request_book_client(callback: CallbackQuery) -> None:
    """Trainer taps 'Записать клиента': show available slots for next 2 weeks, link to request."""
    await callback.answer()
    await _trainer_typing(callback.bot, callback.message.chat.id)
    request_id = safe_parse_id(callback.data[len(REQUEST_BOOK_CLIENT_PREFIX):])
    if request_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        client_info = await get_request_client_for_trainer_booking(session, request_id, trainer_id)
    if not client_info:
        await callback.message.answer(msg.TRAINER_ERROR_REQUEST_GONE)
        return
    today = date.today()
    to_date = today + timedelta(days=14)
    async with async_session_factory() as session:
        slots = await list_slots(session, trainer_id, today, to_date)
    available = [s for s in slots if (s.get("status") or "") == "available"]
    if not available:
        await callback.message.answer(msg.TRAINER_REQUEST_BOOK_NO_SLOTS_TWO_WEEKS)
        return
    rows = []
    for s in available:
        d = s["slot_date"]
        date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
        dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
        time_range = _format_slot_time(s["start_time"], s["end_time"])
        label = f"{date_str} {dow} {time_range}"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"{REQUEST_BOOK_SLOT_PREFIX}{s['id']}:{request_id}",
        )])
    rows.append([InlineKeyboardButton(text=msg.TRAINER_REQUESTS_BACK_TO_LIST, callback_data=REQUESTS_CALLBACK)])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.answer(msg.TRAINER_REQUEST_BOOK_CHOOSE_SLOT, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(REQUEST_BOOK_SLOT_PREFIX))
async def on_request_book_slot(callback: CallbackQuery) -> None:
    """Trainer chose slot for request: create booking, archive request, clear pending, notify success."""
    await callback.answer()
    payload = callback.data[len(REQUEST_BOOK_SLOT_PREFIX):].strip()
    parts = payload.split(":")
    if len(parts) != 2:
        await callback.message.answer(msg.TRAINER_ERROR_REQUEST_BOOK_PAYLOAD)
        return
    slot_id = safe_parse_id(parts[0])
    request_id = safe_parse_id(parts[1])
    if slot_id is None or request_id is None:
        await callback.message.answer(msg.TRAINER_ERROR_REQUEST_BOOK_PAYLOAD_SHORT)
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        client_info = await get_request_client_for_trainer_booking(session, request_id, trainer_id)
    if not client_info:
        await callback.message.answer(msg.TRAINER_ERROR_REQUEST_GONE)
        return
    async with async_session_factory() as session:
        booking_id, booking_milestones = await create_booking(
            session,
            slot_id=slot_id,
            trainer_id=trainer_id,
            client_id=client_info["client_id"],
            service_id=client_info["service_id"],
            client_comment=None,
            client_request_id=request_id,
            created_by_trainer=True,
        )
    if not booking_id:
        await callback.message.answer(msg.TRAINER_ERROR_SLOT_TAKEN_FOR_REQUEST)
        return
    async with async_session_factory() as session:
        await clear_trainer_pending_request_booking(session, trainer_id, request_id)
    async with async_session_factory() as session:
        slot_for_rem = await get_slot(session, slot_id)
    if slot_for_rem and not is_slot_end_in_past_local(
        slot_for_rem.get("slot_date"), slot_for_rem.get("end_time")
    ):
        async with async_session_factory() as session:
            await generate_reminders_for_booking(session, booking_id)
    await callback.message.answer(msg.TRAINER_REQUEST_BOOK_SUCCESS)
    m_first, m_tip = booking_milestones
    await _send_first_booking_milestone_followups(
        callback.message,
        trainer_id,
        milestone=m_first,
        share_tip=m_tip,
        milestone_booking_id=booking_id,
        created_by_trainer=True,
    )
    audit_log("request.trainer_booked_client", ACTOR_TRAINER_BOT, telegram_id, {"request_id": request_id, "trainer_id": trainer_id, "booking_id": booking_id})


@router.callback_query(lambda c: c.data == SCHEDULE_ADD)
async def schedule_add_start(callback: CallbackQuery) -> None:
    """Choose: add to template or to a specific week."""
    await callback.answer()
    this_m = this_week_monday()
    next_m = next_week_monday()
    s1, e1 = _week_range(this_m)
    s2, e2 = _week_range(next_m)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.TRAINER_SCHEDULE_ADD_TO_TEMPLATE_BUTTON, callback_data=SCHEDULE_ADD_TEMPLATE)],
        [InlineKeyboardButton(text=msg.TRAINER_SCHEDULE_THIS_WEEK.format(start=s1, end=e1), callback_data=f"{SCHEDULE_WEEK_PREFIX}{this_m.isoformat()}")],
        [InlineKeyboardButton(text=msg.TRAINER_SCHEDULE_NEXT_WEEK.format(start=s2, end=e2), callback_data=f"{SCHEDULE_WEEK_PREFIX}{next_m.isoformat()}")],
    ])
    await callback.message.edit_text(msg.TRAINER_SCHEDULE_CHOOSE_WEEK, reply_markup=keyboard)


def _day_picker_keyboard(with_back_to_schedule: bool = False) -> InlineKeyboardMarkup:
    """Day-of-week picker: 7 days. Optionally add a Back row to main schedule."""
    rows = [[InlineKeyboardButton(text=msg.TRAINER_DAYS[i], callback_data=f"{SCHEDULE_DAY_PREFIX}{i}")] for i in range(7)]
    if with_back_to_schedule:
        rows.append([InlineKeyboardButton(text=msg.TRAINER_BUTTON_BACK_TO_SCHEDULE, callback_data=SCHEDULE_CANCEL_ADD)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(lambda c: c.data == SCHEDULE_ADD_TEMPLATE)
async def schedule_add_template(callback: CallbackQuery) -> None:
    """Add to template: choose day, with Back to schedule."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    _schedule_add_state[telegram_id] = {"day": None, "hours": set()}
    await callback.message.edit_text(
        msg.TRAINER_SCHEDULE_CHOOSE_DAY,
        reply_markup=_day_picker_keyboard(with_back_to_schedule=True),
    )


@router.callback_query(lambda c: c.data and c.data.startswith(SCHEDULE_WEEK_PREFIX))
async def schedule_add_for_week(callback: CallbackQuery) -> None:
    """Add to a specific week: store week_start, show day picker with Back."""
    await callback.answer()
    week_start_str = callback.data[len(SCHEDULE_WEEK_PREFIX):]
    telegram_id = callback.from_user.id if callback.from_user else 0
    _schedule_add_state[telegram_id] = {"week_start": week_start_str, "day": None, "hours": set()}
    await callback.message.edit_text(
        msg.TRAINER_SCHEDULE_CHOOSE_DAY,
        reply_markup=_day_picker_keyboard(with_back_to_schedule=True),
    )


def _time_grid_keyboard(day: int, selected: set[int], locked: set[int] | None = None) -> InlineKeyboardMarkup:
    """Hours 8–20: ✓ for selected, ✓N🔒 for booked (not toggleable); then Готово and Отмена."""
    locked = locked or set()
    rows = []
    row1 = []
    for h in range(8, 14):
        label = f"✓{h}" if h in selected else str(h)
        if h in locked:
            label = f"✓{h}🔒"
            row1.append(InlineKeyboardButton(text=label, callback_data=f"{SCHEDULE_TIME_LOCKED_PREFIX}{day}:{h}"))
        else:
            row1.append(InlineKeyboardButton(text=label, callback_data=f"{SCHEDULE_TIME_PREFIX}{day}:{h}"))
    rows.append(row1)
    row2 = []
    for h in range(14, 21):
        label = f"✓{h}" if h in selected else str(h)
        if h in locked:
            label = f"✓{h}🔒"
            row2.append(InlineKeyboardButton(text=label, callback_data=f"{SCHEDULE_TIME_LOCKED_PREFIX}{day}:{h}"))
        else:
            row2.append(InlineKeyboardButton(text=label, callback_data=f"{SCHEDULE_TIME_PREFIX}{day}:{h}"))
    rows.append(row2)
    rows.append([
        InlineKeyboardButton(text=msg.TRAINER_SCHEDULE_DONE.format(count=len(selected)), callback_data=f"{SCHEDULE_DONE_PREFIX}{day}"),
        InlineKeyboardButton(text=msg.TRAINER_SCHEDULE_CANCEL_ADD, callback_data=SCHEDULE_CANCEL_ADD),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _hour_from_start_time(st) -> int:
    """Extract hour (0–23) from start_time (time or string)."""
    if hasattr(st, "hour"):
        return st.hour
    s = str(st)
    return int(s.split(":")[0]) if ":" in s else int(s[:2])


def _time_tuple_from_start(st) -> tuple[int, int, int]:
    """(hour, minute, second) from DB time or string."""
    if hasattr(st, "hour"):
        return (
            int(st.hour),
            int(st.minute),
            int(getattr(st, "second", 0) or 0),
        )
    s = str(st).strip()
    parts = s.split(":")
    h = int(parts[0]) if parts else 0
    m = int(parts[1]) if len(parts) > 1 else 0
    sec = int(parts[2]) if len(parts) > 2 else 0
    return (h, m, sec)


async def _merge_week_slot_minutes_with_preserves(
    session,
    trainer_id: int,
    slot_date: date,
    hours: set[int],
) -> set[int]:
    """User-selected whole hours + available slots not on :00 (Mini App only)."""
    start_minutes = {h * 60 for h in hours}
    slots = await list_slots(session, trainer_id, slot_date, slot_date)
    for s in slots:
        hh, mi, sec = _time_tuple_from_start(s["start_time"])
        if mi != 0 or sec != 0:
            if (s.get("status") or "").strip() == "available":
                start_minutes.add(hh * 60 + mi)
    return start_minutes


async def _merge_template_minutes_with_preserves(
    session,
    trainer_id: int,
    day_of_week: int,
    hours: set[int],
) -> tuple[dict[int, int], dict[int, int | None], int | None]:
    """Merge bot hour picks with template rows that do not start on :00."""
    minute_to_cap: dict[int, int] = {}
    minute_to_service: dict[int, int | None] = {}
    group_arena_id: int | None = None
    templates = await list_templates(session, trainer_id)
    for t in templates:
        if t["day_of_week"] != day_of_week:
            continue
        hh, mi, sec = _time_tuple_from_start(t["start_time"])
        m = hh * 60 + mi
        if mi != 0 or sec != 0:
            cap = max(1, min(int(t.get("capacity") or 1), 500))
            minute_to_cap[m] = cap
            if cap > 1:
                sid = t.get("service_id")
                minute_to_service[m] = int(sid) if sid is not None else None
                if group_arena_id is None and t.get("arena_id") is not None:
                    group_arena_id = int(t["arena_id"])
            else:
                minute_to_service[m] = None
    for h in hours:
        minute_to_cap[h * 60] = 1
        minute_to_service[h * 60] = None
    return minute_to_cap, minute_to_service, group_arena_id


@router.callback_query(lambda c: c.data and c.data.startswith(SCHEDULE_DAY_PREFIX))
async def schedule_choose_time(callback: CallbackQuery) -> None:
    """Day chosen; show hour picker 8–20. Pre-fill from template (template) or real slots (week)."""
    await callback.answer()
    day_val = safe_parse_id(callback.data[len(SCHEDULE_DAY_PREFIX):])
    if day_val is None or day_val < 0 or day_val > 6:
        return
    day = day_val
    telegram_id = callback.from_user.id if callback.from_user else 0
    state = _schedule_add_state.get(telegram_id) or {}
    state["day"] = day
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if state.get("week_start"):
            # Week: load all existing slots (available + booked); booked are shown with ✓ but not toggleable
            if trainer_id:
                week_start = date.fromisoformat(state["week_start"])
                slot_date = week_start + timedelta(days=day)
                slots = await list_slots(session, trainer_id, slot_date, slot_date)
                state["hours"] = {_hour_from_start_time(s["start_time"]) for s in slots}
                state["locked_hours"] = {
                    _hour_from_start_time(s["start_time"])
                    for s in slots
                    if (s.get("status") or "").strip() == "booked"
                }
            else:
                state["hours"] = set()
                state["locked_hours"] = set()
        else:
            # Template: load existing template hours for this day (no locked)
            state["locked_hours"] = set()
            if trainer_id:
                templates = await list_templates(session, trainer_id)
                state["hours"] = {
                    _hour_from_start_time(t["start_time"])
                    for t in templates
                    if t["day_of_week"] == day
                }
            else:
                state["hours"] = set()
    _schedule_add_state[telegram_id] = state
    keyboard = _time_grid_keyboard(day, state["hours"], state.get("locked_hours"))
    await callback.message.edit_text(msg.TRAINER_SCHEDULE_CHOOSE_TIME, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(SCHEDULE_TIME_LOCKED_PREFIX))
async def schedule_click_locked_time(callback: CallbackQuery) -> None:
    """Booked slot clicked: cannot uncheck."""
    await callback.answer(msg.TRAINER_SCHEDULE_BOOKED_SLOT_CANNOT_REMOVE, show_alert=True)


@router.callback_query(
    lambda c: c.data and c.data.startswith(SCHEDULE_TIME_PREFIX) and not c.data.startswith(SCHEDULE_TIME_LOCKED_PREFIX)
)
async def schedule_toggle_time(callback: CallbackQuery) -> None:
    """Toggle one hour in selection; re-render grid. Preserve week_start if set. Locked hours not removable here."""
    await callback.answer()
    rest = callback.data[len(SCHEDULE_TIME_PREFIX):]
    day, hour = map(int, rest.split(":"))
    telegram_id = callback.from_user.id if callback.from_user else 0
    state = _schedule_add_state.get(telegram_id)
    if not state or state.get("day") != day:
        old = _schedule_add_state.get(telegram_id)
        state = {"day": day, "hours": set(), "locked_hours": old.get("locked_hours", set()) if old else set()}
        if old and "week_start" in old:
            state["week_start"] = old["week_start"]
        _schedule_add_state[telegram_id] = state
    locked = state.get("locked_hours") or set()
    if hour in state["hours"] and hour not in locked:
        state["hours"].discard(hour)
    else:
        state["hours"].add(hour)
    keyboard = _time_grid_keyboard(day, state["hours"], locked)
    await callback.message.edit_text(msg.TRAINER_SCHEDULE_CHOOSE_TIME, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(SCHEDULE_DONE_PREFIX))
async def schedule_done_times(callback: CallbackQuery) -> None:
    """Save selection (no duration step; fixed 60 min). Return to day picker."""
    day_val = safe_parse_id(callback.data[len(SCHEDULE_DONE_PREFIX):])
    if day_val is None or day_val < 0 or day_val > 6:
        return
    day = day_val
    telegram_id = callback.from_user.id if callback.from_user else 0
    state = _schedule_add_state.get(telegram_id)
    if not state:
        await callback.answer(msg.TRAINER_SCHEDULE_SELECT_AT_LEAST_ONE, show_alert=True)
        return
    hours = state.get("hours") or set()
    await callback.answer()
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if state.get("week_start"):
            week_start = date.fromisoformat(state["week_start"])
            slot_date = week_start + timedelta(days=day)
            start_minutes = await _merge_week_slot_minutes_with_preserves(session, trainer_id, slot_date, hours)
            await replace_slots_for_day(session, trainer_id, slot_date, start_minutes)
            audit_log("schedule.week_slots_updated", ACTOR_TRAINER_BOT, telegram_id, {"trainer_id": trainer_id, "week_start": state["week_start"], "day": day, "slots_count": len(hours)})
            asyncio.create_task(run_after_schedule_changed(trainer_id, callback.bot))
            _schedule_add_state[telegram_id] = {"week_start": state["week_start"]}
            await callback.message.edit_text(
                msg.TRAINER_SCHEDULE_ADDED_TO_WEEK_MORE.format(count=len(hours)) if hours else msg.TRAINER_SCHEDULE_DAY_CLEARED_WEEK,
                reply_markup=_day_picker_keyboard(with_back_to_schedule=True),
            )
        else:
            # Template
            _schedule_add_state.pop(telegram_id, None)
            mcap, mservice, garena = await _merge_template_minutes_with_preserves(session, trainer_id, day, hours)
            await replace_templates_for_day(
                session, trainer_id, day, mcap, 60, mservice, group_arena_id=garena
            )
            if hours:
                text = msg.TRAINER_SCHEDULE_ADDED_MULTI.format(count=len(hours)) + "\n\n" + msg.TRAINER_SCHEDULE_TEMPLATE_CHOOSE_ANOTHER_DAY
            else:
                text = msg.TRAINER_SCHEDULE_DAY_CLEARED + "\n\n" + msg.TRAINER_SCHEDULE_TEMPLATE_CHOOSE_ANOTHER_DAY
            await callback.message.edit_text(text, reply_markup=_day_picker_keyboard(with_back_to_schedule=True))


@router.callback_query(lambda c: c.data == SCHEDULE_CANCEL_ADD)
async def schedule_cancel_add(callback: CallbackQuery) -> None:
    """Cancel multi-select; back to schedule screen."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    _schedule_add_state.pop(telegram_id, None)
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    text, keyboard = await _schedule_keyboard(trainer_id)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == SCHEDULE_GEN_THIS)
async def schedule_confirm_this_week(callback: CallbackQuery) -> None:
    """Show overwrite confirmation for this week; Back or Continue."""
    await callback.answer()
    s1, e1 = _week_range(this_week_monday())
    text = msg.TRAINER_SCHEDULE_CONFIRM_OVERWRITE.format(start=s1, end=e1)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.TRAINER_BUTTON_BACK_TO_SCHEDULE, callback_data=SCHEDULE_CALLBACK)],
        [InlineKeyboardButton(text=msg.TRAINER_SCHEDULE_BUTTON_CONFIRM, callback_data=SCHEDULE_CONFIRM_THIS)],
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == SCHEDULE_GEN_NEXT)
async def schedule_confirm_next_week(callback: CallbackQuery) -> None:
    """Show overwrite confirmation for next week; Back or Continue."""
    await callback.answer()
    s2, e2 = _week_range(next_week_monday())
    text = msg.TRAINER_SCHEDULE_CONFIRM_OVERWRITE.format(start=s2, end=e2)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.TRAINER_BUTTON_BACK_TO_SCHEDULE, callback_data=SCHEDULE_CALLBACK)],
        [InlineKeyboardButton(text=msg.TRAINER_SCHEDULE_BUTTON_CONFIRM, callback_data=SCHEDULE_CONFIRM_NEXT)],
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == SCHEDULE_CONFIRM_THIS)
async def schedule_apply_this_week(callback: CallbackQuery) -> None:
    """Replace this week with template after confirmation."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        count = await replace_week_with_template(session, trainer_id, this_week_monday())
        await apply_recurring_bookings_for_week(session, trainer_id, this_week_monday())
    if count:
        audit_log("schedule.week_applied", ACTOR_TRAINER_BOT, telegram_id, {"trainer_id": trainer_id, "week": "this", "slots_count": count})
        await callback.message.edit_text(msg.TRAINER_SCHEDULE_GENERATED.format(count=count))
    else:
        await callback.message.edit_text(msg.TRAINER_SCHEDULE_GENERATED_NONE)
    asyncio.create_task(run_after_schedule_changed(trainer_id, callback.bot))
    text, keyboard = await _schedule_keyboard(trainer_id)
    await callback.message.answer(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == SCHEDULE_CONFIRM_NEXT)
async def schedule_apply_next_week(callback: CallbackQuery) -> None:
    """Replace next week with template after confirmation."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        count = await replace_week_with_template(session, trainer_id, next_week_monday())
        await apply_recurring_bookings_for_week(session, trainer_id, next_week_monday())
    if count:
        audit_log("schedule.week_applied", ACTOR_TRAINER_BOT, telegram_id, {"trainer_id": trainer_id, "week": "next", "slots_count": count})
        await callback.message.edit_text(msg.TRAINER_SCHEDULE_GENERATED.format(count=count))
    else:
        await callback.message.edit_text(msg.TRAINER_SCHEDULE_GENERATED_NONE)
    asyncio.create_task(run_after_schedule_changed(trainer_id, callback.bot))
    text, keyboard = await _schedule_keyboard(trainer_id)
    await callback.message.answer(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(SCHEDULE_DELETE_PREFIX))
async def schedule_delete(callback: CallbackQuery) -> None:
    """Delete one template and refresh schedule screen."""
    await callback.answer()
    template_id = safe_parse_id(callback.data[len(SCHEDULE_DELETE_PREFIX):])
    if template_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        await delete_template(session, trainer_id, template_id)
    await callback.message.edit_text(msg.TRAINER_SCHEDULE_DELETED)
    text, keyboard = await _schedule_keyboard(trainer_id)
    await callback.message.answer(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(SLOT_DELETE_PREFIX))
async def slot_delete(callback: CallbackQuery) -> None:
    """Delete one applied slot (available only); refresh slots screen."""
    telegram_id = callback.from_user.id if callback.from_user else 0
    slot_id = safe_parse_id(callback.data[len(SLOT_DELETE_PREFIX):])
    if slot_id is None:
        return
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            await callback.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        deleted = await delete_slot(session, trainer_id, slot_id)
    if deleted:
        audit_log("slot.deleted", ACTOR_TRAINER_BOT, telegram_id, {"trainer_id": trainer_id, "slot_id": slot_id})
        await callback.answer(msg.TRAINER_SLOT_DELETED)
    else:
        await callback.answer(msg.TRAINER_SLOT_CANNOT_DELETE_BOOKED, show_alert=True)
        return
    text, _ = await _slots_content(trainer_id)
    await callback.message.edit_text(
        text,
        reply_markup=_schedule_webapp_keyboard(include_back=True, include_create_booking=True),
    )


@router.callback_query(lambda c: c.data == GUIDE_CALLBACK)
async def on_guide_callback(callback: CallbackQuery) -> None:
    """Inline 'Помощь' button: show same as /guide with support button."""
    await callback.answer()
    uid = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        state, _ = await get_trainer_access_state(session, uid)
    if state == TrainerAccessState.NOT_LINKED:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    await callback.message.answer(
        msg.TRAINER_GUIDE,
        parse_mode=ParseMode.HTML,
        reply_markup=_trainer_guide_keyboard(),
    )


@router.callback_query(lambda c: c.data == TRAINER_INVITE_CALLBACK)
async def on_trainer_invite_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    await _trainer_typing(callback.bot, callback.message.chat.id)
    tid = callback.from_user.id if callback.from_user else 0
    await _send_trainer_invite_package(callback.message, tid)


@router.callback_query(lambda c: c.data == TRAINER_SUPPORT_CALLBACK)
async def on_trainer_support_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    tid = callback.from_user.id if callback.from_user else 0
    clear_trainer_relay_reply_pending(tid)
    trainer_support_awaiting.add(tid)
    await callback.message.answer(msg.TRAINER_SUPPORT_PROMPT)


@router.callback_query(lambda c: c.data == TRAINER_FAQ_CALLBACK)
async def on_trainer_faq_callback(callback: CallbackQuery) -> None:
    """Placeholder until FAQ opens a dedicated Mini App (web_app URL on the button)."""
    await callback.answer()
    uid = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        state, _ = await get_trainer_access_state(session, uid)
    if state == TrainerAccessState.NOT_LINKED:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    await callback.message.answer(msg.TRAINER_FAQ_COMING_SOON)


def _parse_relay_sid(data: str, prefix: str) -> int | None:
    if not data or not data.startswith(prefix):
        return None
    try:
        return int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return None


@router.callback_query(lambda c: c.data and str(c.data).startswith("rly_r:"))
async def relay_trainer_begin_reply(callback: CallbackQuery) -> None:
    await callback.answer()
    sid = _parse_relay_sid(callback.data or "", "rly_r:")
    if sid is None or not callback.message:
        return
    uid = callback.from_user.id if callback.from_user else 0
    if not uid:
        return
    await sweep_idle_relay_sessions_and_notify()
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, uid)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        ctx = await relay_session_context_for_id(session, session_id=int(sid), trainer_id=int(trainer_id))
        if not ctx or ctx.get("status") != "open":
            await callback.message.answer("<b>Сессия переписки уже закрыта.</b>")
            return
        set_trainer_relay_reply_pending(uid, int(sid))
    await callback.message.answer(msg.TRAINER_RELAY_REPLY_PROMPT)


@router.callback_query(lambda c: c.data and str(c.data).startswith("rly_xt:"))
async def relay_trainer_close_chat(callback: CallbackQuery) -> None:
    """Trainer ends relay from notification button."""
    await callback.answer()
    sid = _parse_relay_sid(callback.data or "", "rly_xt:")
    if sid is None or not callback.message:
        return
    uid = callback.from_user.id if callback.from_user else 0
    if not uid:
        return
    c_tg: int | None = None
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, uid)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        ctx = await relay_session_context_for_id(session, session_id=int(sid), trainer_id=int(trainer_id))
        if not ctx:
            await callback.message.answer("Сессия не найдена.")
            return
        c_raw = ctx.get("client_telegram_id")
        if c_raw is not None:
            c_tg = int(c_raw)
        await close_relay_session(session, session_id=int(sid), trainer_id=int(trainer_id))
        await session.commit()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(msg.TRAINER_RELAY_SESSION_CLOSED_HINT)
    clear_trainer_relay_reply_pending(uid)
    if c_tg:
        try:
            await send_client_plain_notification(
                telegram_chat_id=c_tg,
                html_text=msg.CLIENT_RELAY_SESSION_CLOSED_HINT,
            )
        except Exception:
            pass


@router.message(Command("cancel"))
async def cmd_cancel_idle(message: Message) -> None:
    telegram_id = message.from_user.id if message.from_user else 0
    _trainer_booking_note_state.pop(telegram_id, None)
    trainer_booking_note_awaiting.discard(telegram_id)
    _clear_booking_decline_state(telegram_id)
    clear_trainer_relay_reply_pending(telegram_id)
    await message.answer(msg.TRAINER_CANCEL_IDLE)


@router.message()
async def fallback(message: Message) -> None:
    """Any other message: handle support state or direct to main menu."""
    telegram_id = message.from_user.id if message.from_user else 0
    sid_pending = peek_trainer_relay_reply_pending(telegram_id)
    if sid_pending is not None and message.text:
        sid = sid_pending
        body = sanitize_relay_body(message.text)
        if body is None:
            await message.answer("Текст пустой — напишите ответ текстом.")
            return
        async with async_session_factory() as session:
            trainer_id = await get_trainer_id_for_webapp_trainer_operations(session, telegram_id)
        if not trainer_id:
            clear_trainer_relay_reply_pending(telegram_id)
            await message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        clear_trainer_relay_reply_pending(telegram_id)
        await deliver_trainer_pending_relay_reply(
            trainer_id=int(trainer_id),
            trainer_telegram_id=int(telegram_id),
            session_id=int(sid),
            body_text=body,
        )
        await message.answer("Готово — отправили клиенту в бота.")
        return
    if telegram_id in trainer_support_awaiting:
        trainer_support_awaiting.discard(telegram_id)
        text = (message.text or "").strip()[: 4000]
        if not text:
            await message.answer(msg.TRAINER_SUPPORT_PROMPT)
            return
        async with async_session_factory() as session:
            await create_support_message(
                session,
                telegram_id,
                SUPPORT_FROM_TRAINER,
                text,
                admin_notify_source_tag="тренерский бот",
            )
        await message.answer(msg.TRAINER_SUPPORT_SENT)
        return
    async with async_session_factory() as session:
        state, trainer = await get_trainer_access_state(session, telegram_id)
    if state == TrainerAccessState.NOT_LINKED:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    if not trainer_may_use_bot_workflows(state):
        await sync_trainer_linked_chat_menu(message.bot, message.chat.id)
        await message.answer(trainer_gate_message(state, trainer), parse_mode=ParseMode.HTML)
        return
    await sync_trainer_linked_chat_menu(message.bot, message.chat.id)
    await message.answer(msg.TRAINER_FALLBACK)
