"""
Client bot handlers: /start and catalog. Public entry; no auth.
"""
import asyncio
import html
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

from aiogram import Bot, Router
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from src.application.client_use_cases import get_or_create_client
from src.application.client_session_use_cases import (
    clear_choices,
    clear_pending_request_id,
    get_or_create_session,
    get_session,
    set_arena,
    set_city,
    set_pending_request_id,
    set_selected_trainer,
    set_service,
)
from src.application.client_request_use_cases import (
    create_client_request,
    delete_client_request,
    list_my_requests_with_responses,
    replace_client_request_with_new,
)
from src.application.booking_use_cases import (
    create_booking,
    generate_reminders_for_booking,
    get_booking_for_client_feedback,
    get_completed_booking_for_repeat,
    list_bookings_for_client,
)
from src.application.recurring_use_cases import (
    add_slot_wait_request,
    create_recurring_client_slot,
    find_available_slot_next_week,
    get_active_recurring_for_booking,
    get_slot_status_next_week,
    has_other_active_recurring,
)
from src.application.trainer_schedule_use_cases import (
    get_slot,
    list_slots,
    next_week_monday,
    this_week_monday,
)
from src.application.trainer_use_cases import add_trainer_rating, get_trainer
from src.bot import messages as msg
from src.shared.audit import ACTOR_CLIENT_BOT, audit_log
from src.bot.client_api import (
    build_photo_url,
    fetch_active_trainers,
    fetch_arenas,
    fetch_cities,
    fetch_photo_bytes,
    fetch_services,
)
from src.infrastructure.db import async_session_factory
from src.shared.map_links import build_yandex_by_map_url, build_yandex_by_map_url_all_arenas
from src.shared.validation import MAX_COMMENT_LEN, safe_parse_id, truncate_text

logger = logging.getLogger(__name__)
router = Router(name="client")

# One catalog-load at a time per chat to avoid duplicate callback showing EMPTY then HEADER.
_catalog_load_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

CATALOG_CALLBACK = "catalog"
GUIDE_CALLBACK = "guide"
REQUEST_CALLBACK = "request"
SETTINGS_CALLBACK = "settings"
SETTINGS_CITY_PREFIX = "settings_city:"
SETTINGS_SERVICE_PREFIX = "settings_service:"
# Catalog flow: select trainer → "Выбран" + Записаться/Настройки (used from catalog and from settings "Выбор тренера").
CATALOG_TRAINER_PREFIX = "catalog_trainer:"
CITY_PREFIX = "city:"
SERVICE_PREFIX = "service:"

# Deep link from site: t.me/Bot?start=client_{city_id}_{service_id}_{trainer_id} — prefill session and show "Записаться".
CLIENT_START_PREFIX = "client_"
BOOK_SLOT_PREFIX = "book_slot:"
BOOKING_SKIP_COMMENT = "booking_skip_comment"
MY_REQUESTS_CALLBACK = "my_requests"
MY_REQUESTS_PAGE_PREFIX = "my_requests_page:"
MY_REQUESTS_PER_PAGE = 8
MY_BOOKINGS_CALLBACK = "my_bookings"
MY_REQUEST_PREFIX = "my_request:"
REQUEST_EDIT_PREFIX = "request_edit:"
REQUEST_EDIT_CONFIRM_PREFIX = "request_edit_confirm:"
REQUEST_DELETE_PREFIX = "request_delete:"
BOOK_FROM_REQUEST_PREFIX = "book_from_req:"
CATALOG_PAGE_PREFIX = "catalog_page:"
PICK_RESPONDER_PREFIX = "pick_responder:"
RESPONDER_PROFILE_PREFIX = "responder_profile:"
CLIENT_DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

# Booking flow state: telegram_id -> { slot_id, trainer_id, phone?, comment? }
_booking_state: dict[int, dict] = {}

# Request (leave demand) flow: telegram_id -> { city_id, service_id }; next step = comment or skip
_request_state: dict[int, dict] = {}
# Request edit: telegram_id -> request_id (int) when awaiting new comment, or { "request_id": int, "pending_comment": str }
_request_edit_state: dict[int, int | dict] = {}

# Feedback after completed booking: telegram_id -> { booking_id, trainer_id, rating? }; next = review text or skip
FEEDBACK_BOOKING_PREFIX = "feedback_booking:"
FEEDBACK_RATING_PREFIX = "feedback_rating:"
REPEAT_BOOKING_PREFIX = "repeat_booking:"
MAKE_RECURRING_PREFIX = "make_recurring:"
BOOK_AVAILABLE_SLOT_PREFIX = "book_available_slot:"
_feedback_state: dict[int, dict] = {}


def _parse_client_start(payload: str) -> tuple[int, int, int] | None:
    """Parse client_<city_id>_<service_id>_<trainer_id>. Returns (city_id, service_id, trainer_id) or None."""
    if not payload or not payload.startswith(CLIENT_START_PREFIX):
        return None
    rest = payload[len(CLIENT_START_PREFIX) :].strip()
    parts = rest.split("_")
    if len(parts) != 3:
        return None
    try:
        city_id, service_id, trainer_id = int(parts[0]), int(parts[1]), int(parts[2])
        if city_id <= 0 or service_id <= 0 or trainer_id <= 0:
            return None
        return (city_id, service_id, trainer_id)
    except ValueError:
        return None


def _trainer_name(trainer: dict) -> str:
    """Short name for trainer from profile."""
    profile = trainer.get("profile") or {}
    name = (profile.get("first_name") or "") + " " + (profile.get("last_name") or "")
    return name.strip() or "Тренер"


def _request_list_button_label(req: dict) -> str:
    """Label for one request in list: city, service only. Telegram button 64 bytes max."""
    city = (req.get("city_name") or "").strip()
    service = (req.get("service_name") or "").strip()
    raw = msg.CLIENT_MY_REQUESTS_BUTTON_LABEL.format(city=city, service=service)
    if len(raw.encode("utf-8")) <= 64:
        return raw
    for n in range(len(raw), 0, -1):
        if len(raw[:n].encode("utf-8")) <= 64:
            return raw[:n].rstrip() + "…"
    return "…"


async def _my_requests_content(telegram_id: int, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    """List = buttons only (one per request). Pagination by page. Back to settings."""
    async with async_session_factory() as db_session:
        requests_list = await list_my_requests_with_responses(db_session, telegram_id)
    if not requests_list:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_REQUEST_BACK, callback_data=SETTINGS_CALLBACK)],
        ])
        text = msg.CLIENT_MY_REQUESTS_TITLE + "\n\n" + msg.CLIENT_MY_REQUESTS_EMPTY
        return text, back_kb
    total = len(requests_list)
    page = max(0, min(page, (total - 1) // MY_REQUESTS_PER_PAGE))
    start = page * MY_REQUESTS_PER_PAGE
    page_requests = requests_list[start : start + MY_REQUESTS_PER_PAGE]
    text = msg.CLIENT_MY_REQUESTS_TITLE + "\n\n" + msg.CLIENT_MY_REQUESTS_LIST_HINT
    button_rows = []
    for req in page_requests:
        button_rows.append([InlineKeyboardButton(
            text=_request_list_button_label(req),
            callback_data=f"{MY_REQUEST_PREFIX}{req['id']}",
        )])
    if total > MY_REQUESTS_PER_PAGE:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                text=msg.CLIENT_MY_REQUESTS_PAGE_PREV,
                callback_data=f"{MY_REQUESTS_PAGE_PREFIX}{page - 1}",
            ))
        if start + MY_REQUESTS_PER_PAGE < total:
            nav.append(InlineKeyboardButton(
                text=msg.CLIENT_MY_REQUESTS_PAGE_NEXT,
                callback_data=f"{MY_REQUESTS_PAGE_PREFIX}{page + 1}",
            ))
        if nav:
            button_rows.append(nav)
    button_rows.append([InlineKeyboardButton(text=msg.CLIENT_REQUEST_BACK, callback_data=SETTINGS_CALLBACK)])
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, keyboard


def _format_services_prices(services: list[dict]) -> str:
    """Format 'Услуга: X BYN' or 'Услуга: по запросу' for each; join with ', '. Uses price_byn (rubles)."""
    if not services:
        return "—"
    parts = []
    for s in services:
        name = (s.get("service_name") or "").strip() or "—"
        byn = s.get("price_byn")
        if byn is not None:
            parts.append(f"{name}: {int(byn)} BYN" if byn == int(byn) else f"{name}: {byn:.2f} BYN")
        else:
            parts.append(f"{name}: по запросу")
    return ", ".join(parts)


def _trainer_caption(trainer: dict) -> str:
    """Format trainer card caption from profile (name, rating, age, experience, arenas, services/prices, description)."""
    profile = trainer.get("profile") or {}
    name = (profile.get("first_name") or "") + " " + (profile.get("last_name") or "")
    name = name.strip() or "Тренер"
    # Rating: "5 ⭐ (1)" or "—" when no votes
    avg = profile.get("rating_avg")
    count = profile.get("rating_count") or 0
    if avg is not None and count and count > 0:
        rating_str = f"{float(avg):.1f} ⭐ ({count})"
    else:
        rating_str = msg.CLIENT_TRAINER_CARD_NO_RATING
    age = profile.get("age")
    age_str = str(age) if age is not None else "—"
    exp = profile.get("experience_years")
    exp_str = f"{exp} лет" if exp is not None else msg.CLIENT_TRAINER_CARD_NO_EXPERIENCE
    arena_names = trainer.get("arena_names") or []
    arenas_str = ", ".join(arena_names) if arena_names else "—"
    services_prices_str = _format_services_prices(trainer.get("services") or [])
    desc = (profile.get("description") or "").strip() or "—"
    duration = profile.get("session_duration_minutes") or 45
    return msg.CLIENT_TRAINER_CARD.format(
        name=name,
        rating=rating_str,
        age=age_str,
        experience=exp_str,
        duration=duration,
        arenas=arenas_str,
        services_prices=services_prices_str,
        description=desc,
    )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Welcome and catalog; or from site deep link: /start client_C_S_T → prefill session, show Записаться."""
    telegram_id = message.from_user.id if message.from_user else 0
    parts = (message.text or "").strip().split(maxsplit=1)
    payload = (parts[1].strip() if len(parts) > 1 else "") or ""
    parsed = _parse_client_start(payload)
    if parsed:
        city_id, service_id, trainer_id = parsed
        async with async_session_factory() as db_session:
            await set_city(telegram_id, city_id, db_session)
            await set_service(telegram_id, service_id, db_session)
            await set_selected_trainer(telegram_id, trainer_id, db_session)
            trainer = await get_trainer(db_session, trainer_id)
        name = _trainer_name(trainer) if trainer else "Тренер"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_BOOK, callback_data="book")],
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_ANOTHER_TRAINER, callback_data=CATALOG_CALLBACK)],
        ])
        await message.answer(
            msg.CLIENT_TRAINER_SELECTED.format(name=name),
            reply_markup=keyboard,
        )
        return
    await message.answer(msg.CLIENT_START_WELCOME)


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    """Open settings from menu button or /settings. Same screen as callback Settings."""
    telegram_id = message.from_user.id if message.from_user else 0
    text, keyboard = await _get_settings_content(telegram_id)
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("request"))
async def cmd_request(message: Message) -> None:
    """Start 'Оставить заявку' from menu (left of attachment). Same flow as callback request."""
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as db_session:
        session = await get_session(telegram_id, db_session)
    city_id = session.get("city_id") if session else None
    service_id = session.get("selected_service_id") if session else None
    if not city_id or not service_id:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_REQUEST_BACK, callback_data=SETTINGS_CALLBACK)],
        ])
        await message.answer(msg.CLIENT_REQUEST_NEED_CITY_SERVICE, reply_markup=back_kb)
        return
    _request_state[telegram_id] = {"city_id": city_id, "service_id": service_id}
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.CLIENT_REQUEST_SKIP, callback_data="request_skip")],
        [InlineKeyboardButton(text=msg.CLIENT_REQUEST_BACK, callback_data="request_back")],
    ])
    await message.answer(msg.CLIENT_REQUEST_PROMPT_COMMENT, reply_markup=keyboard)


@router.message(Command("my_requests"))
async def cmd_my_requests(message: Message) -> None:
    """Open 'Мои заявки и отклики' from menu. List = one button per request."""
    telegram_id = message.from_user.id if message.from_user else 0
    text, keyboard = await _my_requests_content(telegram_id)
    await message.answer(text, reply_markup=keyboard)


def _trainer_display_for_booking(b: dict, client_telegram_id: int) -> str:
    """HTML fragment: trainer name as tg:// link if telegram_id present and not self; else plain name + hint."""
    name = (b.get("trainer_name") or "Тренер").strip() or "Тренер"
    safe_name = html.escape(name)
    tid = b.get("trainer_telegram_id")
    # Don't link when trainer is the same user (opens Saved Messages / "Избранное")
    if tid:
        return f'<a href="tg://user?id={int(tid)}">{safe_name}</a>'
    # Trainer not linked to bot yet — show hint so user knows why there's no link
    return f"{safe_name} (написать в TG можно после подключения тренера к боту)"


async def _my_bookings_content(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Build client's bookings list text and back button. Returns (text, keyboard)."""
    async with async_session_factory() as db_session:
        bookings = await list_bookings_for_client(db_session, telegram_id)
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.CLIENT_BUTTON_BACK_FROM_BOOKINGS, callback_data=GUIDE_CALLBACK)],
    ])
    if not bookings:
        return msg.CLIENT_MY_BOOKINGS_TITLE + "\n\n" + msg.CLIENT_MY_BOOKINGS_EMPTY, back_kb
    lines = [
        msg.CLIENT_MY_BOOKINGS_TITLE,
        "",
        msg.CLIENT_MY_BOOKINGS_CANCEL_HINT,
        "",
    ]
    for i, b in enumerate(bookings, start=1):
        d = b["slot_date"]
        date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
        day_str = CLIENT_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
        st = b["start_time"]
        time_str = st.strftime("%H:%M") if hasattr(st, "strftime") else str(st)[:5]
        duration = b.get("duration_minutes") or 45
        lines.append(msg.CLIENT_MY_BOOKINGS_ROW.format(
            index=i,
            date=date_str,
            day=day_str,
            time=time_str,
            duration=duration,
            trainer_display=_trainer_display_for_booking(b, telegram_id),
        ))
    return "\n".join(lines), back_kb


@router.message(Command("my_bookings"))
async def cmd_my_bookings(message: Message) -> None:
    """Open 'Мои записи' from menu. Same as callback MY_BOOKINGS_CALLBACK."""
    telegram_id = message.from_user.id if message.from_user else 0
    text, keyboard = await _my_bookings_content(telegram_id)
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@router.callback_query(lambda c: c.data == MY_BOOKINGS_CALLBACK)
async def show_my_bookings(callback: CallbackQuery) -> None:
    """List client's bookings (date, time, trainer)."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    text, keyboard = await _my_bookings_content(telegram_id)
    await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@router.message(Command("guide"))
async def cmd_guide(message: Message) -> None:
    """Show instruction only; no buttons — user uses main menu (left of input)."""
    await message.answer(msg.CLIENT_GUIDE)


@router.callback_query(lambda c: c.data == GUIDE_CALLBACK)
async def on_guide_callback(callback: CallbackQuery) -> None:
    """Inline 'Инструкция' button: show same as /guide (no buttons)."""
    await callback.answer()
    await callback.message.answer(msg.CLIENT_GUIDE)


@router.message(Command("book"))
async def cmd_book(message: Message) -> None:
    """From menu: show slots for selected trainer or ask to choose one."""
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as db_session:
        session_data = await get_session(telegram_id, db_session)
    trainer_id = (session_data or {}).get("selected_trainer_id") if session_data else None
    if not trainer_id:
        await message.answer(msg.CLIENT_BOOK_NO_TRAINER)
        return
    text, keyboard = await _client_slots_content(trainer_id)
    if keyboard is None:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Выбор тренера", callback_data=CATALOG_CALLBACK)],
        ])
        await message.answer(text, reply_markup=back_kb)
        return
    back_row = [[InlineKeyboardButton(text=msg.CLIENT_BOOK_BUTTON_BACK, callback_data=CATALOG_CALLBACK)]]
    full_kb = InlineKeyboardMarkup(inline_keyboard=keyboard.inline_keyboard + back_row)
    await message.answer(text, reply_markup=full_kb)


def _trainer_select_keyboard(
    trainer_id: int,
    select_callback_data: str | None = None,
) -> InlineKeyboardMarkup:
    """Inline keyboard: one button 'Выбрать'. Use select_callback_data for settings flow; else catalog_trainer:."""
    data = select_callback_data or f"{CATALOG_TRAINER_PREFIX}{trainer_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.CLIENT_BUTTON_SELECT_TRAINER, callback_data=data)],
    ])


async def _send_trainer_card(
    bot: Bot,
    chat_id: int,
    trainer: dict,
    select_callback_data: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    use_list_photo: bool = False,
) -> None:
    """Send one trainer card (photo + caption). use_list_photo=True: prefer file_key_list (smaller) for catalog."""
    photos = trainer.get("photos") or []
    first_photo = photos[0] if photos else None
    if first_photo and use_list_photo and first_photo.get("file_key_list"):
        file_key = first_photo["file_key_list"]
    else:
        file_key = first_photo.get("file_key") if first_photo else None
    photo_url = build_photo_url(file_key) if file_key else None
    caption = _trainer_caption(trainer)
    keyboard = reply_markup if reply_markup is not None else _trainer_select_keyboard(
        trainer["id"], select_callback_data=select_callback_data
    )
    if photo_url:
        body = await fetch_photo_bytes(photo_url)
        if body:
            try:
                photo_file = BufferedInputFile(body, filename="photo.jpg")
                await bot.send_photo(
                    chat_id=chat_id, photo=photo_file, caption=caption, reply_markup=keyboard
                )
            except Exception as e:
                logger.warning("Failed to send photo for trainer %s: %s", trainer.get("id"), e)
                await bot.send_message(chat_id=chat_id, text=caption, reply_markup=keyboard)
        else:
            await bot.send_message(chat_id=chat_id, text=caption, reply_markup=keyboard)
    else:
        await bot.send_message(chat_id=chat_id, text=caption, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(CATALOG_TRAINER_PREFIX))
async def on_select_trainer(callback: CallbackQuery, bot: Bot) -> None:
    """Save selected trainer in session and show confirmation with next-step buttons."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    trainer_id = safe_parse_id(callback.data[len(CATALOG_TRAINER_PREFIX):])
    if trainer_id is None:
        return
    async with async_session_factory() as db_session:
        await set_selected_trainer(telegram_id, trainer_id, db_session)
        trainer = await get_trainer(db_session, trainer_id)
    name = _trainer_name(trainer) if trainer else "Тренер"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.CLIENT_BUTTON_BOOK, callback_data="book")],
        [InlineKeyboardButton(text=msg.CLIENT_BUTTON_ANOTHER_TRAINER, callback_data=CATALOG_CALLBACK)],
    ])
    await callback.message.answer(
        msg.CLIENT_TRAINER_SELECTED.format(name=name),
        reply_markup=keyboard,
    )


def _format_slot_time(st, et) -> str:
    """HH:MM–HH:MM from time or string."""
    def _str(t):
        if hasattr(t, "strftime"):
            return t.strftime("%H:%M")
        s = str(t)
        return s[:5] if len(s) >= 5 else s
    return f"{_str(st)}–{_str(et)}"


def _slot_duration_minutes(start_time, end_time) -> int:
    """Duration in minutes from slot start/end time (time or string)."""
    try:
        if hasattr(start_time, "hour") and hasattr(end_time, "hour"):
            delta = datetime.combine(date.today(), end_time) - datetime.combine(date.today(), start_time)
            return max(0, int(delta.total_seconds() // 60))
    except (TypeError, ValueError):
        pass
    return 45


async def _client_slots_content(trainer_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    """Available slots for trainer (this + next week). Text with blank line between days; buttons = short labels."""
    this_m = this_week_monday()
    next_m = next_week_monday()
    to_date = next_m + timedelta(days=6)
    async with async_session_factory() as db_session:
        slots = await list_slots(db_session, trainer_id, this_m, to_date)
    available = [s for s in slots if (s.get("status") or "available") == "available"]
    if not available:
        return msg.CLIENT_BOOK_NO_SLOTS, None
    lines = [msg.CLIENT_BOOK_CHOOSE_SLOT]
    prev_d = None
    for s in available:
        d = s["slot_date"]
        if prev_d is not None and d != prev_d:
            lines.append("")
        prev_d = d
        date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
        dow = CLIENT_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
        time_range = _format_slot_time(s["start_time"], s["end_time"])
        lines.append(f"• {date_str} ({dow}) {time_range}")
    text = "\n".join(lines)
    # Short buttons for mobile: "dd.mm 10" (hour only)
    buttons = []
    BUTTONS_PER_ROW = 3
    for i in range(0, len(available), BUTTONS_PER_ROW):
        row = []
        for s in available[i : i + BUTTONS_PER_ROW]:
            d = s["slot_date"]
            date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
            h = s["start_time"].hour if hasattr(s["start_time"], "hour") else int(str(s["start_time"])[:2])
            row.append(InlineKeyboardButton(
                text=f"{date_str} {h}",
                callback_data=f"{BOOK_SLOT_PREFIX}{s['id']}",
            ))
        buttons.append(row)
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(lambda c: c.data == "book")
async def on_book(callback: CallbackQuery) -> None:
    """Show available slots for selected trainer; user picks one to book."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        session_data = await get_session(telegram_id, db_session)
    trainer_id = (session_data or {}).get("selected_trainer_id") if session_data else None
    if not trainer_id:
        await callback.message.answer(msg.CLIENT_BOOK_NO_TRAINER)
        return
    text, keyboard = await _client_slots_content(trainer_id)
    if keyboard is None:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_ANOTHER_TRAINER, callback_data=CATALOG_CALLBACK)],
        ])
        await callback.message.answer(text, reply_markup=back_kb)
        return
    back_row = [[InlineKeyboardButton(text=msg.CLIENT_BOOK_BUTTON_BACK, callback_data=CATALOG_CALLBACK)]]
    full_kb = InlineKeyboardMarkup(inline_keyboard=keyboard.inline_keyboard + back_row)
    await callback.message.answer(text, reply_markup=full_kb)


def _normalize_phone(text: str | None) -> str:
    """Keep digits and + only; empty if invalid."""
    if not text or not text.strip():
        return ""
    s = "".join(c for c in text.strip() if c.isdigit() or c == "+")
    return s if len(s) >= 10 else ""


@router.callback_query(lambda c: c.data and c.data.startswith(BOOK_SLOT_PREFIX))
async def on_book_slot(callback: CallbackQuery) -> None:
    """Start booking flow: ask for phone (slot chosen)."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    slot_id = int(callback.data[len(BOOK_SLOT_PREFIX):])
    async with async_session_factory() as db_session:
        session_data = await get_session(telegram_id, db_session)
        trainer_id = (session_data or {}).get("selected_trainer_id") if session_data else None
    if not trainer_id:
        await callback.message.answer(msg.CLIENT_BOOK_NO_TRAINER)
        return
    _booking_state[telegram_id] = {"slot_id": slot_id, "trainer_id": trainer_id}
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=msg.CLIENT_BOOK_BUTTON_SEND_CONTACT, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await callback.message.answer(msg.CLIENT_BOOK_ENTER_PHONE, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == BOOKING_SKIP_COMMENT)
async def on_booking_skip_comment(callback: CallbackQuery) -> None:
    """Finish booking without comment."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    state = _booking_state.pop(telegram_id, None)
    if not state or "phone" not in state:
        await callback.message.answer(msg.CLIENT_BOOK_NO_TRAINER)
        return
    await _finish_booking(callback.message, telegram_id, state["slot_id"], state["trainer_id"], state["phone"], None)


async def _finish_booking(message: Message, telegram_id: int, slot_id: int, trainer_id: int, phone: str, comment: str | None) -> None:
    """Create booking, show success, remove keyboard. If session has pending_request_id, link and archive that request."""
    client_request_id: int | None = None
    from_user = message.from_user
    first_name = from_user.first_name if from_user else None
    last_name = from_user.last_name if from_user else None
    async with async_session_factory() as db_session:
        session = await get_session(telegram_id, db_session)
        if session and isinstance(session.get("payload"), dict):
            client_request_id = session["payload"].get("pending_request_id")
        client_id = await get_or_create_client(
            db_session, telegram_id, phone=phone, first_name=first_name, last_name=last_name,
        )
        booking_id = await create_booking(
            db_session, slot_id, trainer_id, client_id, client_comment=comment,
            client_request_id=client_request_id,
        )
        if booking_id:
            # Generate client reminders for this booking (24h / 2h depending on creation time).
            await generate_reminders_for_booking(db_session, booking_id)
    if not booking_id:
        await message.answer(msg.CLIENT_BOOK_NO_SLOTS, reply_markup=ReplyKeyboardRemove())
        return
    audit_log("booking.created", ACTOR_CLIENT_BOT, telegram_id, {"booking_id": booking_id, "trainer_id": trainer_id, "slot_id": slot_id})
    if client_request_id is not None:
        async with async_session_factory() as db_session:
            await clear_pending_request_id(telegram_id, db_session)
    async with async_session_factory() as db_session:
        slot = await get_slot(db_session, slot_id)
    if not slot:
        await message.answer(msg.CLIENT_BOOK_RECORDED, reply_markup=ReplyKeyboardRemove())
        return
    d = slot["slot_date"]
    date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
    dow = CLIENT_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
    time_range = _format_slot_time(slot["start_time"], slot["end_time"])
    duration = _slot_duration_minutes(slot["start_time"], slot["end_time"])
    text = msg.CLIENT_BOOK_SUCCESS.format(date=date_str, day=dow, time=time_range, duration=duration)
    await message.answer(text, reply_markup=ReplyKeyboardRemove())
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.CLIENT_BUTTON_ANOTHER_TRAINER, callback_data=CATALOG_CALLBACK)],
    ])
    await message.answer(msg.CLIENT_BOOK_WHAT_NEXT, reply_markup=keyboard)


@router.message(lambda m: m.from_user and m.from_user.id in _booking_state)
async def on_booking_message(message: Message) -> None:
    """Handle phone or comment in booking flow."""
    telegram_id = message.from_user.id if message.from_user else 0
    state = _booking_state.get(telegram_id)
    if not state:
        return
    # Phone step
    if "phone" not in state:
        phone = ""
        if message.contact and message.contact.phone_number:
            phone = _normalize_phone(message.contact.phone_number) or message.contact.phone_number
        elif message.text:
            phone = _normalize_phone(message.text)
        if not phone:
            await message.answer(msg.CLIENT_BOOK_PHONE_INVALID)
            return
        state["phone"] = phone
        _booking_state[telegram_id] = state
        skip_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BOOK_SKIP_COMMENT, callback_data=BOOKING_SKIP_COMMENT)],
        ])
        await message.answer(
            msg.CLIENT_BOOK_ENTER_COMMENT,
            reply_markup=ReplyKeyboardRemove(),
        )
        await message.answer(msg.CLIENT_BOOK_COMMENT_OR_BUTTON, reply_markup=skip_kb)
        return
    # Comment step
    comment = truncate_text(message.text, MAX_COMMENT_LEN)
    slot_id = state["slot_id"]
    trainer_id = state["trainer_id"]
    phone = state["phone"]
    _booking_state.pop(telegram_id, None)
    await _finish_booking(message, telegram_id, slot_id, trainer_id, phone, comment)


# --- Feedback after completed booking: rating 1–5 + optional review ---
FEEDBACK_SKIP_PREFIX = "feedback_skip:"


@router.callback_query(lambda c: c.data and c.data.startswith(FEEDBACK_BOOKING_PREFIX))
async def on_feedback_booking_start(callback: CallbackQuery) -> None:
    """Client tapped 'Leave feedback': show 1–5 stars."""
    await callback.answer()
    raw = (callback.data or "").replace(FEEDBACK_BOOKING_PREFIX, "").strip()
    booking_id = safe_parse_id(raw)
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        booking = await get_booking_for_client_feedback(db_session, booking_id, telegram_id)
    if not booking:
        await callback.message.answer(msg.CLIENT_ERROR_BOOKING_CLOSED)
        return
    _feedback_state[telegram_id] = {"booking_id": booking_id, "trainer_id": booking["trainer_id"]}
    stars = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1⭐", callback_data=f"{FEEDBACK_RATING_PREFIX}{booking_id}:1"),
            InlineKeyboardButton(text="2⭐", callback_data=f"{FEEDBACK_RATING_PREFIX}{booking_id}:2"),
            InlineKeyboardButton(text="3⭐", callback_data=f"{FEEDBACK_RATING_PREFIX}{booking_id}:3"),
            InlineKeyboardButton(text="4⭐", callback_data=f"{FEEDBACK_RATING_PREFIX}{booking_id}:4"),
            InlineKeyboardButton(text="5⭐", callback_data=f"{FEEDBACK_RATING_PREFIX}{booking_id}:5"),
        ],
    ])
    await callback.message.answer(msg.CLIENT_FEEDBACK_RATE_PROMPT, reply_markup=stars)


@router.callback_query(lambda c: c.data and c.data.startswith(FEEDBACK_RATING_PREFIX))
async def on_feedback_rating(callback: CallbackQuery) -> None:
    """Client chose rating; ask for optional review text or skip."""
    await callback.answer()
    # data = feedback_rating:booking_id:rating
    parts = (callback.data or "").replace(FEEDBACK_RATING_PREFIX, "").strip().split(":")
    if len(parts) != 2:
        return
    try:
        booking_id = int(parts[0])
        rating = int(parts[1])
    except ValueError:
        return
    if rating < 1 or rating > 5:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    state = _feedback_state.get(telegram_id)
    if not state or state.get("booking_id") != booking_id:
        async with async_session_factory() as db_session:
            booking = await get_booking_for_client_feedback(db_session, booking_id, telegram_id)
        if not booking:
            await callback.message.answer(msg.CLIENT_ERROR_BOOKING_UNAVAILABLE)
            return
        state = {"booking_id": booking_id, "trainer_id": booking["trainer_id"]}
        _feedback_state[telegram_id] = state
    state["rating"] = rating
    _feedback_state[telegram_id] = state
    skip_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.CLIENT_FEEDBACK_SKIP, callback_data=f"{FEEDBACK_SKIP_PREFIX}{booking_id}")],
    ])
    await callback.message.answer(msg.CLIENT_FEEDBACK_REVIEW_PROMPT, reply_markup=skip_kb)


@router.callback_query(lambda c: c.data and c.data.startswith(FEEDBACK_SKIP_PREFIX))
async def on_feedback_skip(callback: CallbackQuery) -> None:
    """Client skipped review text; save rating only."""
    await callback.answer()
    raw = (callback.data or "").replace(FEEDBACK_SKIP_PREFIX, "").strip()
    booking_id = safe_parse_id(raw)
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    state = _feedback_state.pop(telegram_id, None)
    if not state or state.get("booking_id") != booking_id or "rating" not in state:
        return
    async with async_session_factory() as db_session:
        await add_trainer_rating(
            db_session,
            state["trainer_id"],
            telegram_id,
            state["rating"],
            review_text=None,
        )
    await callback.message.answer(msg.CLIENT_FEEDBACK_THANKS)


@router.message(lambda m: m.from_user and m.from_user.id in _feedback_state)
async def on_feedback_review_message(message: Message) -> None:
    """Client sent review text after rating."""
    telegram_id = message.from_user.id if message.from_user else 0
    state = _feedback_state.pop(telegram_id, None)
    if not state or "rating" not in state:
        return
    review_text = (message.text or "").strip() or None
    async with async_session_factory() as db_session:
        await add_trainer_rating(
            db_session,
            state["trainer_id"],
            telegram_id,
            state["rating"],
            review_text=review_text,
        )
    audit_log("trainer.rated", ACTOR_CLIENT_BOT, telegram_id, {"trainer_id": state["trainer_id"], "booking_id": state.get("booking_id"), "rating": state["rating"]})
    await message.answer(msg.CLIENT_FEEDBACK_THANKS)


# --- Repeat / Become regular: scenarios ---
# Repeat (Повторить): 1) slot next week available → book, success. 2) slot booked → no wait;
#   if another client has recurring for this time → "закреплён за другим постоянным"; else "слот занят, можно стать постоянным или другое время".
# 3) No slot yet → add wait_request, "когда тренер добавит слот — запишем и напишем".
# Become permanent (Стать постоянным): 1) This client already recurring → "уже закреплено". 2) Another client has recurring for (trainer, day, time) → "закреплено за другим". 3) OK → create recurring; if slot next week free → also book and say "записали на следующую неделю".


@router.callback_query(lambda c: c.data and c.data.startswith(REPEAT_BOOKING_PREFIX))
async def on_repeat_booking(callback: CallbackQuery) -> None:
    """Repeat same time next week: book if slot available; else honest message (booked / taken by regular) or add wait."""
    await callback.answer()
    raw = (callback.data or "").replace(REPEAT_BOOKING_PREFIX, "").strip()
    booking_id = safe_parse_id(raw)
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        booking = await get_completed_booking_for_repeat(db_session, booking_id, telegram_id)
    if not booking:
        await callback.message.answer(msg.CLIENT_ERROR_BOOKING_CLOSED)
        return
    trainer_id = booking["trainer_id"]
    client_id = booking["client_id"]
    slot_date = booking["slot_date"]
    start_time = booking["start_time"]
    day_of_week = slot_date.weekday()
    async with async_session_factory() as db_session:
        status, slot_info = await get_slot_status_next_week(db_session, trainer_id, day_of_week, start_time)
    if status == "available" and slot_info:
        async with async_session_factory() as db_session:
            new_booking_id = await create_booking(
                db_session, slot_info["slot_id"], trainer_id, client_id, client_comment=None
            )
        if new_booking_id:
            async with async_session_factory() as db_session:
                await generate_reminders_for_booking(db_session, new_booking_id)
            date_str = slot_info["slot_date"].strftime("%d.%m") if hasattr(slot_info["slot_date"], "strftime") else str(slot_info["slot_date"])
            day_str = msg.TRAINER_DAYS[slot_info["slot_date"].weekday()] if hasattr(slot_info["slot_date"], "weekday") else ""
            time_str = start_time.strftime("%H:%M") if hasattr(start_time, "strftime") else ""
            await callback.message.answer(
                msg.CLIENT_REPEAT_BOOKED.format(date=date_str, day=day_str, time=time_str)
            )
            return
    if status == "booked":
        async with async_session_factory() as db_session:
            taken_by_regular = await has_other_active_recurring(
                db_session, trainer_id, day_of_week, start_time, exclude_client_id=client_id
            )
        # Remove Repeat/Become regular buttons from the message so they don't stay visible
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=msg.CLIENT_BUTTON_LEAVE_FEEDBACK, callback_data=f"feedback_booking:{booking_id}")],
            ])
            await callback.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            pass
        await callback.message.answer(
            msg.CLIENT_REPEAT_SLOT_TAKEN_BY_REGULAR if taken_by_regular else msg.CLIENT_REPEAT_SLOT_BOOKED
        )
        return
    async with async_session_factory() as db_session:
        await add_slot_wait_request(db_session, trainer_id, client_id, day_of_week, start_time)
    await callback.message.answer(msg.CLIENT_REPEAT_NO_SLOT_YET)


@router.callback_query(lambda c: c.data and c.data.startswith(MAKE_RECURRING_PREFIX))
async def on_make_recurring(callback: CallbackQuery) -> None:
    """Become regular: create recurring if no other client has this (trainer, day, time); optionally book next week."""
    await callback.answer()
    raw = (callback.data or "").replace(MAKE_RECURRING_PREFIX, "").strip()
    booking_id = safe_parse_id(raw)
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        booking = await get_completed_booking_for_repeat(db_session, booking_id, telegram_id)
    if not booking:
        await callback.message.answer(msg.CLIENT_ERROR_BOOKING_CLOSED)
        return
    trainer_id = booking["trainer_id"]
    client_id = booking["client_id"]
    slot_date = booking["slot_date"]
    start_time = booking["start_time"]
    end_time = booking["end_time"]
    day_of_week = slot_date.weekday()
    async with async_session_factory() as db_session:
        existing = await get_active_recurring_for_booking(db_session, trainer_id, client_id, day_of_week, start_time)
    if existing:
        await callback.message.answer(msg.CLIENT_RECURRING_ALREADY)
        return
    async with async_session_factory() as db_session:
        if await has_other_active_recurring(db_session, trainer_id, day_of_week, start_time, exclude_client_id=client_id):
            try:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=msg.CLIENT_BUTTON_LEAVE_FEEDBACK, callback_data=f"feedback_booking:{booking_id}")],
                ])
                await callback.message.edit_reply_markup(reply_markup=kb)
            except Exception:
                pass
            await callback.message.answer(msg.CLIENT_RECURRING_SLOT_TAKEN)
            return
    async with async_session_factory() as db_session:
        recurring_id = await create_recurring_client_slot(
            db_session, trainer_id, client_id, day_of_week, start_time, end_time
        )
    if recurring_id is None:
        await callback.message.answer(msg.CLIENT_RECURRING_ALREADY)
        return
    day_str = msg.TRAINER_DAYS[day_of_week]
    time_str = start_time.strftime("%H:%M") if hasattr(start_time, "strftime") else ""
    async with async_session_factory() as db_session:
        slot_info = await find_available_slot_next_week(db_session, trainer_id, day_of_week, start_time)
    if slot_info:
        async with async_session_factory() as db_session:
            new_booking_id = await create_booking(
                db_session, slot_info["slot_id"], trainer_id, client_id, client_comment=None
            )
        if new_booking_id:
            async with async_session_factory() as db_session:
                await generate_reminders_for_booking(db_session, new_booking_id)
        date_str = slot_info["slot_date"].strftime("%d.%m") if hasattr(slot_info["slot_date"], "strftime") else str(slot_info["slot_date"])
        await callback.message.answer(
            msg.CLIENT_RECURRING_DONE_AND_BOOKED.format(date=date_str, day=day_str, time=time_str)
        )
    else:
        await callback.message.answer(
            msg.CLIENT_RECURRING_DONE.format(day=day_str, time=time_str)
        )


@router.callback_query(lambda c: c.data and c.data.startswith(BOOK_AVAILABLE_SLOT_PREFIX))
async def on_book_available_slot(callback: CallbackQuery) -> None:
    """Book the slot from 'slot available' notification (repeat wait)."""
    await callback.answer()
    raw = (callback.data or "").replace(BOOK_AVAILABLE_SLOT_PREFIX, "").strip()
    slot_id = safe_parse_id(raw)
    if slot_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        client_id = await get_or_create_client(db_session, telegram_id)
        slot = await get_slot(db_session, slot_id)
        if not slot or slot.get("status") != "available":
            await callback.message.answer(msg.CLIENT_ERROR_BOOKING_UNAVAILABLE)
            return
        trainer_id = slot["trainer_id"]
        new_booking_id = await create_booking(
            db_session, slot_id, trainer_id, client_id, client_comment=None
        )
    if not new_booking_id:
        await callback.message.answer(msg.CLIENT_ERROR_BOOKING_UNAVAILABLE)
        return
    async with async_session_factory() as db_session:
        await generate_reminders_for_booking(db_session, new_booking_id)
    slot_date = slot["slot_date"]
    start_time = slot["start_time"]
    date_str = slot_date.strftime("%d.%m") if hasattr(slot_date, "strftime") else str(slot_date)
    day_str = msg.TRAINER_DAYS[slot_date.weekday()] if hasattr(slot_date, "weekday") else ""
    time_str = start_time.strftime("%H:%M") if hasattr(start_time, "strftime") else ""
    await callback.message.answer(
        msg.CLIENT_REPEAT_BOOKED.format(date=date_str, day=day_str, time=time_str)
    )


CATALOG_PAGE_SIZE = 10


async def _load_and_show_trainers(
    bot: Bot,
    chat_id: int,
    message_to_edit: Message,
    city_id: int,
    service_id: int,
    offset: int = 0,
    arena_id: int | None = None,
    *,
    select_callback_prefix: str | None = None,
) -> None:
    """
    Fetch one page of trainers (size CATALOG_PAGE_SIZE), send cards, then pagination row.
    arena_id optional: only trainers with slot in this arena.
    """
    lock = _catalog_load_locks[chat_id]
    if lock.locked():
        return
    async with lock:
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        await message_to_edit.edit_text(msg.CLIENT_CATALOG_LOADING, reply_markup=None)
        trainers, total = await fetch_active_trainers(
            limit=CATALOG_PAGE_SIZE,
            offset=offset,
            city_id=city_id,
            service_id=service_id,
            arena_id=arena_id,
            order_by="rating",
        )
        if not trainers:
            request_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=msg.CLIENT_REQUEST_BUTTON_EMPTY_CATALOG, callback_data=REQUEST_CALLBACK)],
            ])
            await message_to_edit.edit_text(msg.CLIENT_CATALOG_EMPTY, reply_markup=request_kb)
            return
        # Best (first by rating) at the end of the page so user sees them after scrolling down
        trainers = list(reversed(trainers))
        await message_to_edit.edit_text(msg.CLIENT_CATALOG_HEADER, reply_markup=None)
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        use_list_photo = True
        if select_callback_prefix:
            for trainer in trainers:
                await _send_trainer_card(
                    bot, chat_id, trainer,
                    select_callback_data=f"{select_callback_prefix}{trainer['id']}",
                    use_list_photo=use_list_photo,
                )
        else:
            await asyncio.gather(*[
                _send_trainer_card(
                    bot, chat_id, t,
                    select_callback_data=f"{CATALOG_TRAINER_PREFIX}{t['id']}",
                    use_list_photo=use_list_photo,
                )
                for t in trainers
            ])
        # Pagination: pass arena_id (0 = no filter)
        aid = arena_id or 0
        page_buttons = []
        if offset > 0:
            page_buttons.append(InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"{CATALOG_PAGE_PREFIX}{city_id}:{service_id}:{aid}:{offset - CATALOG_PAGE_SIZE}",
            ))
        if offset + len(trainers) < total:
            page_buttons.append(InlineKeyboardButton(
                text="Далее ▶️",
                callback_data=f"{CATALOG_PAGE_PREFIX}{city_id}:{service_id}:{aid}:{offset + CATALOG_PAGE_SIZE}",
            ))
        leave_request_text = msg.CLIENT_CATALOG_PAGINATION_LEAVE_REQUEST
        if page_buttons:
            page_buttons.append(InlineKeyboardButton(text=msg.CLIENT_BUTTON_LEAVE_REQUEST, callback_data=REQUEST_CALLBACK))
            await bot.send_message(
                chat_id,
                f"Страница {offset // CATALOG_PAGE_SIZE + 1} из {(total + CATALOG_PAGE_SIZE - 1) // CATALOG_PAGE_SIZE}. Показано {len(trainers)} из {total}.\n\n{leave_request_text}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[page_buttons]),
            )
        else:
            await bot.send_message(
                chat_id,
                f"Показаны все тренеры по вашему запросу.\n\n{leave_request_text}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=msg.CLIENT_BUTTON_LEAVE_REQUEST, callback_data=REQUEST_CALLBACK)],
                ]),
            )


def _city_keyboard(cities: list[dict], callback_prefix: str = CITY_PREFIX) -> InlineKeyboardMarkup:
    """One button per city. Use callback_prefix e.g. settings_city: for settings flow."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=c["name"], callback_data=f"{callback_prefix}{c['id']}")]
        for c in cities
    ])


def _service_keyboard(services: list[dict], callback_prefix: str = SERVICE_PREFIX) -> InlineKeyboardMarkup:
    """One button per service. Use callback_prefix e.g. settings_service: for settings flow."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=s["name"], callback_data=f"{callback_prefix}{s['id']}")]
        for s in services
    ])


async def _get_settings_content(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Build settings message text and keyboard from current session (resolve city/service/trainer names)."""
    cities = await fetch_cities()
    services = await fetch_services()
    city_name = msg.CLIENT_SETTINGS_NOT_SELECTED
    service_name = msg.CLIENT_SETTINGS_NOT_SELECTED
    arena_name = msg.CLIENT_SETTINGS_NOT_SELECTED
    trainer_name = msg.CLIENT_SETTINGS_NOT_SELECTED
    async with async_session_factory() as db_session:
        session = await get_or_create_session(telegram_id, db_session)
        cid = session.get("city_id")
        sid = session.get("selected_service_id")
        aid = session.get("selected_arena_id")
        tid = session.get("selected_trainer_id")
        if cid and cities:
            for c in cities:
                if c.get("id") == cid:
                    city_name = c.get("name", city_name)
                    break
        if sid and services:
            for s in services:
                if s.get("id") == sid:
                    service_name = s.get("name", service_name)
                    break
        if cid and aid:
            arenas = await fetch_arenas(cid)
            for a in arenas:
                if a.get("id") == aid:
                    arena_name = a.get("name", arena_name)
                    break
        if tid:
            trainer = await get_trainer(db_session, tid)
            trainer_name = _trainer_name(trainer) if trainer else msg.CLIENT_SETTINGS_NOT_SELECTED
    text = (
        msg.CLIENT_SETTINGS_TITLE + "\n\n"
        + msg.CLIENT_SETTINGS_ROW_CITY.format(value=city_name) + "\n"
        + msg.CLIENT_SETTINGS_ROW_SERVICE.format(value=service_name) + "\n"
        + msg.CLIENT_SETTINGS_ROW_ARENA.format(value=arena_name) + "\n"
        + msg.CLIENT_SETTINGS_ROW_TRAINER.format(value=trainer_name)
    )
    keyboard_rows = [
        [InlineKeyboardButton(text="Изменить город", callback_data="settings:city")],
        [InlineKeyboardButton(text="Изменить услугу", callback_data="settings:service")],
        [InlineKeyboardButton(text="Изменить арену", callback_data="settings:arena")],
        [InlineKeyboardButton(
            text=msg.CLIENT_BUTTON_CHOOSE_TRAINER if trainer_name == msg.CLIENT_SETTINGS_NOT_SELECTED else "Изменить тренера",
            callback_data="settings:trainer",
        )],
        [InlineKeyboardButton(text=msg.CLIENT_BUTTON_RESET_CHOICES, callback_data="settings:reset")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    return text, keyboard


@router.callback_query(lambda c: c.data == SETTINGS_CALLBACK)
async def show_settings(callback: CallbackQuery) -> None:
    """Open settings: current choices + change/reset buttons."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    text, keyboard = await _get_settings_content(telegram_id)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == "settings:city")
async def settings_show_city(callback: CallbackQuery) -> None:
    """From settings: show city picker (callback_data settings_city:id)."""
    await callback.answer()
    cities = await fetch_cities()
    if not cities:
        await callback.message.edit_text(msg.CLIENT_ERROR_NO_CITIES)
        return
    await callback.message.edit_text(
        msg.CLIENT_CHOOSE_CITY,
        reply_markup=_city_keyboard(cities, callback_prefix=SETTINGS_CITY_PREFIX),
    )


@router.callback_query(lambda c: c.data and c.data.startswith(SETTINGS_CITY_PREFIX))
async def on_settings_select_city(callback: CallbackQuery) -> None:
    """Save city from settings and show settings again."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    city_id = safe_parse_id(callback.data[len(SETTINGS_CITY_PREFIX):])
    if city_id is None:
        return
    async with async_session_factory() as db_session:
        await set_city(telegram_id, city_id, db_session)
    text, keyboard = await _get_settings_content(telegram_id)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == "settings:service")
async def settings_show_service(callback: CallbackQuery) -> None:
    """From settings: show service picker (callback_data settings_service:id)."""
    await callback.answer()
    services = await fetch_services()
    if not services:
        await callback.message.edit_text(msg.CLIENT_ERROR_NO_SERVICES)
        return
    await callback.message.edit_text(
        msg.CLIENT_CHOOSE_SERVICE,
        reply_markup=_service_keyboard(services, callback_prefix=SETTINGS_SERVICE_PREFIX),
    )


@router.callback_query(lambda c: c.data and c.data.startswith(SETTINGS_SERVICE_PREFIX))
async def on_settings_select_service(callback: CallbackQuery) -> None:
    """Save service from settings and show settings again."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    service_id = int(callback.data[len(SETTINGS_SERVICE_PREFIX):])
    async with async_session_factory() as db_session:
        await set_service(telegram_id, service_id, db_session)
    text, keyboard = await _get_settings_content(telegram_id)
    await callback.message.edit_text(text, reply_markup=keyboard)


SETTINGS_ARENA_PREFIX = "settings:arena:"


@router.callback_query(lambda c: c.data == "settings:arena")
async def settings_show_arena(callback: CallbackQuery) -> None:
    """Show arena picker: hint to look on map first, then name+address and [На карте] [Выбрать] per arena."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        session = await get_session(telegram_id, db_session)
    cid = session.get("city_id") if session else None
    if not cid:
        await callback.message.edit_text(msg.CLIENT_ERROR_CHOOSE_CITY_FIRST)
        return
    arenas = await fetch_arenas(cid)
    lines = [
        msg.CLIENT_CHOOSE_ARENA,
        msg.CLIENT_ARENA_UX_HINT,
        "",
    ]
    rows = []
    all_map_url = build_yandex_by_map_url_all_arenas(arenas)
    if all_map_url:
        rows.append([InlineKeyboardButton(text=msg.CLIENT_ARENA_BUTTON_MAP_ALL, url=all_map_url)])
    rows.append([InlineKeyboardButton(text="Любая арена", callback_data=f"{SETTINGS_ARENA_PREFIX}0")])
    for idx, a in enumerate(arenas, 1):
        name = (a.get("name") or "").strip() or "Арена"
        address = (a.get("address") or "").strip()
        lines.append(f"{idx}. <b>{name}</b>")
        if address:
            lines.append(f"   {address}")
        lines.append("")
        map_url = build_yandex_by_map_url(a) if a else None
        select_btn = InlineKeyboardButton(
            text=f"{idx}. {msg.CLIENT_ARENA_BUTTON_SELECT}",
            callback_data=f"{SETTINGS_ARENA_PREFIX}{a['id']}",
        )
        if map_url:
            rows.append([
                InlineKeyboardButton(text=f"{idx}. {msg.CLIENT_ARENA_BUTTON_MAP}", url=map_url),
                select_btn,
            ])
        else:
            rows.append([select_btn])
    rows.append([InlineKeyboardButton(text="В настройки", callback_data=SETTINGS_CALLBACK)])
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(lambda c: c.data and c.data.startswith(SETTINGS_ARENA_PREFIX))
async def on_settings_select_arena(callback: CallbackQuery) -> None:
    """Save arena (0 = any) and show settings again."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    raw = callback.data[len(SETTINGS_ARENA_PREFIX):]
    arena_id = safe_parse_id(raw) if raw and raw != "0" else None
    async with async_session_factory() as db_session:
        await set_arena(telegram_id, arena_id, db_session)
    text, keyboard = await _get_settings_content(telegram_id)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == "settings:trainer")
async def settings_show_trainer(callback: CallbackQuery, bot: Bot) -> None:
    """From settings: show trainer list (catalog_trainer:id) → select leads to "Выбран" + Записаться/Настройки."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        session = await get_session(telegram_id, db_session)
    city_id = session.get("city_id") if session else None
    service_id = session.get("selected_service_id") if session else None
    if not city_id or not service_id:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="В настройки", callback_data=SETTINGS_CALLBACK)],
        ])
        await callback.message.edit_text(msg.CLIENT_SETTINGS_NEED_CITY_SERVICE, reply_markup=back_kb)
        return
    chat_id = callback.message.chat.id
    arena_id = session.get("selected_arena_id") if session else None
    await _load_and_show_trainers(bot, chat_id, callback.message, city_id, service_id, arena_id=arena_id)


@router.callback_query(lambda c: c.data == "settings:reset")
async def settings_reset(callback: CallbackQuery) -> None:
    """Clear city, service, trainer and show settings in one message."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        await clear_choices(telegram_id, db_session)
    text, keyboard = await _get_settings_content(telegram_id)
    await callback.message.edit_text(
        msg.CLIENT_SETTINGS_RESET_DONE + "\n\n" + text,
        reply_markup=keyboard,
    )


# --- Leave request flow (demand when no trainer found) ---
@router.callback_query(lambda c: c.data == REQUEST_CALLBACK)
async def on_request_start(callback: CallbackQuery) -> None:
    """Start leave-request: require city+service from session, then ask optional comment."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        session = await get_session(telegram_id, db_session)
    city_id = session.get("city_id") if session else None
    service_id = session.get("selected_service_id") if session else None
    if not city_id or not service_id:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_REQUEST_BACK, callback_data=SETTINGS_CALLBACK)],
        ])
        await callback.message.answer(msg.CLIENT_REQUEST_NEED_CITY_SERVICE, reply_markup=back_kb)
        return
    _request_state[telegram_id] = {"city_id": city_id, "service_id": service_id}
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.CLIENT_REQUEST_SKIP, callback_data="request_skip")],
        [InlineKeyboardButton(text=msg.CLIENT_REQUEST_BACK, callback_data="request_back")],
    ])
    await callback.message.answer(msg.CLIENT_REQUEST_PROMPT_COMMENT, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == "request_skip")
async def on_request_skip_comment(callback: CallbackQuery) -> None:
    """Submit request without comment."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    state = _request_state.pop(telegram_id, None)
    if not state:
        await callback.message.answer(msg.CLIENT_REQUEST_NEED_CITY_SERVICE)
        return
    from_user = callback.from_user
    first_name = from_user.first_name if from_user else None
    last_name = from_user.last_name if from_user else None
    async with async_session_factory() as db_session:
        client_id = await get_or_create_client(db_session, telegram_id, first_name=first_name, last_name=last_name)
        request_id = await create_client_request(
            db_session, client_id,
            state["city_id"], state["service_id"],
            comment=None,
        )
    audit_log("client_request.created", ACTOR_CLIENT_BOT, telegram_id, {"request_id": request_id, "city_id": state["city_id"], "service_id": state["service_id"]})
    await callback.message.answer(msg.CLIENT_REQUEST_SUCCESS)


@router.callback_query(lambda c: c.data == "request_back")
async def on_request_back(callback: CallbackQuery) -> None:
    """Cancel request flow and return to settings."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    _request_state.pop(telegram_id, None)
    text, keyboard = await _get_settings_content(telegram_id)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.message(lambda m: m.from_user and m.from_user.id in _request_state)
async def on_request_comment_message(message: Message) -> None:
    """Submit request with comment (user sent text)."""
    telegram_id = message.from_user.id if message.from_user else 0
    state = _request_state.pop(telegram_id, None)
    if not state:
        return
    comment = truncate_text(message.text, MAX_COMMENT_LEN)
    from_user = message.from_user
    first_name = from_user.first_name if from_user else None
    last_name = from_user.last_name if from_user else None
    async with async_session_factory() as db_session:
        client_id = await get_or_create_client(db_session, telegram_id, first_name=first_name, last_name=last_name)
        request_id = await create_client_request(
            db_session, client_id,
            state["city_id"], state["service_id"],
            comment=comment,
        )
    audit_log("client_request.created", ACTOR_CLIENT_BOT, telegram_id, {"request_id": request_id, "city_id": state["city_id"], "service_id": state["service_id"]})
    await message.answer(msg.CLIENT_REQUEST_SUCCESS)


@router.callback_query(lambda c: c.data == MY_REQUESTS_CALLBACK)
async def show_my_requests(callback: CallbackQuery) -> None:
    """List = one button per request (page 0)."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    text, keyboard = await _my_requests_content(telegram_id)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(MY_REQUESTS_PAGE_PREFIX))
async def show_my_requests_page(callback: CallbackQuery) -> None:
    """Pagination for My requests list."""
    await callback.answer()
    try:
        page = int(callback.data[len(MY_REQUESTS_PAGE_PREFIX):])
    except ValueError:
        page = 0
    telegram_id = callback.from_user.id if callback.from_user else 0
    text, keyboard = await _my_requests_content(telegram_id, page=page)
    await callback.message.edit_text(text, reply_markup=keyboard)


def _format_request_responses_keyboard(req: dict) -> InlineKeyboardMarkup:
    """Build keyboard: each responder → Profile; then Edit/Delete; then Back."""
    rows = []
    for r in (req.get("responses") or []):
        name = r.get("name") or "Тренер"
        rows.append([InlineKeyboardButton(
            text=f"{msg.CLIENT_BUTTON_RESPONDER_PROFILE}: {name}",
            callback_data=f"{RESPONDER_PROFILE_PREFIX}{req['id']}:{r['trainer_id']}",
        )])
    rows.append([InlineKeyboardButton(
        text=msg.CLIENT_REQUEST_EDIT_DELETE_BUTTON,
        callback_data=f"{REQUEST_EDIT_PREFIX}{req['id']}",
    )])
    rows.append([InlineKeyboardButton(text=msg.CLIENT_BUTTON_BACK_TO_REQUESTS, callback_data=MY_REQUESTS_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(lambda c: c.data and c.data.startswith(MY_REQUEST_PREFIX))
async def show_request_responses(callback: CallbackQuery) -> None:
    """Show responders for one request: Write + Book buttons."""
    await callback.answer()
    request_id = int(callback.data[len(MY_REQUEST_PREFIX):])
    telegram_id = callback.from_user.id if callback.from_user else 0
    _request_edit_state.pop(telegram_id, None)
    async with async_session_factory() as db_session:
        requests_list = await list_my_requests_with_responses(db_session, telegram_id)
    req = next((r for r in requests_list if r["id"] == request_id), None)
    if not req:
        await callback.message.answer(msg.CLIENT_ERROR_REQUEST_NOT_FOUND)
        return
    request_index = next((i for i, r in enumerate(requests_list, 1) if r["id"] == request_id), 1)
    comment = (req.get("comment") or "").strip()
    if comment:
        text = msg.CLIENT_MY_REQUESTS_ROW.format(
            index=request_index, city=req["city_name"], service=req["service_name"], comment=comment
        )
    else:
        text = msg.CLIENT_MY_REQUESTS_ROW_NO_COMMENT.format(
            index=request_index, city=req["city_name"], service=req["service_name"]
        )
    text += "\n\n" + msg.CLIENT_MY_REQUESTS_RESPONSES_HEADER.format(count=len(req.get("responses") or []))
    for r in (req.get("responses") or []):
        name = r.get("name") or "Тренер"
        tc = (r.get("trainer_comment") or "").strip()
        if tc:
            text += "\n" + msg.CLIENT_RESPONDER_LINE.format(name=name, comment=tc)
        else:
            text += "\n" + msg.CLIENT_RESPONDER_LINE_NO_COMMENT.format(name=name)
    keyboard = _format_request_responses_keyboard(req)
    await callback.message.answer(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == "req_no_resp")
async def req_no_resp_callback(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith(REQUEST_EDIT_PREFIX))
async def show_request_edit(callback: CallbackQuery) -> None:
    """Show edit screen: city, service, current comment; await new message or Delete."""
    await callback.answer()
    try:
        request_id = int(callback.data[len(REQUEST_EDIT_PREFIX):])
    except ValueError:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        requests_list = await list_my_requests_with_responses(db_session, telegram_id)
    req = next((r for r in requests_list if r["id"] == request_id), None)
    if not req:
        await callback.message.answer(msg.CLIENT_ERROR_REQUEST_NOT_FOUND)
        return
    _request_edit_state[telegram_id] = request_id
    city = (req.get("city_name") or "").strip() or "—"
    service = (req.get("service_name") or "").strip() or "—"
    comment = (req.get("comment") or "").strip()
    if comment:
        body = msg.CLIENT_REQUEST_EDIT_CURRENT.format(city=city, service=service, comment=comment)
    else:
        body = msg.CLIENT_REQUEST_EDIT_CURRENT_NO_COMMENT.format(city=city, service=service)
    text = msg.CLIENT_REQUEST_EDIT_HEAD + "\n\n" + body + "\n\n" + msg.CLIENT_REQUEST_EDIT_PROMPT
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.CLIENT_REQUEST_DELETE_BUTTON, callback_data=f"{REQUEST_DELETE_PREFIX}{request_id}")],
        [InlineKeyboardButton(text=msg.CLIENT_REQUEST_EDIT_BACK, callback_data=f"{MY_REQUEST_PREFIX}{request_id}")],
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(REQUEST_EDIT_CONFIRM_PREFIX))
async def confirm_request_edit(callback: CallbackQuery) -> None:
    """Save new comment and return to request detail."""
    await callback.answer()
    try:
        request_id = int(callback.data[len(REQUEST_EDIT_CONFIRM_PREFIX):])
    except ValueError:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    state = _request_edit_state.get(telegram_id)
    pending = state.get("pending_comment", "") if isinstance(state, dict) else None
    if not isinstance(state, dict) or state.get("request_id") != request_id or pending is None:
        _request_edit_state.pop(telegram_id, None)
        await callback.message.answer(msg.CLIENT_ERROR_REQUEST_NOT_FOUND)
        return
    _request_edit_state.pop(telegram_id, None)
    async with async_session_factory() as db_session:
        new_request_id = await replace_client_request_with_new(
            db_session, request_id, telegram_id, pending
        )
    if new_request_id is None:
        await callback.message.answer(msg.CLIENT_ERROR_REQUEST_NOT_FOUND)
        return
    async with async_session_factory() as db_session:
        requests_list = await list_my_requests_with_responses(db_session, telegram_id)
    req = next((r for r in requests_list if r["id"] == new_request_id), None)
    if not req:
        await callback.message.answer(msg.CLIENT_REQUEST_EDIT_SAVED)
        return
    comment = (req.get("comment") or "").strip()
    text = msg.CLIENT_REQUEST_EDIT_SAVED + "\n\n"
    text += msg.CLIENT_MY_REQUESTS_ROW.format(
        index=1, city=req["city_name"], service=req["service_name"], comment=comment
    ) if comment else msg.CLIENT_MY_REQUESTS_ROW_NO_COMMENT.format(
        index=1, city=req["city_name"], service=req["service_name"]
    )
    text += "\n\n" + msg.CLIENT_MY_REQUESTS_RESPONSES_HEADER.format(count=len(req.get("responses") or []))
    for r in (req.get("responses") or []):
        name = r.get("name") or "Тренер"
        tc = (r.get("trainer_comment") or "").strip()
        text += "\n" + (msg.CLIENT_RESPONDER_LINE.format(name=name, comment=tc) if tc else msg.CLIENT_RESPONDER_LINE_NO_COMMENT.format(name=name))
    await callback.message.edit_text(text, reply_markup=_format_request_responses_keyboard(req))


@router.callback_query(lambda c: c.data and c.data.startswith(REQUEST_DELETE_PREFIX))
async def delete_request(callback: CallbackQuery) -> None:
    """Delete client request and show list."""
    await callback.answer()
    try:
        request_id = int(callback.data[len(REQUEST_DELETE_PREFIX):])
    except ValueError:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    _request_edit_state.pop(telegram_id, None)
    async with async_session_factory() as db_session:
        ok = await delete_client_request(db_session, request_id, telegram_id)
    if not ok:
        await callback.message.answer(msg.CLIENT_ERROR_REQUEST_NOT_FOUND)
        return
    await callback.answer(msg.CLIENT_REQUEST_DELETED)
    text, keyboard = await _my_requests_content(telegram_id)
    await callback.message.edit_text(msg.CLIENT_REQUEST_DELETED + "\n\n" + text, reply_markup=keyboard)


@router.message(lambda m: m.text and m.from_user and m.from_user.id in _request_edit_state)
async def on_request_edit_message(message: Message) -> None:
    """User sent new comment text → show confirm (Save or Delete)."""
    telegram_id = message.from_user.id if message.from_user else 0
    state = _request_edit_state.get(telegram_id)
    if state is None:
        return
    request_id = state if isinstance(state, int) else state.get("request_id")
    if request_id is None:
        _request_edit_state.pop(telegram_id, None)
        return
    comment = truncate_text(message.text, MAX_COMMENT_LEN)
    _request_edit_state[telegram_id] = {"request_id": request_id, "pending_comment": comment}
    preview = comment if comment else "(пусто)"
    text = msg.CLIENT_REQUEST_EDIT_CONFIRM.format(comment=preview)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=msg.CLIENT_REQUEST_EDIT_SAVE, callback_data=f"{REQUEST_EDIT_CONFIRM_PREFIX}{request_id}"),
            InlineKeyboardButton(text=msg.CLIENT_REQUEST_DELETE_BUTTON, callback_data=f"{REQUEST_DELETE_PREFIX}{request_id}"),
        ],
        [InlineKeyboardButton(text=msg.CLIENT_REQUEST_EDIT_BACK, callback_data=f"{MY_REQUEST_PREFIX}{request_id}")],
    ])
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(RESPONDER_PROFILE_PREFIX))
async def show_responder_profile(callback: CallbackQuery, bot: Bot) -> None:
    """Show full trainer card (photo + info) for a responder, with Write / Book / Back to responses."""
    await callback.answer()
    payload = callback.data[len(RESPONDER_PROFILE_PREFIX):].strip()
    parts = payload.split(":")
    if len(parts) != 2:
        await callback.message.answer(msg.CLIENT_ERROR_TRY_AGAIN)
        return
    request_id = safe_parse_id(parts[0])
    trainer_id = safe_parse_id(parts[1])
    if request_id is None or trainer_id is None:
        await callback.message.answer(msg.CLIENT_ERROR_TRY_AGAIN)
        return
    async with async_session_factory() as db_session:
        trainer = await get_trainer(db_session, trainer_id)
    if not trainer:
        await callback.message.answer(msg.CLIENT_ERROR_TRAINER_NOT_FOUND)
        return
    client_telegram_id = callback.from_user.id if callback.from_user else 0
    trainer_comment = None
    async with async_session_factory() as db_session:
        requests_list = await list_my_requests_with_responses(db_session, client_telegram_id)
    req = next((r for r in requests_list if r["id"] == request_id), None)
    if req:
        resp = next((r for r in (req.get("responses") or []) if r.get("trainer_id") == trainer_id), None)
        if resp:
            trainer_comment = (resp.get("trainer_comment") or "").strip() or None
    if trainer_comment:
        await callback.message.answer(msg.CLIENT_TRAINER_COMMENT_LABEL.format(comment=trainer_comment))
    telegram_id = trainer.get("telegram_id")
    buttons = []
    if telegram_id:
        buttons.append([InlineKeyboardButton(
            text=msg.CLIENT_BUTTON_RESPONDER_WRITE,
            url=f"tg://user?id={telegram_id}",
        )])
    buttons.append([InlineKeyboardButton(
        text=msg.CLIENT_BUTTON_RESPONDER_BOOK,
        callback_data=f"{BOOK_FROM_REQUEST_PREFIX}{request_id}:{trainer_id}",
    )])
    buttons.append([InlineKeyboardButton(
        text=msg.CLIENT_BUTTON_BACK_TO_RESPONSES,
        callback_data=f"{MY_REQUEST_PREFIX}{request_id}",
    )])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    chat_id = callback.message.chat.id if callback.message.chat else 0
    await _send_trainer_card(bot, chat_id, trainer, reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith(BOOK_FROM_REQUEST_PREFIX))
async def book_from_request(callback: CallbackQuery) -> None:
    """Set trainer from request + pending_request_id, then show slot list (booking from request flow)."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    payload = callback.data[len(BOOK_FROM_REQUEST_PREFIX):].strip()
    parts = payload.split(":")
    if len(parts) != 2:
        await callback.message.answer(msg.CLIENT_ERROR_TRY_AGAIN)
        return
    try:
        request_id = int(parts[0])
        trainer_id = int(parts[1])
    except ValueError:
        await callback.message.answer(msg.CLIENT_ERROR_TRY_AGAIN)
        return
    async with async_session_factory() as db_session:
        await set_selected_trainer(telegram_id, trainer_id, db_session)
        await set_pending_request_id(telegram_id, request_id, db_session)
    text, keyboard = await _client_slots_content(trainer_id)
    await callback.message.answer(msg.CLIENT_PICK_TRAINER_DONE)
    if keyboard is None:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_ANOTHER_TRAINER, callback_data=CATALOG_CALLBACK)],
        ])
        await callback.message.answer(text, reply_markup=back_kb)
        return
    back_row = [[InlineKeyboardButton(text=msg.CLIENT_BOOK_BUTTON_BACK, callback_data=CATALOG_CALLBACK)]]
    full_kb = InlineKeyboardMarkup(inline_keyboard=keyboard.inline_keyboard + back_row)
    await callback.message.answer(text, reply_markup=full_kb)


@router.callback_query(lambda c: c.data and c.data.startswith(PICK_RESPONDER_PREFIX))
async def pick_responder(callback: CallbackQuery) -> None:
    """Set selected trainer from responder and show slot list (book flow)."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    trainer_id = safe_parse_id(callback.data[len(PICK_RESPONDER_PREFIX):])
    if trainer_id is None:
        return
    async with async_session_factory() as db_session:
        await set_selected_trainer(telegram_id, trainer_id, db_session)
    text, keyboard = await _client_slots_content(trainer_id)
    await callback.message.answer(msg.CLIENT_PICK_TRAINER_DONE)
    if keyboard is None:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_ANOTHER_TRAINER, callback_data=CATALOG_CALLBACK)],
        ])
        await callback.message.answer(text, reply_markup=back_kb)
        return
    back_row = [[InlineKeyboardButton(text=msg.CLIENT_BOOK_BUTTON_BACK, callback_data=CATALOG_CALLBACK)]]
    full_kb = InlineKeyboardMarkup(inline_keyboard=keyboard.inline_keyboard + back_row)
    await callback.message.answer(text, reply_markup=full_kb)


@router.callback_query(lambda c: c.data == CATALOG_CALLBACK)
async def show_catalog(callback: CallbackQuery, bot: Bot) -> None:
    """Flow: city → service → trainers. Show current step from session."""
    await callback.answer()
    chat_id = callback.message.chat.id
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        await clear_pending_request_id(telegram_id, db_session)
        session = await get_or_create_session(telegram_id, db_session)
    if session.get("city_id") is None:
        cities = await fetch_cities()
        if not cities:
            await callback.message.answer(msg.CLIENT_ERROR_NO_CITIES_ADMIN)
            return
        await callback.message.answer(msg.CLIENT_CHOOSE_CITY, reply_markup=_city_keyboard(cities))
        return
    if session.get("selected_service_id") is None:
        services = await fetch_services()
        if not services:
            await callback.message.answer(msg.CLIENT_ERROR_NO_SERVICES_ADMIN)
            return
        await callback.message.answer(msg.CLIENT_CHOOSE_SERVICE, reply_markup=_service_keyboard(services))
        return
    await _load_and_show_trainers(
        bot, chat_id, callback.message,
        session["city_id"], session["selected_service_id"],
        arena_id=session.get("selected_arena_id"),
    )


@router.callback_query(lambda c: c.data and c.data.startswith(CATALOG_PAGE_PREFIX))
async def on_catalog_page(callback: CallbackQuery, bot: Bot) -> None:
    """Load next/prev page. Format: city_id:service_id:arena_id:offset (arena_id 0 = any)."""
    await callback.answer()
    payload = callback.data[len(CATALOG_PAGE_PREFIX):].strip()
    parts = payload.split(":")
    if len(parts) != 4:
        await callback.message.answer(msg.CLIENT_ERROR_TRY_AGAIN)
        return
    city_id = safe_parse_id(parts[0])
    service_id = safe_parse_id(parts[1])
    arena_id_raw = safe_parse_id(parts[2])
    offset = safe_parse_id(parts[3])
    if city_id is None or service_id is None or arena_id_raw is None or offset is None:
        await callback.message.answer(msg.CLIENT_ERROR_TRY_AGAIN)
        return
    arena_id = arena_id_raw if arena_id_raw else None
    chat_id = callback.message.chat.id if callback.message.chat else 0
    await _load_and_show_trainers(
        bot, chat_id, callback.message, city_id, service_id, offset=offset, arena_id=arena_id
    )


@router.callback_query(lambda c: c.data and c.data.startswith(CITY_PREFIX))
async def on_select_city(callback: CallbackQuery) -> None:
    """Save city and show service picker."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    city_id = safe_parse_id(callback.data[len(CITY_PREFIX):])
    if city_id is None:
        return
    async with async_session_factory() as db_session:
        await set_city(telegram_id, city_id, db_session)
    services = await fetch_services()
    if not services:
        await callback.message.answer(msg.CLIENT_ERROR_NO_SERVICES)
        return
    await callback.message.answer(msg.CLIENT_CHOOSE_SERVICE, reply_markup=_service_keyboard(services))


@router.callback_query(lambda c: c.data and c.data.startswith(SERVICE_PREFIX))
async def on_select_service(callback: CallbackQuery, bot: Bot) -> None:
    """Save service and show catalog (trainers filtered by city + service)."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    service_id = safe_parse_id(callback.data[len(SERVICE_PREFIX):])
    if service_id is None:
        return
    async with async_session_factory() as db_session:
        await set_service(telegram_id, service_id, db_session)
    chat_id = callback.message.chat.id
    async with async_session_factory() as db_session:
        sess = await get_session(telegram_id, db_session)
    city_id = sess.get("city_id") if sess else None
    arena_id = sess.get("selected_arena_id") if sess else None
    if not city_id:
        await callback.message.answer(msg.CLIENT_ERROR_CHOOSE_CITY_FIRST)
        return
    await _load_and_show_trainers(bot, chat_id, callback.message, city_id, service_id, arena_id=arena_id)


@router.message()
async def fallback(message: Message) -> None:
    """Any other message: direct to main menu and /guide; no buttons."""
    await message.answer(msg.CLIENT_FALLBACK)
