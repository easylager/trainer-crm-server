"""
Trainer bot: entry only via paid link from site (t.me/bot?start=link_<token>).
Schedule: by calendar week (this/next). Template for quick apply; add slots to a specific week.
"""
import asyncio
import html
from datetime import date, datetime, time, timedelta
from itertools import groupby

from aiogram import Bot, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from src.application.booking_use_cases import (
    cancel_booking,
    confirm_booking,
    create_booking,
    decline_booking,
    generate_reminders_for_booking,
    get_booking_for_trainer_feedback,
    get_booking_with_slot,
    get_first_service_id_for_trainer,
    get_trainer_default_city_and_service,
    list_bookings_for_trainer,
    list_trainer_clients,
    set_booking_trainer_review,
)
from src.application.trainer_invite_links import build_trainer_invite_links
from src.application.recurring_use_cases import (
    apply_recurring_bookings_for_week,
    cancel_recurring_client_slot,
    create_recurring_client_slot,
    get_active_recurring_for_booking,
)
from src.application.client_request_use_cases import (
    add_trainer_pending_request_booking,
    clear_trainer_pending_request_booking,
    create_request_decline,
    create_request_response,
    get_request_client_for_trainer_booking,
    list_requests_for_trainer,
)
from src.application.stats_use_cases import get_trainer_stats
from src.application.subscription_use_cases import ensure_trainer_welcome_trial
from src.application.subscription_tier_use_cases import (
    get_effective_subscription_tier,
    get_trainer_subscription_status,
    tier_satisfies,
)
from src.application.trainer_access_state import TrainerAccessState, get_trainer_access_state
from src.application.trainer_link import consume_link_token, get_trainer_id_by_telegram_id
from src.application.trainer_use_cases import get_trainer
from src.application.support_use_cases import create_support_message
from src.infrastructure.db.models import SUBSCRIPTION_TIER_ANALYTICS, SUBSCRIPTION_TIER_CRM, SUPPORT_FROM_TRAINER
from src.shared.audit import ACTOR_TRAINER_BOT, audit_log
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
from src.bot import messages as msg
from src.bot.trainer_bot_state import trainer_support_awaiting
from src.bot.trainer_gate_text import trainer_first_link_onboarding_html, trainer_gate_message
from src.bot.trainer_menu_commands import sync_trainer_menu_commands
from src.shared.config import Settings
from src.shared.notification_hours import NOTIFICATION_TZ

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]
from src.bot.schedule_notifications import run_after_schedule_changed
from src.infrastructure.db import async_session_factory

router = Router(name="trainer")


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


async def _trainer_has_crm_subscription(session, trainer_id: int) -> bool:
    """True if trainer has an active paid tier at least CRM (schedule, clients, passes)."""
    tier = await get_effective_subscription_tier(session, trainer_id)
    return tier_satisfies(tier, SUBSCRIPTION_TIER_CRM)


START_LINK_PREFIX = "link_"
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
SCHEDULE_GEN_THIS = "schedule:gen:this"
SCHEDULE_GEN_NEXT = "schedule:gen:next"
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


def _post_welcome_link_keyboard(*, for_active_menu: bool) -> InlineKeyboardMarkup:
    """
    After /start with link_: profile (+ subscription when fully active), then guide callback.
    """
    rows: list[list[InlineKeyboardButton]] = []
    profile_url = _trainer_profile_webapp_url()
    if profile_url:
        rows.append(
            [InlineKeyboardButton(text=msg.TRAINER_PROFILE_BTN_MINI_APP, web_app=WebAppInfo(url=profile_url))]
        )
    base = (Settings().webapp_base_url or "").rstrip("/")
    if for_active_menu and base.lower().startswith("https://"):
        rows.append(
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BUTTON_SUBSCRIPTION_CONSTRUCTOR,
                    web_app=WebAppInfo(url=f"{base}/webapp/trainer-subscription"),
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="❓ Как пользоваться ботом", callback_data=GUIDE_CALLBACK)]
    )
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
# Trainer declining booking: telegram_id -> booking_id (awaiting required comment)
_booking_decline_state: dict[int, int] = {}


async def _trainer_typing(bot: Bot, chat_id: int) -> None:
    """Typing indicator while DB or heavy work runs (constitution § VII)."""
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)


def _format_time(t) -> str:
    if hasattr(t, "strftime"):
        return t.strftime("%H:%M")
    s = str(t)
    return s[:5] if len(s) >= 5 else s


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
        lines.append(msg.TRAINER_SCHEDULE_ROW.format(
            day=day_name,
            time=_format_time(t["start_time"]),
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


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await _trainer_typing(message.bot, message.chat.id)
    user_id = message.from_user.id if message.from_user else 0
    text = message.text or ""
    args = text.split(maxsplit=1)
    async with async_session_factory() as session:
        if len(args) > 1 and args[1].startswith(START_LINK_PREFIX):
            token = args[1].removeprefix(START_LINK_PREFIX)
            username = (message.from_user.username if message.from_user else None) or None
            trainer_id = await consume_link_token(session, token, user_id, telegram_username=username)
            if trainer_id is not None:
                audit_log("trainer.linked", ACTOR_TRAINER_BOT, user_id, {"trainer_id": trainer_id})
                state, trainer = await get_trainer_access_state(session, user_id)
                if state == TrainerAccessState.ACTIVE:
                    async with async_session_factory() as s2:
                        await ensure_trainer_welcome_trial(s2, trainer_id)
                        sub_st = await get_trainer_subscription_status(s2, trainer_id)
                    if (
                        sub_st.get("is_active")
                        and sub_st.get("is_trial")
                        and (sub_st.get("effective_tier") or "none") != "none"
                    ):
                        tier_label = html.escape(
                            (sub_st.get("tier_name_ru") or "Аналитика").strip() or "Аналитика"
                        )
                        exp_fmt = _format_expires_ru_from_iso(sub_st.get("expires_at"))
                        await message.answer(
                            msg.TRAINER_WELCOME_TRIAL_ACTIVATED.format(
                                tier_name=tier_label,
                                expires_date=html.escape(exp_fmt),
                            ),
                            parse_mode=ParseMode.HTML,
                            reply_markup=_post_welcome_link_keyboard(for_active_menu=True),
                        )
                    else:
                        await message.answer(
                            msg.TRAINER_LINK_SUCCESS_ACTIVE,
                            parse_mode=ParseMode.HTML,
                            reply_markup=_post_welcome_link_keyboard(for_active_menu=True),
                        )
                else:
                    await message.answer(
                        trainer_first_link_onboarding_html(state, trainer),
                        parse_mode=ParseMode.HTML,
                        reply_markup=_post_welcome_link_keyboard(for_active_menu=False),
                    )
                if state == TrainerAccessState.ACTIVE:
                    await sync_trainer_menu_commands(message.bot, message.chat.id, trainer_id, session)
            else:
                await message.answer(msg.TRAINER_LINK_INVALID)
            return
        state, trainer = await get_trainer_access_state(session, user_id)
    if state == TrainerAccessState.NOT_LINKED:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    if state == TrainerAccessState.ACTIVE:
        await message.answer(msg.TRAINER_START_WELCOME)
        async with async_session_factory() as session:
            tid = await get_trainer_id_by_telegram_id(session, user_id)
            if tid:
                await sync_trainer_menu_commands(message.bot, message.chat.id, tid, session)
        return
    await message.answer(trainer_gate_message(state, trainer))


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
    await message.answer(
        msg.TRAINER_GUIDE,
        parse_mode=ParseMode.HTML,
        reply_markup=_trainer_guide_keyboard(),
    )


async def _send_trainer_invite_package(chat_message: Message, telegram_id: int) -> None:
    """Two messages: HTML intro + plain text block the trainer can forward to clients."""
    settings = Settings()
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
    if links.catalog_page_url:
        plain = msg.TRAINER_INVITE_PLAIN_CLIENT_WITH_CATALOG.format(
            deep_link=links.client_bot_deep_link,
            catalog_url=links.catalog_page_url,
        )
    else:
        plain = msg.TRAINER_INVITE_PLAIN_CLIENT_NO_CATALOG.format(deep_link=links.client_bot_deep_link)
    await chat_message.answer(msg.TRAINER_INVITE_INTRO_HTML)
    await chat_message.answer(plain, parse_mode=None)


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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
            [InlineKeyboardButton(text=msg.TRAINER_BUTTON_SCHEDULE, web_app=WebAppInfo(url=url))],
        ])
        await message.answer(
            msg.TRAINER_EDITOR_OPEN_HINT,
            reply_markup=kb,
        )
        return
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
        if not trainer_id:
            await message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        tier = await get_effective_subscription_tier(session, trainer_id)
        if not tier_satisfies(tier, SUBSCRIPTION_TIER_ANALYTICS):
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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


def _subscription_tier_name_ru(tier: str) -> str:
    return {"crm": "CRM", "online": "Онлайн-запись", "analytics": "Аналитика"}.get(tier, tier)


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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    base = (Settings().webapp_base_url or "").rstrip("/")
    constructor_url = f"{base}/webapp/trainer-subscription" if base and base.startswith("https://") else None
    async with async_session_factory() as session:
        tier_status = await get_trainer_subscription_status(session, trainer_id)
        eff = (tier_status.get("effective_tier") or "none").strip().lower()
        if eff != "none" and tier_status.get("is_active") and tier_status.get("expires_at"):
            expires_date = _format_iso_date_ru(tier_status.get("expires_at"))
            text = msg.TRAINER_SUBSCRIPTION_WITH_TIER.format(
                tier_name=_subscription_tier_name_ru(eff),
                expires_date=expires_date,
            )
        else:
            text = msg.TRAINER_SUBSCRIPTION_WITHOUT_TIER
        rows: list[list[InlineKeyboardButton]] = []
        if constructor_url:
            rows.append(
                [InlineKeyboardButton(text=msg.TRAINER_BUTTON_SUBSCRIPTION_CONSTRUCTOR, web_app=WebAppInfo(url=constructor_url))]
            )
        kb = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
        await sync_trainer_menu_commands(message.bot, message.chat.id, trainer_id, session)
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@router.callback_query(lambda c: c.data == SCHEDULE_CALLBACK)
async def show_schedule(callback: CallbackQuery) -> None:
    await callback.answer()
    await _trainer_typing(callback.bot, callback.message.chat.id)
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        name = ((c.get("first_name") or "") + " " + (c.get("last_name") or "")).strip() or "Клиент"
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


@router.callback_query(lambda c: c.data and c.data.startswith(SCHEDULE_CREATE_BOOKING_CLIENT_PREFIX))
async def schedule_create_booking_finalize(callback: CallbackQuery) -> None:
    """Create booking for chosen client and slot."""
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        booking_id = await create_booking(
            session,
            slot_id=slot_id,
            trainer_id=trainer_id,
            client_id=client_id,
            service_id=service_id,
            client_comment=None,
            client_request_id=None,
            created_by_trainer=True,
        )
    if not booking_id:
        await callback.message.answer(msg.TRAINER_CREATE_BOOKING_SLOT_UNAVAILABLE)
        return
    async with async_session_factory() as session:
        await generate_reminders_for_booking(session, booking_id)
    slot_date = slot.get("slot_date")
    start_time = slot.get("start_time")
    date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
    day_str = msg.TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
    time_str = _format_time(start_time)
    # For confirmation we don't fetch client name again; it is secondary.
    await callback.message.answer(
        msg.TRAINER_CREATE_BOOKING_DONE.format(
            client_name="клиент",
            date=date_str,
            day=day_str,
            time=time_str,
        )
    )


@router.callback_query(lambda c: c.data == BOOKINGS_CALLBACK)
async def show_bookings(callback: CallbackQuery) -> None:
    """List = buttons: one per booking (page 0)."""
    await callback.answer()
    await _trainer_typing(callback.bot, callback.message.chat.id)
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
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
    rows = [
        [
            InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_BUTTON_WRITE, callback_data=f"{WRITE_BOOKING_PREFIX}{booking_id}"),
            InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_BUTTON_CANCEL, callback_data=f"{CANCEL_BOOKING_PREFIX}{booking_id}"),
        ],
    ]
    if recurring:
        rows.append([InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_BUTTON_REMOVE_REGULARITY, callback_data=f"{REMOVE_RECURRING_PREFIX}{recurring['id']}")])
    else:
        rows.append([InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_BUTTON_MAKE_REGULAR, callback_data=f"{MAKE_RECURRING_TRAINER_PREFIX}{booking_id}")])
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        recurring_id = await create_recurring_client_slot(
            session, trainer_id, client_id, day_of_week, start_time, end_time
        )
    if recurring_id is None:
        await callback.message.answer(msg.TRAINER_RECURRING_DONE)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        ok = await cancel_recurring_client_slot(session, trainer_id, recurring_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        info = await confirm_booking(session, booking_id, trainer_id)
    if not info:
        await callback.message.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
        return
    d = info["slot_date"]
    date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
    dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
    start_time = info["start_time"]
    time_str = _format_time(start_time)
    client_phone = info.get("client_phone") or "—"
    client_display = client_phone
    # Notify trainer in current chat
    text_trainer = msg.TRAINER_BOOKING_CONFIRMED.format(
        client_display=client_display,
        date=date_str,
        day=dow,
        time=time_str,
    )
    await callback.message.answer(text_trainer)
    # Notify client via client bot (separate token)
    client_tid = info.get("client_telegram_id")
    if not client_tid:
        return
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
    try:
        await client_bot.send_message(
            chat_id=client_tid,
            text=msg.CLIENT_BOOKING_CONFIRMED_BY_TRAINER.format(
                date=date_str,
                day=dow,
                time=time_str,
                trainer_name=trainer_name,
            ),
        )
    finally:
        await client_bot.session.close()

@router.callback_query(lambda c: c.data and c.data.startswith(CANCEL_BOOKING_PREFIX))
async def show_cancel_booking_confirm(callback: CallbackQuery) -> None:
    """Show warning and confirm before cancelling a booking."""
    await callback.answer()
    booking_id = safe_parse_id(callback.data[len(CANCEL_BOOKING_PREFIX):])
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        ok = await cancel_booking(session, booking_id, trainer_id)
    if not ok:
        await callback.message.answer(msg.TRAINER_ERROR_CANCEL_FAILED)
        return
    audit_log("booking.cancelled", ACTOR_TRAINER_BOT, telegram_id, {"booking_id": booking_id, "trainer_id": trainer_id})
    text, keyboard = await _bookings_content(trainer_id)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.message.answer(msg.TRAINER_BOOKINGS_CANCELLED)


@router.callback_query(lambda c: c.data and c.data.startswith(DECLINE_BOOKING_PREFIX))
async def on_decline_booking_start(callback: CallbackQuery) -> None:
    """Trainer tapped 'Отклонить' in notification: ask for required comment."""
    await callback.answer()
    booking_id = safe_parse_id(callback.data[len(DECLINE_BOOKING_PREFIX) :])
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        booking = await get_booking_with_slot(session, booking_id, trainer_id)
    if not booking:
        await callback.message.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
        return
    _booking_decline_state[telegram_id] = booking_id
    await callback.message.answer(msg.TRAINER_BOOKING_DECLINE_PROMPT)


@router.callback_query(lambda c: c.data and c.data.startswith(FEEDBACK_BOOKING_TRAINER_PREFIX))
async def on_feedback_booking_trainer(callback: CallbackQuery) -> None:
    """Trainer tapped 'Leave feedback' after completed booking: ask for optional review text."""
    await callback.answer()
    raw = (callback.data or "").replace(FEEDBACK_BOOKING_TRAINER_PREFIX, "").strip()
    booking_id = safe_parse_id(raw)
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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


@router.message(lambda m: m.from_user and m.from_user.id in _trainer_feedback_state)
async def on_trainer_feedback_message(message: Message) -> None:
    """Trainer sent review text for completed booking."""
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


@router.message(lambda m: m.from_user and m.from_user.id in _booking_decline_state)
async def on_decline_booking_comment(message: Message) -> None:
    """Trainer sent decline comment for booking."""
    telegram_id = message.from_user.id if message.from_user else 0
    booking_id = _booking_decline_state.get(telegram_id)
    if booking_id is None:
        return
    raw_comment = (message.text or "").strip()
    if not raw_comment:
        await message.answer(msg.TRAINER_BOOKING_DECLINE_COMMENT_REQUIRED)
        return
    comment = truncate_text(raw_comment, MAX_COMMENT_LEN)
    _booking_decline_state.pop(telegram_id, None)
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        info = await decline_booking(session, booking_id, trainer_id)
    if not info:
        await message.answer(msg.TRAINER_ERROR_BOOKING_NOT_FOUND)
        return
    d = info["slot_date"]
    date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
    dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
    start_time = info["start_time"]
    time_str = _format_time(start_time)
    await message.answer(msg.TRAINER_BOOKING_DECLINED_DONE)
    client_tid = info.get("client_telegram_id")
    if not client_tid:
        return
    settings = Settings()
    client_bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await client_bot.send_message(
            chat_id=client_tid,
            text=msg.CLIENT_BOOKING_DECLINED_BY_TRAINER.format(
                date=date_str,
                day=dow,
                time=time_str,
                reason=comment,
            ),
        )
    finally:
        await client_bot.session.close()


@router.message(lambda m: m.text and m.from_user and m.from_user.id in _request_respond_state)
async def on_request_respond_comment_message(message: Message) -> None:
    """Trainer sent comment text for their response to a request."""
    telegram_id = message.from_user.id if message.from_user else 0
    request_id = _request_respond_state.pop(telegram_id, None)
    if request_id is None:
        return
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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


@router.callback_query(lambda c: c.data and c.data.startswith(REQUEST_RESPOND_PREFIX))
async def on_request_respond(callback: CallbackQuery) -> None:
    """Trainer taps 'Готов взять': ask optional comment, then create response."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    request_id = safe_parse_id(callback.data[len(REQUEST_RESPOND_PREFIX):])
    if request_id is None:
        return
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        client_info = await get_request_client_for_trainer_booking(session, request_id, trainer_id)
    if not client_info:
        await callback.message.answer(msg.TRAINER_ERROR_REQUEST_GONE)
        return
    async with async_session_factory() as session:
        booking_id = await create_booking(
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
        await generate_reminders_for_booking(session, booking_id)
    await callback.message.answer(msg.TRAINER_REQUEST_BOOK_SUCCESS)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
        if not trainer_id:
            await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
            return
        if state.get("week_start"):
            week_start = date.fromisoformat(state["week_start"])
            slot_date = week_start + timedelta(days=day)
            await replace_slots_for_day(session, trainer_id, slot_date, hours)
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
            await replace_templates_for_day(session, trainer_id, day, hours, 60)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
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


@router.message(Command("cancel"))
async def cmd_cancel_idle(message: Message) -> None:
    await message.answer(msg.TRAINER_CANCEL_IDLE)


@router.message()
async def fallback(message: Message) -> None:
    """Any other message: handle support state or direct to main menu."""
    telegram_id = message.from_user.id if message.from_user else 0
    if telegram_id in trainer_support_awaiting:
        trainer_support_awaiting.discard(telegram_id)
        text = (message.text or "").strip()[: 4000]
        if not text:
            await message.answer(msg.TRAINER_SUPPORT_PROMPT)
            return
        async with async_session_factory() as session:
            await create_support_message(session, telegram_id, SUPPORT_FROM_TRAINER, text)
        await message.answer(msg.TRAINER_SUPPORT_SENT)
        return
    async with async_session_factory() as session:
        state, trainer = await get_trainer_access_state(session, telegram_id)
    if state == TrainerAccessState.NOT_LINKED:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    if state != TrainerAccessState.ACTIVE:
        await message.answer(trainer_gate_message(state, trainer))
        return
    await message.answer(msg.TRAINER_FALLBACK)
