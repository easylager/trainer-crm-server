"""
Client bot handlers: /start and catalog. Public entry; no auth.
"""
import asyncio
import html
import logging
import random
import re
import string
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ChatType, ParseMode
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
    WebAppInfo,
)

from src.application.booking_use_cases import (
    count_trainer_services,
    create_booking,
    generate_reminders_for_booking,
    get_booking_for_client_feedback,
    get_completed_booking_for_repeat,
    get_first_service_id_for_trainer,
    get_trainer_default_city_and_service,
    get_trainer_telegram_id,
    list_bookings_for_client,
    resolve_welcome_session_city_service,
    trainer_has_access_to_client,
)
from src.application.subscription_tier_use_cases import trainer_allows_online_booking
from src.application.certificate_use_cases import activate_certificate_by_code
from src.application.client_username_enrich import sync_client_telegram_username_from_client_bot
from src.application.client_use_cases import (
    apply_certificate_recipient_to_client,
    attach_telegram_id_to_client,
    get_client_by_phone,
    get_client_id_by_telegram_id,
    get_client_phone_for_webapp,
    get_client_telegram_id,
    get_or_create_client,
    get_client_profile_basic,
    normalize_phone,
)
from src.application.client_session_use_cases import (
    clear_selected_service,
    clear_choices,
    clear_pending_request_id,
    get_or_create_session,
    get_session,
    save_catalog_filters,
    set_arena,
    set_city,
    set_pending_request_id,
    set_selected_trainer,
    set_service,
)
from src.application.client_trainer_edge_use_cases import set_primary_trainer
from src.application.client_request_comment_display import (
    client_request_comment_editable,
    client_visible_request_comment,
)
from src.application.client_request_use_cases import (
    create_client_request,
    delete_client_request,
    get_client_request_for_booking,
    list_my_requests_with_responses,
    replace_client_request_with_new,
)
from src.application.recurring_use_cases import (
    add_slot_wait_request,
    create_recurring_client_slot,
    find_available_slot_next_week,
    get_active_recurring_for_booking,
    get_slot_status_on_date,
    has_other_active_recurring,
    trainer_calendar_interval_clear,
    try_insert_client_repeat_gap_notification,
)
from src.application.trainer_schedule_use_cases import (
    get_slot,
    list_slots,
    next_week_monday,
    this_week_monday,
)
from src.application.demand_signals_use_cases import record_profile_view_commit
from src.application.trainer_use_cases import add_trainer_rating, get_trainer
from src.application.trainer_invite_links import SHARE_REF_PREFIX
from src.application.support_use_cases import create_support_message
from src.application.group_attendance_use_cases import (
    attendance_rsvp_verify,
    respond_attendance_rsvp,
    rsvp_hmac_secret,
)
from src.application.welcome_link_use_cases import (
    WELCOME_TOKEN_TYPE_CERT,
    WELCOME_TOKEN_TYPE_CLIENT_BIND,
    WELCOME_TOKEN_TYPE_FAMILY_ACCESS,
    WELCOME_TOKEN_TYPE_GENERIC,
    WELCOME_TOKEN_TYPE_PASS,
    consume_welcome_link_token,
)
from src.infrastructure.db.models import DEMAND_SOURCE_CLIENT_APP, DEMAND_SOURCE_CLIENT_SHARE, SUPPORT_FROM_CLIENT
from src.application.family_access_use_cases import attach_family_member_from_invite
from src.application.trainer_client_registration_notify import notify_trainers_family_access_member_joined
from src.bot.handlers.relay_handlers import (
    maybe_route_client_relay_text_reply,
    on_client_bot_relay_close_callback,
    on_client_bot_relay_reply_callback,
)
from src.bot import messages as msg
from src.shared.config import Settings
from src.shared.mini_app_https import mini_app_https_base
from src.shared.notification_hours import NOTIFICATION_TZ, working_hours_between
from src.shared.audit import ACTOR_CLIENT_BOT, audit_log
from src.bot.client_api import (
    build_photo_url,
    fetch_active_trainers,
    fetch_arenas,
    fetch_cities,
    fetch_photo_bytes,
    fetch_services,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db import async_session_factory
from src.shared.map_links import build_yandex_by_map_url, build_yandex_by_map_url_all_arenas

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]
from src.shared.byr_currency_display import format_rubles_byn_display
from src.shared.validation import MAX_COMMENT_LEN, safe_parse_id, truncate_text

logger = logging.getLogger(__name__)
router = Router(name="client")

# One catalog-load at a time per chat to avoid duplicate callback showing EMPTY then HEADER.
_catalog_load_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

CATALOG_CALLBACK = "catalog"
GUIDE_CALLBACK = "guide"
CLIENT_SUPPORT_CALLBACK = "client:support"
_client_support_awaiting: set[int] = set()
REQUEST_CALLBACK = "request"
SETTINGS_CALLBACK = "settings"
# Invite/bind «Главная» when WEBAPP_BASE_URL is not HTTPS — mirror /home (mini_app_https may still yield API HTTPS).
CLIENT_HOME_WEBAPP_CALLBACK = "client_home_webapp"
SETTINGS_CITY_PREFIX = "settings_city:"
SETTINGS_SERVICE_PREFIX = "settings_service:"
# Catalog flow: select trainer → "Выбран" + Записаться/Настройки (used from catalog and from settings "Выбор тренера").
CATALOG_TRAINER_PREFIX = "catalog_trainer:"
CITY_PREFIX = "city:"
SERVICE_PREFIX = "service:"

# Deep link from site: t.me/Bot?start=client_{city_id}_{service_id}_{trainer_id} — prefill session and show "Записаться".
CLIENT_START_PREFIX = "client_"
CERT_START_PREFIX = "cert_"
BOOK_SLOT_PREFIX = "book_slot:"
BOOKING_SKIP_COMMENT = "booking_skip_comment"
BOOKING_USE_TG_NAME = "booking_use_tg_name"
BOOKING_ENTER_MANUAL = "booking_enter_manual"
MY_REQUESTS_CALLBACK = "my_requests"
# Telegram Bot API: max 100 rows per inline keyboard — no chat pagination (full UX in Mini App).
MAX_INLINE_MY_REQUESTS = 100
MY_BOOKINGS_CALLBACK = "my_bookings"
MY_REQUEST_PREFIX = "my_request:"
REQUEST_EDIT_PREFIX = "request_edit:"
REQUEST_EDIT_CONFIRM_PREFIX = "request_edit_confirm:"
REQUEST_DELETE_PREFIX = "request_delete:"
BOOK_FROM_REQUEST_PREFIX = "book_from_req:"
CATALOG_PAGE_PREFIX = "catalog_page:"
PICK_RESPONDER_PREFIX = "pick_responder:"


def client_passes_certificates_webapp_url(base: str, *, certificates_tab: bool = False) -> str:
    """Combined client Mini App (tabs); optional deep link to certificates."""
    url = f"{base.rstrip('/')}/webapp/client-passes-certificates"
    if certificates_tab:
        url += "?tab=certificates"
    return url
RESPONDER_PROFILE_PREFIX = "responder_profile:"
CLIENT_DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

# Booking flow state: telegram_id -> { slot_id, trainer_id, phone?, comment? }
_booking_state: dict[int, dict] = {}

# Link-by-phone: trainer added client without Telegram; user attaches telegram_id after code verification.
_link_phone_state: dict[int, dict] = {}  # telegram_id -> { "step": "phone"|"code", "client_id": int, "code": str }

# Request (leave demand) flow: telegram_id -> { city_id, service_id }; next step = comment or skip
_request_state: dict[int, dict] = {}
# Request edit: telegram_id -> request_id (int) when awaiting new comment, or { "request_id": int, "pending_comment": str }
_request_edit_state: dict[int, int | dict] = {}

# Feedback after completed booking: telegram_id -> { booking_id, trainer_id, rating? }; next = review text or skip
FEEDBACK_BOOKING_PREFIX = "feedback_booking:"
FEEDBACK_RATING_PREFIX = "feedback_rating:"
REPEAT_BOOKING_PREFIX = "repeat_booking:"
# Must match trainer_handlers.TRAINER_REPEAT_WEEK_PREFIX (trainer bot callback).
TRAINER_REPEAT_WEEK_CALLBACK_PREFIX = "trainer_repeat_week:"
MAKE_RECURRING_PREFIX = "make_recurring:"
BOOK_AVAILABLE_SLOT_PREFIX = "book_available_slot:"
_feedback_state: dict[int, dict] = {}


def _parse_client_start(payload: str) -> tuple[int, int | None, int] | None:
    """Parse client_<city_id>_<service_id_or_0>_<trainer_id>. Returns (city_id, service_id|None, trainer_id) or None."""
    if not payload or not payload.startswith(CLIENT_START_PREFIX):
        return None
    rest = payload[len(CLIENT_START_PREFIX) :].strip()
    parts = rest.split("_")
    if len(parts) != 3:
        return None
    try:
        city_id, service_id_raw, trainer_id = int(parts[0]), int(parts[1]), int(parts[2])
        if city_id <= 0 or service_id_raw < 0 or trainer_id <= 0:
            return None
        service_id = service_id_raw if service_id_raw > 0 else None
        return (city_id, service_id, trainer_id)
    except ValueError:
        return None


def _certificate_amount_display(cents: int | None) -> str:
    if cents is None:
        return "—"
    v = int(cents) / 100.0
    return format_rubles_byn_display(v)


def _trainer_name(trainer: dict) -> str:
    """Short name for trainer from profile."""
    profile = trainer.get("profile") or {}
    name = (profile.get("first_name") or "") + " " + (profile.get("last_name") or "")
    return name.strip() or "Тренер"


def _book_webapp_service_id_query_param(
    *,
    default_service_id: int | None,
    trainer_services_count: int,
    explicit_service_from_link: bool = False,
) -> int | None:
    """
    Build ?service_id= for /webapp/book. When the trainer offers several services and the link
    did not pin one, omit service_id so the Mini App adds force_service_choice=1 and shows picker.
    """
    if explicit_service_from_link and default_service_id is not None:
        return default_service_id
    if trainer_services_count <= 1:
        return default_service_id
    return None


def _trainer_catalog_card_rows(
    base: str,
    trainer_id: int,
    *,
    city_id: int | None = None,
    service_id: int | None = None,
    arena_id: int | None = None,
    button_text: str | None = None,
) -> list[list[InlineKeyboardButton]]:
    """Mini App: trainer catalog card (user books from there). Not /webapp/book deep link."""
    label = (button_text or "").strip() or msg.CLIENT_BUTTON_BOOK
    b = (base or "").rstrip("/")
    if b.startswith("https://"):
        q = f"trainer_id={int(trainer_id)}"
        if city_id is not None:
            q += f"&city_id={int(city_id)}"
        if service_id is not None:
            q += f"&service_id={int(service_id)}"
        if arena_id is not None:
            q += f"&arena_id={int(arena_id)}"
        url = f"{b}/webapp/catalog?{q}"
        return [[InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))]]
    return [[InlineKeyboardButton(text=label, callback_data=f"{CATALOG_TRAINER_PREFIX}{trainer_id}")]]


def _trainer_book_rows(
    base: str,
    trainer_id: int,
    *,
    service_id: int | None = None,
    button_text: str | None = None,
) -> list[list[InlineKeyboardButton]]:
    """Primary booking CTA: Mini App when HTTPS is configured, else legacy callback."""
    label = (button_text or "").strip() or msg.CLIENT_BUTTON_BOOK
    b = (base or "").rstrip("/")
    if b.startswith("https://"):
        url = f"{b}/webapp/book?trainer_id={trainer_id}&v=20260420d"
        if service_id is not None:
            url += f"&service_id={int(service_id)}"
        else:
            # Deep links without explicit service must start from service picker, not stale client session.
            url += "&force_service_choice=1"
        return [[InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))]]
    return [[InlineKeyboardButton(text=label, callback_data="book")]]


def _client_buy_pass_webapp_url(
    base: str, trainer_id: int, pass_product_id: int | None = None
) -> str:
    """Client Mini App price list; optional pass_product_id highlights that product on open."""
    b = (base or "").rstrip("/")
    q = f"trainer_id={int(trainer_id)}"
    if pass_product_id is not None:
        q += f"&pass_product_id={int(pass_product_id)}"
    return f"{b}/webapp/client-buy-pass?{q}"


def _trainer_book_markup(
    base: str,
    trainer_id: int,
    *,
    include_catalog_alternative: bool = False,
    service_id: int | None = None,
) -> InlineKeyboardMarkup:
    """Inline keyboard: book (+ optional «другой тренер» for catalog flows)."""
    rows = _trainer_book_rows(base, trainer_id, service_id=service_id)
    if include_catalog_alternative:
        rows = rows + [
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_ANOTHER_TRAINER, callback_data=CATALOG_CALLBACK)],
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _trainer_invite_welcome_markup(
    base: str,
    trainer_id: int,
    *,
    city_id: int | None = None,
    service_id: int | None = None,
) -> InlineKeyboardMarkup:
    """Invite / welcome_ref / share_ref: одна кнопка → карточка тренера в каталоге Mini App."""
    return InlineKeyboardMarkup(
        inline_keyboard=_trainer_catalog_card_rows(
            base,
            trainer_id,
            city_id=city_id,
            service_id=service_id,
            button_text=msg.CLIENT_BUTTON_INVITE_TRAINER_PROFILE,
        )
    )


def _welcome_pass_invite_body(trainer: dict | None) -> str:
    """Единый текст после welcome-токена / ref / share_ref: тренер + контекст Ice Studio."""
    name = html.escape(_trainer_name(trainer) if trainer else "Тренер")
    return msg.CLIENT_PASS_WELCOME.format(name=name)


async def _bind_client_invite_trainer_context(
    telegram_id: int,
    trainer_id: int,
    db_session: AsyncSession,
    *,
    preferred_service_id: int | None = None,
) -> tuple[int | None, int | None]:
    """
    Persist catalog filters + primary trainer after invite / share_ref / welcome_ref.
    Ensures Mini App opens the inviter's card and «Мой тренер» matches the link.
    """
    if preferred_service_id is not None:
        city_id, service_id = await resolve_welcome_session_city_service(
            db_session,
            trainer_id,
            preferred_service_id=preferred_service_id,
        )
    else:
        city_id, service_id = await get_trainer_default_city_and_service(db_session, trainer_id)
    await save_catalog_filters(
        telegram_id,
        db_session,
        city_id=city_id,
        service_id=service_id,
        trainer_id=int(trainer_id),
    )
    await set_primary_trainer(telegram_id, int(trainer_id), db_session)
    return city_id, service_id


# Mirrors redirect username rules so /r/tg/{id} does not 404 when the user taps «Написать».
_CLIENT_TG_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,64}$")


def _client_trainer_write_url(*, base: str, trainer: dict) -> str | None:
    """
    Prefer HTTPS /r/tg/{id} (records contact_click) when public base and @username exist;
    otherwise fall back to tg://user (no server-side click signal).
    """
    b = (base or "").rstrip("/")
    trainer_id = trainer.get("id")
    telegram_id = trainer.get("telegram_id")
    if trainer_id is None:
        return None
    if b.startswith("https://"):
        raw_u = (trainer.get("telegram_username") or "").strip().lstrip("@")
        if raw_u and _CLIENT_TG_USERNAME_RE.fullmatch(raw_u):
            return f"{b}/r/tg/{int(trainer_id)}?src={DEMAND_SOURCE_CLIENT_APP}"
    if telegram_id:
        return f"tg://user?id={int(telegram_id)}"
    return None


def _invite_welcome_text(trainer: dict | None, base: str) -> str:
    """Welcome copy for invite/deep-link: one screen, name + CTA matched to Web App vs inline."""
    name = html.escape(_trainer_name(trainer) if trainer else "Тренер")
    b = (base or "").rstrip("/")
    cta = (
        msg.CLIENT_WELCOME_INVITE_CTA_WEBAPP
        if b.startswith("https://")
        else msg.CLIENT_WELCOME_INVITE_CTA_INLINE
    )
    return msg.CLIENT_WELCOME_INVITE.format(name=name, cta=cta)


def _bind_first_impression_markup() -> InlineKeyboardMarkup:
    """После invite/bind одна кнопка — клиентский хаб Mini App (`/webapp/client-home`)."""
    label = msg.CLIENT_BUTTON_TRAINER_AND_BOOKING
    https_base, _ = mini_app_https_base(Settings())
    if https_base and https_base.lower().startswith("https://"):
        hub_url = f"{https_base.rstrip('/')}/webapp/client-home"
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=label, web_app=WebAppInfo(url=hub_url))],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=CLIENT_HOME_WEBAPP_CALLBACK)],
        ]
    )


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


async def _my_requests_content(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Legacy chat list: one button per request, single screen (capped at Telegram row limit)."""
    async with async_session_factory() as db_session:
        requests_list = await list_my_requests_with_responses(db_session, telegram_id)
    if not requests_list:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_REQUEST_BACK, callback_data=SETTINGS_CALLBACK)],
        ])
        text = msg.CLIENT_MY_REQUESTS_TITLE + "\n\n" + msg.CLIENT_MY_REQUESTS_EMPTY
        return text, back_kb
    total = len(requests_list)
    truncated = total > MAX_INLINE_MY_REQUESTS
    display = requests_list[:MAX_INLINE_MY_REQUESTS] if truncated else requests_list
    text = msg.CLIENT_MY_REQUESTS_TITLE + "\n\n" + msg.CLIENT_MY_REQUESTS_LIST_HINT
    if truncated:
        text += msg.CLIENT_MY_REQUESTS_TRUNCATED_NOTE.format(
            shown=MAX_INLINE_MY_REQUESTS, total=total
        )
    button_rows = []
    for req in display:
        button_rows.append([InlineKeyboardButton(
            text=_request_list_button_label(req),
            callback_data=f"{MY_REQUEST_PREFIX}{req['id']}",
        )])
    button_rows.append([InlineKeyboardButton(text=msg.CLIENT_REQUEST_BACK, callback_data=SETTINGS_CALLBACK)])
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, keyboard


def _format_services_prices(services: list[dict]) -> str:
    """Format 'Услуга: X + suffix' or 'Услуга: по запросу' for each; join with ', '. Uses price_byn (rubles)."""
    if not services:
        return "—"
    parts = []
    for s in services:
        name = (s.get("service_name") or "").strip() or "—"
        byn = s.get("price_byn")
        if byn is not None:
            parts.append(f"{name}: {format_rubles_byn_display(byn)}")
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


def _parse_cert_start(payload: str) -> tuple[str, int | None]:
    """Parse cert_<CODE> or cert_<CODE>_ref_<trainer_id>. Returns (code, ref_trainer_id or None)."""
    if not payload or not payload.startswith(CERT_START_PREFIX):
        return ("", None)
    rest = payload[len(CERT_START_PREFIX) :].strip()
    if "_ref_" in rest:
        code_part, _, ref_part = rest.partition("_ref_")
        code = code_part.strip()
        try:
            ref_id = int(ref_part.strip())
            return (code, ref_id if ref_id > 0 else None)
        except ValueError:
            return (code, None)
    return (rest, None)


WELCOME_REF_PREFIX = "welcome_ref_"
WELCOME_T_PREFIX = "welcome_t_"
PASS_START_PREFIX = "pass_"


def _parse_welcome_t_token(payload: str) -> uuid.UUID | None:
    """Parse welcome_t_<uuid>. Returns UUID or None."""
    if not payload or not payload.startswith(WELCOME_T_PREFIX):
        return None
    rest = payload[len(WELCOME_T_PREFIX) :].strip()
    try:
        return uuid.UUID(rest)
    except (ValueError, TypeError):
        return None


def _parse_welcome_ref(payload: str) -> int | None:
    """Parse welcome_ref_<trainer_id>. Returns trainer_id or None."""
    if not payload or not payload.startswith(WELCOME_REF_PREFIX):
        return None
    try:
        tid = int(payload[len(WELCOME_REF_PREFIX) :].strip())
        return tid if tid > 0 else None
    except ValueError:
        return None


def _parse_share_ref(payload: str) -> int | None:
    """Parse share_ref_<trainer_id>. Returns trainer_id or None."""
    if not payload or not payload.startswith(SHARE_REF_PREFIX):
        return None
    try:
        tid = int(payload[len(SHARE_REF_PREFIX) :].strip())
        return tid if tid > 0 else None
    except ValueError:
        return None


def _parse_pass_start(payload: str) -> tuple[int | None, int | None]:
    """Parse pass_<product_id>_ref_<trainer_id>. Returns (pass_product_id, trainer_id) or (None, None)."""
    if not payload or not payload.startswith(PASS_START_PREFIX):
        return (None, None)
    rest = payload[len(PASS_START_PREFIX) :].strip()
    if "_ref_" not in rest:
        return (None, None)
    product_part, _, ref_part = rest.partition("_ref_")
    try:
        product_id = int(product_part.strip())
        trainer_id = int(ref_part.strip())
        return (product_id if product_id > 0 else None, trainer_id if trainer_id > 0 else None)
    except ValueError:
        return (None, None)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Welcome and catalog; or deep link: /start client_C_S_T or /start cert_<CODE> (bind certificate, set trainer)."""
    telegram_id = message.from_user.id if message.from_user else 0
    parts = (message.text or "").strip().split(maxsplit=1)
    payload = (parts[1].strip() if len(parts) > 1 else "") or ""

    # One-time token: welcome_t_<uuid> — burn token, then run cert/pass/generic flow
    token_uuid = _parse_welcome_t_token(payload)
    if token_uuid is not None:
        async with async_session_factory() as db_session:
            payload_data = await consume_welcome_link_token(db_session, token_uuid)
        if not payload_data:
            await message.answer(msg.CLIENT_WELCOME_LINK_USED)
            return
        token_type = payload_data.get("type") or ""
        trainer_id = payload_data.get("trainer_id")
        if not trainer_id:
            await message.answer(msg.CLIENT_WELCOME_LINK_USED)
            return
        preferred_svc = payload_data.get("service_id")
        if token_type == WELCOME_TOKEN_TYPE_CLIENT_BIND:
            bind_client_id = payload_data.get("client_id")
            if bind_client_id is None:
                await message.answer(msg.CLIENT_WELCOME_LINK_USED)
                return
            uname = None
            if message.from_user and (message.from_user.username or "").strip():
                uname = (message.from_user.username or "").strip()[:64]
            async with async_session_factory() as db_session:
                allowed = await trainer_has_access_to_client(
                    db_session, int(trainer_id), int(bind_client_id)
                )
                row_tg = await get_client_telegram_id(db_session, int(bind_client_id))
                other = await get_client_id_by_telegram_id(db_session, telegram_id)
            if not allowed:
                await message.answer(msg.CLIENT_WELCOME_BIND_FAILED)
                return
            if row_tg is None:
                if other is not None and int(other) != int(bind_client_id):
                    await message.answer(msg.CLIENT_WELCOME_BIND_OTHER_PROFILE)
                    return
                async with async_session_factory() as db_session:
                    ok = await attach_telegram_id_to_client(
                        db_session,
                        int(bind_client_id),
                        telegram_id,
                        telegram_username=uname,
                    )
                    if ok:
                        await get_or_create_client(
                            db_session, telegram_id, telegram_username=uname
                        )
                    await sync_client_telegram_username_from_client_bot(db_session, telegram_id)
                    await db_session.commit()
                if not ok:
                    await message.answer(msg.CLIENT_WELCOME_BIND_FAILED)
                    return
            else:
                if int(row_tg) != telegram_id:
                    await message.answer(msg.CLIENT_WELCOME_LINK_USED)
                    return
                async with async_session_factory() as db_session:
                    await get_or_create_client(
                        db_session, telegram_id, telegram_username=uname
                    )
                    await sync_client_telegram_username_from_client_bot(db_session, telegram_id)
                    await db_session.commit()
        elif token_type == WELCOME_TOKEN_TYPE_FAMILY_ACCESS:
            fam_client_id = payload_data.get("client_id")
            if fam_client_id is None:
                await message.answer(msg.CLIENT_WELCOME_LINK_USED)
                return
            uname_fam = None
            if message.from_user and (message.from_user.username or "").strip():
                uname_fam = (message.from_user.username or "").strip()[:64]
            async with async_session_factory() as db_session:
                allowed_fam = await trainer_has_access_to_client(
                    db_session, int(trainer_id), int(fam_client_id)
                )
                owner_tid_fam = await get_client_telegram_id(db_session, int(fam_client_id))
                other_fam = await get_client_id_by_telegram_id(db_session, telegram_id)
            if not allowed_fam:
                await message.answer(msg.CLIENT_WELCOME_BIND_FAILED)
                return
            if owner_tid_fam is not None and int(owner_tid_fam) == int(telegram_id):
                await message.answer(msg.CLIENT_FAMILY_ACCESS_ALREADY_OWNER)
                return
            if other_fam is not None and int(other_fam) != int(fam_client_id):
                await message.answer(msg.CLIENT_WELCOME_BIND_OTHER_PROFILE)
                return
            async with async_session_factory() as db_session:
                ok_fam, err_fam, is_new_fam = await attach_family_member_from_invite(
                    db_session,
                    primary_client_id=int(fam_client_id),
                    member_telegram_id=int(telegram_id),
                    invited_by_telegram_id=None,
                    telegram_username=uname_fam,
                )
                if ok_fam:
                    await sync_client_telegram_username_from_client_bot(db_session, telegram_id)
                await db_session.commit()
            if not ok_fam:
                if err_fam == "limit_reached":
                    await message.answer(msg.CLIENT_FAMILY_ACCESS_LIMIT)
                elif err_fam == "duplicate_client":
                    await message.answer(msg.CLIENT_WELCOME_BIND_OTHER_PROFILE)
                elif err_fam == "no_owner_telegram":
                    await message.answer(msg.CLIENT_WELCOME_BIND_FAILED)
                else:
                    await message.answer(msg.CLIENT_WELCOME_BIND_FAILED)
                return
            if is_new_fam:
                async with async_session_factory() as db_session:
                    await notify_trainers_family_access_member_joined(
                        session=db_session,
                        primary_client_id=int(fam_client_id),
                        member_telegram_id=int(telegram_id),
                        member_telegram_username=uname_fam,
                    )
        else:
            async with async_session_factory() as db_session:
                await get_or_create_client(db_session, telegram_id)
                await db_session.commit()
        async with async_session_factory() as db_session:
            city_id, service_id = await _bind_client_invite_trainer_context(
                telegram_id,
                trainer_id,
                db_session,
                preferred_service_id=preferred_svc,
            )
            n_trainer_svc = await count_trainer_services(db_session, int(trainer_id))
            book_url_svc = _book_webapp_service_id_query_param(
                default_service_id=service_id,
                trainer_services_count=n_trainer_svc,
                explicit_service_from_link=preferred_svc is not None,
            )
            await record_profile_view_commit(
                db_session,
                trainer_id=int(trainer_id),
                source=DEMAND_SOURCE_CLIENT_APP,
            )
        if token_type == WELCOME_TOKEN_TYPE_CLIENT_BIND:
            async with async_session_factory() as db_session:
                trainer = await get_trainer(db_session, int(trainer_id))
            name = html.escape(_trainer_name(trainer) if trainer else "Тренер")
            await message.answer(
                msg.CLIENT_WELCOME_BIND_FIRST_IMPRESSION.format(name=name),
                parse_mode=ParseMode.HTML,
                reply_markup=_bind_first_impression_markup(),
            )
        elif token_type == WELCOME_TOKEN_TYPE_FAMILY_ACCESS:
            await message.answer(
                msg.CLIENT_FAMILY_ACCESS_WELCOME,
                parse_mode=ParseMode.HTML,
                reply_markup=_bind_first_impression_markup(),
            )
        elif token_type == WELCOME_TOKEN_TYPE_CERT:
            cert_code = payload_data.get("cert_code")
            if cert_code:
                async with async_session_factory() as db_session:
                    client_id = await get_client_id_by_telegram_id(db_session, telegram_id)
                    bound = await activate_certificate_by_code(db_session, client_id, cert_code) if client_id else None
                    if bound:
                        await apply_certificate_recipient_to_client(
                            db_session, client_id,
                            bound.get("recipient_name"), bound.get("recipient_phone"),
                        )
                        await db_session.commit()
                if bound:
                    base = (Settings().webapp_base_url or "").rstrip("/")
                    async with async_session_factory() as db_session:
                        trainer = await get_trainer(db_session, int(trainer_id))
                    tname = _trainer_name(trainer) if trainer else "Тренер"
                    cert_body = msg.format_client_certificate_bound_html(
                        amount_display=_certificate_amount_display(bound.get("amount_cents")),
                        code=str(cert_code).strip(),
                        trainer_name=tname,
                    )
                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=_trainer_catalog_card_rows(
                            base,
                            trainer_id,
                            city_id=city_id,
                            service_id=service_id,
                            button_text=msg.CLIENT_BUTTON_CERT_TRAINER_BOOK,
                        )
                    )
                    await message.answer(cert_body, reply_markup=keyboard, parse_mode=ParseMode.HTML)
                else:
                    await message.answer(msg.CLIENT_CERT_CODE_INVALID)
            else:
                async with async_session_factory() as db_session:
                    trainer = await get_trainer(db_session, trainer_id)
                base = (Settings().webapp_base_url or "").rstrip("/")
                welcome_body = _welcome_pass_invite_body(trainer)
                await message.answer(
                    welcome_body,
                    parse_mode=ParseMode.HTML,
                    reply_markup=_trainer_invite_welcome_markup(
                        base, trainer_id, city_id=city_id, service_id=book_url_svc
                    ),
                )
        elif token_type == WELCOME_TOKEN_TYPE_PASS:
            async with async_session_factory() as db_session:
                trainer = await get_trainer(db_session, trainer_id)
            base = (Settings().webapp_base_url or "").rstrip("/")
            await message.answer(
                _welcome_pass_invite_body(trainer),
                parse_mode=ParseMode.HTML,
                reply_markup=_trainer_invite_welcome_markup(
                    base, trainer_id, city_id=city_id, service_id=book_url_svc
                ),
            )
        else:
            async with async_session_factory() as db_session:
                trainer = await get_trainer(db_session, trainer_id)
            base = (Settings().webapp_base_url or "").rstrip("/")
            welcome_body = _welcome_pass_invite_body(trainer)
            await message.answer(
                welcome_body,
                parse_mode=ParseMode.HTML,
                reply_markup=_trainer_invite_welcome_markup(
                    base, trainer_id, city_id=city_id, service_id=book_url_svc
                ),
            )
        return

    # Certificate link: cert_<CODE> or cert_<CODE>_ref_<trainer_id>
    cert_code, ref_trainer_id = _parse_cert_start(payload)
    if cert_code:
        async with async_session_factory() as db_session:
            client_id = await get_or_create_client(db_session, telegram_id)
            await db_session.commit()
            bound = await activate_certificate_by_code(db_session, client_id, cert_code)
            if bound:
                await apply_certificate_recipient_to_client(
                    db_session,
                    client_id,
                    bound.get("recipient_name"),
                    bound.get("recipient_phone"),
                )
                await db_session.commit()
        if bound:
            trainer_id = bound["trainer_id"]
            async with async_session_factory() as db_session:
                city_id, service_id = await _bind_client_invite_trainer_context(
                    telegram_id, trainer_id, db_session
                )
                await record_profile_view_commit(
                    db_session,
                    trainer_id=int(trainer_id),
                    source=DEMAND_SOURCE_CLIENT_APP,
                )
            base = (Settings().webapp_base_url or "").rstrip("/")
            async with async_session_factory() as db_session:
                trainer = await get_trainer(db_session, int(trainer_id))
            tname = _trainer_name(trainer) if trainer else "Тренер"
            cert_body = msg.format_client_certificate_bound_html(
                amount_display=_certificate_amount_display(bound.get("amount_cents")),
                code=str(cert_code).strip(),
                trainer_name=tname,
            )
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=_trainer_catalog_card_rows(
                    base,
                    trainer_id,
                    city_id=city_id,
                    service_id=service_id,
                    button_text=msg.CLIENT_BUTTON_CERT_TRAINER_BOOK,
                )
            )
            await message.answer(cert_body, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        else:
            # Optional: preselected trainer from link (ref) so user can still book
            if ref_trainer_id:
                async with async_session_factory() as db_session:
                    await set_selected_trainer(telegram_id, ref_trainer_id, db_session)
                    await record_profile_view_commit(
                        db_session,
                        trainer_id=int(ref_trainer_id),
                        source=DEMAND_SOURCE_CLIENT_APP,
                    )
            await message.answer(msg.CLIENT_CERT_CODE_INVALID)
        return

    # Shared trainer profile: share_ref_<trainer_id> — friend recommendation deep link.
    # Same session setup as welcome_ref but records DEMAND_SOURCE_CLIENT_SHARE for PLG analytics.
    trainer_id_share = _parse_share_ref(payload)
    if trainer_id_share is not None:
        async with async_session_factory() as db_session:
            await get_or_create_client(db_session, telegram_id)
            await db_session.commit()
        async with async_session_factory() as db_session:
            city_id, service_id = await _bind_client_invite_trainer_context(
                telegram_id, trainer_id_share, db_session
            )
            n_trainer_svc = await count_trainer_services(db_session, int(trainer_id_share))
            book_url_share = _book_webapp_service_id_query_param(
                default_service_id=service_id,
                trainer_services_count=n_trainer_svc,
            )
            trainer = await get_trainer(db_session, trainer_id_share)
            await record_profile_view_commit(
                db_session,
                trainer_id=int(trainer_id_share),
                source=DEMAND_SOURCE_CLIENT_SHARE,
            )
        base = (Settings().webapp_base_url or "").rstrip("/")
        welcome_body = _welcome_pass_invite_body(trainer)
        await message.answer(
            welcome_body,
            parse_mode=ParseMode.HTML,
            reply_markup=_trainer_invite_welcome_markup(
                base, trainer_id_share, city_id=city_id, service_id=book_url_share
            ),
        )
        return

    # Generic invite: welcome_ref_<trainer_id> — universal entry point.
    # Client with saved phone → book flow; no phone yet (even if clients row exists) → registration form.
    trainer_id_ref = _parse_welcome_ref(payload)
    if trainer_id_ref is not None:
        async with async_session_factory() as db_session:
            phone_for_identify = await get_client_phone_for_webapp(db_session, telegram_id)
        phone_known = normalize_phone(phone_for_identify) is not None
        base = (Settings().webapp_base_url or "").rstrip("/")
        async with async_session_factory() as db_session:
            trainer = await get_trainer(db_session, trainer_id_ref)
            await record_profile_view_commit(
                db_session,
                trainer_id=int(trainer_id_ref),
                source=DEMAND_SOURCE_CLIENT_APP,
            )
        if not phone_known and base.lower().startswith("https://"):
            # No reachable phone yet: route to self-registration form in Mini App
            name = html.escape(_trainer_name(trainer) if trainer else "тренер")
            register_url = f"{base}/webapp/client-register?trainer_id={trainer_id_ref}"
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text=msg.CLIENT_UNIVERSAL_INVITE_REGISTER_BTN,
                        web_app=WebAppInfo(url=register_url),
                    )
                ]]
            )
            await message.answer(
                msg.CLIENT_UNIVERSAL_INVITE_UNKNOWN.format(name=name),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            return
        # Phone on file: inviter is primary; open client hub (not registration again).
        name = html.escape(_trainer_name(trainer) if trainer else "тренер")
        async with async_session_factory() as db_session:
            await get_or_create_client(db_session, telegram_id)
            await _bind_client_invite_trainer_context(
                telegram_id, trainer_id_ref, db_session
            )
        if base.lower().startswith("https://"):
            home_url = f"{base}/webapp/client-home"
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.CLIENT_BUTTON_TRAINER_AND_BOOKING,
                            web_app=WebAppInfo(url=home_url),
                        )
                    ],
                ]
            )
            await message.answer(
                msg.CLIENT_UNIVERSAL_INVITE_REGISTERED.format(name=name),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            return
        welcome_body = _welcome_pass_invite_body(trainer)
        await message.answer(welcome_body, parse_mode=ParseMode.HTML)
        return

    # Pass invite: pass_<product_id>_ref_<trainer_id> — set trainer, offer book + buy pass
    pass_product_id, pass_trainer_id = _parse_pass_start(payload)
    if pass_product_id is not None and pass_trainer_id is not None:
        async with async_session_factory() as db_session:
            await get_or_create_client(db_session, telegram_id)
            await db_session.commit()
        async with async_session_factory() as db_session:
            city_id, service_id = await _bind_client_invite_trainer_context(
                telegram_id, pass_trainer_id, db_session
            )
            n_trainer_svc = await count_trainer_services(db_session, int(pass_trainer_id))
            book_url_pass = _book_webapp_service_id_query_param(
                default_service_id=service_id,
                trainer_services_count=n_trainer_svc,
            )
            trainer = await get_trainer(db_session, pass_trainer_id)
            await record_profile_view_commit(
                db_session,
                trainer_id=int(pass_trainer_id),
                source=DEMAND_SOURCE_CLIENT_APP,
            )
        base = (Settings().webapp_base_url or "").rstrip("/")
        await message.answer(
            _welcome_pass_invite_body(trainer),
            parse_mode=ParseMode.HTML,
            reply_markup=_trainer_invite_welcome_markup(
                base,
                pass_trainer_id,
                city_id=city_id,
                service_id=book_url_pass,
            ),
        )
        return

    parsed = _parse_client_start(payload)
    if parsed:
        city_id, service_id, trainer_id = parsed
        async with async_session_factory() as db_session:
            await set_city(telegram_id, city_id, db_session)
            if service_id is not None:
                await set_service(telegram_id, service_id, db_session)
            else:
                # Deep link client_<city>_0_<trainer>: force explicit service choice in client flow.
                await clear_selected_service(telegram_id, db_session)
            await set_selected_trainer(telegram_id, trainer_id, db_session)
            trainer = await get_trainer(db_session, trainer_id)
            await record_profile_view_commit(
                db_session,
                trainer_id=int(trainer_id),
                source=DEMAND_SOURCE_CLIENT_APP,
            )
            service_label = None
            if service_id is not None:
                rsvc = await db_session.execute(
                    text(
                        "SELECT COALESCE(NULLIF(TRIM(name), ''), 'Услуга') FROM services WHERE id = :sid LIMIT 1"
                    ),
                    {"sid": service_id},
                )
                srow = rsvc.fetchone()
                service_label = ((srow[0] or "Услуга").strip() if srow else None) or "Услуга"
        trainer_name_html = html.escape(_trainer_name(trainer) if trainer else "Тренер")
        base = (Settings().webapp_base_url or "").rstrip("/")
        body = (
            msg.CLIENT_DEEP_LINK_BOOK_INVITE.format(
                trainer=trainer_name_html,
                service=html.escape(service_label or "Услуга"),
            )
            if service_id is not None
            else msg.CLIENT_DEEP_LINK_BOOK_INVITE_PICK_SERVICE.format(trainer=trainer_name_html)
        )
        await message.answer(
            body,
            parse_mode=ParseMode.HTML,
            reply_markup=_trainer_book_markup(
                base, trainer_id, include_catalog_alternative=False, service_id=service_id
            ),
        )
        return
    await message.answer(msg.CLIENT_START_WELCOME)


async def _send_client_home_webapp_offer(message: Message) -> None:
    """Открыть клиентский хаб в Mini App или сообщить, что нужен HTTPS (как /home)."""
    base, _ = mini_app_https_base(Settings())
    if not base or not base.lower().startswith("https://"):
        await message.answer(msg.CLIENT_HOME_HTTPS_REQUIRED)
        return
    url = f"{base.rstrip('/')}/webapp/client-home"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_HOME_WEBAPP, web_app=WebAppInfo(url=url))],
        ]
    )
    await message.answer(msg.CLIENT_HOME_OPEN_WEBAPP, parse_mode=ParseMode.HTML, reply_markup=kb)


@router.message(Command("home"))
async def cmd_home(message: Message) -> None:
    """Client hub Mini App: contextual hero + links to catalog, bookings, requests, passes."""
    await _send_client_home_webapp_offer(message)


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    """Menu 'Тренеры и запись': open catalog Mini App (HTTPS) or show settings screen."""
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.startswith("https://"):
        catalog_url = f"{base}/webapp/catalog"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Тренеры и запись", web_app=WebAppInfo(url=catalog_url))],
        ])
        await message.answer(
            msg.CLIENT_SETTINGS_CATALOG_INTRO,
            reply_markup=kb,
        )
        return
    telegram_id = message.from_user.id if message.from_user else 0
    text, keyboard = await _get_settings_content(telegram_id)
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("request"))
async def cmd_request(message: Message) -> None:
    """Legacy command: request is created from catalog context (list footer or trainer card)."""
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.startswith("https://"):
        catalog_url = f"{base}/webapp/catalog"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Тренеры и запись", web_app=WebAppInfo(url=catalog_url))],
        ])
        await message.answer(msg.CLIENT_MENU_REQUEST_MOVED, reply_markup=kb)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Тренеры и запись", callback_data=CATALOG_CALLBACK)],
    ])
    await message.answer(msg.CLIENT_MENU_REQUEST_MOVED, reply_markup=kb)


@router.message(Command("my_requests"))
async def cmd_my_requests(message: Message) -> None:
    """Open 'Мои заявки и отклики': Mini App (HTTPS) or inline list."""
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.startswith("https://"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_MY_REQUESTS, web_app=WebAppInfo(url=base + "/webapp/client-requests"))],
        ])
        await message.answer(
            msg.CLIENT_MY_REQUESTS_WEBAPP_INTRO,
            reply_markup=kb,
        )
        return
    telegram_id = message.from_user.id if message.from_user else 0
    text, keyboard = await _my_requests_content(telegram_id)
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


def _trainer_display_for_booking(b: dict, client_telegram_id: int, *, base: str = "") -> str:
    """HTML fragment: trainer name as trackable or tg:// link if telegram_id present and not self."""
    name = (b.get("trainer_name") or "Тренер").strip() or "Тренер"
    safe_name = html.escape(name)
    tid = b.get("trainer_telegram_id")
    if tid and int(tid) == int(client_telegram_id):
        # Same Telegram account as client — avoid tg:// deep link to self.
        return safe_name
    if tid:
        trainer_id = b.get("trainer_id")
        uname = (b.get("trainer_telegram_username") or "").strip().lstrip("@")
        mini = (base or "").rstrip("/")
        if (
            mini.startswith("https://")
            and trainer_id is not None
            and uname
            and _CLIENT_TG_USERNAME_RE.fullmatch(uname)
        ):
            href = f"{mini}/r/tg/{int(trainer_id)}?src={DEMAND_SOURCE_CLIENT_APP}"
            return f'<a href="{html.escape(href, quote=True)}">{safe_name}</a>'
        return f'<a href="tg://user?id={int(tid)}">{safe_name}</a>'
    # Trainer not linked to bot yet — show hint so user knows why there's no link
    return f"{safe_name} (написать в TG можно после подключения тренера к боту)"


async def _my_bookings_content(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Build client's bookings list text. No back button — user navigates via menu."""
    base = (Settings().webapp_base_url or "").rstrip("/")
    async with async_session_factory() as db_session:
        bookings = await list_bookings_for_client(db_session, telegram_id)
    back_kb = InlineKeyboardMarkup(inline_keyboard=[])
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
        raw_status = (b.get("status") or "").strip()
        if raw_status == "pending":
            status_label = msg.CLIENT_MY_BOOKINGS_STATUS_PENDING
        elif raw_status == "confirmed":
            status_label = msg.CLIENT_MY_BOOKINGS_STATUS_CONFIRMED
        else:
            status_label = raw_status or "—"
        lines.append(
            msg.CLIENT_MY_BOOKINGS_ROW.format(
                index=i,
                date=date_str,
                day=day_str,
                time=time_str,
                duration=duration,
                trainer_display=_trainer_display_for_booking(b, telegram_id, base=base),
                place=b.get("place_display") or "Уточните у тренера",
                status=status_label,
            )
        )
    return "\n".join(lines), back_kb


@router.message(Command("my_bookings"))
async def cmd_my_bookings(message: Message) -> None:
    """Open 'Мои записи': Mini App (HTTPS) or inline list."""
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.startswith("https://"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_MY_BOOKINGS, web_app=WebAppInfo(url=base + "/webapp/client-bookings"))],
        ])
        await message.answer(msg.CLIENT_MY_BOOKINGS_WEBAPP_INTRO, reply_markup=kb)
        return
    telegram_id = message.from_user.id if message.from_user else 0
    text, keyboard = await _my_bookings_content(telegram_id)
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@router.callback_query(lambda c: c.data == MY_BOOKINGS_CALLBACK)
async def show_my_bookings(callback: CallbackQuery) -> None:
    """List client's bookings: open Mini App or inline list."""
    await callback.answer()
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.startswith("https://"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_MY_BOOKINGS, web_app=WebAppInfo(url=base + "/webapp/client-bookings"))],
        ])
        await callback.message.answer(msg.CLIENT_MY_BOOKINGS_WEBAPP_INTRO, reply_markup=kb)
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    text, keyboard = await _my_bookings_content(telegram_id)
    await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@router.message(Command("my_passes"))
async def cmd_my_passes(message: Message) -> None:
    """Open combined Mini App (passes + certificates); default tab — абонементы."""
    await _send_passes_certificates_webapp(message, certificates_tab=False)


@router.message(Command("my_certificates"))
async def cmd_my_certificates(message: Message) -> None:
    """Legacy command: same Mini App, вкладка «Сертификаты»."""
    await _send_passes_certificates_webapp(message, certificates_tab=True)


async def _send_passes_certificates_webapp(message: Message, *, certificates_tab: bool) -> None:
    base = (Settings().webapp_base_url or "").rstrip("/")
    if not base or not base.startswith("https://"):
        await message.answer(
            msg.CLIENT_MY_PASSES_AND_CERTIFICATES_INTRO
            + "\n\n(Mini App временно недоступен — проверьте настройки.)"
        )
        return
    url = client_passes_certificates_webapp_url(base, certificates_tab=certificates_tab)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_MY_PASSES_AND_CERTIFICATES, web_app=WebAppInfo(url=url))],
        ]
    )
    await message.answer(msg.CLIENT_MY_PASSES_AND_CERTIFICATES_INTRO, reply_markup=kb)


def _guide_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать в поддержку", callback_data=CLIENT_SUPPORT_CALLBACK)],
    ])


@router.message(Command("guide"))
async def cmd_guide(message: Message) -> None:
    """Show help (Помощь) and support button."""
    await message.answer(msg.CLIENT_GUIDE, reply_markup=_guide_keyboard())


@router.callback_query(lambda c: c.data == GUIDE_CALLBACK)
async def on_guide_callback(callback: CallbackQuery) -> None:
    """Inline 'Помощь' button: show same as /guide with support button."""
    await callback.answer()
    await callback.message.answer(msg.CLIENT_GUIDE, reply_markup=_guide_keyboard())


@router.callback_query(lambda c: c.data == CLIENT_SUPPORT_CALLBACK)
async def on_client_support_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    tid = callback.from_user.id if callback.from_user else 0
    _client_support_awaiting.add(tid)
    await callback.message.answer(msg.CLIENT_SUPPORT_PROMPT)


@router.message(Command("book"))
async def cmd_book(message: Message) -> None:
    """Legacy command: booking is done from catalog Mini App (trainer card → slots)."""
    telegram_id = message.from_user.id if message.from_user else 0
    async with async_session_factory() as db_session:
        session_data = await get_session(telegram_id, db_session)
    trainer_id = (session_data or {}).get("selected_trainer_id") if session_data else None
    if not trainer_id:
        await message.answer(msg.CLIENT_BOOK_NO_TRAINER)
        return

    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.startswith("https://"):
        city_id = (session_data or {}).get("city_id") if session_data else None
        service_id = (session_data or {}).get("selected_service_id") if session_data else None
        arena_id = (session_data or {}).get("selected_arena_id") if session_data else None
        q = f"trainer_id={int(trainer_id)}"
        if city_id is not None:
            q += f"&city_id={int(city_id)}"
        if service_id is not None:
            q += f"&service_id={int(service_id)}"
        if arena_id is not None:
            q += f"&arena_id={int(arena_id)}"
        catalog_url = f"{base}/webapp/catalog?{q}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_BOOK, web_app=WebAppInfo(url=catalog_url))],
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_ANOTHER_TRAINER, web_app=WebAppInfo(url=f"{base}/webapp/catalog"))],
        ])
        await message.answer(msg.CLIENT_MENU_BOOKING_MOVED, reply_markup=kb)
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    text, keyboard = await _client_slots_content(trainer_id, client_telegram_id=telegram_id)
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
    trainer_id = safe_parse_id(callback.data[len(CATALOG_TRAINER_PREFIX):])
    if trainer_id is None:
        return
    async with async_session_factory() as db_session:
        await set_selected_trainer(telegram_id, trainer_id, db_session)
        trainer = await get_trainer(db_session, trainer_id)
        allows_online = await trainer_allows_online_booking(db_session, trainer_id)
        await record_profile_view_commit(
            db_session,
            trainer_id=trainer_id,
            source=DEMAND_SOURCE_CLIENT_APP,
        )
    name = html.escape(_trainer_name(trainer) if trainer else "Тренер")
    base = (Settings().webapp_base_url or "").rstrip("/")
    if not allows_online:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_LEAVE_REQUEST, callback_data=REQUEST_CALLBACK)],
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_ANOTHER_TRAINER, callback_data=CATALOG_CALLBACK)],
        ])
        await callback.message.answer(
            msg.CLIENT_TRAINER_SELECTED_NO_SELF_BOOK.format(name=name),
            reply_markup=keyboard,
        )
        return
    await callback.message.answer(
        msg.CLIENT_TRAINER_SELECTED.format(name=name),
        reply_markup=_trainer_book_markup(base, trainer_id, include_catalog_alternative=True),
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


async def _client_slots_content(
    trainer_id: int,
    *,
    client_telegram_id: int | None = None,
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Available slots for trainer (this + next week). Excludes slots within trainer's min working hours before booking."""
    this_m = this_week_monday()
    next_m = next_week_monday()
    to_date = next_m + timedelta(days=6)
    async with async_session_factory() as db_session:
        slots = await list_slots(db_session, trainer_id, this_m, to_date)
        trainer = await get_trainer(db_session, trainer_id)
        daypart: str | None = None
        if client_telegram_id:
            from src.application.client_booking_daypart_use_cases import (
                filter_raw_slots_by_daypart,
                get_client_booking_daypart,
            )

            cid = await get_client_id_by_telegram_id(db_session, client_telegram_id)
            if cid:
                daypart = await get_client_booking_daypart(db_session, trainer_id, int(cid))
    min_hours = 3
    if trainer and trainer.get("profile"):
        min_hours = trainer["profile"].get("min_hours_before_booking", 3) or 3
    available = [s for s in slots if (s.get("status") or "available") == "available"]
    now_minsk = datetime.now(ZoneInfo(NOTIFICATION_TZ))
    available = [
        s for s in available
        if working_hours_between(now_minsk, s["slot_date"], s["start_time"]) >= min_hours
    ]
    if daypart:
        available = filter_raw_slots_by_daypart(available, daypart)
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
    """Show available slots for selected trainer; or open Mini App to book (if HTTPS)."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    async with async_session_factory() as db_session:
        session_data = await get_session(telegram_id, db_session)
        client_id = await get_client_id_by_telegram_id(db_session, telegram_id)
    trainer_id = (session_data or {}).get("selected_trainer_id") if session_data else None
    if not trainer_id:
        await callback.message.answer(msg.CLIENT_BOOK_NO_TRAINER)
        return
    async with async_session_factory() as db_session:
        if not await trainer_allows_online_booking(db_session, trainer_id):
            await callback.message.answer(
                msg.CLIENT_BOOK_NO_ONLINE_TIER,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=msg.CLIENT_BUTTON_ANOTHER_TRAINER, callback_data=CATALOG_CALLBACK)],
                    ]
                ),
            )
            return
    # No client yet: offer link-by-phone (trainer may have added them by phone)
    if client_id is None:
        _link_phone_state[telegram_id] = {"step": "phone"}
        await callback.message.answer(msg.CLIENT_LINK_PHONE_PROMPT)
        return

    chat_id = callback.message.chat.id if callback.message.chat else 0
    await callback.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    text, keyboard = await _client_slots_content(trainer_id, client_telegram_id=telegram_id)
    base = (Settings().webapp_base_url or "").rstrip("/")
    if base.startswith("https://") and keyboard is not None:
        book_url = f"{base}/webapp/book?trainer_id={trainer_id}"
        sess_sid = (session_data or {}).get("selected_service_id")
        if sess_sid is not None:
            book_url += f"&service_id={int(sess_sid)}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BUTTON_BOOK, web_app=WebAppInfo(url=book_url))],
            [InlineKeyboardButton(text=msg.CLIENT_BOOK_BUTTON_BACK, callback_data=CATALOG_CALLBACK)],
        ])
        await callback.message.answer(
            msg.CLIENT_BOOK_CHOOSE_SLOT + msg.CLIENT_BOOK_WEBAPP_FOOTER,
            reply_markup=kb,
        )
        return

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
    """Start booking flow: ask name (first time), then phone / comment as needed."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    slot_id = int(callback.data[len(BOOK_SLOT_PREFIX):])
    async with async_session_factory() as db_session:
        session_data = await get_session(telegram_id, db_session)
        trainer_id = (session_data or {}).get("selected_trainer_id") if session_data else None
        profile = await get_client_profile_basic(db_session, telegram_id)
    if not trainer_id:
        await callback.message.answer(msg.CLIENT_BOOK_SESSION_EXPIRED)
        return
    state: dict = {"slot_id": slot_id, "trainer_id": trainer_id}
    first_name_existing = (profile.get("first_name") or "").strip() if profile else ""
    last_name_existing = (profile.get("last_name") or "").strip() if profile else ""
    phone_existing = (profile.get("phone") or "").strip() if profile else ""
    # Фамилия в профиле опциональна; для повторных записей достаточно сохранённого имени.
    need_name = not first_name_existing
    has_phone = bool(phone_existing)
    state["has_phone"] = has_phone
    if not need_name:
        # Чтобы при завершении записи не подставлялись имена из Telegram вместо сохранённых в БД.
        state["override_first_name"] = first_name_existing
        state["override_last_name"] = last_name_existing
    # 1) Нет имени — предложить из Telegram или ввести вручную
    if need_name:
        from_user = callback.from_user
        tg_first = (from_user.first_name or "").strip() if from_user else ""
        tg_last = (from_user.last_name or "").strip() if from_user else ""
        if tg_first:
            state["need_name"] = True
            _booking_state[telegram_id] = state
            name_display = f"{tg_first} {tg_last}".strip()
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=msg.CLIENT_BUTTON_USE_TG_NAME, callback_data=BOOKING_USE_TG_NAME)],
                [InlineKeyboardButton(text=msg.CLIENT_BUTTON_ENTER_MANUAL, callback_data=BOOKING_ENTER_MANUAL)],
            ])
            await callback.message.answer(
                msg.CLIENT_PROFILE_USE_TELEGRAM_NAME.format(name=name_display),
                reply_markup=ReplyKeyboardRemove(),
            )
            await callback.message.answer("Выберите:", reply_markup=kb)
            return
        state["need_name"] = True
        _booking_state[telegram_id] = state
        await callback.message.answer(msg.CLIENT_PROFILE_ENTER_NAME, reply_markup=ReplyKeyboardRemove())
        return
    # 2) Есть имя в профиле и уже сохранён телефон — сразу переходим к комментарию
    if has_phone:
        state["phone"] = phone_existing
        _booking_state[telegram_id] = state
        skip_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BOOK_SKIP_COMMENT, callback_data=BOOKING_SKIP_COMMENT)],
        ])
        await callback.message.answer(
            msg.CLIENT_BOOK_ENTER_COMMENT,
            reply_markup=ReplyKeyboardRemove(),
        )
        await callback.message.answer(msg.CLIENT_BOOK_COMMENT_OR_BUTTON, reply_markup=skip_kb)
        return
    # 3) Имя в профиле есть, телефона нет — просим телефон
    _booking_state[telegram_id] = state
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=msg.CLIENT_BOOK_BUTTON_SEND_CONTACT, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await callback.message.answer(msg.CLIENT_BOOK_ENTER_PHONE, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == BOOKING_USE_TG_NAME)
async def on_booking_use_tg_name(callback: CallbackQuery) -> None:
    """Apply Telegram name and continue to phone or comment step."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    state = _booking_state.get(telegram_id)
    if not state or not state.get("need_name"):
        await callback.message.answer(msg.CLIENT_BOOK_SESSION_EXPIRED)
        return
    from_user = callback.from_user
    state["override_first_name"] = (from_user.first_name or "").strip() if from_user else ""
    state["override_last_name"] = (from_user.last_name or "").strip() if from_user else ""
    state.pop("need_name", None)
    _booking_state[telegram_id] = state
    if state.get("has_phone"):
        state["phone"] = (await _get_phone_from_profile(telegram_id)) or ""
        skip_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_BOOK_SKIP_COMMENT, callback_data=BOOKING_SKIP_COMMENT)],
        ])
        await callback.message.answer(msg.CLIENT_BOOK_ENTER_COMMENT, reply_markup=ReplyKeyboardRemove())
        await callback.message.answer(msg.CLIENT_BOOK_COMMENT_OR_BUTTON, reply_markup=skip_kb)
        return
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=msg.CLIENT_BOOK_BUTTON_SEND_CONTACT, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await callback.message.answer(msg.CLIENT_BOOK_ENTER_PHONE, reply_markup=keyboard)


async def _get_phone_from_profile(telegram_id: int) -> str | None:
    """Return saved phone for client; used when continuing booking flow from callback (no session)."""
    async with async_session_factory() as db_session:
        profile = await get_client_profile_basic(db_session, telegram_id)
    return (profile.get("phone") or "").strip() or None


@router.callback_query(lambda c: c.data == BOOKING_ENTER_MANUAL)
async def on_booking_enter_manual(callback: CallbackQuery) -> None:
    """User chose to enter name manually — show text prompt."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    if telegram_id not in _booking_state:
        await callback.message.answer(msg.CLIENT_BOOK_SESSION_EXPIRED)
        return
    await callback.message.answer(msg.CLIENT_PROFILE_ENTER_NAME, reply_markup=ReplyKeyboardRemove())


@router.callback_query(lambda c: c.data == BOOKING_SKIP_COMMENT)
async def on_booking_skip_comment(callback: CallbackQuery) -> None:
    """Finish booking without comment."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    state = _booking_state.pop(telegram_id, None)
    if not state or "phone" not in state:
        await callback.message.answer(msg.CLIENT_BOOK_SESSION_EXPIRED)
        return
    await _finish_booking(
        callback.message,
        telegram_id,
        state["slot_id"],
        state["trainer_id"],
        state["phone"],
        None,
        override_first_name=state.get("override_first_name"),
        override_last_name=state.get("override_last_name"),
    )


async def _finish_booking(
    message: Message,
    telegram_id: int,
    slot_id: int,
    trainer_id: int,
    phone: str,
    comment: str | None,
    *,
    override_first_name: str | None = None,
    override_last_name: str | None = None,
) -> None:
    """Create booking, show success, remove keyboard. If session has pending_request_id, link and archive that request."""
    client_request_id: int | None = None
    from_user = message.from_user
    first_name = override_first_name if override_first_name is not None else (from_user.first_name if from_user else None)
    last_name = override_last_name if override_last_name is not None else (from_user.last_name if from_user else None)
    async with async_session_factory() as db_session:
        session = await get_session(telegram_id, db_session)
        if session and isinstance(session.get("payload"), dict):
            client_request_id = session["payload"].get("pending_request_id")
        service_id: int | None = None
        if client_request_id:
            req = await get_client_request_for_booking(db_session, client_request_id, telegram_id)
            if req:
                service_id = req.get("service_id")
        if service_id is None and session:
            service_id = session.get("selected_service_id")
        if service_id is None:
            service_id = await get_first_service_id_for_trainer(db_session, trainer_id)
        if service_id is None:
            await message.answer(msg.CLIENT_ERROR_SERVICE_UNKNOWN_FOR_BOOKING, reply_markup=ReplyKeyboardRemove())
            return
        username = from_user.username if from_user else None
        client_id = await get_or_create_client(
            db_session,
            telegram_id,
            phone=phone,
            first_name=first_name,
            last_name=last_name,
            telegram_username=username,
        )
        booking_id, _ = await create_booking(
            db_session, slot_id, trainer_id, client_id, service_id=service_id, client_comment=comment,
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
    await message.answer(msg.CLIENT_BOOK_WHAT_NEXT)
    await message.answer(msg.CLIENT_BOOK_SUCCESS_HINT)


@router.message(lambda m: m.from_user and m.from_user.id in _booking_state)
async def on_booking_message(message: Message) -> None:
    """Handle name (first time), then phone or comment in booking flow."""
    telegram_id = message.from_user.id if message.from_user else 0
    state = _booking_state.get(telegram_id)
    if not state:
        return
    # Name step for new clients
    if state.get("need_name"):
        full = (message.text or "").strip()
        parts = full.split()
        if not parts or not parts[0].strip():
            await message.answer(msg.CLIENT_PROFILE_NAME_INVALID)
            return
        first_name = parts[0]
        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
        state.pop("need_name", None)
        state["override_first_name"] = first_name
        state["override_last_name"] = last_name
        _booking_state[telegram_id] = state
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=msg.CLIENT_BOOK_BUTTON_SEND_CONTACT, request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await message.answer(msg.CLIENT_BOOK_ENTER_PHONE, reply_markup=keyboard)
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
    override_first_name = state.get("override_first_name")
    override_last_name = state.get("override_last_name")
    _booking_state.pop(telegram_id, None)
    await _finish_booking(
        message,
        telegram_id,
        slot_id,
        trainer_id,
        phone,
        comment,
        override_first_name=override_first_name,
        override_last_name=override_last_name,
    )


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
    """Client chose rating: persist immediately, then optional review (skip or message)."""
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
    async with async_session_factory() as db_session:
        ok = await add_trainer_rating(
            db_session,
            state["trainer_id"],
            telegram_id,
            rating,
            review_text=None,
        )
    if not ok:
        await callback.message.answer(msg.CLIENT_ERROR_TRY_AGAIN)
        return
    audit_log(
        "trainer.rated",
        ACTOR_CLIENT_BOT,
        telegram_id,
        {"trainer_id": state["trainer_id"], "booking_id": state.get("booking_id"), "rating": rating},
    )
    skip_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=msg.CLIENT_FEEDBACK_SKIP, callback_data=f"{FEEDBACK_SKIP_PREFIX}{booking_id}")],
    ])
    await callback.message.answer(msg.CLIENT_FEEDBACK_REVIEW_PROMPT, reply_markup=skip_kb)


@router.callback_query(lambda c: c.data and c.data.startswith(FEEDBACK_SKIP_PREFIX))
async def on_feedback_skip(callback: CallbackQuery) -> None:
    """Client skipped review text; rating already saved on star tap."""
    await callback.answer()
    raw = (callback.data or "").replace(FEEDBACK_SKIP_PREFIX, "").strip()
    booking_id = safe_parse_id(raw)
    if booking_id is None:
        return
    telegram_id = callback.from_user.id if callback.from_user else 0
    state = _feedback_state.pop(telegram_id, None)
    if not state or state.get("booking_id") != booking_id or "rating" not in state:
        return
    await callback.message.answer(msg.CLIENT_FEEDBACK_THANKS)


@router.message(lambda m: m.from_user and m.from_user.id in _feedback_state)
async def on_feedback_review_message(message: Message) -> None:
    """Client sent review text after rating (rating already persisted on star tap)."""
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


# --- Repeat / Become regular: scenarios ---
# Repeat (Повторить): target = slot_date + 7; exact slot available → book. booked → honest message (+ recurring hint).
#   No exact slot but calendar interval clear → idempotent trainer ping + client «ждите». Else → wait_request.


def _repeat_interval_duration_minutes(start_time: object, end_time: object) -> int:
    """Wall-clock length of [start, end) on one day for repeat / trainer gap notices."""
    try:
        if start_time and end_time and hasattr(start_time, "hour") and hasattr(end_time, "hour"):
            delta = datetime.combine(date.today(), end_time) - datetime.combine(date.today(), start_time)
            return max(1, int(delta.total_seconds() // 60))
    except (TypeError, ValueError):
        pass
    return 45


@router.callback_query(lambda c: c.data and c.data.startswith(REPEAT_BOOKING_PREFIX))
async def on_repeat_booking(callback: CallbackQuery) -> None:
    """Repeat same clock interval on slot_date + 7: book exact slot, ping trainer if calendar gap, or waitlist."""
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
    slot_date_val = booking["slot_date"]
    slot_d = slot_date_val.date() if hasattr(slot_date_val, "date") else slot_date_val
    target_date = slot_d + timedelta(days=7)
    start_time = booking["start_time"]
    end_time = booking["end_time"]
    st = start_time.replace(second=0, microsecond=0) if hasattr(start_time, "replace") else start_time
    et = end_time.replace(second=0, microsecond=0) if hasattr(end_time, "replace") else end_time
    day_of_week = slot_d.weekday()
    async with async_session_factory() as db_session:
        status, slot_info = await get_slot_status_on_date(db_session, trainer_id, target_date, st)
    if status == "available" and slot_info:
        service_id = booking.get("service_id")
        if not service_id:
            async with async_session_factory() as db_session:
                service_id = await get_first_service_id_for_trainer(db_session, trainer_id)
        if service_id:
            async with async_session_factory() as db_session:
                new_booking_id, _ = await create_booking(
                    db_session,
                    slot_info["slot_id"],
                    trainer_id,
                    client_id,
                    service_id=service_id,
                    client_comment=None,
                    service_price_variant_id=booking.get("service_price_variant_id"),
                )
            if new_booking_id:
                async with async_session_factory() as db_session:
                    await generate_reminders_for_booking(db_session, new_booking_id)
                date_str = slot_info["slot_date"].strftime("%d.%m") if hasattr(slot_info["slot_date"], "strftime") else str(slot_info["slot_date"])
                day_str = msg.TRAINER_DAYS[slot_info["slot_date"].weekday()] if hasattr(slot_info["slot_date"], "weekday") else ""
                time_str = st.strftime("%H:%M") if hasattr(st, "strftime") else ""
                await callback.message.answer(
                    msg.CLIENT_REPEAT_BOOKED.format(date=date_str, day=day_str, time=time_str)
                )
                return
    if status == "booked":
        async with async_session_factory() as db_session:
            taken_by_regular = await has_other_active_recurring(
                db_session, trainer_id, day_of_week, st, exclude_client_id=client_id
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
        interval_clear = await trainer_calendar_interval_clear(db_session, trainer_id, target_date, st, et)
    if not interval_clear:
        async with async_session_factory() as db_session:
            await add_slot_wait_request(db_session, trainer_id, client_id, day_of_week, st)
        await callback.message.answer(msg.CLIENT_REPEAT_NO_SLOT_YET)
        return

    async with async_session_factory() as db_session:
        inserted = await try_insert_client_repeat_gap_notification(db_session, booking_id, target_date)

    if inserted:
        trainer_tid: int | None = None
        client_display = "Клиент"
        trainer_notify_ok = False
        async with async_session_factory() as db_session:
            trainer_tid = await get_trainer_telegram_id(db_session, trainer_id)
            rnm = await db_session.execute(
                text("SELECT first_name, last_name FROM clients WHERE id = :cid"),
                {"cid": client_id},
            )
            nrow = rnm.fetchone()
        if nrow:
            fn, ln = (nrow[0] or ""), (nrow[1] or "")
            client_display = (str(fn) + " " + str(ln)).strip() or "Клиент"

        if trainer_tid:
            settings = Settings()
            trainer_bot = Bot(
                token=settings.telegram_bot_token_trainer,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            date_str = target_date.strftime("%d.%m")
            day_str = msg.TRAINER_DAYS[target_date.weekday()]
            time_str = st.strftime("%H:%M") if hasattr(st, "strftime") else str(st)
            trainer_text = msg.format_trainer_client_repeat_gap_request_html(
                client_name=client_display,
                service_name=booking.get("service_name"),
                arena_name=booking.get("arena_name"),
                date_str=date_str,
                day_str=day_str,
                time_str=time_str,
                duration_minutes=_repeat_interval_duration_minutes(st, et),
            )
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.TRAINER_BUTTON_BOOK_SAME_TIME_NEXT_WEEK,
                            callback_data=f"{TRAINER_REPEAT_WEEK_CALLBACK_PREFIX}{booking_id}",
                        ),
                    ],
                ],
            )
            try:
                await trainer_bot.send_message(
                    chat_id=int(trainer_tid),
                    text=trainer_text,
                    reply_markup=kb,
                )
                trainer_notify_ok = True
            except Exception as e:
                logging.warning(
                    "repeat_gap trainer notify failed booking_id=%s trainer_id=%s: %s",
                    booking_id,
                    trainer_id,
                    e,
                )
            finally:
                await trainer_bot.session.close()
        else:
            logging.warning(
                "repeat_gap: no trainer telegram_id trainer_id=%s booking_id=%s",
                trainer_id,
                booking_id,
            )

        await callback.message.answer(
            msg.CLIENT_REPEAT_GAP_TRAINER_NOTIFIED
            if trainer_notify_ok
            else msg.CLIENT_REPEAT_GAP_TRAINER_OFFLINE
        )
        return

    await callback.message.answer(msg.CLIENT_REPEAT_GAP_ALREADY_NOTIFIED)


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
    service_id = booking.get("service_id")
    if not service_id:
        async with async_session_factory() as db_session:
            service_id = await get_first_service_id_for_trainer(db_session, trainer_id)
    async with async_session_factory() as db_session:
        slot_info = await find_available_slot_next_week(db_session, trainer_id, day_of_week, start_time)
    if slot_info and service_id:
        async with async_session_factory() as db_session:
            new_booking_id, _ = await create_booking(
                db_session,
                slot_info["slot_id"],
                trainer_id,
                client_id,
                service_id=service_id,
                client_comment=None,
                service_price_variant_id=booking.get("service_price_variant_id"),
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
        username = callback.from_user.username if callback.from_user else None
        client_id = await get_or_create_client(db_session, telegram_id, telegram_username=username)
        slot = await get_slot(db_session, slot_id)
        if not slot or slot.get("status") != "available":
            await callback.message.answer(msg.CLIENT_ERROR_BOOKING_UNAVAILABLE)
            return
        trainer_id = slot["trainer_id"]
        service_id = await get_first_service_id_for_trainer(db_session, trainer_id)
        if not service_id:
            await callback.message.answer(msg.CLIENT_ERROR_BOOKING_UNAVAILABLE)
            return
        new_booking_id, _ = await create_booking(
            db_session, slot_id, trainer_id, client_id, service_id=service_id, client_comment=None
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
        username = callback.from_user.username if callback.from_user else None
        client_id = await get_or_create_client(
            db_session,
            telegram_id,
            first_name=first_name,
            last_name=last_name,
            telegram_username=username,
        )
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
        username = message.from_user.username if message.from_user else None
        client_id = await get_or_create_client(
            db_session,
            telegram_id,
            first_name=first_name,
            last_name=last_name,
            telegram_username=username,
        )
        request_id = await create_client_request(
            db_session, client_id,
            state["city_id"], state["service_id"],
            comment=comment,
        )
    audit_log("client_request.created", ACTOR_CLIENT_BOT, telegram_id, {"request_id": request_id, "city_id": state["city_id"], "service_id": state["service_id"]})
    await message.answer(msg.CLIENT_REQUEST_SUCCESS)


@router.callback_query(lambda c: c.data == MY_REQUESTS_CALLBACK)
async def show_my_requests(callback: CallbackQuery) -> None:
    """List = one button per request (full list, capped by Telegram)."""
    await callback.answer()
    telegram_id = callback.from_user.id if callback.from_user else 0
    text, keyboard = await _my_requests_content(telegram_id)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


def _format_request_responses_keyboard(req: dict) -> InlineKeyboardMarkup:
    """Build keyboard: each responder → Profile; then Edit/Delete; then Back."""
    rows = []
    for r in (req.get("responses") or []):
        name = r.get("name") or "Тренер"
        rows.append([InlineKeyboardButton(
            text=f"{msg.CLIENT_BUTTON_RESPONDER_PROFILE}: {name}",
            callback_data=f"{RESPONDER_PROFILE_PREFIX}{req['id']}:{r['trainer_id']}",
        )])
    if client_request_comment_editable(req.get("comment")):
        rows.append([InlineKeyboardButton(
            text=msg.CLIENT_REQUEST_EDIT_DELETE_BUTTON,
            callback_data=f"{REQUEST_EDIT_PREFIX}{req['id']}",
        )])
    else:
        rows.append([InlineKeyboardButton(
            text=msg.CLIENT_REQUEST_DELETE_BUTTON,
            callback_data=f"{REQUEST_DELETE_PREFIX}{req['id']}",
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
    comment = client_visible_request_comment(req.get("comment")) or ""
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
    if not client_request_comment_editable(req.get("comment")):
        await callback.message.answer(msg.CLIENT_REQUEST_EDIT_NOT_ALLOWED)
        return
    _request_edit_state[telegram_id] = request_id
    city = (req.get("city_name") or "").strip() or "—"
    service = (req.get("service_name") or "").strip() or "—"
    comment = client_visible_request_comment(req.get("comment")) or ""
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
    comment = client_visible_request_comment(req.get("comment")) or ""
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
    await callback.message.edit_text(
        msg.CLIENT_REQUEST_DELETED + "\n\n" + text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


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
    async with async_session_factory() as db_session:
        await record_profile_view_commit(
            db_session,
            trainer_id=trainer_id,
            source=DEMAND_SOURCE_CLIENT_APP,
        )
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
    buttons = []
    base = (Settings().webapp_base_url or "").rstrip("/")
    write_url = _client_trainer_write_url(base=base, trainer=trainer)
    if write_url:
        buttons.append([InlineKeyboardButton(
            text=msg.CLIENT_BUTTON_RESPONDER_WRITE,
            url=write_url,
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
        await record_profile_view_commit(
            db_session,
            trainer_id=trainer_id,
            source=DEMAND_SOURCE_CLIENT_APP,
        )
    text, keyboard = await _client_slots_content(trainer_id, client_telegram_id=telegram_id)
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
        await record_profile_view_commit(
            db_session,
            trainer_id=trainer_id,
            source=DEMAND_SOURCE_CLIENT_APP,
        )
    text, keyboard = await _client_slots_content(trainer_id, client_telegram_id=telegram_id)
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


@router.callback_query(lambda c: c.data == CLIENT_HOME_WEBAPP_CALLBACK)
async def on_client_home_webapp_callback(callback: CallbackQuery) -> None:
    """Fallback когда в разметке invite/bind не смогли встроить Web App URL (нет HTTPS base)."""
    await callback.answer()
    if callback.message:
        await _send_client_home_webapp_offer(callback.message)


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


@router.message(lambda m: getattr(m, "web_app_data", None) is not None)
async def on_catalog_web_app_data(message: Message) -> None:
    """Mini App closed with sendData: trainer_selected -> confirmation; leave_request -> start request flow."""
    import json
    try:
        payload = json.loads(message.web_app_data.data)
    except (TypeError, ValueError):
        await message.answer(msg.CLIENT_ERROR_TRY_AGAIN)
        return

    action = payload.get("action")

    if action == "submit_request":
        # Mini App sent full form: city, service, optional comment, optional trainer_id (personalized)
        try:
            telegram_id = message.from_user.id if message.from_user else 0
            city_id = payload.get("city_id")
            service_id = payload.get("service_id")
            if not city_id or not service_id:
                await message.answer(msg.CLIENT_REQUEST_NEED_CITY_SERVICE)
                return
            city_id = int(city_id)
            service_id = int(service_id)
            trainer_id = payload.get("trainer_id")
            trainer_id = int(trainer_id) if trainer_id is not None else None
            raw_comment = payload.get("comment")
            comment = truncate_text(str(raw_comment) if raw_comment is not None else None, MAX_COMMENT_LEN)
        except (TypeError, ValueError):
            await message.answer(msg.CLIENT_ERROR_TRY_AGAIN)
            return
        except Exception as e:
            logging.exception("submit_request web_app_data: %s", e)
            await message.answer(msg.CLIENT_ERROR_TRY_AGAIN)
            return
        from_user = message.from_user
        first_name = from_user.first_name if from_user else None
        last_name = from_user.last_name if from_user else None
        async with async_session_factory() as db_session:
            username = message.from_user.username if message.from_user else None
            client_id = await get_or_create_client(
                db_session,
                telegram_id,
                first_name=first_name,
                last_name=last_name,
                telegram_username=username,
            )
            request_id = await create_client_request(
                db_session, client_id, city_id, service_id, comment=comment, trainer_id=trainer_id
            )
        audit_log("client_request.created", ACTOR_CLIENT_BOT, telegram_id, {"request_id": request_id, "city_id": city_id, "service_id": service_id, "trainer_id": trainer_id})
        await message.answer(msg.CLIENT_REQUEST_SUCCESS)
        return

    if action == "leave_request":
        try:
            telegram_id = message.from_user.id if message.from_user else 0
            city_id = payload.get("city_id")
            service_id = payload.get("service_id")
            if not city_id or not service_id:
                async with async_session_factory() as db_session:
                    session = await get_or_create_session(telegram_id, db_session)
                city_id = city_id or session.get("city_id")
                service_id = service_id or session.get("selected_service_id")
            if not city_id or not service_id:
                await message.answer(msg.CLIENT_REQUEST_NEED_CITY_SERVICE)
                return
            city_id = int(city_id)
            service_id = int(service_id)
        except (TypeError, ValueError):
            await message.answer(msg.CLIENT_ERROR_TRY_AGAIN)
            return
        except Exception as e:
            logging.exception("leave_request web_app_data: %s", e)
            await message.answer(msg.CLIENT_ERROR_TRY_AGAIN)
            return
        _request_state[telegram_id] = {"city_id": city_id, "service_id": service_id}
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=msg.CLIENT_REQUEST_SKIP, callback_data="request_skip")],
            [InlineKeyboardButton(text=msg.CLIENT_REQUEST_BACK, callback_data="request_back")],
        ])
        await message.answer(msg.CLIENT_REQUEST_PROMPT_COMMENT, reply_markup=keyboard)
        return

    if action != "trainer_selected":
        return
    trainer_id = payload.get("trainer_id")
    if not trainer_id:
        return
    async with async_session_factory() as db_session:
        trainer = await get_trainer(db_session, int(trainer_id))
        await record_profile_view_commit(
            db_session,
            trainer_id=int(trainer_id),
            source=DEMAND_SOURCE_CLIENT_APP,
        )
    name = html.escape(_trainer_name(trainer) if trainer else "Тренер")
    base = (Settings().webapp_base_url or "").rstrip("/")
    await message.answer(
        msg.CLIENT_TRAINER_SELECTED.format(name=name),
        reply_markup=_trainer_book_markup(base, int(trainer_id), include_catalog_alternative=True),
    )


def _has_link_phone_state(message: Message) -> bool:
    tid = message.from_user.id if message.from_user else 0
    return tid in _link_phone_state


@router.message(F.text, _has_link_phone_state)
async def on_link_phone_message(message: Message) -> None:
    """Handle phone or verification code when user is in link-by-phone flow."""
    telegram_id = message.from_user.id if message.from_user else 0
    state = _link_phone_state.get(telegram_id)
    if not state:
        return
    text = (message.text or "").strip()
    if not text:
        return

    if state.get("step") == "phone":
        async with async_session_factory() as db_session:
            client = await get_client_by_phone(db_session, text)
        if not client:
            await message.answer(msg.CLIENT_LINK_PHONE_NOT_FOUND)
            return
        if client.get("telegram_id") is not None:
            await message.answer(msg.CLIENT_LINK_PHONE_ALREADY_LINKED)
            return
        code = "".join(random.choices(string.digits, k=4))
        _link_phone_state[telegram_id] = {"step": "code", "client_id": client["id"], "code": code}
        # TODO: send real SMS; for now code in bot message. Never log the code unless DEBUG (secrets in logs policy).
        if Settings().debug:
            logger.info(
                "Phone verification code for client_id=%s (debug only): %s",
                client["id"],
                code,
            )
        else:
            logger.info("Phone verification code issued for client_id=%s", client["id"])
        dev_hint = msg.CLIENT_LINK_CODE_DEV.format(code=code)
        await message.answer(msg.CLIENT_LINK_CODE_SENT + dev_hint, parse_mode=ParseMode.HTML)
        return

    if state.get("step") == "code":
        if text != state.get("code"):
            await message.answer(msg.CLIENT_LINK_CODE_WRONG)
            return
        client_id = state.get("client_id")
        if not client_id:
            _link_phone_state.pop(telegram_id, None)
            await message.answer(msg.CLIENT_ERROR_TRY_AGAIN)
            return
        un_link = None
        if message.from_user and (message.from_user.username or "").strip():
            un_link = (message.from_user.username or "").strip()[:64]
        async with async_session_factory() as db_session:
            ok = await attach_telegram_id_to_client(
                db_session, client_id, telegram_id, telegram_username=un_link
            )
            await sync_client_telegram_username_from_client_bot(db_session, telegram_id)
            await db_session.commit()
        _link_phone_state.pop(telegram_id, None)
        if not ok:
            await message.answer(msg.CLIENT_ERROR_TRY_AGAIN)
            return
        await message.answer(msg.CLIENT_LINK_SUCCESS)
        return


@router.callback_query(lambda c: c.data and (c.data.startswith("RSY:") or c.data.startswith("RSN:")))
async def on_group_rsvp_callback(callback: CallbackQuery) -> None:
    """Cohort attendance: confirm or decline from inline keyboard."""
    raw = callback.data or ""
    parts = raw.split(":", 2)
    if len(parts) != 3:
        await callback.answer()
        return
    pref, pid_s, sig = parts
    try:
        prompt_id = int(pid_s)
    except ValueError:
        await callback.answer()
        return
    action = "y" if pref == "RSY" else "n"
    secret = rsvp_hmac_secret(Settings().telegram_bot_token_client)
    if not attendance_rsvp_verify(prompt_id, action, sig, secret):
        await callback.answer("Кнопка устарела или недействительна.", show_alert=True)
        return
    await callback.answer()
    _ok, message_text = await respond_attendance_rsvp(
        prompt_id=prompt_id,
        telegram_user_id=callback.from_user.id,
        accept=(action == "y"),
    )
    if callback.message:
        try:
            await callback.message.edit_text(message_text)
        except Exception:
            await callback.message.answer(message_text)


@router.callback_query(F.data.startswith("rly_ck:"))
async def client_relay_reply_callback(callback: CallbackQuery) -> None:
    await on_client_bot_relay_reply_callback(callback)


@router.callback_query(F.data.startswith("rly_xc:"))
async def client_relay_close_callback(callback: CallbackQuery) -> None:
    """Client ends bot-mediated chat with trainer."""
    await on_client_bot_relay_close_callback(callback)


@router.message()
async def fallback(message: Message) -> None:
    """Any other message: handle support state or direct to main menu."""
    telegram_id = message.from_user.id if message.from_user else 0
    if message.text and getattr(message.chat, "type", None) == ChatType.PRIVATE:
        if await maybe_route_client_relay_text_reply(message):
            return
    if telegram_id in _client_support_awaiting:
        _client_support_awaiting.discard(telegram_id)
        text = (message.text or "").strip()[: 4000]
        if not text:
            await message.answer(msg.CLIENT_SUPPORT_PROMPT)
            return
        async with async_session_factory() as session:
            await create_support_message(
                session,
                telegram_id,
                SUPPORT_FROM_CLIENT,
                text,
                admin_notify_source_tag="клиентский бот",
            )
        await message.answer(msg.CLIENT_SUPPORT_SENT)
        return
    await message.answer(msg.CLIENT_FALLBACK)
