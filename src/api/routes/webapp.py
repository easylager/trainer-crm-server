"""
Web App API: trainer schedule (Mini App) and client booking (Mini App). Auth via validated initData.
"""
import asyncio
import html
import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Literal

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from src.api.deps import get_session
from src.application.booking_use_cases import (
    active_booking_summaries_by_slot_for_trainer_range,
    cancel_booking,
    cancel_booking_by_client,
    confirm_booking,
    count_trainer_client_sessions,
    count_trainer_client_upcoming,
    create_booking,
    decline_booking,
    generate_reminders_for_booking,
    get_booking_no_pass_notify_payload,
    get_trainer_default_city_and_service,
    mark_booking_completed_by_trainer,
    get_booking_with_slot,
    get_trainer_client_next_booking,
    list_bookings_for_client,
    list_bookings_for_trainer,
    list_trainer_clients,
    list_trainer_client_history,
)
from src.application.client_use_cases import (
    get_client_id_by_telegram_id,
    get_client_profile_basic,
    get_client_telegram_id,
    get_or_create_client,
    get_or_create_client_by_phone,
)
from src.application.client_request_use_cases import (
    add_trainer_pending_request_booking,
    clear_trainer_pending_request_booking,
    create_client_request,
    create_request_decline,
    create_request_response,
    delete_client_request,
    get_client_request_for_booking,
    get_request_client_for_trainer_booking,
    list_my_requests_with_responses,
    list_requests_for_trainer,
    replace_client_request_with_new,
)
from src.application.client_session_use_cases import (
    get_or_create_session as get_client_session,
    set_arena,
    set_city,
    set_selected_trainer,
    set_service,
)
from src.application.catalog_use_cases import list_arenas, list_cities, list_services
from src.application.recurring_use_cases import (
    cancel_recurring_client_slot,
    create_recurring_client_slot,
    get_active_recurring_for_booking,
)
from src.application.trainer_link import get_trainer_id_by_telegram_id, get_trainer_id_linked_any_status
from src.application.welcome_link_use_cases import (
    WELCOME_TOKEN_TYPE_CERT,
    WELCOME_TOKEN_TYPE_GENERIC,
    WELCOME_TOKEN_TYPE_PASS,
    create_welcome_link_token,
)
from src.application.stats_use_cases import get_platform_stats, get_trainer_stats_dashboard
from src.application.support_use_cases import (
    create_support_message,
    list_support_messages,
    reply_support_message,
)
from src.application.pass_product_use_cases import (
    create_pass_product,
    delete_pass_product,
    issue_pass_to_client,
    list_client_pass_instances,
    list_pass_instances_for_trainer_client,
    list_pass_products,
    update_pass_product,
)
from src.application.certificate_use_cases import (
    AMOUNT_CENTS_UNSET,
    create_certificate_product,
    delete_certificate_product,
    get_certificate_file_key,
    get_idempotency_response,
    insert_certificate_email_outbox,
    issue_certificate,
    list_certificate_instances_for_trainer_client,
    list_certificate_products,
    list_client_certificate_instances,
    list_trainer_certificate_instances,
    redeem_certificate,
    activate_certificate_by_code,
    set_idempotency_response,
    update_certificate_email_sent_at,
    update_certificate_product,
)
from src.application.subscription_use_cases import (
    confirm_subscription_invoice_after_payment,
    create_subscription_invoice,
    get_paid_plan_id,
    get_pending_subscription_invoice,
    list_paid_subscription_plans,
)
from src.application.subscription_tier_use_cases import (
    get_effective_subscription_tier,
    get_subscription_tier_catalog,
    get_trainer_subscription_status,
    list_subscription_tier_pricing_for_admin,
    set_subscription_after_mock_payment,
    tier_satisfies,
    trainer_allows_online_booking,
    trainer_has_crm_access,
    update_subscription_tier_pricing,
)
from src.infrastructure.db.models import SUBSCRIPTION_TIER_ANALYTICS, SUBSCRIPTION_TIERS
from src.billing.payment_gateway import create_checkout
from src.application.trainer_schedule_use_cases import (
    delete_slot as schedule_delete_slot,
    get_slot,
    list_slots,
    list_templates,
    replace_slots_for_day,
    replace_templates_for_day,
    replace_week_with_template,
)
from src.application.recurring_use_cases import apply_recurring_bookings_for_week
from src.application.client_notes_use_cases import (
    get_trainer_client_note,
    upsert_trainer_client_note,
)
from src.bot.schedule_notifications import run_after_schedule_changed
from src.application.trainer_use_cases import (
    get_trainer,
    get_trainer_moderation_readiness,
    try_submit_trainer_for_moderation_review,
)
from src.bot import messages as msg
from src.shared.ttl_cache import get_slots_cached, set_slots_cached
from src.shared.config import Settings
from src.shared.notification_hours import NOTIFICATION_TZ, working_hours_between
from src.shared.telegram_webapp import InitDataAuthError, require_telegram_user_id

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

router = APIRouter(prefix="/api/webapp", tags=["webapp"])


def _get_telegram_id_from_init_data(init_data: str, *, bot_token: str) -> int:
    try:
        return require_telegram_user_id(init_data, bot_token)
    except InitDataAuthError:
        raise HTTPException(status_code=401, detail="Invalid or expired init data") from None


def _trainer_telegram_id(init_data: str) -> int:
    return _get_telegram_id_from_init_data(init_data, bot_token=Settings().telegram_bot_token_trainer)


def _client_telegram_id(init_data: str) -> int:
    return _get_telegram_id_from_init_data(init_data, bot_token=Settings().telegram_bot_token_client)


def _admin_telegram_id(init_data: str) -> int:
    """Validate init_data with admin bot token; require telegram_id in admin_telegram_ids."""
    token = Settings().telegram_bot_token_admin
    if not token:
        raise HTTPException(status_code=503, detail="Admin Web App not configured")
    tid = _get_telegram_id_from_init_data(init_data, bot_token=token)
    admin_ids = Settings().admin_telegram_ids or []
    if tid not in admin_ids:
        raise HTTPException(status_code=403, detail="Not an admin")
    return tid


@router.get("/schedule")
async def get_schedule(
    from_date: date | None = Query(None, description="YYYY-MM-DD"),
    to_date: date | None = Query(None, description="YYYY-MM-DD"),
    init_data: str | None = Query(None, description="Telegram Web App initData (if header stripped by proxy)"),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """
    Return trainer's slots for date range. Requires Telegram Web App initData
    in header X-Telegram-Init-Data or in query param init_data (proxy-safe).
    """
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data (header or init_data query)")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")

    today = date.today()
    if from_date is None:
        # Monday of current week
        from_date = today - timedelta(days=today.weekday())
    if to_date is None:
        to_date = from_date + timedelta(days=7 * 4 - 1)  # 4 weeks

    slots = await list_slots(session, trainer_id, from_date, to_date)
    summaries = await active_booking_summaries_by_slot_for_trainer_range(
        session, trainer_id, from_date, to_date
    )
    out_slots: list[dict[str, Any]] = []
    for s in slots:
        st = s.get("status") or "available"
        row: dict[str, Any] = {
            "id": s["id"],
            "slot_date": s["slot_date"].isoformat() if hasattr(s["slot_date"], "isoformat") else str(s["slot_date"]),
            "start_time": s["start_time"].strftime("%H:%M") if hasattr(s["start_time"], "strftime") else str(s["start_time"])[:5],
            "end_time": s["end_time"].strftime("%H:%M") if hasattr(s["end_time"], "strftime") else str(s["end_time"])[:5],
            "status": st,
        }
        if st == "booked":
            bsum = summaries.get(s["id"])
            if bsum:
                row["booking_id"] = bsum["booking_id"]
                row["booking_status"] = bsum["status"]
                row["venue_label"] = bsum["venue_label"]
                row["client_preview"] = bsum["client_preview"]
        out_slots.append(row)
    return {"slots": out_slots}


# --- Schedule editor Mini App (trainer): templates, slots, apply week, delete slot ---

@router.get("/schedule/templates")
async def get_schedule_templates(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List weekly template entries (day_of_week, start_time, duration). Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    templates = await list_templates(session, trainer_id)
    return {
        "templates": [
            {
                "id": t["id"],
                "day_of_week": t["day_of_week"],
                "start_time": t["start_time"].strftime("%H:%M") if hasattr(t["start_time"], "strftime") else str(t["start_time"])[:5],
                "duration_minutes": t["duration_minutes"],
            }
            for t in templates
        ],
    }


class ScheduleTemplateDayBody(BaseModel):
    day_of_week: int  # 0=Mon .. 6=Sun
    start_hours: list[int]  # e.g. [9, 10, 11]
    duration_minutes: int = 60


@router.put("/schedule/templates/day")
async def put_schedule_templates_day(
    body: ScheduleTemplateDayBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Set template for one week day: replace all slots for that day with given hours. Auth: trainer."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    # Require CRM tier to edit templates
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail="Subscription tier required: CRM")
    if body.day_of_week < 0 or body.day_of_week > 6:
        raise HTTPException(status_code=400, detail="day_of_week must be 0-6")
    hours_set = {h for h in body.start_hours if 0 <= h <= 23}
    await replace_templates_for_day(session, trainer_id, body.day_of_week, hours_set, body.duration_minutes)
    return {"ok": True}


class ScheduleSlotsDayBody(BaseModel):
    slot_date: str  # YYYY-MM-DD
    start_hours: list[int]
    duration_minutes: int = 60


@router.post("/schedule/slots")
async def post_schedule_slots(
    body: ScheduleSlotsDayBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Set slots for one calendar day: replace available slots. Auth: trainer."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    # Require CRM tier to create/update slots
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail="Subscription tier required: CRM")
    try:
        slot_date = date.fromisoformat(body.slot_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slot_date")
    hours_set = {h for h in body.start_hours if 0 <= h <= 23}
    await replace_slots_for_day(session, trainer_id, slot_date, hours_set, body.duration_minutes)
    return {"ok": True}


class ScheduleApplyWeekBody(BaseModel):
    week_start: str  # YYYY-MM-DD (Monday)


@router.post("/schedule/apply-week")
async def post_schedule_apply_week(
    body: ScheduleApplyWeekBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Replace one week with template (free slots only); then apply recurring. Auth: trainer."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    # Require CRM tier to apply template and recurring bookings
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail="Subscription tier required: CRM")
    try:
        week_start = date.fromisoformat(body.week_start)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid week_start")
    count = await replace_week_with_template(session, trainer_id, week_start)
    await apply_recurring_bookings_for_week(session, trainer_id, week_start)
    trainer_bot = Bot(
        token=Settings().telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    asyncio.create_task(run_after_schedule_changed(trainer_id, trainer_bot))
    return {"ok": True, "slots_created": count}


@router.delete("/schedule/slots/{slot_id:int}")
async def delete_schedule_slot(
    slot_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Delete one applied slot (available only). Auth: trainer."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    deleted = await schedule_delete_slot(session, trainer_id, slot_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Slot not found or booked")
    return {"ok": True}


# --- Client booking Mini App (initData validated with client bot token) ---

@router.get("/client/slots")
async def get_client_slots(
    trainer_id: int = Query(..., description="Trainer to book"),
    min_hours: int | None = Query(None, description="From list/card; skip get_trainer when set"),
    trainer_name: str | None = Query(None, description="From list/card; skip get_trainer when set"),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """
    Available slots for a trainer (client view). Pass min_hours and trainer_name from
    catalog when opening card to avoid extra get_trainer round-trip.
    """
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    _client_telegram_id(raw)  # auth only

    if not await trainer_allows_online_booking(session, trainer_id):
        trainer_row = await get_trainer(session, trainer_id)
        if not trainer_row or (trainer_row.get("status") or "").strip().lower() != "active":
            raise HTTPException(status_code=404, detail="Trainer not found")
        tn = (trainer_name or "").strip()
        if not tn and trainer_row.get("profile"):
            first = (trainer_row["profile"].get("first_name") or "").strip()
            last = (trainer_row["profile"].get("last_name") or "").strip()
            tn = (first + " " + last).strip() or "Тренер"
        if not tn:
            tn = "Тренер"
        return {"trainer_name": tn, "slots": [], "online_booking_available": False}

    min_hours_val = min_hours if min_hours is not None else 3
    trainer_name_val = (trainer_name or "Тренер").strip() or "Тренер"
    if min_hours is None or trainer_name is None:
        trainer = await get_trainer(session, trainer_id)
        if min_hours is None and trainer and trainer.get("profile"):
            min_hours_val = trainer["profile"].get("min_hours_before_booking", 3) or 3
        if trainer_name is None and trainer and trainer.get("profile"):
            first = (trainer["profile"].get("first_name") or "").strip()
            last = (trainer["profile"].get("last_name") or "").strip()
            trainer_name_val = (first + " " + last).strip() or trainer_name_val

    cached_slots = get_slots_cached(trainer_id, min_hours_val)
    if cached_slots is not None:
        return {"trainer_name": trainer_name_val, "slots": cached_slots, "online_booking_available": True}

    this_m = _this_week_monday()
    next_m = this_m + timedelta(days=7)
    to_date = next_m + timedelta(days=6)
    slots = await list_slots(session, trainer_id, this_m, to_date)
    available = [s for s in slots if (s.get("status") or "available") == "available"]
    now_minsk = datetime.now(ZoneInfo(NOTIFICATION_TZ))
    available = [
        s for s in available
        if working_hours_between(now_minsk, s["slot_date"], s["start_time"]) >= min_hours_val
    ]
    serialized = [
        {
            "id": s["id"],
            "slot_date": s["slot_date"].isoformat() if hasattr(s["slot_date"], "isoformat") else str(s["slot_date"]),
            "start_time": s["start_time"].strftime("%H:%M") if hasattr(s["start_time"], "strftime") else str(s["start_time"])[:5],
            "end_time": s["end_time"].strftime("%H:%M") if hasattr(s["end_time"], "strftime") else str(s["end_time"])[:5],
        }
        for s in available
    ]
    set_slots_cached(trainer_id, min_hours_val, serialized)
    return {"trainer_name": trainer_name_val, "slots": serialized, "online_booking_available": True}


def _this_week_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


class ClientBookingBody(BaseModel):
    slot_id: int
    phone: str
    comment: str | None = None
    request_id: int | None = None  # when booking from "my request" flow, link and archive request
    service_id: int | None = None  # required when no request_id; when request_id set, taken from request


@router.post("/client/booking")
async def post_client_booking(
    body: ClientBookingBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """
    Create booking from client Mini App. Auth: client bot initData.
    
    Requires trainer to have tier >= 'online' for self-booking.
    Phone required. service_id required (or from request).
    """
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _client_telegram_id(raw)

    phone = (body.phone or "").strip()
    if not phone or len("".join(c for c in phone if c.isdigit() or c == "+")) < 10:
        raise HTTPException(status_code=400, detail="Valid phone required")

    slot = await get_slot(session, body.slot_id)
    if not slot or slot.get("status") != "available":
        raise HTTPException(status_code=400, detail="Slot not available")
    trainer_id = slot["trainer_id"]

    # Check trainer has online booking tier
    if not await trainer_allows_online_booking(session, trainer_id):
        raise HTTPException(
            status_code=403,
            detail="Online booking not available for this trainer",
            headers={"X-Error-Code": "TRAINER_NO_ONLINE_TIER"},
        )

    client_request_id: int | None = None
    service_id: int
    if body.request_id is not None:
        req = await get_client_request_for_booking(session, body.request_id, telegram_id)
        if not req or not any(r.get("trainer_id") == trainer_id for r in req.get("responses") or []):
            raise HTTPException(status_code=400, detail="Request not found or trainer did not respond")
        client_request_id = body.request_id
        service_id = req["service_id"]
    else:
        if body.service_id is None:
            raise HTTPException(status_code=400, detail="service_id required when not booking from request")
        service_id = body.service_id

    client_id = await get_or_create_client(session, telegram_id, phone=phone)
    booking_id = await create_booking(
        session,
        body.slot_id,
        trainer_id,
        client_id,
        service_id=service_id,
        client_comment=body.comment,
        client_request_id=client_request_id,
        created_by_trainer=False,
    )
    if not booking_id:
        raise HTTPException(status_code=400, detail="Slot not available")
    await generate_reminders_for_booking(session, booking_id)
    return {"success": True, "booking_id": booking_id}


@router.get("/client/session")
async def get_client_session_state(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Return client session with resolved names (city, service, arena, trainer) for catalog UI. Auth: client initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _client_telegram_id(raw)
    row = await get_client_session(telegram_id, session)
    profile = await get_client_profile_basic(session, telegram_id)
    client_phone = (
        ((profile.get("phone") or "").strip() or None) if profile else None
    )
    city_id = row.get("city_id")
    service_id = row.get("selected_service_id")
    arena_id = row.get("selected_arena_id")
    trainer_id = row.get("selected_trainer_id")

    city_name = None
    service_name = None
    arena_name = None
    trainer_name = None

    if city_id:
        cities = await list_cities(session)
        for c in cities:
            if c.get("id") == city_id:
                city_name = c.get("name") or ""
                break
    if service_id:
        services = await list_services(session)
        for s in services:
            if s.get("id") == service_id:
                service_name = s.get("name") or ""
                break
    if city_id and arena_id:
        arenas = await list_arenas(session, city_id)
        for a in arenas:
            if a.get("id") == arena_id:
                arena_name = a.get("name") or ""
                break
    if trainer_id:
        trainer = await get_trainer(session, trainer_id)
        if trainer and trainer.get("profile"):
            p = trainer["profile"]
            first = (p.get("first_name") or "").strip()
            last = (p.get("last_name") or "").strip()
            trainer_name = (first + " " + last).strip() or "Тренер"

    return {
        "city_id": city_id,
        "city_name": city_name,
        "service_id": service_id,
        "service_name": service_name,
        "arena_id": arena_id,
        "arena_name": arena_name or (None if arena_id is None else "—"),
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        "client_phone": client_phone,
    }


class ClientSessionBody(BaseModel):
    """Catalog selection: set all at once when user selects a trainer in Mini App."""
    city_id: int
    service_id: int
    arena_id: int | None = None
    trainer_id: int


@router.post("/client/session")
async def post_client_session(
    body: ClientSessionBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Save catalog choice (city, service, arena, trainer) so bot can show 'Выбран: X'. Auth: client initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _client_telegram_id(raw)

    await set_city(telegram_id, body.city_id, session)
    await set_service(telegram_id, body.service_id, session)
    await set_arena(telegram_id, body.arena_id, session)
    await set_selected_trainer(telegram_id, body.trainer_id, session)
    return {"success": True}


def _serialize_client_request(req: dict) -> dict:
    """Request + responses to JSON-safe (created_at as string)."""
    created_at = req.get("created_at")
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    elif created_at is not None:
        created_at = str(created_at)
    return {
        "id": req["id"],
        "city_id": req["city_id"],
        "service_id": req["service_id"],
        "comment": req.get("comment"),
        "created_at": created_at,
        "status": req.get("status"),
        "city_name": req.get("city_name"),
        "service_name": req.get("service_name"),
        "responses": [
            {
                "trainer_id": r.get("trainer_id"),
                "name": r.get("name"),
                "telegram_id": r.get("telegram_id"),
                "telegram_username": r.get("telegram_username"),
                "trainer_comment": r.get("trainer_comment"),
                "rating_avg": r.get("rating_avg"),
                "rating_count": r.get("rating_count") or 0,
                "experience_years": r.get("experience_years"),
                "description": r.get("description"),
                "session_duration_minutes": r.get("session_duration_minutes"),
                "photo_key": r.get("photo_key"),
                "services": r.get("services") or [],
            }
            for r in (req.get("responses") or [])
        ],
    }


class ClientRequestCreateBody(BaseModel):
    """Create request from catalog Mini App: city, service, optional comment and trainer_id."""
    city_id: int
    service_id: int
    comment: str | None = None
    trainer_id: int | None = None


@router.post("/client/request")
async def post_client_request(
    body: ClientRequestCreateBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Create a client request (from catalog Mini App). Auth: client initData. Returns request_id so UI can show success before closing."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _client_telegram_id(raw)
    client_id = await get_or_create_client(session, telegram_id, first_name=None, last_name=None)
    comment = (body.comment or "").strip() or None
    request_id = await create_client_request(
        session, client_id, body.city_id, body.service_id, comment=comment, trainer_id=body.trainer_id
    )
    return {"success": True, "request_id": request_id}


@router.get("/client/requests")
async def get_client_requests(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List my requests with responses. Auth: client bot initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _client_telegram_id(raw)
    items = await list_my_requests_with_responses(session, telegram_id)
    return {"items": [_serialize_client_request(r) for r in items]}


# --- Client pass products (buy) and my passes ---


@router.get("/client/pass-products")
async def get_client_pass_products(
    trainer_id: int = Query(..., description="Trainer whose products to list"),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List active pass products for a trainer (for purchase). Enriched with price_per_session_cents and savings when product has service_id."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    _client_telegram_id(raw)
    # Only trainers with online tier expose pass products in catalog (clients can book)
    if not await trainer_allows_online_booking(session, trainer_id):
        raise HTTPException(status_code=404, detail="Trainer not found")
    items = await list_pass_products(session, trainer_id, active_only=True)
    from sqlalchemy import text
    r = await session.execute(
        text("SELECT service_id, price_cents FROM trainer_services WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    price_by_service = {row[0]: row[1] for row in r.fetchall() if row[1] is not None}
    default_single = min(price_by_service.values()) if price_by_service else None
    # When trainer has no service prices: use max pass per-session price as "single" reference so we can show savings
    if default_single is None and items:
        pass_rates = [
            p["price_cents"] // p["sessions_total"]
            for p in items if p.get("sessions_total") and p.get("price_cents")
        ]
        if pass_rates:
            default_single = max(pass_rates)
    for p in items:
        sid = p.get("service_id")
        single = price_by_service.get(sid) if sid else default_single
        p["price_per_session_cents"] = single
        # Always expose pass price per session so client can show "X BYN за занятие"
        if p.get("sessions_total") and p.get("price_cents"):
            p["pass_price_per_session_cents"] = p["price_cents"] // p["sessions_total"]
        else:
            p["pass_price_per_session_cents"] = None
        if single is not None and p.get("sessions_total") and p.get("price_cents"):
            pass_per_session = p["price_cents"] // p["sessions_total"]
            savings = single - pass_per_session
            p["savings_per_session_cents"] = max(0, savings)
            p["savings_total_cents"] = max(0, savings) * p["sessions_total"]
        else:
            p["savings_per_session_cents"] = None
            p["savings_total_cents"] = None
    return {"items": items}


CLIENT_DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def _serialize_client_booking(b: dict) -> dict:
    """Client booking to JSON: date/time strings, arena, address, map_link."""
    slot_date = b.get("slot_date")
    start_time = b.get("start_time")
    end_time = b.get("end_time")
    return {
        "id": b["id"],
        "slot_id": b.get("slot_id"),
        "trainer_id": b.get("trainer_id"),
        "trainer_name": (b.get("trainer_name") or "Тренер").strip(),
        "trainer_telegram_id": b.get("trainer_telegram_id"),
        "slot_date": slot_date.isoformat() if hasattr(slot_date, "isoformat") else str(slot_date),
        "start_time": start_time.strftime("%H:%M") if hasattr(start_time, "strftime") else str(start_time)[:5],
        "end_time": end_time.strftime("%H:%M") if hasattr(end_time, "strftime") else str(end_time)[:5],
        "duration_minutes": b.get("duration_minutes") or 45,
        "status": (b.get("status") or "pending").strip(),
        "place_display": b.get("place_display") or "Уточните у тренера",
        "arena_name": b.get("arena_name"),
        "arena_address": b.get("arena_address"),
        "map_link": b.get("map_link"),
    }


@router.get("/client/bookings")
async def get_client_bookings(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List client's upcoming bookings grouped by day. Arena + address + map_link. Auth: client initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _client_telegram_id(raw)
    bookings = await list_bookings_for_client(session, telegram_id)
    if not bookings:
        return {"days": []}
    from itertools import groupby
    days_list = []
    for slot_date, group in groupby(bookings, key=lambda b: b["slot_date"]):
        day_bookings = list(group)
        date_str = slot_date.isoformat() if hasattr(slot_date, "isoformat") else str(slot_date)
        dow = slot_date.weekday() if hasattr(slot_date, "weekday") else 0
        day_label = CLIENT_DAYS[dow] if dow < len(CLIENT_DAYS) else ""
        days_list.append({
            "date": date_str,
            "day_label": day_label,
            "bookings": [_serialize_client_booking(b) for b in day_bookings],
        })
    return {"days": days_list}


@router.get("/client/passes")
async def get_client_passes(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List current client's pass instances (my passes). Auth: client initData. One query with JOINs."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _client_telegram_id(raw)
    client_id = await get_client_id_by_telegram_id(session, telegram_id)
    if not client_id:
        return {"items": []}
    items = await list_client_pass_instances(session, client_id)
    return {"items": items}


@router.get("/client/certificates")
async def get_client_certificates(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List current client's certificate instances (my certificates). Auth: client initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _client_telegram_id(raw)
    client_id = await get_client_id_by_telegram_id(session, telegram_id)
    if not client_id:
        return {"items": []}
    items = await list_client_certificate_instances(session, client_id)
    return {"items": items}


class ClientCertificateActivateBody(BaseModel):
    code: str


@router.post("/client/certificates/activate")
async def post_client_certificate_activate(
    body: ClientCertificateActivateBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """
    Client activates a certificate by code.
    - Binds certificate to this client (activated_client_id) and marks status=activated.
    - Returns basic info (trainer_id, amount_cents, product_id, expires_at).
    Auth: client initData.
    """
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    client_tid = _client_telegram_id(raw)
    client_id = await get_client_id_by_telegram_id(session, client_tid)
    if not client_id:
        raise HTTPException(status_code=403, detail="Client not found")
    code = (body.code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Code is required")
    result = await activate_certificate_by_code(session, client_id, code)
    if not result:
        raise HTTPException(status_code=404, detail="Certificate not found or cannot be activated")
    # Prefill client session so catalog opens with this trainer and city selected
    trainer_id = result.get("trainer_id")
    if trainer_id:
        city_id, service_id = await get_trainer_default_city_and_service(session, trainer_id)
        if city_id is not None:
            result["city_id"] = city_id
        if service_id is not None:
            result["service_id"] = service_id
    return result


class ClientCancelBookingBody(BaseModel):
    reason: str | None = None


@router.post("/client/bookings/{booking_id:int}/cancel")
async def post_client_booking_cancel(
    booking_id: int,
    body: ClientCancelBookingBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Cancel own booking with optional reason. Auth: client initData. Notifies trainer immediately."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _client_telegram_id(raw)
    payload = await cancel_booking_by_client(
        session, booking_id, telegram_id, reason=body.reason
    )
    if not payload:
        raise HTTPException(status_code=400, detail="Booking not found or already cancelled")
    # Notify trainer right away (async in same flow, no polling)
    trainer_tid = payload.get("trainer_telegram_id")
    if trainer_tid:
        slot_date = payload.get("slot_date")
        start_time = payload.get("start_time")
        client_name = (payload.get("client_name") or "Клиент").strip() or "Клиент"
        client_name_safe = html.escape(client_name)
        reason = payload.get("reason")
        reason_safe = html.escape(reason) if reason else ""
        date_str = slot_date.strftime("%d.%m") if hasattr(slot_date, "strftime") else str(slot_date)
        day_label = CLIENT_DAYS[slot_date.weekday()] if hasattr(slot_date, "weekday") else ""
        time_str = start_time.strftime("%H:%M") if hasattr(start_time, "strftime") else str(start_time)[:5]
        if reason:
            text = msg.TRAINER_BOOKING_CANCELLED_BY_CLIENT.format(
                client_name=client_name_safe, date=date_str, day=day_label, time=time_str, reason=reason_safe
            )
        else:
            text = msg.TRAINER_BOOKING_CANCELLED_BY_CLIENT_NO_REASON.format(
                client_name=client_name_safe, date=date_str, day=day_label, time=time_str
            )
        trainer_bot = Bot(
            token=Settings().telegram_bot_token_trainer,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            await trainer_bot.send_message(chat_id=trainer_tid, text=text)
        finally:
            await trainer_bot.session.close()
    return {"success": True}


class ClientRequestPatchBody(BaseModel):
    comment: str | None = None


@router.patch("/client/requests/{request_id}")
async def patch_client_request(
    request_id: int,
    body: ClientRequestPatchBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Replace request with new comment (re-create so trainers get new notification). Auth: client initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _client_telegram_id(raw)
    new_id = await replace_client_request_with_new(
        session, request_id, telegram_id, body.comment
    )
    if new_id is None:
        raise HTTPException(status_code=404, detail="Request not found")
    items = await list_my_requests_with_responses(session, telegram_id)
    req = next((r for r in items if r["id"] == new_id), None)
    if not req:
        return {"success": True, "request": None}
    return {"success": True, "request": _serialize_client_request(req)}


@router.delete("/client/requests/{request_id}")
async def delete_client_request_route(
    request_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Delete my request. Auth: client initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _client_telegram_id(raw)
    ok = await delete_client_request(session, request_id, telegram_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Request not found")
    return {"success": True}


# --- Trainer bookings Mini App (initData validated with trainer bot token) ---

TRAINER_DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def _serialize_booking(b: dict) -> dict:
    """Booking dict to JSON-safe (date/time as string)."""
    slot_date = b.get("slot_date")
    start_time = b.get("start_time")
    end_time = b.get("end_time")
    return {
        "id": b["id"],
        "slot_id": b.get("slot_id"),
        "client_telegram_id": b.get("client_telegram_id"),
        "client_has_telegram": b.get("client_telegram_id") is not None,
        "client_phone": (b.get("client_phone") or "").strip(),
        "client_first_name": b.get("client_first_name"),
        "client_last_name": b.get("client_last_name"),
        "client_comment": (b.get("client_comment") or "").strip() or None,
        "slot_date": slot_date.isoformat() if hasattr(slot_date, "isoformat") else str(slot_date),
        "start_time": start_time.strftime("%H:%M") if hasattr(start_time, "strftime") else str(start_time)[:5],
        "end_time": end_time.strftime("%H:%M") if hasattr(end_time, "strftime") else str(end_time)[:5],
        "session_num": b.get("session_num") or 1,
        "services_str": b.get("services_str"),
        "arenas_str": b.get("arenas_str"),
        "status": (b.get("status") or "confirmed").strip(),
    }


def _serialize_trainer_dashboard(data: dict) -> dict:
    """JSON-serializable dashboard: dates to ISO strings."""
    out = {**data}
    for key in ("week_start", "week_end", "month_start", "month_end", "busiest_date"):
        if key in out and hasattr(out[key], "isoformat"):
            out[key] = out[key].isoformat()
    return out


@router.get("/trainer/stats")
async def get_trainer_stats_api(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Full stats dashboard for trainer Mini App: KPIs, trends, by-day, insights. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    tier = await get_effective_subscription_tier(session, trainer_id)
    if not tier_satisfies(tier, SUBSCRIPTION_TIER_ANALYTICS):
        raise HTTPException(status_code=403, detail="Analytics tier required for statistics")
    data = await get_trainer_stats_dashboard(session, trainer_id)
    return _serialize_trainer_dashboard(data)


# --- Support: client/trainer send message; admin list and reply ---

class SupportCreateBody(BaseModel):
    message: str
    role: str = "client"  # client | trainer


class SupportReplyBody(BaseModel):
    reply_text: str


@router.post("/support")
async def post_support(
    body: SupportCreateBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Create support ticket from client or trainer Mini App. Auth: client or trainer initData; role in body."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    role = (body.role or "client").strip().lower()
    if role == "trainer":
        telegram_id = _trainer_telegram_id(raw)
    else:
        telegram_id = _client_telegram_id(raw)
        role = "client"
    from src.infrastructure.db.models import SUPPORT_FROM_CLIENT, SUPPORT_FROM_TRAINER
    from_role = SUPPORT_FROM_TRAINER if role == "trainer" else SUPPORT_FROM_CLIENT
    result = await create_support_message(session, telegram_id, from_role, body.message or "")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="Empty message")
    return result


@router.get("/admin/stats")
async def get_admin_stats(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Platform stats + alerts for admin Mini App. Auth: admin bot initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    _admin_telegram_id(raw)
    data = await get_platform_stats(session)
    # Serialize dates for JSON
    return {
        **data,
        "week_start": data["week_start"].isoformat() if hasattr(data["week_start"], "isoformat") else str(data["week_start"]),
        "week_end": data["week_end"].isoformat() if hasattr(data["week_end"], "isoformat") else str(data["week_end"]),
        "today": data["today"].isoformat() if hasattr(data["today"], "isoformat") else str(data["today"]),
    }


@router.get("/admin/support")
async def get_admin_support(
    status: str | None = Query(None, description="Filter: new, replied, closed"),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List support tickets for admin. Auth: admin initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    _admin_telegram_id(raw)
    items = await list_support_messages(session, limit=50, status=status)
    return {"items": items}


@router.post("/admin/support/{support_id:int}/reply")
async def post_admin_support_reply(
    support_id: int,
    body: SupportReplyBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Admin replies to support ticket. Auth: admin initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    admin_tid = _admin_telegram_id(raw)
    ok = await reply_support_message(session, support_id, admin_tid, body.reply_text or "")
    if not ok:
        raise HTTPException(status_code=404, detail="Ticket not found or already replied")
    return {"ok": True}


@router.get("/trainer/subscription-plans")
async def get_trainer_subscription_plans(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List paid subscription plans for trainer to choose (Месяц, 3 месяца, Год, 1.5 года). Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    plans = await list_paid_subscription_plans(session)
    return {"plans": plans}


@router.get("/trainer/subscription-payment-url")
async def get_trainer_subscription_payment_url(
    plan_id: int | None = Query(None, description="Chosen plan id; if omitted, use pending invoice or default plan"),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """
    Create (or reuse pending) invoice and return payment_url. When plan_id is set, create invoice for that plan
    (period: next after current subscription or from now). Response includes plan_name, period for clarity.
    """
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    plan_name: str | None = None
    period_start = period_end = None
    if plan_id is not None:
        inv = await create_subscription_invoice(session, trainer_id, plan_id)
        if not inv:
            raise HTTPException(status_code=400, detail="Invalid plan or could not create invoice")
        invoice_id = inv["invoice_id"]
        amount_cents = inv["amount_cents"]
        period_start = inv["period_start"]
        period_end = inv["period_end"]
        plan_name = inv.get("plan_name")
    else:
        pending = await get_pending_subscription_invoice(session, trainer_id)
        if pending:
            invoice_id = pending["invoice_id"]
            amount_cents = pending["amount_cents"]
            period_start = pending["period_start"]
            period_end = pending["period_end"]
            plan_name = pending.get("plan_name")
        else:
            default_plan_id = await get_paid_plan_id(session)
            if not default_plan_id:
                raise HTTPException(status_code=400, detail="No paid subscription plan configured")
            inv = await create_subscription_invoice(session, trainer_id, default_plan_id)
            if not inv:
                raise HTTPException(status_code=400, detail="Could not create subscription invoice")
            invoice_id = inv["invoice_id"]
            amount_cents = inv["amount_cents"]
            period_start = inv["period_start"]
            period_end = inv["period_end"]
            plan_name = inv.get("plan_name")
    settings = Settings()
    webapp_base = (settings.webapp_base_url or "").rstrip("/")
    api_base = (settings.api_base_url or webapp_base).rstrip("/")
    return_url = f"{webapp_base}/webapp/trainer-pay-subscription?payment_success=1"
    notification_url = f"{api_base}/api/webhooks/bepaid"
    tracking_id = f"inv_{invoice_id}"
    result = await create_checkout(
        amount_cents=amount_cents,
        currency="BYN",
        description=(plan_name or "Подписка")[:255],
        tracking_id=tracking_id,
        return_url=return_url,
        notification_url=notification_url,
        success_url=return_url,
    )
    def _date_str(d):
        if d is None:
            return None
        return d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]
    return {
        "payment_url": result["payment_url"],
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "plan_name": plan_name or "Подписка",
        "period_start": _date_str(period_start),
        "period_end": _date_str(period_end),
    }


class SubscriptionStubConfirmBody(BaseModel):
    invoice_id: int


@router.post("/trainer/subscription-stub-confirm")
async def post_trainer_subscription_stub_confirm(
    body: SubscriptionStubConfirmBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """
    In sandbox/stub mode: gateway returns to front with payment_stub=1&tracking_id=inv_XXX
    and does not send webhook. Front calls this to confirm the subscription invoice.
    """
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    if not Settings().payment_sandbox:
        raise HTTPException(status_code=404, detail="Not available when payment_sandbox is false")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    from sqlalchemy import text
    r = await session.execute(
        text("SELECT trainer_id FROM trainer_invoices WHERE id = :iid"),
        {"iid": body.invoice_id},
    )
    row = r.fetchone()
    if not row or row[0] != trainer_id:
        raise HTTPException(status_code=403, detail="Invoice not found or not yours")
    payment_external_id = f"stub-inv-{body.invoice_id}-{uuid.uuid4().hex[:12]}"
    ok = await confirm_subscription_invoice_after_payment(
        session, body.invoice_id, payment_external_id
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Invoice already paid or invalid")
    return {"success": True}


# --- Trainer subscription tiers (three-level access model) ---


@router.get("/trainer/subscription/catalog")
async def get_trainer_subscription_tier_catalog(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """
    List subscription tiers with pricing for catalog display.
    
    Returns CRM, Online, Analytics tiers with prices, periods, and descriptions.
    Auth: trainer initData.
    """
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    
    tiers = await get_subscription_tier_catalog(session)
    return {"tiers": tiers}


@router.get("/trainer/subscription/status")
async def get_trainer_subscription_tier_status(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """
    Get trainer's current subscription status.
    
    Returns effective tier, expiration date, and unlocked features.
    Auth: trainer initData.
    """
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    
    status = await get_trainer_subscription_status(session, trainer_id)
    return status


class SubscriptionTierMockCheckoutBody(BaseModel):
    tier: str
    period_months: Literal[1, 3, 12]


@router.post("/trainer/subscription/mock-checkout")
async def post_trainer_subscription_mock_checkout(
    body: SubscriptionTierMockCheckoutBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """
    Mock checkout for subscription tier (demo payment).
    
    Activates the tier subscription using pricing from subscription_tier_period_pricing.
    In production this would redirect to payment gateway.
    Auth: trainer initData.
    """
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    
    if body.tier not in SUBSCRIPTION_TIERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier. Must be one of: {', '.join(SUBSCRIPTION_TIERS)}",
        )
    
    result = await set_subscription_after_mock_payment(
        session, trainer_id, body.tier, body.period_months
    )
    if not result:
        raise HTTPException(status_code=400, detail="Could not activate tier subscription")
    
    return {
        "ok": True,
        "tier": result["tier"],
        "expires_at": result["expires_at"],
        "price_cents": result["price_cents"],
        "currency": result["currency"],
        "period_days": result["period_days"],
        "period_months": result["period_months"],
    }


# --- Trainer pass products (subscription products for sale) ---


@router.get("/trainer/pass-products")
async def get_trainer_pass_products(
    active_only: bool = Query(False, description="If true, return only is_active=true"),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List trainer's pass products. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail="Subscription tier required: CRM")
    items = await list_pass_products(session, trainer_id, active_only=active_only)
    return {"items": items}


class PassProductCreateBody(BaseModel):
    name: str
    sessions_total: int
    price_cents: int
    service_id: int | None = None
    sort_order: int = 0


@router.post("/trainer/pass-products")
async def post_trainer_pass_product(
    body: PassProductCreateBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Create a pass product. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail="Subscription tier required: CRM")
    product_id = await create_pass_product(
        session,
        trainer_id,
        name=body.name,
        sessions_total=body.sessions_total,
        price_cents=body.price_cents,
        service_id=body.service_id,
        sort_order=body.sort_order,
    )
    return {"success": True, "id": product_id}


class PassProductPatchBody(BaseModel):
    name: str | None = None
    sessions_total: int | None = None
    price_cents: int | None = None
    service_id: int | None = None
    is_active: bool | None = None
    sort_order: int | None = None


@router.patch("/trainer/pass-products/{product_id:int}")
async def patch_trainer_pass_product(
    product_id: int,
    body: PassProductPatchBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Update pass product. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail="Subscription tier required: CRM")
    patch = body.model_dump(exclude_unset=True)
    ok = await update_pass_product(
        session,
        product_id,
        trainer_id,
        _patch=patch if patch else None,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"success": True}


@router.delete("/trainer/pass-products/{product_id:int}")
async def delete_trainer_pass_product(
    product_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Delete pass product only if no purchases. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail="Subscription tier required: CRM")
    try:
        ok = await delete_pass_product(session, product_id, trainer_id)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=400,
            detail="Нельзя удалить абонемент: по нему уже выдали занятия. Снимите галочку «Активен», чтобы скрыть из каталога.",
        )
    if not ok:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"success": True}


# --- Admin: cities and arenas management for catalog (Mini App) ---


class AdminCityCreateBody(BaseModel):
    name: str
    sort_order: int | None = None


class AdminCityPatchBody(BaseModel):
    name: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


@router.get("/admin/cities")
async def get_admin_cities(
    q: str | None = Query(None, description="Search by city name"),
    include_inactive: bool = Query(False, description="Include inactive cities"),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List cities for admin: id, name, sort_order, arenas_count, is_active."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    _admin_telegram_id(raw)
    from sqlalchemy import text

    # Only q_like param (no :q) so asyncpg never gets NULL / ambiguous type.
    q_like = f"%{(q or '').strip()}%" if (q or "").strip() else "%"
    sql = """
        SELECT c.id, c.name, c.sort_order, c.is_active,
               COUNT(a.id) FILTER (WHERE a.is_active) AS arenas_count
        FROM cities c
        LEFT JOIN arenas a ON a.city_id = c.id
        WHERE (c.is_active = :active_ok OR :include_inactive)
        AND c.name ILIKE :q_like
        GROUP BY c.id, c.name, c.sort_order, c.is_active
        ORDER BY c.sort_order, c.id
    """
    params: dict[str, Any] = {
        "active_ok": True,
        "include_inactive": include_inactive,
        "q_like": q_like,
    }
    r = await session.execute(text(sql), params)
    rows = r.fetchall()
    return {
        "items": [
            {
                "id": row[0],
                "name": row[1],
                "sort_order": row[2],
                "is_active": row[3],
                "arenas_count": row[4],
            }
            for row in rows
        ]
    }


@router.post("/admin/cities")
async def post_admin_city(
    body: AdminCityCreateBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Create city (for catalog). Admin only."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    _admin_telegram_id(raw)
    from sqlalchemy import text

    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    sort_order = body.sort_order if body.sort_order is not None else 0
    r = await session.execute(
        text(
            """
            INSERT INTO cities (name, sort_order)
            VALUES (:name, :sort_order)
            RETURNING id, name, sort_order
            """
        ),
        {"name": name, "sort_order": sort_order},
    )
    row = r.fetchone()
    await session.commit()
    return {"id": row[0], "name": row[1], "sort_order": row[2]}


@router.patch("/admin/cities/{city_id:int}")
async def patch_admin_city(
    city_id: int,
    body: AdminCityPatchBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Update city name/sort_order. Admin only."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    _admin_telegram_id(raw)
    from sqlalchemy import text

    updates = []
    params = {"id": city_id}
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        updates.append("name = :name")
        params["name"] = name
    if body.sort_order is not None:
        updates.append("sort_order = :sort_order")
        params["sort_order"] = body.sort_order
    if body.is_active is not None:
        updates.append("is_active = :is_active")
        params["is_active"] = body.is_active
    if not updates:
        return {"ok": True}
    q = "UPDATE cities SET " + ", ".join(updates) + " WHERE id = :id"
    r = await session.execute(text(q), params)
    if r.rowcount == 0:
        raise HTTPException(status_code=404, detail="City not found")
    await session.commit()
    return {"ok": True}


class AdminArenaCreateBody(BaseModel):
    city_id: int
    name: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    sort_order: int | None = None


class AdminArenaPatchBody(BaseModel):
    city_id: int | None = None
    name: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    sort_order: int | None = None
    is_active: bool | None = None


@router.get("/admin/arenas")
async def get_admin_arenas(
    city_id: int = Query(..., description="City id"),
    q: str | None = Query(None, description="Search by name or address"),
    include_inactive: bool = Query(False, description="Include inactive arenas"),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List arenas for a city: id, name, address, lat/lon, sort_order, is_active."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    _admin_telegram_id(raw)
    from sqlalchemy import text

    q_like = f"%{(q or '').strip()}%" if (q or "").strip() else "%"
    sql = """
        SELECT id, name, address, latitude, longitude, sort_order, is_active
        FROM arenas
        WHERE city_id = :cid
        AND (is_active = :active_ok OR :include_inactive)
        AND (name ILIKE :q_like OR (address IS NOT NULL AND address ILIKE :q_like))
        ORDER BY sort_order, id
    """
    params: dict[str, Any] = {
        "cid": city_id,
        "active_ok": True,
        "include_inactive": include_inactive,
        "q_like": q_like,
    }
    r = await session.execute(text(sql), params)
    rows = r.fetchall()
    return {
        "items": [
            {
                "id": row[0],
                "name": row[1],
                "address": row[2],
                "latitude": row[3],
                "longitude": row[4],
                "sort_order": row[5],
                "is_active": row[6],
            }
            for row in rows
        ]
    }


@router.post("/admin/arenas")
async def post_admin_arena(
    body: AdminArenaCreateBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Create arena in a city. Admin only."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    _admin_telegram_id(raw)
    from sqlalchemy import text

    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    # Ensure city exists
    r_chk = await session.execute(text("SELECT 1 FROM cities WHERE id = :cid"), {"cid": body.city_id})
    if not r_chk.fetchone():
        raise HTTPException(status_code=400, detail="City not found")
    sort_order = body.sort_order if body.sort_order is not None else 0
    r = await session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, latitude, longitude, sort_order, is_active)
            VALUES (:city_id, :name, :address, :lat, :lon, :sort_order, true)
            RETURNING id, name, address, latitude, longitude, sort_order, is_active
            """
        ),
        {
            "city_id": body.city_id,
            "name": name,
            "address": (body.address or "").strip() or None,
            "lat": body.latitude,
            "lon": body.longitude,
            "sort_order": sort_order,
        },
    )
    row = r.fetchone()
    await session.commit()
    return {
        "id": row[0],
        "name": row[1],
        "address": row[2],
        "latitude": row[3],
        "longitude": row[4],
        "sort_order": row[5],
        "is_active": row[6],
    }


@router.patch("/admin/arenas/{arena_id:int}")
async def patch_admin_arena(
    arena_id: int,
    body: AdminArenaPatchBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Update arena fields. Admin only."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    _admin_telegram_id(raw)
    from sqlalchemy import text

    updates = []
    params: dict[str, Any] = {"id": arena_id}
    if body.city_id is not None:
        # Ensure city exists
        r_chk = await session.execute(text("SELECT 1 FROM cities WHERE id = :cid"), {"cid": body.city_id})
        if not r_chk.fetchone():
            raise HTTPException(status_code=400, detail="City not found")
        updates.append("city_id = :city_id")
        params["city_id"] = body.city_id
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        updates.append("name = :name")
        params["name"] = name
    if body.address is not None:
        addr = body.address.strip()
        updates.append("address = :address")
        params["address"] = addr or None
    if body.latitude is not None:
        updates.append("latitude = :lat")
        params["lat"] = body.latitude
    if body.longitude is not None:
        updates.append("longitude = :lon")
        params["lon"] = body.longitude
    if body.sort_order is not None:
        updates.append("sort_order = :sort_order")
        params["sort_order"] = body.sort_order
    if body.is_active is not None:
        updates.append("is_active = :is_active")
        params["is_active"] = body.is_active
    if not updates:
        return {"ok": True}
    q = "UPDATE arenas SET " + ", ".join(updates) + " WHERE id = :id"
    r = await session.execute(text(q), params)
    if r.rowcount == 0:
        raise HTTPException(status_code=404, detail="Arena not found")
    await session.commit()
    return {"ok": True}


@router.get("/admin/geocode")
async def get_admin_geocode(
    address: str = Query(..., min_length=3, description="Address or place name to geocode"),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
):
    """Resolve address to coordinates (Nominatim/OSM). Admin only. For Belarus/global addresses."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    _admin_telegram_id(raw)
    import aiohttp
    addr = address.strip()
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": addr, "format": "json", "limit": 1}
    headers = {"User-Agent": "TrainerCRM-Belarus-Admin/1.0"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=502, detail="Geocoder unavailable")
                data = await resp.json()
    except aiohttp.ClientError as e:
        logger.warning("geocode request failed: %s", e)
        raise HTTPException(status_code=502, detail="Geocoder request failed")
    if not data or not isinstance(data, list):
        raise HTTPException(status_code=404, detail="Address not found")
    first = data[0]
    lat = first.get("lat")
    lon = first.get("lon")
    if lat is None or lon is None:
        raise HTTPException(status_code=404, detail="No coordinates in result")
    try:
        return {"latitude": float(lat), "longitude": float(lon)}
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Invalid coordinates")


# --- Admin: subscription tier pricing management ---


@router.get("/admin/subscription-tiers")
async def get_admin_subscription_tiers(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """
    List all subscription tier pricing records for admin editing.
    
    Returns CRM, Online, Analytics tiers with prices, descriptions, active status.
    Auth: admin initData.
    """
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    _admin_telegram_id(raw)
    
    tiers = await list_subscription_tier_pricing_for_admin(session)
    return {"tiers": tiers}


class SubscriptionTierPatchBody(BaseModel):
    """Metadata on subscription_tier_pricing; matrix prices in period_prices (cents, keys 1 / 3 / 12)."""

    period_prices: dict[str, int] | None = None
    name_ru: str | None = None
    short_description_ru: str | None = None
    bullets: list[str] | None = None
    display_order: int | None = None
    is_active: bool | None = None


@router.patch("/admin/subscription-tiers/{tier}")
async def patch_admin_subscription_tier(
    tier: str,
    body: SubscriptionTierPatchBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """
    Update subscription tier pricing. Changes are logged to audit table.
    
    Auth: admin initData. Tier must be one of: crm, online, analytics.
    """
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    admin_tid = _admin_telegram_id(raw)
    
    if tier not in SUBSCRIPTION_TIERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier. Must be one of: {', '.join(SUBSCRIPTION_TIERS)}",
        )
    
    if body.period_prices:
        allowed = {"1", "3", "12"}
        for k, v in body.period_prices.items():
            if str(k) not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail="period_prices keys must be 1, 3, or 12 (months)",
                )
            if v < 0:
                raise HTTPException(status_code=400, detail="period_prices values must be >= 0")

    result = await update_subscription_tier_pricing(
        session,
        tier,
        admin_tid,
        period_prices=body.period_prices,
        name_ru=body.name_ru,
        short_description_ru=body.short_description_ru,
        bullets=body.bullets,
        display_order=body.display_order,
        is_active=body.is_active,
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Tier not found")
    
    return {"ok": True, "tier": result}


# --- Trainer certificate products (fixed amount or "any amount") ---


@router.get("/trainer/certificate-products")
async def get_trainer_certificate_products(
    active_only: bool = Query(False, description="If true, return only is_active=true"),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List trainer's certificate products. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    items = await list_certificate_products(session, trainer_id, active_only=active_only)
    return {"items": items}


class CertificateProductCreateBody(BaseModel):
    name: str
    amount_cents: int | None = None  # None = "любая сумма"
    expires_in_days: int | None = None
    sort_order: int = 0


@router.post("/trainer/certificate-products")
async def post_trainer_certificate_product(
    body: CertificateProductCreateBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Create certificate product. amount_cents=null means 'any amount'. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    product_id = await create_certificate_product(
        session,
        trainer_id,
        name=body.name,
        amount_cents=body.amount_cents,
        sort_order=body.sort_order,
    )
    return {"success": True, "id": product_id}


class CertificateProductPatchBody(BaseModel):
    name: str | None = None
    amount_cents: int | None = None  # None = "любая сумма"; omit = do not change
    expires_in_days: int | None = None
    is_active: bool | None = None
    sort_order: int | None = None


@router.patch("/trainer/certificate-products/{product_id:int}")
async def patch_trainer_certificate_product(
    product_id: int,
    body: CertificateProductPatchBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Update certificate product. Auth: trainer initData. Use model_dump(exclude_unset=True) to only send changed fields."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    payload = body.model_dump(exclude_unset=True)
    name = payload.get("name") if "name" in payload else None
    amount_cents = payload.get("amount_cents") if "amount_cents" in payload else AMOUNT_CENTS_UNSET
    expires_in_days = payload.get("expires_in_days") if "expires_in_days" in payload else None
    is_active = payload.get("is_active") if "is_active" in payload else None
    sort_order = payload.get("sort_order") if "sort_order" in payload else None
    ok = await update_certificate_product(
        session,
        product_id,
        trainer_id,
        name=name,
        amount_cents=amount_cents,
        expires_in_days=expires_in_days,
        is_active=is_active,
        sort_order=sort_order,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"success": True}


@router.delete("/trainer/certificate-products/{product_id:int}")
async def delete_trainer_certificate_product(
    product_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Delete certificate product. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    ok = await delete_certificate_product(session, product_id, trainer_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"success": True}


@router.get("/trainer/certificates")
async def get_trainer_certificates(
    active_only: bool = Query(True, description="If true, return only active (for redeem list)"),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List certificate instances issued by this trainer. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    items = await list_trainer_certificate_instances(session, trainer_id, active_only=active_only)
    return {"items": items}


class CertificateIssueBody(BaseModel):
    certificate_product_id: int
    purchased_by_name: str | None = None
    recipient_name: str = ""
    recipient_email: str | None = None
    recipient_phone: str | None = None


@router.post("/trainer/certificate-issue")
async def post_trainer_certificate_issue(
    body: CertificateIssueBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
):
    """Issue a certificate: create instance, generate PDF, save file_url; optionally send PDF to recipient_email. Idempotent by Idempotency-Key. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    if idempotency_key:
        cached = await get_idempotency_response(session, idempotency_key)
        if cached is not None:
            return cached
    try:
        instance = await issue_certificate(
            session,
            trainer_id,
            body.certificate_product_id,
            purchased_by_name=body.purchased_by_name,
            recipient_name=body.recipient_name or "—",
            recipient_email=body.recipient_email,
            recipient_phone=body.recipient_phone,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Generate PDF, upload, set file_url; then optionally send email. On failure return instance without file_url.
    try:
        from src.application.certificate_pdf import build_certificate_pdf
        from src.application.trainer_use_cases import get_trainer
        from src.infrastructure.s3 import upload_certificate_file
        from src.application.certificate_use_cases import get_certificate_product, update_certificate_file_url
        from src.shared.email_sender import send_certificate_pdf_email

        trainer = await get_trainer(session, trainer_id)
        profile = (trainer or {}).get("profile") or {}
        first = profile.get("first_name") or ""
        last = profile.get("last_name") or ""
        trainer_name = (first + " " + last).strip() or "Тренер"
        product = await get_certificate_product(session, body.certificate_product_id, trainer_id)
        product_name = (product or {}).get("name") or "Сертификат"
        issued_at = instance.get("issued_at")
        expires_at = instance.get("expires_at")
        if isinstance(issued_at, str):
            from datetime import datetime
            try:
                issued_at = datetime.fromisoformat(issued_at.replace("Z", "+00:00")).date() if issued_at else None
            except Exception:
                issued_at = None
        if isinstance(expires_at, str):
            from datetime import datetime
            try:
                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).date() if expires_at else None
            except Exception:
                expires_at = None

        _s = Settings()
        _code = (instance.get("code") or "").strip()
        _un = (_s.client_bot_username or "").strip().lstrip("@")
        _activation = f"https://t.me/{_un}?start=cert_{_code}" if _un and _code else None

        pdf_bytes = build_certificate_pdf(
            trainer_name=trainer_name,
            product_name=product_name,
            amount_cents=instance.get("amount_cents") or 0,
            code=instance.get("code") or "",
            recipient_name=instance.get("recipient_name") or "—",
            purchased_by_name=instance.get("purchased_by_name"),
            issued_at=issued_at,
            expires_at=expires_at,
            activation_url=_activation,
        )
        file_key = upload_certificate_file(pdf_bytes, trainer_id, instance["id"])
        await update_certificate_file_url(session, instance["id"], trainer_id, file_key)
        instance["file_url"] = file_key

        recipient_email = (body.recipient_email or "").strip() or None
        instance["email_pending"] = False
        if recipient_email:
            sent = await send_certificate_pdf_email(
                recipient_email,
                pdf_bytes,
                trainer_name=trainer_name,
                code=instance.get("code") or "",
            )
            instance["email_sent"] = sent
            if sent:
                await update_certificate_email_sent_at(session, instance["id"])
            else:
                logger.warning("Certificate email not sent to %s (instance id=%s), adding to outbox", recipient_email, instance.get("id"))
                inserted = await insert_certificate_email_outbox(session, instance["id"], recipient_email)
                instance["email_pending"] = inserted
        else:
            instance["email_sent"] = False
    except Exception as e:
        logger.exception("Certificate PDF/upload failed for instance %s: %s", instance.get("id"), e)
        instance["file_url"] = None
        instance["email_sent"] = False
        instance["email_pending"] = False

    instance.setdefault("email_pending", False)
    if idempotency_key:
        await set_idempotency_response(session, idempotency_key, instance)
    return instance


@router.get("/trainer/certificates/{certificate_id:int}/file")
async def get_trainer_certificate_file(
    certificate_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Download certificate PDF. Auth: trainer initData; certificate must belong to trainer."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    file_key = await get_certificate_file_key(session, certificate_id, trainer_id)
    if not file_key:
        raise HTTPException(status_code=404, detail="Certificate not found or file not ready")
    from src.infrastructure.s3 import get_file
    result = get_file(file_key, allowed_prefixes=("certificates/",))
    if not result:
        raise HTTPException(status_code=404, detail="File not found")
    body, content_type = result
    return Response(
        content=body,
        media_type=content_type,
        headers={"Content-Disposition": 'attachment; filename="certificate.pdf"'},
    )

@router.get("/trainer/welcome-link")
async def get_trainer_welcome_link(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Generic one-time invite link. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    settings = Settings()
    if not settings.client_bot_username:
        return {"welcome_link": None}
    token_id = await create_welcome_link_token(
        session, WELCOME_TOKEN_TYPE_GENERIC, trainer_id
    )
    link = (
        f"https://t.me/{settings.client_bot_username.lstrip('@')}?start=welcome_t_{token_id}"
    )
    return {"welcome_link": link}


@router.get("/trainer/welcome-link/pass")
async def get_trainer_welcome_link_pass(
    pass_product_id: int = Query(..., description="Pass product id (must belong to trainer)"),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """One-time pass invite link. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    from src.application.pass_product_use_cases import get_pass_product
    product = await get_pass_product(session, pass_product_id, trainer_id)
    if not product:
        raise HTTPException(status_code=404, detail="Pass product not found or not yours")
    settings = Settings()
    if not settings.client_bot_username:
        return {"welcome_link": None}
    token_id = await create_welcome_link_token(
        session, WELCOME_TOKEN_TYPE_PASS, trainer_id, pass_product_id=pass_product_id
    )
    link = (
        f"https://t.me/{settings.client_bot_username.lstrip('@')}?start=welcome_t_{token_id}"
    )
    return {"welcome_link": link, "product_name": product.get("name") or ""}


class WelcomeLinkCertBody(BaseModel):
    certificate_product_id: int


@router.post("/trainer/welcome-link/cert")
async def post_trainer_welcome_link_cert(
    body: WelcomeLinkCertBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """One-time cert welcome link: issue cert (no recipient name/phone), create token, return link. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    try:
        instance = await issue_certificate(
            session,
            trainer_id,
            body.certificate_product_id,
            purchased_by_name=None,
            recipient_name="—",
            recipient_email=None,
            recipient_phone=None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    code = (instance.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=500, detail="Certificate issue did not return code")
    token_id = await create_welcome_link_token(
        session, WELCOME_TOKEN_TYPE_CERT, trainer_id, cert_code=code
    )
    settings = Settings()
    if not settings.client_bot_username:
        return {"welcome_link": None, "code": code}
    link = (
        f"https://t.me/{settings.client_bot_username.lstrip('@')}?start=welcome_t_{token_id}"
    )
    return {"welcome_link": link, "code": code}


class CertificateRedeemByCodeBody(BaseModel):
    code: str


@router.post("/trainer/certificates/redeem")
async def post_trainer_certificates_redeem_by_code(
    body: CertificateRedeemByCodeBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Redeem certificate by code. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    try:
        result = await redeem_certificate(session, trainer_id, code=(body.code or "").strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result:
        raise HTTPException(status_code=404, detail="Certificate not found or already redeemed")
    return result


@router.post("/trainer/certificates/{certificate_id:int}/redeem")
async def post_trainer_certificate_redeem_by_id(
    certificate_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Redeem certificate by instance id. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    result = await redeem_certificate(session, trainer_id, certificate_instance_id=certificate_id)
    if not result:
        raise HTTPException(status_code=404, detail="Certificate not found or already redeemed")
    return result


@router.get("/client/certificate-products")
async def get_client_certificate_products(
    trainer_id: int = Query(..., description="Trainer whose certificate products to list"),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List active certificate products for a trainer (info only for client). Auth: client initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    _client_telegram_id(raw)
    items = await list_certificate_products(session, trainer_id, active_only=True)
    return {"items": items}


@router.get("/trainer/bookings")
async def get_trainer_bookings(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List trainer's upcoming bookings grouped by day. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")

    bookings = await list_bookings_for_trainer(session, trainer_id)
    today = date.today()
    if not bookings:
        return {"days": []}

    from itertools import groupby
    days_list = []
    for slot_date, group in groupby(bookings, key=lambda b: b["slot_date"]):
        day_bookings = list(group)
        date_str = slot_date.isoformat() if hasattr(slot_date, "isoformat") else str(slot_date)
        dow = slot_date.weekday() if hasattr(slot_date, "weekday") else 0
        day_label = TRAINER_DAYS[dow] if dow < len(TRAINER_DAYS) else ""
        days_list.append({
            "date": date_str,
            "day_label": day_label,
            "bookings": [_serialize_booking(b) for b in day_bookings],
        })
    # Only days that have at least one booking (no empty "today" slot)
    return {"days": days_list}


@router.get("/trainer/bookings/{booking_id:int}")
async def get_trainer_booking_detail(
    booking_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """One booking detail with recurring info. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")

    bookings = await list_bookings_for_trainer(session, trainer_id)
    b = next((x for x in bookings if x["id"] == booking_id), None)
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    detail = _serialize_booking(b)
    slot_date = b.get("slot_date")
    if hasattr(slot_date, "weekday"):
        detail["day_label"] = TRAINER_DAYS[slot_date.weekday()]
    else:
        detail["day_label"] = ""
    booking = await get_booking_with_slot(session, booking_id, trainer_id)
    recurring = None
    if booking:
        recurring = await get_active_recurring_for_booking(
            session, trainer_id, booking["client_id"],
            b["slot_date"].weekday(), b["start_time"],
        )
    detail["recurring_id"] = recurring["id"] if recurring else None
    return detail


class DeclineBody(BaseModel):
    comment: str


@router.post("/trainer/bookings/{booking_id:int}/confirm")
async def post_trainer_booking_confirm(
    booking_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    info = await confirm_booking(session, booking_id, trainer_id)
    if not info:
        raise HTTPException(status_code=400, detail="Booking not found or not pending")
    # Notify client (same as in trainer_handlers)
    client_tid = info.get("client_telegram_id")
    if client_tid:
        d = info["slot_date"]
        date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
        dow = TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
        time_str = (info["start_time"].strftime("%H:%M") if hasattr(info["start_time"], "strftime") else str(info["start_time"])[:5])
        trainer_obj = await get_trainer(session, trainer_id)
        profile = (trainer_obj or {}).get("profile") or {}
        trainer_name = ((profile.get("first_name") or "") + " " + (profile.get("last_name") or "")).strip() or "Тренер"
        settings = Settings()
        client_bot = Bot(
            token=settings.telegram_bot_token_client,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            await client_bot.send_message(
                chat_id=client_tid,
                text=msg.CLIENT_BOOKING_CONFIRMED_BY_TRAINER.format(
                    date=date_str, day=dow, time=time_str, trainer_name=trainer_name,
                ),
            )
        finally:
            await client_bot.session.close()
    return {"success": True}


@router.post("/trainer/bookings/{booking_id:int}/decline")
async def post_trainer_booking_decline(
    booking_id: int,
    body: DeclineBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    comment = (body.comment or "").strip()
    if not comment:
        raise HTTPException(status_code=400, detail="Comment required for decline")
    info = await decline_booking(session, booking_id, trainer_id)
    if not info:
        raise HTTPException(status_code=400, detail="Booking not found or not pending")
    # Notify client (same as in trainer_handlers)
    client_tid = info.get("client_telegram_id")
    if client_tid:
        d = info["slot_date"]
        date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
        dow = TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
        time_str = (info["start_time"].strftime("%H:%M") if hasattr(info["start_time"], "strftime") else str(info["start_time"])[:5])
        trainer_obj = await get_trainer(session, trainer_id)
        profile = (trainer_obj or {}).get("profile") or {}
        trainer_name = ((profile.get("first_name") or "") + " " + (profile.get("last_name") or "")).strip() or "Тренер"
        settings = Settings()
        client_bot = Bot(
            token=settings.telegram_bot_token_client,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            await client_bot.send_message(
                chat_id=client_tid,
                text=msg.CLIENT_BOOKING_DECLINED_BY_TRAINER.format(
                    date=date_str, day=dow, time=time_str, reason=comment[:500],
                ),
            )
        finally:
            await client_bot.session.close()
    return {"success": True}


@router.post("/trainer/bookings/{booking_id:int}/cancel")
async def post_trainer_booking_cancel(
    booking_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    ok = await cancel_booking(session, booking_id, trainer_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Cancel failed")
    return {"success": True}


@router.post("/trainer/bookings/{booking_id:int}/complete")
async def post_trainer_booking_complete(
    booking_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Mark booking as conducted (completed). Redeems one pass session if client has a matching pass. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    result = await mark_booking_completed_by_trainer(session, booking_id, trainer_id)
    if not result:
        raise HTTPException(status_code=400, detail="Booking not found or not confirmed")
    if not result.get("pass_redeemed"):
        payload = await get_booking_no_pass_notify_payload(session, booking_id)
        if payload and payload.get("trainer_telegram_id"):
            try:
                text = msg.TRAINER_NO_PASS_FOR_SERVICE.format(
                    client_name=payload["client_name"],
                    date=payload["date"],
                    time=payload["time"],
                    service_name=payload["service_name"],
                )
                settings = Settings()
                trainer_bot = Bot(
                    token=settings.telegram_bot_token_trainer,
                    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
                )
                try:
                    await trainer_bot.send_message(
                        chat_id=payload["trainer_telegram_id"],
                        text=text,
                    )
                finally:
                    await trainer_bot.session.close()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Failed to send no-pass notification to trainer %s: %s",
                    payload.get("trainer_telegram_id"),
                    e,
                )
    return result


class TrainerCreateBookingBody(BaseModel):
    """Create booking from schedule: trainer picks slot + client + service."""
    slot_id: int
    client_id: int
    service_id: int


class TrainerCreateClientBody(BaseModel):
    """Create client by phone (no telegram_id); for trainer recording from schedule."""
    phone: str
    first_name: str | None = None
    last_name: str | None = None


@router.get("/trainer/my-services")
async def get_trainer_my_services(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List services offered by this trainer (for booking: choose service). Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    from sqlalchemy import text
    r = await session.execute(
        text("""
            SELECT s.id, s.name
            FROM trainer_services ts
            JOIN services s ON s.id = ts.service_id
            WHERE ts.trainer_id = :tid
            ORDER BY s.sort_order, s.id
        """),
        {"tid": trainer_id},
    )
    rows = r.fetchall()
    return {"services": [{"id": row[0], "name": (row[1] or "").strip() or "—"} for row in rows]}


@router.get("/trainer/clients")
async def get_trainer_clients(
    q: str | None = Query(None, description="Search by name or phone (optional)"),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List clients that have at least one booking with this trainer. Optional search by name/phone. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    clients = await list_trainer_clients(session, trainer_id, limit=100)
    if q and (q := (q or "").strip()):
        q_lower = q.lower()
        digits = "".join(c for c in q if c.isdigit())
        phone_digits_only = lambda s: "".join(c for c in (s or "") if c.isdigit())
        clients = [
            c for c in clients
            if q_lower in ((c.get("first_name") or "") + " " + (c.get("last_name") or "")).strip().lower()
            or q_lower in (c.get("phone") or "").lower()
            or (digits and digits in phone_digits_only(c.get("phone")))
        ]
    return {"clients": clients}


@router.get("/trainer/clients/{client_id:int}/history")
async def get_trainer_client_history(
    client_id: int,
    limit: int = Query(20, ge=1, le=100),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Last bookings for this client with this trainer. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    items = await list_trainer_client_history(session, trainer_id, client_id, limit=limit)
    total = await count_trainer_client_sessions(session, trainer_id, client_id)
    return {"items": items, "total": total}


@router.get("/trainer/clients/{client_id:int}/next-booking")
async def get_trainer_client_next_booking_route(
    client_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Next upcoming booking for this client with this trainer, or null. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    next_booking = await get_trainer_client_next_booking(session, trainer_id, client_id)
    upcoming_count = await count_trainer_client_upcoming(session, trainer_id, client_id)
    return {"next_booking": next_booking, "upcoming_count": upcoming_count}


@router.get("/trainer/clients/{client_id:int}/passes")
async def get_trainer_client_passes(
    client_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List pass instances for this client (issued by this trainer). Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    items = await list_pass_instances_for_trainer_client(session, trainer_id, client_id)
    return {"items": items}


@router.get("/trainer/clients/{client_id:int}/certificates")
async def get_trainer_client_certificates(
    client_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List certificate instances for this client (issued by this trainer). Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    items = await list_certificate_instances_for_trainer_client(session, trainer_id, client_id)
    return {"items": items}


class TrainerPassIssueBody(BaseModel):
    pass_product_id: int


@router.post("/trainer/clients/{client_id:int}/pass-issue")
async def post_trainer_client_pass_issue(
    client_id: int,
    body: TrainerPassIssueBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Issue a pass to this client (trainer recorded external payment). Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    try:
        instance = await issue_pass_to_client(
            session, trainer_id, client_id, body.pass_product_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Notify client about issued pass (best-effort; do not fail API on send error)
    client_telegram_id = await get_client_telegram_id(session, client_id)
    if client_telegram_id:
        try:
            trainer_obj = await get_trainer(session, trainer_id)
            profile = (trainer_obj or {}).get("profile") or {}
            trainer_name = (
                ((profile.get("first_name") or "") + " " + (profile.get("last_name") or "")).strip()
                or "Тренер"
            )
            text = msg.CLIENT_PASS_ISSUED.format(
                product_name=instance["product_name"],
                sessions_total=instance["sessions_total"],
                sessions_remaining=instance["sessions_remaining"],
                trainer_name=trainer_name,
            )
            base_url = (Settings().api_base_url or "").rstrip("/")
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.CLIENT_BUTTON_MY_PASSES_AND_CERTIFICATES,
                            web_app=WebAppInfo(url=f"{base_url}/webapp/client-passes-certificates"),
                        )
                    ]
                ]
            )
            settings = Settings()
            client_bot = Bot(
                token=settings.telegram_bot_token_client,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            try:
                await client_bot.send_message(
                    chat_id=client_telegram_id,
                    text=text,
                    reply_markup=kb,
                )
            finally:
                await client_bot.session.close()
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to send pass-issued notification to client %s: %s", client_id, e)
    return instance


class TrainerClientNoteBody(BaseModel):
    note: str


@router.get("/trainer/clients/{client_id:int}/note")
async def get_trainer_client_note_route(
    client_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get trainer's private note about this client. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    note = await get_trainer_client_note(session, trainer_id, client_id)
    return {"note": (note or {}).get("note", "")}


@router.post("/trainer/clients/{client_id:int}/note")
async def post_trainer_client_note_route(
    client_id: int,
    body: TrainerClientNoteBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create or update trainer's private note about this client. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    result = await upsert_trainer_client_note(session, trainer_id, client_id, body.note)
    return {"note": result.get("note", "")}


@router.post("/trainer/clients")
async def post_trainer_clients(
    body: TrainerCreateClientBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Create or get client by phone (no telegram_id). For recording from schedule. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    try:
        client_id = await get_or_create_client_by_phone(
            session,
            body.phone,
            first_name=body.first_name,
            last_name=body.last_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await session.commit()
    return {"client_id": client_id}


@router.post("/trainer/booking")
async def post_trainer_booking(
    body: TrainerCreateBookingBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Create booking: trainer assigns client to slot (from schedule). Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    from src.application.trainer_schedule_use_cases import get_slot
    slot = await get_slot(session, body.slot_id)
    if not slot or slot.get("trainer_id") != trainer_id or (slot.get("status") or "").strip() != "available":
        raise HTTPException(status_code=400, detail="Slot not found or not available")
    booking_id = await create_booking(
        session,
        slot_id=body.slot_id,
        trainer_id=trainer_id,
        client_id=body.client_id,
        service_id=body.service_id,
        client_comment=None,
        client_request_id=None,
        created_by_trainer=True,
    )
    if not booking_id:
        raise HTTPException(status_code=400, detail="Slot not available")
    await generate_reminders_for_booking(session, booking_id)
    return {"success": True, "booking_id": booking_id}


@router.post("/trainer/bookings/{booking_id:int}/make_regular")
async def post_trainer_booking_make_regular(
    booking_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    booking = await get_booking_with_slot(session, booking_id, trainer_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    recurring_id = await create_recurring_client_slot(
        session, trainer_id, booking["client_id"],
        booking["slot_date"].weekday(), booking["start_time"], booking["end_time"],
    )
    return {"success": True, "recurring_id": recurring_id}


@router.post("/trainer/recurring/{recurring_id:int}/remove")
async def post_trainer_recurring_remove(
    recurring_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    ok = await cancel_recurring_client_slot(session, trainer_id, recurring_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Recurring not found")
    return {"success": True}


# --- Trainer client requests Mini App (list, respond, decline, remind, book client) ---


def _serialize_trainer_request(req: dict) -> dict:
    """Request dict to JSON-safe for trainer requests list/detail."""
    created_at = req.get("created_at")
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    elif created_at is not None:
        created_at = str(created_at)
    return {
        "id": req["id"],
        "city_id": req["city_id"],
        "service_id": req["service_id"],
        "comment": req.get("comment"),
        "created_at": created_at,
        "city_name": req.get("city_name"),
        "service_name": req.get("service_name"),
        "is_personalized": bool(req.get("is_personalized")),
        "has_responded": bool(req.get("has_responded")),
        "client_id": req.get("client_id"),
        "client_telegram_id": req.get("client_telegram_id"),
        "client_first_name": req.get("client_first_name"),
        "client_last_name": req.get("client_last_name"),
    }


@router.get("/trainer/onboarding/moderation-readiness")
async def webapp_trainer_moderation_readiness(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Profile completeness for moderation queue; works for linked trainers before active (onboarding Mini App)."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_linked_any_status(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Telegram not linked to a trainer")
    data = await get_trainer_moderation_readiness(session, trainer_id)
    if not data:
        raise HTTPException(status_code=404, detail="Trainer not found")
    return data


@router.post("/trainer/onboarding/submit-for-moderation")
async def webapp_trainer_submit_for_moderation(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Reject incomplete profiles with 422 + missing field list; otherwise same rules as REST submit."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_linked_any_status(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Telegram not linked to a trainer")
    result = await try_submit_trainer_for_moderation_review(session, trainer_id)
    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="Trainer not found")
    if not result.get("ok"):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Profile incomplete for moderation",
                "missing_fields": result.get("missing_fields", []),
                "missing_labels_ru": result.get("missing_labels_ru", []),
            },
        )
    if result.get("noop"):
        return {
            "ok": True,
            "noop": True,
            "trainer_status": result.get("trainer_status"),
            "reason": result.get("reason"),
        }
    return {"ok": True, "submitted": True}


@router.get("/trainer/requests/ping")
async def trainer_requests_ping(step: str | None = Query(None)):
    """Diagnostic: no auth, just log. step=img|script|loadList to trace where page execution reaches."""
    logger.info("trainer_requests_ping step=%s", step or "none")
    return {"ok": True}


@router.get("/trainer/requests")
async def get_trainer_requests(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """List client requests for this trainer (city+service match). New first, then in progress. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    logger.info("GET /trainer/requests has_init_data=%s", bool(raw))
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    items = await list_requests_for_trainer(session, trainer_id)
    if not items:
        logger.info("trainer_requests_empty trainer_id=%s (profile city+service may not match any request)", trainer_id)
    new_list = [r for r in items if not r.get("has_responded")]
    in_progress_list = [r for r in items if r.get("has_responded")]
    combined = new_list + in_progress_list
    return {"items": [_serialize_trainer_request(r) for r in combined]}


class TrainerRespondBody(BaseModel):
    trainer_comment: str | None = None


@router.post("/trainer/requests/{request_id:int}/respond")
async def post_trainer_request_respond(
    request_id: int,
    body: TrainerRespondBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Respond to request (optional comment). Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    comment = (body.trainer_comment or "").strip() or None
    resp_id = await create_request_response(session, request_id, trainer_id, trainer_comment=comment)
    if resp_id is None:
        raise HTTPException(status_code=400, detail="Already responded or request not found")
    return {"success": True, "response_id": resp_id}


@router.post("/trainer/requests/{request_id:int}/decline")
async def post_trainer_request_decline(
    request_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Decline request (hide from trainer list). Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    ok = await create_request_decline(session, request_id, trainer_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Decline failed")
    return {"success": True}


@router.post("/trainer/requests/{request_id:int}/remind-slots")
async def post_trainer_request_remind_slots(
    request_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Set 'remind me when I have slots' for this request. Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    await add_trainer_pending_request_booking(session, trainer_id, request_id)
    return {"success": True}


@router.get("/trainer/requests/{request_id:int}/slots")
async def get_trainer_request_slots(
    request_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Available slots for next 2 weeks (for booking client from request). Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    client_info = await get_request_client_for_trainer_booking(session, request_id, trainer_id)
    if not client_info:
        raise HTTPException(status_code=404, detail="Request not found or not responded")
    today = date.today()
    to_date = today + timedelta(days=14)
    slots = await list_slots(session, trainer_id, today, to_date)
    available = [s for s in slots if (s.get("status") or "available") == "available"]
    now_minsk = datetime.now(ZoneInfo(NOTIFICATION_TZ))
    trainer = await get_trainer(session, trainer_id)
    min_hours = 3
    if trainer and trainer.get("profile"):
        min_hours = trainer["profile"].get("min_hours_before_booking", 3) or 3
    available = [
        s for s in available
        if working_hours_between(now_minsk, s["slot_date"], s["start_time"]) >= min_hours
    ]
    return {
        "slots": [
            {
                "id": s["id"],
                "slot_date": s["slot_date"].isoformat() if hasattr(s["slot_date"], "isoformat") else str(s["slot_date"]),
                "start_time": s["start_time"].strftime("%H:%M") if hasattr(s["start_time"], "strftime") else str(s["start_time"])[:5],
                "end_time": s["end_time"].strftime("%H:%M") if hasattr(s["end_time"], "strftime") else str(s["end_time"])[:5],
            }
            for s in available
        ],
    }


class TrainerBookRequestBody(BaseModel):
    slot_id: int


@router.post("/trainer/requests/{request_id:int}/book")
async def post_trainer_request_book(
    request_id: int,
    body: TrainerBookRequestBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    """Create booking for client from request (trainer books client). Auth: trainer initData."""
    raw = init_data or x_telegram_init_data
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")
    telegram_id = _trainer_telegram_id(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, telegram_id)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked or not active")
    client_info = await get_request_client_for_trainer_booking(session, request_id, trainer_id)
    if not client_info:
        raise HTTPException(status_code=404, detail="Request not found or not responded")
    booking_id = await create_booking(
        session,
        slot_id=body.slot_id,
        trainer_id=trainer_id,
        client_id=client_info["client_id"],
        service_id=client_info["service_id"],
        client_comment=None,
        client_request_id=request_id,
        created_by_trainer=True,
    )
    if not booking_id:
        raise HTTPException(status_code=400, detail="Slot not available")
    await clear_trainer_pending_request_booking(session, trainer_id, request_id)
    await generate_reminders_for_booking(session, booking_id)
    return {"success": True, "booking_id": booking_id}
