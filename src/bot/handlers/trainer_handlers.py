"""
Trainer bot: entry only via paid link from site (t.me/bot?start=link_<token>).
Schedule: by calendar week (this/next). Template for quick apply; add slots to a specific week.
"""
from datetime import date, time, timedelta

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.application.booking_use_cases import (
    cancel_booking,
    get_booking_for_trainer_feedback,
    get_booking_with_slot,
    list_bookings_for_trainer,
    set_booking_trainer_review,
)
from src.application.client_request_use_cases import (
    create_request_response,
    list_requests_for_trainer,
)
from src.application.stats_use_cases import get_trainer_stats
from src.application.trainer_link import consume_link_token, get_trainer_by_telegram_id, get_trainer_id_by_telegram_id
from src.shared.audit import ACTOR_TRAINER_BOT, audit_log
from src.shared.validation import MAX_REVIEW_LEN, safe_parse_id, truncate_text
from src.application.trainer_schedule_use_cases import (
    add_template,
    delete_slot,
    delete_template,
    list_slots,
    list_templates,
    next_week_monday,
    replace_slots_for_day,
    replace_templates_for_day,
    replace_week_with_template,
    this_week_monday,
)
from src.bot import messages as msg
from src.infrastructure.db import async_session_factory

router = Router(name="trainer")

START_LINK_PREFIX = "link_"
SCHEDULE_CALLBACK = "schedule"
SCHEDULE_ADD = "schedule:add"
SCHEDULE_ADD_TEMPLATE = "schedule:template"
SCHEDULE_WEEK_PREFIX = "schedule:week:"
SCHEDULE_DAY_PREFIX = "schedule:day:"
SCHEDULE_TIME_PREFIX = "schedule:time:"
SCHEDULE_DONE_PREFIX = "schedule:done:"
SCHEDULE_CANCEL_ADD = "schedule:cancel_add"
SCHEDULE_GEN_THIS = "schedule:gen:this"
SCHEDULE_GEN_NEXT = "schedule:gen:next"
SCHEDULE_CONFIRM_THIS = "schedule:confirm:this"
SCHEDULE_CONFIRM_NEXT = "schedule:confirm:next"
SCHEDULE_DELETE_PREFIX = "schedule:del:"
SLOT_DELETE_PREFIX = "slot:del:"
SLOTS_CALLBACK = "slots"
BOOKINGS_CALLBACK = "bookings"
WRITE_BOOKING_LIST = "bookings:write"
WRITE_BOOKING_PREFIX = "write_booking:"
CANCEL_BOOKING_LIST = "bookings:cancel"
CANCEL_BOOKING_PREFIX = "cancel_booking:"
CANCEL_BOOKING_CONFIRM_PREFIX = "cancel_booking_confirm:"
REQUESTS_CALLBACK = "requests"
REQUEST_RESPOND_PREFIX = "request_respond:"
FEEDBACK_BOOKING_TRAINER_PREFIX = "feedback_booking_trainer:"
GUIDE_CALLBACK = "guide"

# Add state: telegram_id -> { week_start?: str (YYYY-MM-DD), day: int, hours: set[int] }. No week_start = template.
_schedule_add_state: dict[int, dict] = {}
# Trainer feedback after completed booking: telegram_id -> { booking_id, trainer_id }
_trainer_feedback_state: dict[int, dict] = {}


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

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.TRAINER_BUTTON_MY_SLOTS, callback_data=SLOTS_CALLBACK)],
        [InlineKeyboardButton(text=msg.TRAINER_BUTTON_ADD_SLOT, callback_data=SCHEDULE_ADD)],
        [InlineKeyboardButton(text=f"{msg.TRAINER_BUTTON_APPLY_THIS_WEEK}", callback_data=SCHEDULE_GEN_THIS)],
        [InlineKeyboardButton(text=f"{msg.TRAINER_BUTTON_APPLY_NEXT_WEEK}", callback_data=SCHEDULE_GEN_NEXT)],
    ])
    return text, keyboard


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    text = message.text or ""
    args = text.split(maxsplit=1)
    async with async_session_factory() as session:
        if len(args) > 1 and args[1].startswith(START_LINK_PREFIX):
            token = args[1].removeprefix(START_LINK_PREFIX)
            trainer_id = await consume_link_token(session, token, user_id)
            if trainer_id is not None:
                audit_log("trainer.linked", ACTOR_TRAINER_BOT, user_id, {"trainer_id": trainer_id})
                await message.answer(msg.TRAINER_LINK_SUCCESS)
            else:
                await message.answer(msg.TRAINER_LINK_INVALID)
            return
        is_trainer = await get_trainer_by_telegram_id(session, user_id)
    if not is_trainer:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    await message.answer(msg.TRAINER_START_WELCOME)


@router.message(Command("guide"))
async def cmd_guide(message: Message) -> None:
    """Show instruction only; no buttons — trainer uses main menu (left of input)."""
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, message.from_user.id if message.from_user else 0)
    if not trainer_id:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    await message.answer(msg.TRAINER_GUIDE)


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


async def _slots_content(trainer_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    """Build applied schedule screen: text only (this week / next week), no delete buttons. Always returns (text, None)."""
    this_m = this_week_monday()
    next_m = next_week_monday()
    to_date = next_m + timedelta(days=6)
    async with async_session_factory() as session:
        slots = await list_slots(session, trainer_id, this_m, to_date)
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
    """Open schedule editor from menu button or /editor. Same screen as callback Редактор расписания."""
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    text, keyboard = await _schedule_keyboard(trainer_id)
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("schedule"))
async def cmd_schedule(message: Message) -> None:
    """View applied schedule (this week + next) from menu or /schedule."""
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    text, _ = await _slots_content(trainer_id)
    back_row = [[InlineKeyboardButton(text=msg.TRAINER_BUTTON_BACK_TO_SCHEDULE, callback_data=SCHEDULE_CALLBACK)]]
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=back_row))


async def _bookings_content(trainer_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Build bookings list text and two action buttons: Write / Cancel (then choose which booking)."""
    async with async_session_factory() as session:
        bookings = await list_bookings_for_trainer(session, trainer_id)
    if not bookings:
        text = msg.TRAINER_BOOKINGS_TITLE + "\n\n" + msg.TRAINER_BOOKINGS_EMPTY
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.TRAINER_BUTTON_BACK_TO_SCHEDULE, callback_data=SCHEDULE_CALLBACK)],
        ])
        return text, keyboard

    lines = [msg.TRAINER_BOOKINGS_TITLE]
    current_date = None
    for b in bookings:
        d = b["slot_date"]
        if d != current_date:
            current_date = d
            date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
            dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
            lines.append(msg.TRAINER_BOOKINGS_DAY_HEADER.format(date=date_str, day=dow))

        time_range = _format_slot_time(b["start_time"], b["end_time"])
        first = (b.get("client_first_name") or "").strip()
        last = (b.get("client_last_name") or "").strip()
        client_display = f"{first} {last}".strip() or (b.get("client_phone") or "Клиент")
        services = b.get("services_str") or "—"
        arenas = b.get("arenas_str") or "—"
        session_num = b.get("session_num") or 1
        session_label = msg.TRAINER_BOOKINGS_SESSION_NTH.format(n=session_num)
        extra = ", ".join([services, arenas, client_display, session_label])
        lines.append(msg.TRAINER_BOOKINGS_ROW_TIME_CLIENT.format(time=time_range, client_display=client_display))
        lines.append(msg.TRAINER_BOOKINGS_ROW_EXTRA.format(extra=extra))
        comment = (b.get("client_comment") or "").strip()
        if comment:
            lines.append(msg.TRAINER_BOOKINGS_ROW_COMMENT.format(comment=comment))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_BUTTON_WRITE, callback_data=WRITE_BOOKING_LIST)],
        [InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_BUTTON_CANCEL, callback_data=CANCEL_BOOKING_LIST)],
        [InlineKeyboardButton(text=msg.TRAINER_BUTTON_BACK_TO_SCHEDULE, callback_data=SCHEDULE_CALLBACK)],
    ])
    return "\n".join(lines), keyboard


async def _requests_content(trainer_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Build requests list text and keyboard (back = to schedule)."""
    async with async_session_factory() as session:
        requests_list = await list_requests_for_trainer(session, trainer_id)
    if not requests_list:
        text = msg.TRAINER_REQUESTS_TITLE + "\n\n" + msg.TRAINER_REQUESTS_EMPTY
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.TRAINER_BUTTON_BACK_TO_SCHEDULE, callback_data=SCHEDULE_CALLBACK)],
        ])
        return text, keyboard
    lines = [msg.TRAINER_REQUESTS_TITLE]
    buttons = []
    for i, req in enumerate(requests_list, start=1):
        comment = (req.get("comment") or "").strip()
        if comment:
            lines.append(msg.TRAINER_REQUEST_ROW.format(
                index=i, city=req["city_name"], service=req["service_name"], comment=comment
            ))
        else:
            lines.append(msg.TRAINER_REQUEST_ROW_NO_COMMENT.format(
                index=i, city=req["city_name"], service=req["service_name"]
            ))
        if req.get("has_responded"):
            buttons.append([InlineKeyboardButton(
                text=msg.TRAINER_RESPONDED_INDEX.format(index=i),
                callback_data="req_done",
            )])
        else:
            buttons.append([InlineKeyboardButton(
                text=msg.TRAINER_BUTTON_RESPOND_INDEX.format(index=i),
                callback_data=f"{REQUEST_RESPOND_PREFIX}{req['id']}",
            )])
    buttons.append([InlineKeyboardButton(text=msg.TRAINER_BUTTON_BACK_TO_SCHEDULE, callback_data=SCHEDULE_CALLBACK)])
    # Separate each request with a blank line for readability
    body = "\n\n".join(lines[1:])  # skip title
    text = lines[0] + "\n\n" + body if body else lines[0]
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("bookings"))
async def cmd_bookings(message: Message) -> None:
    """Open 'Мои записи' from menu (left of attachment)."""
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    text, keyboard = await _bookings_content(trainer_id)
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("requests"))
async def cmd_requests(message: Message) -> None:
    """Open 'Заявки клиентов' from menu (left of attachment)."""
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    text, keyboard = await _requests_content(trainer_id)
    await message.answer(text, reply_markup=keyboard)


def _format_stats_date(d: date) -> str:
    return d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Show trainer statistics: week/month bookings, load, new clients, rating."""
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
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
    await message.answer("\n".join(parts))


@router.callback_query(lambda c: c.data == SCHEDULE_CALLBACK)
async def show_schedule(callback: CallbackQuery) -> None:
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    text, keyboard = await _schedule_keyboard(trainer_id)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == SLOTS_CALLBACK)
async def show_slots_from_schedule(callback: CallbackQuery) -> None:
    """Open applied-slots view from schedule screen; add Back to schedule."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    text, _ = await _slots_content(trainer_id)
    back_row = [[InlineKeyboardButton(text=msg.TRAINER_BUTTON_BACK_TO_SCHEDULE, callback_data=SCHEDULE_CALLBACK)]]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=back_row))


@router.callback_query(lambda c: c.data == BOOKINGS_CALLBACK)
async def show_bookings(callback: CallbackQuery) -> None:
    """List trainer's bookings with actions: Write / Cancel."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    text, keyboard = await _bookings_content(trainer_id)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == WRITE_BOOKING_LIST)
async def show_write_booking_list(callback: CallbackQuery) -> None:
    """Show list of bookings to choose which client to write."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        bookings = await list_bookings_for_trainer(session, trainer_id)
    if not bookings:
        await callback.message.answer(msg.TRAINER_BOOKINGS_EMPTY)
        return
    buttons = []
    for b in bookings:
        d = b["slot_date"]
        date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
        start_time_str = _format_time(b["start_time"])
        dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
        buttons.append([InlineKeyboardButton(
            text=f"{date_str} ({dow}) {start_time_str}",
            callback_data=f"{WRITE_BOOKING_PREFIX}{b['id']}",
        )])
    buttons.append([InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_BUTTON_BACK_TO_LIST, callback_data=BOOKINGS_CALLBACK)])
    await callback.message.edit_text(
        msg.TRAINER_BOOKINGS_CHOOSE_WRITE,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


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


@router.callback_query(lambda c: c.data == CANCEL_BOOKING_LIST)
async def show_cancel_booking_list(callback: CallbackQuery) -> None:
    """Show list of bookings to choose which to cancel."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        bookings = await list_bookings_for_trainer(session, trainer_id)
    if not bookings:
        await callback.message.answer(msg.TRAINER_BOOKINGS_EMPTY)
        return
    buttons = []
    for b in bookings:
        d = b["slot_date"]
        date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
        start_time_str = _format_time(b["start_time"])
        dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
        buttons.append([InlineKeyboardButton(
            text=f"{date_str} ({dow}) {start_time_str}",
            callback_data=f"{CANCEL_BOOKING_PREFIX}{b['id']}",
        )])
    buttons.append([InlineKeyboardButton(text=msg.TRAINER_BOOKINGS_BUTTON_BACK_TO_LIST, callback_data=BOOKINGS_CALLBACK)])
    await callback.message.edit_text(
        msg.TRAINER_BOOKINGS_CHOOSE_CANCEL,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
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


@router.callback_query(lambda c: c.data == REQUESTS_CALLBACK)
async def show_requests(callback: CallbackQuery) -> None:
    """List client requests matching trainer's city+service; button 'Готов взять' or 'Вы откликнулись'."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    text, keyboard = await _requests_content(trainer_id)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(REQUEST_RESPOND_PREFIX))
async def on_request_respond(callback: CallbackQuery) -> None:
    """Trainer taps 'Готов взять': create response, notify."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    request_id = int(callback.data[len(REQUEST_RESPOND_PREFIX):])
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    async with async_session_factory() as session:
        resp_id = await create_request_response(session, request_id, trainer_id)
    if resp_id is None:
        await callback.message.answer(msg.TRAINER_ERROR_RESPOND_FAILED)
        return
    audit_log("request_response.created", ACTOR_TRAINER_BOT, telegram_id, {"request_id": request_id, "trainer_id": trainer_id, "response_id": resp_id})
    await callback.message.answer(msg.TRAINER_RESPOND_SUCCESS)
    # Refresh requests list
    text, keyboard = await _requests_content(trainer_id)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == "req_done")
async def request_done_callback(callback: CallbackQuery) -> None:
    """User tapped 'Вы откликнулись' (no-op, just answer)."""
    await callback.answer()


@router.callback_query(lambda c: c.data == SCHEDULE_ADD)
async def schedule_add_start(callback: CallbackQuery) -> None:
    """Choose: add to template or to a specific week."""
    await callback.answer()
    this_m = this_week_monday()
    next_m = next_week_monday()
    s1, e1 = _week_range(this_m)
    s2, e2 = _week_range(next_m)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В шаблон (для быстрого применения)", callback_data=SCHEDULE_ADD_TEMPLATE)],
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


def _time_grid_keyboard(day: int, selected: set[int]) -> InlineKeyboardMarkup:
    """Hours 8–20: short labels (8, ✓10) for narrow mobile; then Готово and Отмена."""
    rows = []
    row1 = []
    for h in range(8, 14):
        label = f"✓{h}" if h in selected else str(h)
        row1.append(InlineKeyboardButton(text=label, callback_data=f"{SCHEDULE_TIME_PREFIX}{day}:{h}"))
    rows.append(row1)
    row2 = []
    for h in range(14, 21):
        label = f"✓{h}" if h in selected else str(h)
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
            # Week: load existing available slots for this day from real schedule
            if trainer_id:
                week_start = date.fromisoformat(state["week_start"])
                slot_date = week_start + timedelta(days=day)
                slots = await list_slots(session, trainer_id, slot_date, slot_date)
                state["hours"] = {
                    _hour_from_start_time(s["start_time"])
                    for s in slots
                    if (s.get("status") or "available") == "available"
                }
            else:
                state["hours"] = set()
        else:
            # Template: load existing template hours for this day
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
    keyboard = _time_grid_keyboard(day, state["hours"])
    await callback.message.edit_text(msg.TRAINER_SCHEDULE_CHOOSE_TIME, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(SCHEDULE_TIME_PREFIX))
async def schedule_toggle_time(callback: CallbackQuery) -> None:
    """Toggle one hour in selection; re-render grid. Preserve week_start if set."""
    await callback.answer()
    rest = callback.data[len(SCHEDULE_TIME_PREFIX):]
    day, hour = map(int, rest.split(":"))
    telegram_id = callback.from_user.id if callback.from_user else 0
    state = _schedule_add_state.get(telegram_id)
    if not state or state.get("day") != day:
        old = _schedule_add_state.get(telegram_id)
        state = {"day": day, "hours": set()}
        if old and "week_start" in old:
            state["week_start"] = old["week_start"]
        _schedule_add_state[telegram_id] = state
    if hour in state["hours"]:
        state["hours"].discard(hour)
    else:
        state["hours"].add(hour)
    keyboard = _time_grid_keyboard(day, state["hours"])
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
    if count:
        audit_log("schedule.week_applied", ACTOR_TRAINER_BOT, telegram_id, {"trainer_id": trainer_id, "week": "this", "slots_count": count})
        await callback.message.edit_text(msg.TRAINER_SCHEDULE_GENERATED.format(count=count))
    else:
        await callback.message.edit_text(msg.TRAINER_SCHEDULE_GENERATED_NONE)
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
    if count:
        audit_log("schedule.week_applied", ACTOR_TRAINER_BOT, telegram_id, {"trainer_id": trainer_id, "week": "next", "slots_count": count})
        await callback.message.edit_text(msg.TRAINER_SCHEDULE_GENERATED.format(count=count))
    else:
        await callback.message.edit_text(msg.TRAINER_SCHEDULE_GENERATED_NONE)
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
    back_row = [[InlineKeyboardButton(text=msg.TRAINER_BUTTON_BACK_TO_SCHEDULE, callback_data=SCHEDULE_CALLBACK)]]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=back_row))


@router.callback_query(lambda c: c.data == GUIDE_CALLBACK)
async def on_guide_callback(callback: CallbackQuery) -> None:
    """Inline 'Инструкция' button: show same as /guide (no buttons)."""
    await callback.answer()
    async with async_session_factory() as session:
        trainer_id = await get_trainer_id_by_telegram_id(session, callback.from_user.id if callback.from_user else 0)
    if not trainer_id:
        await callback.message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    await callback.message.answer(msg.TRAINER_GUIDE)


@router.message()
async def fallback(message: Message) -> None:
    """Any other message: direct to main menu and /guide; no buttons."""
    async with async_session_factory() as session:
        is_trainer = await get_trainer_by_telegram_id(session, message.from_user.id if message.from_user else 0)
    if not is_trainer:
        await message.answer(msg.TRAINER_ONLY_VIA_SITE)
        return
    await message.answer(msg.TRAINER_FALLBACK)
