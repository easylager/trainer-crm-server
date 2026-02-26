"""
Client bot handlers: /start and catalog. Public entry; no auth.
"""
import asyncio
import logging
from collections import defaultdict
from datetime import timedelta

from aiogram import Bot, Router
from aiogram.enums import ChatAction
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
    list_my_requests_with_responses,
)
from src.application.booking_use_cases import (
    create_booking,
    generate_reminders_for_booking,
    get_booking_for_client_feedback,
)
from src.application.trainer_schedule_use_cases import (
    get_slot,
    list_slots,
    next_week_monday,
    this_week_monday,
)
from src.application.trainer_use_cases import add_trainer_rating, get_trainer
from src.bot import messages as msg
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

logger = logging.getLogger(__name__)
router = Router(name="client")

# One catalog-load at a time per chat to avoid duplicate callback showing EMPTY then HEADER.
_catalog_load_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

CATALOG_CALLBACK = "catalog"
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
MY_REQUEST_PREFIX = "my_request:"
BOOK_FROM_REQUEST_PREFIX = "book_from_req:"
CATALOG_PAGE_PREFIX = "catalog_page:"
PICK_RESPONDER_PREFIX = "pick_responder:"
RESPONDER_PROFILE_PREFIX = "responder_profile:"
CLIENT_DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

# Booking flow state: telegram_id -> { slot_id, trainer_id, phone?, comment? }
_booking_state: dict[int, dict] = {}

# Request (leave demand) flow: telegram_id -> { city_id, service_id }; next step = comment or skip
_request_state: dict[int, dict] = {}

# Feedback after completed booking: telegram_id -> { booking_id, trainer_id, rating? }; next = review text or skip
FEEDBACK_BOOKING_PREFIX = "feedback_booking:"
FEEDBACK_RATING_PREFIX = "feedback_rating:"
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
    return msg.CLIENT_TRAINER_CARD.format(
        name=name,
        rating=rating_str,
        age=age_str,
        experience=exp_str,
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
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Каталог тренеров", callback_data=CATALOG_CALLBACK)],
    ])
    await message.answer(msg.CLIENT_START_WELCOME, reply_markup=keyboard)


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
    """Open 'Мои заявки и отклики' from menu (left of attachment). Same as callback MY_REQUESTS_CALLBACK."""
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as db_session:
        requests_list = await list_my_requests_with_responses(db_session, telegram_id)
    if not requests_list:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_REQUEST_BACK, callback_data=SETTINGS_CALLBACK)],
        ])
        await message.answer(msg.CLIENT_MY_REQUESTS_EMPTY, reply_markup=back_kb)
        return
    lines = [msg.CLIENT_MY_REQUESTS_TITLE]
    buttons = []
    for i, req in enumerate(requests_list, start=1):
        comment = (req.get("comment") or "").strip()
        if comment:
            lines.append(msg.CLIENT_MY_REQUESTS_ROW.format(
                index=i, city=req["city_name"], service=req["service_name"], comment=comment
            ))
        else:
            lines.append(msg.CLIENT_MY_REQUESTS_ROW_NO_COMMENT.format(
                index=i, city=req["city_name"], service=req["service_name"]
            ))
        count = len(req.get("responses") or [])
        if count:
            buttons.append([InlineKeyboardButton(
                text=msg.CLIENT_MY_REQUESTS_BUTTON_RESPONSES.format(index=i, count=count),
                callback_data=f"{MY_REQUEST_PREFIX}{req['id']}",
            )])
        else:
            buttons.append([InlineKeyboardButton(
                text=msg.CLIENT_MY_REQUESTS_NO_RESPONSES.format(index=i),
                callback_data="req_no_resp",
            )])
    buttons.append([InlineKeyboardButton(text=msg.CLIENT_REQUEST_BACK, callback_data=SETTINGS_CALLBACK)])
    body = "\n\n".join(lines[1:])
    text = lines[0] + "\n\n" + body if body else lines[0]
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


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
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_ANOTHER_TRAINER, callback_data=CATALOG_CALLBACK)],
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
    trainer_id = int(callback.data[len(CATALOG_TRAINER_PREFIX):])
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
    async with async_session_factory() as db_session:
        session = await get_session(telegram_id, db_session)
        if session and isinstance(session.get("payload"), dict):
            client_request_id = session["payload"].get("pending_request_id")
        booking_id = await create_booking(
            db_session, slot_id, trainer_id, telegram_id, phone, comment,
            client_request_id=client_request_id,
        )
        if booking_id:
            # Generate client reminders for this booking (24h / 2h depending on creation time).
            await generate_reminders_for_booking(db_session, booking_id)
    if not booking_id:
        await message.answer(msg.CLIENT_BOOK_NO_SLOTS, reply_markup=ReplyKeyboardRemove())
        return
    if client_request_id is not None:
        async with async_session_factory() as db_session:
            await clear_pending_request_id(telegram_id, db_session)
    async with async_session_factory() as db_session:
        slot = await get_slot(db_session, slot_id)
    if not slot:
        await message.answer("Запись оформлена.", reply_markup=ReplyKeyboardRemove())
        return
    d = slot["slot_date"]
    date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
    dow = CLIENT_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
    time_range = _format_slot_time(slot["start_time"], slot["end_time"])
    text = msg.CLIENT_BOOK_SUCCESS.format(date=date_str, day=dow, time=time_range)
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
        await message.answer("Напишите комментарий или нажмите кнопку:", reply_markup=skip_kb)
        return
    # Comment step
    comment = (message.text or "").strip() or None
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
    if not raw:
        return
    try:
        booking_id = int(raw)
    except ValueError:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        booking = await get_booking_for_client_feedback(db_session, booking_id, telegram_id)
    if not booking:
        await callback.message.answer("Эта запись уже закрыта или недоступна.")
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
            await callback.message.answer("Эта запись недоступна.")
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
    try:
        booking_id = int(raw)
    except ValueError:
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
    await message.answer(msg.CLIENT_FEEDBACK_THANKS)


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
        await callback.message.edit_text("Нет доступных городов.")
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
    city_id = int(callback.data[len(SETTINGS_CITY_PREFIX):])
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
        await callback.message.edit_text("Нет доступных услуг.")
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
        await callback.message.edit_text("Сначала выберите город.")
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
    arena_id = int(raw) if raw and raw != "0" else None
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
    async with async_session_factory() as db_session:
        await create_client_request(
            db_session, telegram_id,
            state["city_id"], state["service_id"],
            comment=None,
        )
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
    comment = (message.text or "").strip() or None
    async with async_session_factory() as db_session:
        await create_client_request(
            db_session, telegram_id,
            state["city_id"], state["service_id"],
            comment=comment,
        )
    await message.answer(msg.CLIENT_REQUEST_SUCCESS)


@router.callback_query(lambda c: c.data == MY_REQUESTS_CALLBACK)
async def show_my_requests(callback: CallbackQuery) -> None:
    """List client's requests; each with button to show responders."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        requests_list = await list_my_requests_with_responses(db_session, telegram_id)
    if not requests_list:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_REQUEST_BACK, callback_data=SETTINGS_CALLBACK)],
        ])
        await callback.message.answer(msg.CLIENT_MY_REQUESTS_EMPTY, reply_markup=back_kb)
        return
    lines = [msg.CLIENT_MY_REQUESTS_TITLE]
    buttons = []
    for i, req in enumerate(requests_list, start=1):
        comment = (req.get("comment") or "").strip()
        if comment:
            lines.append(msg.CLIENT_MY_REQUESTS_ROW.format(
                index=i, city=req["city_name"], service=req["service_name"], comment=comment
            ))
        else:
            lines.append(msg.CLIENT_MY_REQUESTS_ROW_NO_COMMENT.format(
                index=i, city=req["city_name"], service=req["service_name"]
            ))
        count = len(req.get("responses") or [])
        if count:
            buttons.append([InlineKeyboardButton(
                text=msg.CLIENT_MY_REQUESTS_BUTTON_RESPONSES.format(index=i, count=count),
                callback_data=f"{MY_REQUEST_PREFIX}{req['id']}",
            )])
        else:
            buttons.append([InlineKeyboardButton(
                text=msg.CLIENT_MY_REQUESTS_NO_RESPONSES.format(index=i),
                callback_data="req_no_resp",
            )])
    buttons.append([InlineKeyboardButton(text=msg.CLIENT_REQUEST_BACK, callback_data=SETTINGS_CALLBACK)])
    body = "\n\n".join(lines[1:])
    text = lines[0] + "\n\n" + body if body else lines[0]
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


def _format_request_responses_keyboard(req: dict) -> InlineKeyboardMarkup:
    """Build keyboard: for each responder, button 'Профиль: {name}' → opens full trainer card; then Back."""
    rows = []
    for r in (req.get("responses") or []):
        name = r.get("name") or "Тренер"
        rows.append([InlineKeyboardButton(
            text=f"{msg.CLIENT_BUTTON_RESPONDER_PROFILE}: {name}",
            callback_data=f"{RESPONDER_PROFILE_PREFIX}{req['id']}:{r['trainer_id']}",
        )])
    rows.append([InlineKeyboardButton(text=msg.CLIENT_BUTTON_BACK_TO_REQUESTS, callback_data=MY_REQUESTS_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(lambda c: c.data and c.data.startswith(MY_REQUEST_PREFIX))
async def show_request_responses(callback: CallbackQuery) -> None:
    """Show responders for one request: Write + Book buttons."""
    await callback.answer()
    request_id = int(callback.data[len(MY_REQUEST_PREFIX):])
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        requests_list = await list_my_requests_with_responses(db_session, telegram_id)
    req = next((r for r in requests_list if r["id"] == request_id), None)
    if not req:
        await callback.message.answer("Заявка не найдена.")
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
    keyboard = _format_request_responses_keyboard(req)
    await callback.message.answer(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == "req_no_resp")
async def req_no_resp_callback(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith(RESPONDER_PROFILE_PREFIX))
async def show_responder_profile(callback: CallbackQuery, bot: Bot) -> None:
    """Show full trainer card (photo + info) for a responder, with Write / Book / Back to responses."""
    await callback.answer()
    payload = callback.data[len(RESPONDER_PROFILE_PREFIX):].strip()
    parts = payload.split(":")
    if len(parts) != 2:
        await callback.message.answer("Ошибка. Попробуйте снова.")
        return
    try:
        request_id = int(parts[0])
        trainer_id = int(parts[1])
    except ValueError:
        await callback.message.answer("Ошибка. Попробуйте снова.")
        return
    async with async_session_factory() as db_session:
        trainer = await get_trainer(db_session, trainer_id)
    if not trainer:
        await callback.message.answer("Тренер не найден.")
        return
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
        await callback.message.answer("Ошибка. Попробуйте снова.")
        return
    try:
        request_id = int(parts[0])
        trainer_id = int(parts[1])
    except ValueError:
        await callback.message.answer("Ошибка. Попробуйте снова.")
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
    trainer_id = int(callback.data[len(PICK_RESPONDER_PREFIX):])
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
            await callback.message.answer("Нет доступных городов. Обратитесь к администратору.")
            return
        await callback.message.answer(msg.CLIENT_CHOOSE_CITY, reply_markup=_city_keyboard(cities))
        return
    if session.get("selected_service_id") is None:
        services = await fetch_services()
        if not services:
            await callback.message.answer("Нет доступных услуг. Обратитесь к администратору.")
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
        await callback.message.answer("Ошибка. Попробуйте снова.")
        return
    try:
        city_id = int(parts[0])
        service_id = int(parts[1])
        arena_id_raw = int(parts[2])
        offset = int(parts[3])
    except ValueError:
        await callback.message.answer("Ошибка. Попробуйте снова.")
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
    city_id = int(callback.data[len(CITY_PREFIX):])
    async with async_session_factory() as db_session:
        await set_city(telegram_id, city_id, db_session)
    services = await fetch_services()
    if not services:
        await callback.message.answer("Нет доступных услуг.")
        return
    await callback.message.answer(msg.CLIENT_CHOOSE_SERVICE, reply_markup=_service_keyboard(services))


@router.callback_query(lambda c: c.data and c.data.startswith(SERVICE_PREFIX))
async def on_select_service(callback: CallbackQuery, bot: Bot) -> None:
    """Save service and show catalog (trainers filtered by city + service)."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    service_id = int(callback.data[len(SERVICE_PREFIX):])
    async with async_session_factory() as db_session:
        await set_service(telegram_id, service_id, db_session)
    chat_id = callback.message.chat.id
    async with async_session_factory() as db_session:
        sess = await get_session(telegram_id, db_session)
    city_id = sess.get("city_id") if sess else None
    arena_id = sess.get("selected_arena_id") if sess else None
    if not city_id:
        await callback.message.answer("Сначала выберите город.")
        return
    await _load_and_show_trainers(bot, chat_id, callback.message, city_id, service_id, arena_id=arena_id)


@router.message()
async def fallback(message: Message) -> None:
    """Any other message: hint to use /start or catalog."""
    await message.answer(msg.CLIENT_FALLBACK)
