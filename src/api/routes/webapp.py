"""
Web App API: trainer schedule (Mini App) and client booking (Mini App). Auth via validated initData.
"""
import asyncio
import html
import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone
from itertools import groupby
from typing import Any, Literal
from urllib.parse import parse_qsl

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from src.api.deps import get_session
from src.shared.byr_currency_display import BYR_SIGN
from src.shared.price_tier_kind import normalize_price_tier_kind, price_tier_label_ru, sql_order_case_tier_kind
from src.shared.profile_phone import coerce_required_belarus_phone
from src.application.booking_problem_notifications import send_booking_problem_telegram_notifications
from src.application.booking_problem_rollout import booking_problem_api_allowed_for_trainer
from src.application.booking_problem_use_cases import (
    classify_booking_problem_payment_class,
    get_trainer_booking_problem_options,
    submit_trainer_booking_problem,
)
from src.application.booking_client_no_show_notifications import (
    send_booking_client_no_show_telegram_notifications,
)
from src.application.booking_no_show_use_cases import (
    get_trainer_booking_client_no_show_options,
    submit_trainer_booking_client_no_show,
)
from src.application.booking_use_cases import (
    ServicePriceVariantRequired,
    active_booking_summaries_by_slot_for_trainer_range,
    cancel_booking,
    cancel_booking_by_client,
    client_latest_booking_primary_candidate,
    client_upcoming_booking_primary_candidate,
    client_rebook_trainer_targets,
    confirm_booking,
    coerce_service_id_and_name_for_trainer_catalog,
    count_trainer_client_sessions,
    count_trainer_client_upcoming,
    create_booking,
    create_trainer_quick_booking,
    get_trainer_hub_session_summary_counts,
    explain_trainer_booking_failure,
    decline_booking,
    detach_trainer_client_from_roster_miniapp,
    format_trainer_reminder_plan_for_client_day,
    generate_reminders_for_booking,
    get_booking_milestone_display_for_trainer,
    get_trainer_default_city_and_service,
    list_trainer_services_for_welcome_link,
    resolve_service_id_for_generic_welcome_link,
    mark_booking_completed_by_trainer,
    purge_past_booking_from_schedule_history,
    get_booking_with_slot,
    get_trainer_booking_detail_payload,
    load_booking_service_edit_context,
    resolve_booking_service_edit_ui_flags,
    update_trainer_booking_service,
    get_trainer_client_next_booking,
    get_trainer_client_for_card,
    get_trainer_client_last_booking_service_defaults,
    get_trainer_client_booking_defaults_from_booking_id,
    get_trainer_client_last_booking_price_variant_for_service,
    get_trainer_client_latest_booking_service_id,
    get_trainer_group_slot_hub,
    resolve_client_catalog_service_for_trainer,
    is_slot_end_in_past_local,
    link_trainer_client_roster,
    list_bookings_for_trainer,
    list_trainer_clients,
    list_trainer_fill_slots_invite_candidates,
    list_trainer_client_history,
    patch_trainer_client_identity_for_card,
    resolve_arena_for_client_self_booking,
    get_trainer_primary_arena_resolved,
    get_trainer_slot_for_mass_client_invite,
    trainer_client_roster_link_exists,
    is_slot_start_in_past_local,
    get_first_service_id_for_trainer,
)
from src.application.client_username_enrich import enrich_booking_dicts_with_client_telegram_usernames
from src.application.family_access_use_cases import (
    create_family_access_invite_token,
    list_family_access_members_api,
    revoke_family_member,
)
from src.application.trainer_client_relay_use_cases import (
    RELAY_SENDER_TRAINER,
    assert_trainer_may_use_relay,
    close_relay_session,
    get_open_session_id,
    insert_relay_message,
    open_relay_session,
    sanitize_relay_body,
    trainer_public_display_name,
)
from src.application.trainer_relay_delivery import send_client_relay_from_trainer, sweep_idle_relay_sessions_and_notify
from src.application.trainer_client_registration_notify import (
    notify_trainer_client_registered_from_invite,
)
from src.application.client_stats_use_cases import get_client_activity_snapshot
from src.application.client_use_cases import (
    attach_telegram_id_to_client,
    get_client_by_phone,
    get_client_id_by_telegram_id,
    reset_orphan_client_miniapp_trainer_pointers,
    trainer_id_belongs_to_telegram,
    get_client_phone_for_webapp,
    get_client_profile_basic,
    get_client_telegram_id,
    get_or_create_client,
    get_or_create_client_by_phone,
    get_or_create_sandbox_client_for_trainer,
    normalize_phone,
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
    count_unanswered_requests_for_trainer,
    list_requests_for_trainer,
    replace_client_request_with_new,
)
from src.application.client_pass_order_use_cases import (
    get_primary_pass_order_catalog,
    split_pass_order_comment,
    submit_pass_product_order_request,
)
from src.application.client_cert_order_use_cases import (
    get_primary_cert_order_catalog,
    split_cert_order_comment,
    submit_certificate_product_order_request,
)
from src.application.client_session_use_cases import (
    get_or_create_session as get_client_session,
    get_session as read_client_bot_session,
    save_catalog_filters,
    set_arena,
    set_city,
    set_selected_trainer,
    set_service,
    sync_session_catalog_after_client_booking,
)
from src.application.client_trainer_edge_use_cases import (
    get_all_edges as get_all_trainer_edges,
    get_edge as get_trainer_edge,
    get_primary_edge as get_primary_trainer_edge,
    get_saved_edges as get_saved_trainer_edges,
    notify_slot_waitlist as uc_notify_slot_waitlist,
    record_booking_edge,
    save_trainer as uc_save_trainer,
    set_primary_trainer as uc_set_primary_trainer,
    subscribe_notify_slots as uc_subscribe_notify_slots,
    trainer_display_hints_by_ids,
    unset_primary_trainer as uc_unset_primary_trainer,
    unsave_trainer as uc_unsave_trainer,
    unsubscribe_notify_slots as uc_unsubscribe_notify_slots,
)
from src.application.catalog_use_cases import list_arenas, list_cities, list_services
from src.application.trainer_schedule_use_cases import this_week_monday, trainer_default_slot_arena_id
from src.application.recurring_use_cases import (
    cancel_recurring_client_slot,
    create_recurring_client_slot,
    get_active_recurring_for_booking,
    has_other_active_recurring,
    list_active_recurring_slots_for_trainer_client,
    list_recurring_booking_suggestions_for_trainer_client,
    list_upcoming_recurring_bookings_for_trainer_client,
    materialize_recurring_horizon,
)
from src.application.trainer_access_state import (
    TrainerAccessState,
    get_trainer_access_state_from_principal,
)
from src.shared.trainer_status import normalize_trainer_status_value
from src.application.trainer_link import (
    get_trainer_id_by_telegram_id_from_principal,
    get_trainer_id_for_webapp_trainer_operations_from_principal,
    get_trainer_id_linked_any_status_from_principal,
)
from src.application.welcome_link_use_cases import (
    WELCOME_TOKEN_TYPE_CERT,
    WELCOME_TOKEN_TYPE_CLIENT_BIND,
    WELCOME_TOKEN_TYPE_GENERIC,
    WELCOME_TOKEN_TYPE_PASS,
    create_welcome_link_token,
)
from src.application.stats_use_cases import (
    get_platform_stats,
    get_trainer_hub_revenue_month_to_date,
    get_trainer_revenue_breakdown_for_range,
    get_trainer_stats_dashboard,
)
from src.application.admin_analytics_use_cases import (
    get_admin_clients_stats,
    get_admin_engagement_stats,
    get_admin_growth_stats,
    get_admin_money_stats,
    get_admin_product_analytics,
    get_admin_retention_stats,
)
from src.application.support_use_cases import (
    create_support_message,
    list_support_messages,
    reply_support_message,
)
from src.application.pass_product_use_cases import (
    create_pass_product,
    delete_pass_product,
    enrich_pass_items_with_catalog_reference_prices,
    issue_pass_to_client,
    list_client_pass_instances,
    list_pass_instances_for_trainer_client,
    list_pass_products,
    update_pass_product,
)
from src.application.certificate_use_cases import (
    AMOUNT_CENTS_UNSET,
    DESCRIPTION_UNSET,
    create_certificate_product,
    delete_certificate_product,
    get_certificate_product,
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
from src.application.subscription_invoice_admin_notify import notify_admins_new_catalog_subscription_invoice
from src.application.subscription_use_cases import (
    confirm_subscription_invoice_after_payment,
    create_catalog_subscription_invoice_for_trainer,
    create_subscription_invoice,
    ensure_trainer_welcome_trial,
    get_paid_plan_id,
    get_pending_subscription_invoice,
    list_paid_subscription_plans,
)
from src.application.subscription_tier_use_cases import (
    get_subscription_constructor_catalog,
    get_subscription_tier_catalog,
    get_trainer_subscription_status,
    list_subscription_tier_pricing_for_admin,
    normalize_modules_dict,
    set_subscription_after_mock_payment,
    set_subscription_constructor_after_mock_payment,
    trainer_allows_online_booking,
    trainer_has_analytics_access,
    trainer_has_crm_access,
    update_subscription_tier_pricing,
)
from src.application.lifecycle_use_cases import (
    LifecycleSnapshot,
    LifecycleStage,
    resolve_lifecycle_snapshot,
)
from src.application.demand_signals_use_cases import (
    RECAP_WINDOW_14D,
    SignalsRecap,
    get_signals_recap,
    get_signals_since,
)
from src.infrastructure.db import async_session_factory
from src.infrastructure.db.models import SUBSCRIPTION_TIERS, TRAINER_STATUS_ACTIVE
from src.shared.webapp_http_messages import (
    TRAINER_WEBAPP_FORBIDDEN_DETAIL,
    WEBAPP_DETAIL_SUBSCRIPTION_ANALYTICS_REQUIRED,
    WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED,
)
from src.billing.payment_gateway import create_checkout
from src.application.arena_schedule_preset import (
    get_schedule_grid_preset_for_trainer,
    get_schedule_grid_preset_for_trainer_arena,
    schedule_grid_preset_to_api,
)
from src.application.trainer_schedule_use_cases import (
    delete_slot as schedule_delete_slot,
    get_slot,
    list_slots,
    list_templates,
    replace_slots_for_day,
    replace_templates_for_day,
    replace_week_with_template,
    trainer_offers_service,
)
from src.application.recurring_use_cases import apply_recurring_bookings_for_week
from src.application.welcome_link_use_cases import WELCOME_TOKEN_TYPE_CLIENT_BIND, create_welcome_link_token
from src.application.trainer_invite_links import build_trainer_invite_links, build_trainer_share_link
from src.application.client_share_message import (
    compose_client_share_message,
    share_body_for_native_share_dialog,
)
from src.application.trainer_fill_slots_invite_send import send_trainer_fill_slots_invites
from src.application.client_notes_use_cases import (
    get_trainer_client_note,
    upsert_trainer_client_note,
)
from src.bot.schedule_notifications import run_after_schedule_changed
from src.application.trainer_onboarding_checklist import get_trainer_onboarding_checklist
from src.application.trainer_use_cases import (
    get_trainer,
    get_trainer_moderation_readiness,
    try_submit_trainer_for_moderation_review,
)
from src.bot import messages as msg
from src.bot.share_catalog_tip import send_trainer_share_catalog_tip_to_chat
from src.bot.trainer_cancel_client_notify import send_trainer_cancel_notification_for_booking_now
from src.shared.config import Settings
from src.shared.map_links import build_yandex_by_map_url
from src.shared.notification_hours import NOTIFICATION_TZ, working_hours_between
from src.shared.telegram_webapp import InitDataAuthError, parse_user_json_from_init_data
from src.shared.ttl_cache import get_slots_cached, invalidate_slots_for_trainer, set_slots_cached

from src.api.miniapp_auth import (
    MiniAppPlatform,
    MiniAppPrincipal,
    MiniappCredentialIn,
    client_catalog_telegram_key,
    get_admin_miniapp_principal,
    get_client_miniapp_principal,
    get_trainer_miniapp_principal,
    miniapp_credential_http_exception,
    reject_unsupported_miniapp_platform,
    require_miniapp_credential_in,
    trainer_legacy_telegram_id_for_storage,
    verify_vk_miniapp_launch_principal,
)
from src.api.miniapp_auth.telegram import verify_telegram_init_data_principal
from src.api.miniapp_auth.vk_launch_params import vk_launch_display_user_fields
from src.api.routes.webapp_init_data import (
    strip_client_name_field as _strip_client_name_field,
)
from src.application.client_trainer_primary_graph import (
    compute_primary_edge_meta as _compute_primary_edge_meta,
    hub_booking_primary_ids as _hub_booking_primary_ids,
    resolve_primary_catalog_service_id as _resolve_primary_catalog_service_id,
)
from src.api.routes.webapp_client_payloads import (
    CLIENT_DAYS,
    client_bookings_days_payload as _client_bookings_days_payload,
    client_requests_list_payload as _client_requests_list_payload,
    serialize_client_request as _serialize_client_request,
)

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

router = APIRouter(prefix="/api/webapp", tags=["webapp"])


def _trainer_bot_notify_telegram_id(principal: MiniAppPrincipal) -> int | None:
    """Trainer-bot Telegram chat id; no push target when Mini App host is not Telegram."""
    if principal.platform == MiniAppPlatform.TELEGRAM:
        return int(principal.user_id)
    return None


async def _ensure_client_for_webapp_miniapp(
    session: AsyncSession,
    principal: MiniAppPrincipal,
    raw_credential: str,
    *,
    phone: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> int:
    """
    Mini App: client row must have first_name (last_name optional).
    If profile already has first_name, only phone is updated when provided.
    Otherwise first_name is taken from body or host user payload (Telegram initData / VK launch).
    """
    catalog_tid = client_catalog_telegram_key(principal)
    vk_uid = int(principal.user_id) if principal.platform == MiniAppPlatform.MAX else None

    profile = await get_client_profile_basic(session, catalog_tid)
    if principal.platform == MiniAppPlatform.TELEGRAM:
        tg_user = parse_user_json_from_init_data(raw_credential) or {}
    else:
        q = dict(parse_qsl(raw_credential.lstrip("?"), keep_blank_values=True))
        tg_user = vk_launch_display_user_fields(q)
    body_f = _strip_client_name_field(first_name)
    body_l = _strip_client_name_field(last_name)
    _tgf = tg_user.get("first_name")
    _tgl = tg_user.get("last_name")
    tg_first = _strip_client_name_field(str(_tgf).strip() if _tgf is not None else None)
    tg_last = _strip_client_name_field(str(_tgl).strip() if _tgl is not None else None)
    has_saved_name = bool(profile and (profile.get("first_name") or "").strip())

    if has_saved_name:
        return await get_or_create_client(session, catalog_tid, vk_user_id=vk_uid, phone=phone)

    resolved_first = body_f or tg_first
    resolved_last = body_l if body_l is not None else tg_last
    if not resolved_first:
        raise HTTPException(
            status_code=400,
            detail="Укажите имя",
            headers={"X-Error-Code": "CLIENT_NAME_REQUIRED"},
        )
    return await get_or_create_client(
        session,
        catalog_tid,
        vk_user_id=vk_uid,
        phone=phone,
        first_name=resolved_first,
        last_name=resolved_last,
    )


# --- Trainer bookings Mini App (initData validated with trainer bot token) ---

TRAINER_DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
BOOKING_ADD_NOTE_PREFIX = "booking_add_note:"
BOOKING_INVITE_CLIENT_PREFIX = "booking_invite_client:"


def _format_time_hhmm(t) -> str:
    if hasattr(t, "strftime"):
        return t.strftime("%H:%M")
    s = str(t or "").strip()
    return s[:5] if len(s) >= 5 else (s or "—")


async def _send_trainer_post_booking_feedback(
    *,
    session: AsyncSession,
    trainer_id: int,
    trainer_telegram_id: int | None,
    booking_id: int,
    client_id: int,
    slot_date,
    start_time,
    first_booking_milestone: bool = False,
    share_catalog_tip: bool = False,
    is_sandbox: bool = False,
) -> None:
    """Best-effort trainer post-action push after trainer-created booking from Mini App."""
    if trainer_telegram_id is None:
        return
    client_card = await get_trainer_client_for_card(session, trainer_id, client_id)
    first_name = (client_card or {}).get("first_name") or ""
    last_name = (client_card or {}).get("last_name") or ""
    client_name = f"{first_name} {last_name}".strip() or "Клиент"
    client_tg_id_raw = (client_card or {}).get("telegram_id")
    client_tg_id = int(client_tg_id_raw) if client_tg_id_raw else None

    date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
    day_str = TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
    time_str = _format_time_hhmm(start_time)

    trainer_bot = Bot(
        token=Settings().telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    settings_push = Settings()
    try:
        if first_booking_milestone:
            info_for_card = await get_booking_milestone_display_for_trainer(session, booking_id, trainer_id)
            if info_for_card:
                card_html = msg.format_trainer_first_booking_milestone_from_booking_row(info_for_card)
            else:
                card_html = (
                    "🎉 <b>Старт засчитан: это ваша первая запись в Ice Pro!</b>\n\n"
                    + msg.TRAINER_FIRST_BOOKING_MILESTONE_FOOTER_HTML
                )
            has_crm_push = await trainer_has_crm_access(session, trainer_id)
            milestone_kb = msg.build_trainer_first_booking_milestone_reply_markup(
                webapp_base=settings_push.webapp_base_url or "",
                booking_id=booking_id,
                client_id=client_id,
                client_telegram_id=client_tg_id,
                trainer_has_crm=has_crm_push,
                is_sandbox=is_sandbox,
            )
            await trainer_bot.send_message(
                chat_id=trainer_telegram_id,
                text=card_html,
                reply_markup=milestone_kb,
            )
        else:
            # Sandbox copy: replace Telegram-attached / not-attached lines with a calm preview note,
            # so the trainer doesn't see «не привязан Telegram» for a phantom identity. The
            # ``Пригласить в бот`` button is also dropped — there's no one to invite.
            if is_sandbox:
                reminder_plan = "не отправляются — это пример"
                client_confirmation = "не отправляется — это пример"
            else:
                reminder_plan = await format_trainer_reminder_plan_for_client_day(
                    session,
                    client_id=client_id,
                    slot_date=slot_date,
                    client_has_telegram=bool(client_tg_id),
                )
                client_confirmation = "не применимо: у клиента не привязан Telegram"
                if client_tg_id:
                    client_confirmation = msg.TRAINER_CREATE_BOOKING_CLIENT_CONFIRMATION_QUEUED
            keyboard_rows: list[list[InlineKeyboardButton]] = [
                [
                    InlineKeyboardButton(
                        text=msg.TRAINER_BUTTON_ADD_BOOKING_NOTE,
                        callback_data=f"{BOOKING_ADD_NOTE_PREFIX}{booking_id}",
                    )
                ]
            ]
            if not client_tg_id and not is_sandbox:
                keyboard_rows.append(
                    [
                        InlineKeyboardButton(
                            text=msg.TRAINER_BUTTON_INVITE_CLIENT_TO_BOT,
                            callback_data=f"{BOOKING_INVITE_CLIENT_PREFIX}{booking_id}",
                        )
                    ]
                )
            done_text = msg.TRAINER_CREATE_BOOKING_DONE.format(
                client_name=html.escape(client_name),
                date=date_str,
                day=day_str,
                time=time_str,
                reminder_plan=html.escape(reminder_plan),
                client_confirmation=html.escape(client_confirmation),
            )
            if is_sandbox:
                done_text += msg.TRAINER_CREATE_BOOKING_SANDBOX_CANCEL_HINT
            await trainer_bot.send_message(
                chat_id=trainer_telegram_id,
                text=done_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
            )
        if share_catalog_tip:
            await send_trainer_share_catalog_tip_to_chat(
                bot=trainer_bot,
                chat_id=trainer_telegram_id,
                trainer_id=trainer_id,
            )
    except Exception as e:
        logger.warning(
            "MiniApp trainer booking: failed trainer post-action push (booking_id=%s trainer_tg_id=%s): %s",
            booking_id,
            trainer_telegram_id,
            e,
        )
    finally:
        await trainer_bot.session.close()


@router.get("/trainer/access")
async def get_trainer_access_for_webapp(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Single source of truth for Mini App onboarding: linked trainer may be non-active.
    Use this before feature APIs that require status=active (schedule, requests, CRM, etc.).
    """
    state, trainer = await get_trainer_access_state_from_principal(session, principal)
    tid = int(trainer["id"]) if trainer and trainer.get("id") is not None else None
    if tid is not None:
        await ensure_trainer_welcome_trial(session, tid)
    norm_status = normalize_trainer_status_value(trainer.get("status") if trainer else None)
    # Belt-and-suspenders: state machine + raw status (drivers may have returned non-str before normalize in repo).
    is_active = (state == TrainerAccessState.ACTIVE) or (norm_status == TRAINER_STATUS_ACTIVE)
    schedule_unlocked = state in (TrainerAccessState.ACTIVE, TrainerAccessState.BOOKING_READY)
    return {
        "access_state": state.value,
        "trainer_id": tid,
        "trainer_status": norm_status,
        "is_active": is_active,
        "schedule_unlocked": schedule_unlocked,
        "force_client_chat_relay": bool(Settings().trainer_webapp_force_client_chat_relay),
    }


@router.get("/schedule")
async def get_schedule(
    from_date: date | None = Query(None, description="YYYY-MM-DD"),
    to_date: date | None = Query(None, description="YYYY-MM-DD"),
    arena_id: int | None = Query(
        None,
        description="When set, schedule_grid matches this trainer-linked arena (quick book / multi-venue).",
    ),
    view: Literal["list"] | None = Query(
        None,
        description="view=list: slots only (compact JSON for read-only schedule screen; omits schedule_grid).",
    ),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Return trainer's slots for date range. Requires Telegram Web App initData
    in header X-Telegram-Init-Data or in query param init_data (proxy-safe).
    """
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)

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
        cap = max(1, int(s.get("capacity") or 1))
        occ = int(s.get("active_bookings") or 0)
        spots_left = max(0, cap - occ)
        svc_lbl = (s.get("service_name") or "").strip() or None
        ar_lbl = (s.get("arena_name") or "").strip() or None
        row = {
            "id": s["id"],
            "slot_date": s["slot_date"].isoformat() if hasattr(s["slot_date"], "isoformat") else str(s["slot_date"]),
            "start_time": s["start_time"].strftime("%H:%M") if hasattr(s["start_time"], "strftime") else str(s["start_time"])[:5],
            "end_time": s["end_time"].strftime("%H:%M") if hasattr(s["end_time"], "strftime") else str(s["end_time"])[:5],
            "status": st,
            "capacity": cap,
            "service_id": s.get("service_id"),
            "arena_id": s.get("arena_id"),
            "service_label": svc_lbl,
            "arena_label": ar_lbl,
            "training_group_id": s.get("training_group_id"),
            "training_group_name": s.get("training_group_name"),
            "active_bookings": occ,
            "spots_left": spots_left,
        }
        bsum = summaries.get(s["id"])
        if bsum:
            row["booking_id"] = bsum["booking_id"]
            row["booking_status"] = bsum["status"]
            row["venue_label"] = bsum["venue_label"]
            row["client_preview"] = bsum["client_preview"]
            if int(bsum.get("booking_count") or 1) > 1:
                row["booking_count"] = int(bsum["booking_count"])
            if bsum.get("bookings") is not None:
                row["bookings"] = bsum["bookings"]
            if bool(bsum.get("has_sandbox_booking")):
                row["has_sandbox_booking"] = True
            cid = bsum.get("client_id")
            if cid is not None:
                row["client_id"] = int(cid)
            ctid = bsum.get("client_telegram_id")
            if ctid is not None:
                row["client_telegram_id"] = int(ctid)
            cun = (bsum.get("client_telegram_username") or "").strip()
            if cun:
                row["client_telegram_username"] = cun
            cph = (bsum.get("client_phone") or "").strip()
            if cph:
                row["client_phone"] = cph
        # Slot row often has no service_name; mini-cards need catalog label from the booking's service.
        if not row.get("service_label") and bsum:
            bsvc = (bsum.get("services_str") or "").strip()
            if bsvc:
                row["service_label"] = bsvc
        # Individual slots often have NULL service on the slot row; accent + labels need the booking's catalog id.
        if row.get("service_id") is None and bsum and bsum.get("booking_service_id") is not None:
            row["service_id"] = int(bsum["booking_service_id"])
        out_slots.append(row)
    # Same as hub bookings list: getChat backfill when DB lacks telegram_username → DM vs relay matches «Ближайшие записи».
    _sched_dm_enrich = [
        r
        for r in out_slots
        if r.get("client_telegram_id") is not None
        and not str(r.get("client_telegram_username") or "").strip()
    ]
    if _sched_dm_enrich:
        await enrich_booking_dicts_with_client_telegram_usernames(session, _sched_dm_enrich)
    if view == "list":
        return {"trainer_id": trainer_id, "slots": out_slots}

    trainer_row = await get_trainer(session, trainer_id)
    group_classes_enabled = bool(
        (trainer_row.get("profile") or {}).get("group_classes_enabled")
    )
    profile = trainer_row.get("profile") or {}
    session_duration_minutes = profile.get("session_duration_minutes")
    if arena_id is not None:
        try:
            grid_preset = await get_schedule_grid_preset_for_trainer_arena(session, trainer_id, int(arena_id))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    else:
        grid_preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
    return {
        "trainer_id": trainer_id,
        "slots": out_slots,
        "group_classes_enabled": group_classes_enabled,
        "session_duration_minutes": session_duration_minutes,
        "schedule_grid": schedule_grid_preset_to_api(grid_preset),
    }


# --- Schedule editor Mini App (trainer): templates, slots, apply week, delete slot ---

@router.get("/schedule/templates")
async def get_schedule_templates(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """List weekly template entries (day_of_week, start_time, duration). Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    templates = await list_templates(session, trainer_id)
    grid_preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
    return {
        "templates": [
            {
                "id": t["id"],
                "day_of_week": t["day_of_week"],
                "start_time": t["start_time"].strftime("%H:%M") if hasattr(t["start_time"], "strftime") else str(t["start_time"])[:5],
                "duration_minutes": t["duration_minutes"],
                "capacity": int(t.get("capacity") or 1),
                "service_id": t.get("service_id"),
                "arena_id": t.get("arena_id"),
            }
            for t in templates
        ],
        "schedule_grid": schedule_grid_preset_to_api(grid_preset),
    }


class ScheduleTemplateSlotBody(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    capacity: int = Field(default=1, ge=1, le=500)
    service_id: int | None = Field(default=None, description="Required when capacity > 1 (group slot for this service)")
    duration_minutes: int | None = Field(
        default=None,
        ge=15,
        le=480,
        description="Optional per-slot duration; omit to use top-level duration_minutes for this row.",
    )
    arena_id: int | None = Field(
        default=None,
        description="For capacity == 1 only: venue for this template row; omit → default arena when generating slots.",
    )


class ScheduleTemplateDayBody(BaseModel):
    day_of_week: int  # 0=Mon .. 6=Sun
    duration_minutes: int = Field(default=45, ge=15, le=480)
    start_hours: list[int] | None = None  # legacy: all capacity 1, :00 only
    slots: list[ScheduleTemplateSlotBody] | None = None  # preferred: per-slot capacity + minute
    group_arena_id: int | None = Field(
        default=None,
        description="Venue for all group template rows (capacity>1); required when trainer has multiple arenas",
    )

    @model_validator(mode="after")
    def _normalize_slots(self):
        if self.slots is not None:
            return self
        self.slots = [ScheduleTemplateSlotBody(hour=h, minute=0, capacity=1) for h in (self.start_hours or [])]
        return self


@router.put("/schedule/templates/day")
async def put_schedule_templates_day(
    body: ScheduleTemplateDayBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Set template for one week day: replace template rows for that weekday (per-hour capacity). Auth: trainer."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    # Require CRM tier to edit templates
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED)
    if body.day_of_week < 0 or body.day_of_week > 6:
        raise HTTPException(status_code=400, detail="day_of_week must be 0-6")
    slots = body.slots or []
    trainer_row = await get_trainer(session, trainer_id) or {}
    group_classes_enabled = bool((trainer_row.get("profile") or {}).get("group_classes_enabled"))
    if any((x.capacity or 1) > 1 for x in slots) and not group_classes_enabled:
        raise HTTPException(
            status_code=400,
            detail="Включите «Групповые занятия» в профиле, чтобы задавать групповые слоты в шаблоне.",
        )
    r_arena_n = await session.execute(
        text("SELECT COUNT(*) FROM trainer_arenas WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    arena_n = int(r_arena_n.scalar() or 0)
    has_group = any((x.capacity or 1) > 1 for x in slots)
    if has_group and arena_n == 0:
        raise HTTPException(
            status_code=400,
            detail="Добавьте хотя бы одну площадку в профиле, чтобы задавать групповые слоты в шаблоне.",
        )
    if has_group and arena_n > 1:
        if body.group_arena_id is None:
            raise HTTPException(
                status_code=400,
                detail="Выберите площадку для групповых слотов в шаблоне.",
            )
        rchk = await session.execute(
            text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
            {"tid": trainer_id, "aid": int(body.group_arena_id)},
        )
        if not rchk.fetchone():
            raise HTTPException(status_code=400, detail="Площадка не привязана к вашему профилю")

    minute_to_cap: dict[int, int] = {}
    minute_to_service: dict[int, int | None] = {}
    minute_to_duration: dict[int, int] = {}
    minute_to_row_arena: dict[int, int] = {}
    for s in slots:
        sm = s.hour * 60 + s.minute
        if sm in minute_to_cap:
            raise HTTPException(status_code=400, detail="Повторяется время начала слота в шаблоне.")
        minute_to_cap[sm] = s.capacity
        row_dur = int(s.duration_minutes) if s.duration_minutes is not None else int(body.duration_minutes)
        minute_to_duration[sm] = row_dur
        if s.capacity > 1:
            if s.arena_id is not None:
                raise HTTPException(
                    status_code=400,
                    detail="Для групповых слотов в шаблоне указывайте площадку через «Площадка для группы», а не через поле слота.",
                )
            if s.service_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="Укажите услугу для групповых слотов в шаблоне.",
                )
            if not await trainer_offers_service(session, trainer_id, int(s.service_id)):
                raise HTTPException(status_code=400, detail="Услуга не найдена в вашем списке.")
            minute_to_service[sm] = int(s.service_id)
        else:
            minute_to_service[sm] = None
            if s.arena_id is not None:
                aid_cell = int(s.arena_id)
                r_own = await session.execute(
                    text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
                    {"tid": trainer_id, "aid": aid_cell},
                )
                if not r_own.fetchone():
                    raise HTTPException(status_code=400, detail="Площадка не привязана к вашему профилю")
                minute_to_row_arena[sm] = aid_cell
    try:
        await replace_templates_for_day(
            session,
            trainer_id,
            body.day_of_week,
            minute_to_cap,
            body.duration_minutes,
            minute_to_service,
            group_arena_id=int(body.group_arena_id) if body.group_arena_id is not None else None,
            minute_to_duration=minute_to_duration,
            minute_to_arena_id=minute_to_row_arena if minute_to_row_arena else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


def _hhmm_strings_to_minutes(values: list[str]) -> set[int]:
    """Parse HH:MM strings into minutes from midnight."""
    out: set[int] = set()
    for raw in values:
        s = raw.strip()
        parts = s.split(":")
        if len(parts) != 2:
            raise ValueError("Неверный формат времени (нужно ЧЧ:ММ).")
        h, m = int(parts[0]), int(parts[1])
        if h < 0 or h > 23 or m < 0 or m > 59:
            raise ValueError("Время вне допустимого диапазона.")
        out.add(h * 60 + m)
    return out


class SlotEntryBody(BaseModel):
    """Single slot row: start time + duration; optional venue when capacity=1 (mixed grid + precise)."""

    start_time: str = Field(..., description="HH:MM start of the slot")
    duration_minutes: int = Field(ge=15, le=480)
    arena_id: int | None = Field(
        default=None,
        description="When capacity=1, optional venue for this start; omitted → trainer default slot arena",
    )


class ScheduleSlotsDayBody(BaseModel):
    slot_date: str  # YYYY-MM-DD
    start_hours: list[int] | None = None  # legacy: whole hours only
    start_times: list[str] | None = None  # preferred: "HH:MM" starts, uniform duration
    duration_minutes: int = Field(default=45, ge=15, le=480)
    capacity: int = Field(default=1, ge=1, le=500)
    group_service_id: int | None = Field(default=None, description="services.id for group slots (capacity > 1)")
    arena_id: int | None = Field(
        default=None,
        description="Venue for new group slots (capacity > 1), or uniform venue for slot_entries without per-entry arena_id",
    )
    # Per-slot pairs: each entry carries its own duration and bypasses arena grid alignment check.
    slot_entries: list[SlotEntryBody] | None = Field(default=None)

    @model_validator(mode="after")
    def _one_time_source(self):
        sources = sum([
            self.start_times is not None,
            self.start_hours is not None,
            self.slot_entries is not None,
        ])
        if sources > 1:
            raise ValueError("Укажите только один способ: start_times, start_hours или slot_entries.")
        return self


@router.post("/schedule/slots")
async def post_schedule_slots(
    body: ScheduleSlotsDayBody,
    background_tasks: BackgroundTasks,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Set slots for one calendar day: replace available slots. Auth: trainer."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    # Require CRM tier to create/update slots
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED)
    if body.capacity > 1:
        trainer_row = await get_trainer(session, trainer_id) or {}
        if not bool((trainer_row.get("profile") or {}).get("group_classes_enabled")):
            raise HTTPException(
                status_code=400,
                detail="Включите «Групповые занятия» в профиле, чтобы создавать групповые слоты в календаре.",
            )
        if body.group_service_id is None:
            raise HTTPException(
                status_code=400,
                detail="Для группового слота укажите услугу.",
            )
        if not await trainer_offers_service(session, trainer_id, int(body.group_service_id)):
            raise HTTPException(status_code=400, detail="Услуга не в вашем списке")
        if body.arena_id is not None:
            rchk = await session.execute(
                text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
                {"tid": trainer_id, "aid": int(body.arena_id)},
            )
            if not rchk.fetchone():
                raise HTTPException(status_code=400, detail="Площадка не привязана к вашему профилю")
    try:
        slot_date = date.fromisoformat(body.slot_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slot_date")

    arena_arg = int(body.arena_id) if body.capacity > 1 and body.arena_id is not None else None

    if body.slot_entries is not None:
        # Per-slot precise mode: each entry carries its own start + duration, no grid validation.
        per_slot: dict[int, int] = {}
        per_slot_arena: dict[int, int] = {}
        for entry in body.slot_entries:
            try:
                m_set = _hhmm_strings_to_minutes([entry.start_time])
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            start_m = next(iter(m_set))
            per_slot[start_m] = entry.duration_minutes
            if entry.arena_id is not None:
                if body.capacity != 1:
                    raise HTTPException(
                        status_code=400,
                        detail="Площадку на уровне одного слота можно задать только для индивидуальных слотов.",
                    )
                aid_ent = int(entry.arena_id)
                rchk_ent = await session.execute(
                    text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
                    {"tid": trainer_id, "aid": aid_ent},
                )
                if not rchk_ent.fetchone():
                    raise HTTPException(status_code=400, detail="Площадка не привязана к вашему профилю")
                per_slot_arena[start_m] = aid_ent
        try:
            await replace_slots_for_day(
                session,
                trainer_id,
                slot_date,
                set(per_slot.keys()),
                duration_minutes=45,  # unused — per_slot_duration overrides
                capacity=body.capacity,
                group_service_id=body.group_service_id,
                slot_arena_id=arena_arg,
                per_slot_duration=per_slot,
                per_slot_arena_id=per_slot_arena if per_slot_arena else None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if per_slot:
            background_tasks.add_task(_bg_notify_slot_waitlist, trainer_id)
        invalidate_slots_for_trainer(trainer_id)
        return {"ok": True, "trainer_id": trainer_id}

    if body.start_times is not None:
        try:
            minutes_set = _hhmm_strings_to_minutes(body.start_times)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    elif body.start_hours is not None:
        minutes_set = {h * 60 for h in body.start_hours if 0 <= h <= 23}
    else:
        minutes_set = set()
    try:
        await replace_slots_for_day(
            session,
            trainer_id,
            slot_date,
            minutes_set,
            body.duration_minutes,
            capacity=body.capacity,
            group_service_id=body.group_service_id,
            slot_arena_id=arena_arg,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Notify waitlisted clients in background after slots are committed
    if minutes_set:
        background_tasks.add_task(_bg_notify_slot_waitlist, trainer_id)

    # Mini app: schedule-editor clears hub rhythm dismiss + sets fill-slots boost (per-trainer storage).
    invalidate_slots_for_trainer(trainer_id)
    return {"ok": True, "trainer_id": trainer_id}


class ScheduleApplyWeekBody(BaseModel):
    week_start: str  # YYYY-MM-DD (Monday)


@router.post("/schedule/apply-week")
async def post_schedule_apply_week(
    body: ScheduleApplyWeekBody,
    background_tasks: BackgroundTasks,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Replace one week with template (free slots only); then apply recurring. Auth: trainer."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    # Require CRM tier to apply template and recurring bookings
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED)
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
    if count:
        background_tasks.add_task(_bg_notify_slot_waitlist, trainer_id)
    return {"ok": True, "slots_created": count, "trainer_id": trainer_id}


@router.delete("/schedule/slots/{slot_id:int}")
async def delete_schedule_slot(
    slot_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Delete one applied slot (available only). Auth: trainer."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED)
    deleted = await schedule_delete_slot(session, trainer_id, slot_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Slot not found or booked")
    return {"ok": True}


def _client_slots_arena_ids_query_param(raw: str | None) -> frozenset[int] | None:
    """Comma-separated positive arena IDs (OR semantics). Blank or invalid tokens ⇒ no filter."""
    if raw is None or not str(raw).strip():
        return None
    out: list[int] = []
    for part in str(raw).replace(" ", "").split(","):
        if not part or not part.isdigit():
            continue
        v = int(part)
        if v > 0:
            out.append(v)
    return frozenset(out) if out else None


def _filter_client_slots_payload_by_arenas(rows: list[dict], arena_ids: frozenset[int] | None) -> list[dict]:
    """Post-filter serialized slot rows without burning a cache entry per arena combination."""
    if not arena_ids:
        return rows
    filtered: list[dict] = []
    for row in rows:
        aid = row.get("arena_id")
        if aid is None:
            continue
        try:
            if int(aid) in arena_ids:
                filtered.append(row)
        except (TypeError, ValueError):
            continue
    return filtered


def _client_catalog_slot_map_link(s: dict) -> str | None:
    """Map link for client booking UI: prefer coordinates, else Yandex search by venue line."""
    name = (s.get("arena_name") or "").strip()
    addr = (s.get("arena_address") or "").strip()
    city = (s.get("arena_city_name") or "").strip()
    parts = [p for p in (name, addr, city) if p]
    text = ", ".join(parts) if parts else None
    return build_yandex_by_map_url(
        {
            "latitude": s.get("arena_latitude"),
            "longitude": s.get("arena_longitude"),
            "address": text,
        }
    )


@router.get("/client/slots")
async def get_client_slots(
    trainer_id: int = Query(..., description="Trainer to book"),
    min_hours: int | None = Query(None, description="From list/card; skip get_trainer when set"),
    trainer_name: str | None = Query(None, description="From list/card; skip get_trainer when set"),
    service_id: int | None = Query(
        None,
        description="Catalog/service context: show individual slots + group slots for this service only",
    ),
    arena_ids: str | None = Query(
        None,
        description="Comma-separated arena IDs (OR); filters serialized slots",
    ),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """
    Available slots for a trainer (client view). Pass min_hours and trainer_name from
    catalog when opening card to avoid extra get_trainer round-trip.
    Pass service_id from catalog filter so group slots are scoped to that service.
    arena_ids restricts the response to slots on those venues (NULL slot venues resolve
    to the trainer schedule default arena for filtering and JSON).
    Without service_id, only individual (capacity 1) slots are returned — unless the
    client's bot session already pins the same trainer and a service (welcome link,
    book button without query param): then group slots for that service are included.
    """
    client_telegram_id = client_catalog_telegram_key(principal)
    arena_filter = _client_slots_arena_ids_query_param(arena_ids)

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

    filter_service_id = int(service_id) if service_id is not None else None
    if filter_service_id is None:
        sess_row = await read_client_bot_session(client_telegram_id, session)
        sess_tid = sess_row.get("selected_trainer_id") if sess_row else None
        sess_sid = sess_row.get("selected_service_id") if sess_row else None
        if (
            sess_tid is not None
            and sess_sid is not None
            and int(sess_tid) == int(trainer_id)
        ):
            filter_service_id = int(sess_sid)

    cached_slots = get_slots_cached(trainer_id, min_hours_val, filter_service_id)
    if cached_slots is not None:
        return {
            "trainer_name": trainer_name_val,
            "slots": _filter_client_slots_payload_by_arenas(cached_slots, arena_filter),
            "online_booking_available": True,
        }

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
    if filter_service_id is not None:
        # Individual slots (cap 1) are not tied to a service in the UI. Group slots use service_id;
        # capacity>1 with NULL service_id still counts as «open» and must not disappear when link pins a service.
        filtered: list[dict] = []
        for s in available:
            cap = max(1, int(s.get("capacity") or 1))
            sid = s.get("service_id")
            if cap == 1:
                filtered.append(s)
            elif sid is None or int(sid) == filter_service_id:
                filtered.append(s)
        available = filtered
    else:
        available = [s for s in available if max(1, int(s.get("capacity") or 1)) == 1]
    default_arena_for_slot = await trainer_default_slot_arena_id(session, trainer_id)
    serialized_full: list[dict] = []
    for s in available:
        an = (s.get("arena_name") or "").strip() or None
        aa = (s.get("arena_address") or "").strip() or None
        acn = (s.get("arena_city_name") or "").strip() or None
        raw_slot_arena = s.get("arena_id")
        eff_slot_arena = (
            int(raw_slot_arena) if raw_slot_arena is not None else default_arena_for_slot
        )
        serialized_full.append(
            {
                "id": s["id"],
                "slot_date": s["slot_date"].isoformat()
                if hasattr(s["slot_date"], "isoformat")
                else str(s["slot_date"]),
                "start_time": s["start_time"].strftime("%H:%M")
                if hasattr(s["start_time"], "strftime")
                else str(s["start_time"])[:5],
                "end_time": s["end_time"].strftime("%H:%M")
                if hasattr(s["end_time"], "strftime")
                else str(s["end_time"])[:5],
                "capacity": max(1, int(s.get("capacity") or 1)),
                "spots_left": max(
                    0,
                    max(1, int(s.get("capacity") or 1)) - int(s.get("active_bookings") or 0),
                ),
                "service_id": s.get("service_id"),
                "arena_id": eff_slot_arena,
                "arena_name": an,
                "arena_address": aa,
                "arena_city_name": acn,
                "map_link": _client_catalog_slot_map_link(s),
            }
        )
    set_slots_cached(trainer_id, min_hours_val, serialized_full, filter_service_id)
    return {
        "trainer_name": trainer_name_val,
        "slots": _filter_client_slots_payload_by_arenas(serialized_full, arena_filter),
        "online_booking_available": True,
    }


def _this_week_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


class ClientBookingBody(BaseModel):
    slot_id: int
    phone: str
    comment: str | None = None
    request_id: int | None = None  # when booking from "my request" flow, link and archive request
    service_id: int | None = None  # required when no request_id; when request_id set, taken from request
    service_price_variant_id: int | None = None  # required when trainer has multiple tiers for this service
    first_name: str | None = None  # required when client has no saved first_name (unless present in initData user)
    last_name: str | None = None


class FamilyAccessRevokeBody(BaseModel):
    member_telegram_id: int = Field(..., gt=0)


async def _client_booking_post_create_effects(
    booking_id: int,
    telegram_id: int,
    trainer_id: int,
    service_id: int,
) -> None:
    """
    Edge counters + reminder rows after the booking row is committed.
    Runs in BackgroundTasks so the HTTP client gets JSON quickly (reduces false «network error» when
    the connection drops after the DB work but before the response is fully delivered).
    """
    try:
        from src.infrastructure.db.session import async_session_factory

        async with async_session_factory() as s:
            await record_booking_edge(
                telegram_id,
                trainer_id,
                completed=False,
                session=s,
                booking_service_id=service_id,
            )
            await sync_session_catalog_after_client_booking(
                telegram_id, trainer_id, service_id, s
            )
            await generate_reminders_for_booking(s, booking_id)
    except Exception:
        logger.exception(
            "client booking post-create effects failed booking_id=%s trainer_id=%s",
            booking_id,
            trainer_id,
        )


@router.post("/client/booking")
async def post_client_booking(
    body: ClientBookingBody,
    background_tasks: BackgroundTasks,
    cred: MiniappCredentialIn = Depends(require_miniapp_credential_in),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """
    Create booking from client Mini App. Auth: client bot initData.
    
    Requires trainer to have tier >= 'online' for self-booking.
    Phone required. service_id required (or from request).
    Optional ``Idempotency-Key``: repeat submits within 24h return the same JSON (slot already taken
    is avoided when the first request succeeded but the client did not receive the body).
    """
    telegram_id = client_catalog_telegram_key(principal)
    raw = cred.raw
    ik = (idempotency_key or "").strip()
    idem_cache_key = (f"bkc{telegram_id}_{ik}"[:64]) if ik else ""
    if idem_cache_key:
        cached = await get_idempotency_response(session, idem_cache_key)
        if isinstance(cached, dict) and cached.get("success") is True:
            return cached

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

    r_ts_offers = await session.execute(
        text("SELECT 1 FROM trainer_services WHERE trainer_id = :tid AND service_id = :sid"),
        {"tid": trainer_id, "sid": service_id},
    )
    if not r_ts_offers.fetchone():
        raise HTTPException(
            status_code=400,
            detail="Эта услуга недоступна у выбранного тренера. Откройте карточку тренера и выберите услугу снова.",
        )

    client_id = await _ensure_client_for_webapp_miniapp(
        session,
        principal,
        raw,
        phone=phone,
        first_name=body.first_name,
        last_name=body.last_name,
    )

    slot_cap = max(1, int(slot.get("capacity") or 1))
    arena_for_booking: int | None = None
    used_primary_despite_filter = False
    if client_request_id is None:
        if slot_cap > 1:
            # Group: venue is stored on the slot; catalog/session arena filter does not apply.
            arena_for_booking = None
            used_primary_despite_filter = False
        else:
            slot_arena_sa = slot.get("arena_id")
            if slot_arena_sa is not None:
                r_sa = await session.execute(
                    text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
                    {"tid": trainer_id, "aid": int(slot_arena_sa)},
                )
                if not r_sa.fetchone():
                    raise HTTPException(
                        status_code=400,
                        detail="Слот привязан к площадке, недоступной для этого тренера.",
                    )
                arena_for_booking = int(slot_arena_sa)
                sess_row = await get_client_session(telegram_id, session)
                sess_arena = sess_row.get("selected_arena_id") if sess_row else None
                primary_sa = await get_trainer_primary_arena_resolved(session, trainer_id)
                used_primary_despite_filter = bool(
                    sess_arena is not None
                    and primary_sa is not None
                    and int(sess_arena) != int(primary_sa)
                    and int(slot_arena_sa) == int(primary_sa)
                )
            else:
                sess_row = await get_client_session(telegram_id, session)
                sess_arena = sess_row.get("selected_arena_id") if sess_row else None
                resolved, err, used_primary_despite_filter = await resolve_arena_for_client_self_booking(
                    session, trainer_id, sess_arena
                )
                if err == "no_venue":
                    raise HTTPException(
                        status_code=400,
                        detail="У тренера не настроена основная площадка — запись через каталог недоступна.",
                    )
                if err == "invalid_arena":
                    raise HTTPException(status_code=400, detail="Выбранная арена недоступна для этого тренера.")
                arena_for_booking = resolved

    try:
        booking_id, _ = await create_booking(
            session,
            body.slot_id,
            trainer_id,
            client_id,
            service_id=service_id,
            client_comment=body.comment,
            client_request_id=client_request_id,
            created_by_trainer=False,
            arena_id=arena_for_booking,
            service_price_variant_id=body.service_price_variant_id,
            strict_service_price_variant=True,
        )
    except ServicePriceVariantRequired:
        raise HTTPException(
            status_code=400,
            detail="Выберите категорию цены (тариф) для этой услуги.",
        ) from None
    if not booking_id:
        raise HTTPException(status_code=400, detail="Slot not available")
    out: dict[str, object] = {"success": True, "booking_id": booking_id}
    if client_request_id is None and used_primary_despite_filter:
        out["used_primary_venue_for_online_booking"] = True
    if idem_cache_key:
        await set_idempotency_response(session, idem_cache_key, dict(out))
    background_tasks.add_task(
        _client_booking_post_create_effects,
        int(booking_id),
        int(telegram_id),
        int(trainer_id),
        int(service_id),
    )
    return out


@router.get("/client/session")
async def get_client_session_state(
    for_trainer_id: int | None = Query(None, description="When set, suggested_service_id_for_trainer uses this trainer."),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Return client session with resolved names (city, service, arena, trainer) for catalog UI. Auth: client initData."""
    telegram_id = client_catalog_telegram_key(principal)
    profile = await get_client_profile_basic(session, telegram_id)
    needs_profile_name = not bool(profile and (profile.get("first_name") or "").strip())
    row = await get_client_session(telegram_id, session)
    client_phone = await get_client_phone_for_webapp(session, telegram_id)
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
            # Catalog UI: session row may lack city while service/trainer were saved — infer from trainer profile.
            if not city_id:
                profile_city = p.get("city_id")
                if profile_city is not None:
                    city_id = int(profile_city)
                    for c in await list_cities(session):
                        if c.get("id") == city_id:
                            city_name = c.get("name") or ""
                            break

    cfn = (profile.get("first_name") or "").strip() if profile else ""
    cln = (profile.get("last_name") or "").strip() if profile else ""
    suggested_sid: int | None = None
    tid_for_suggest = for_trainer_id if for_trainer_id is not None else trainer_id
    tid_for_suggest_int: int | None = int(tid_for_suggest) if tid_for_suggest else None
    client_row_id: int | None = None
    if tid_for_suggest_int is not None:
        client_row_id = await get_client_id_by_telegram_id(session, telegram_id)
        if client_row_id is not None:
            suggested_sid = await get_trainer_client_latest_booking_service_id(
                session, tid_for_suggest_int, client_row_id
            )
    book_ctx_sid: int | None = None
    book_ctx_nm: str | None = None
    if for_trainer_id is not None:
        hint_ids: list[int | None] = []
        edge = await get_trainer_edge(telegram_id, int(for_trainer_id), session)
        if edge:
            hint_ids.append(edge.get("saved_catalog_service_id"))
            hint_ids.append(edge.get("last_booking_service_id"))
        hint_ids.append(suggested_sid)
        book_ctx_sid, book_ctx_nm = await resolve_client_catalog_service_for_trainer(
            session, int(for_trainer_id), row, *hint_ids
        )
    book_ctx_vid: int | None = None
    if (
        for_trainer_id is not None
        and book_ctx_sid is not None
        and client_row_id is not None
    ):
        book_ctx_vid = await get_trainer_client_last_booking_price_variant_for_service(
            session, int(for_trainer_id), client_row_id, int(book_ctx_sid)
        )
    # Repeat-booking UX: last row by created_at (same as trainer booking-defaults), independent of catalog hint merge.
    last_created_sid: int | None = None
    last_created_vid: int | None = None
    if tid_for_suggest_int is not None and client_row_id is not None:
        lc_sid, lc_vid, _, _ = await get_trainer_client_last_booking_service_defaults(
            session, tid_for_suggest_int, client_row_id
        )
        last_created_sid = lc_sid
        last_created_vid = lc_vid
    payload = {
        "city_id": city_id,
        "city_name": city_name,
        "service_id": service_id,
        "service_name": service_name,
        "arena_id": arena_id,
        "arena_name": arena_name or (None if arena_id is None else "—"),
        "trainer_id": trainer_id,
        "trainer_name": trainer_name,
        # Client must only apply suggested_service_id when viewing this trainer (avoids primary-trainer hint on another card).
        "suggested_service_for_trainer_id": tid_for_suggest_int,
        "suggested_service_id_for_trainer": suggested_sid,
        # Per-trainer booking/catalog choice when for_trainer_id was passed (see resolve_client_catalog_service_for_trainer).
        "booking_context_service_id": book_ctx_sid,
        "booking_context_service_name": book_ctx_nm,
        "booking_context_service_price_variant_id": book_ctx_vid,
        "last_created_booking_service_id": last_created_sid,
        "last_created_booking_service_price_variant_id": last_created_vid,
        "client_phone": client_phone,
        "needs_profile_name": needs_profile_name,
        "client_first_name": cfn or None,
        "client_last_name": cln or None,
    }
    return JSONResponse(
        content=payload,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


class ClientSessionBody(BaseModel):
    """Catalog selection: set all at once when user selects a trainer in Mini App."""
    city_id: int
    service_id: int
    arena_id: int | None = None
    trainer_id: int


@router.post("/client/session")
async def post_client_session(
    body: ClientSessionBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Save catalog choice (city, service, arena, trainer) so bot can show 'Выбран: X'. Auth: client initData."""
    telegram_id = client_catalog_telegram_key(principal)

    await save_catalog_filters(
        telegram_id,
        session,
        city_id=body.city_id,
        service_id=body.service_id,
        arena_id=body.arena_id,
        trainer_id=body.trainer_id,
    )
    return {"success": True}


class ClientCatalogFiltersBody(BaseModel):
    """Partial catalog filter persistence from summary screen (trainer optional)."""

    city_id: int | None = None
    service_id: int | None = None
    arena_id: int | None = None
    trainer_id: int | None = None


@router.patch("/client/session/catalog-filters")
async def patch_client_catalog_filters(
    body: ClientCatalogFiltersBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Save city/service/arena (and optionally trainer) without requiring a trainer card open."""
    telegram_id = client_catalog_telegram_key(principal)
    if (
        body.city_id is None
        and body.service_id is None
        and body.arena_id is None
        and body.trainer_id is None
    ):
        return {"success": True}
    await save_catalog_filters(
        telegram_id,
        session,
        city_id=body.city_id,
        service_id=body.service_id,
        arena_id=body.arena_id,
        trainer_id=body.trainer_id,
    )
    return {"success": True}


# ── Client ↔ trainer edges API: see webapp_client_trainer_edges.py (notify waitlist after slot create) ──

async def _bg_notify_slot_waitlist(trainer_id: int) -> None:
    """
    Background task: dispatch slot-availability notifications to subscribed clients.
    Creates its own DB session so the slot-creation transaction is already committed.
    """
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from src.infrastructure.db.session import async_session_factory

    settings = Settings()
    try:
        async with async_session_factory() as session:
            # Fetch trainer display name for the message
            r = await session.execute(
                text("""
                    SELECT COALESCE(TRIM(tp.first_name || ' ' || tp.last_name), 'Тренер')
                    FROM trainers t
                    LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
                    WHERE t.id = :tid
                """),
                {"tid": trainer_id},
            )
            row = r.fetchone()
            display_name = row[0].strip() if row else "Тренер"

            client_bot = Bot(
                token=settings.telegram_bot_token_client,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            online = await trainer_allows_online_booking(session, trainer_id)
            kb = msg.build_client_fill_slots_invite_keyboard(
                webapp_base_url=settings.webapp_base_url,
                trainer_id=trainer_id,
                online_booking=online,
                slot_id=None,
            )
            try:
                async def _send(tg_id: int, txt: str, markup=None) -> None:
                    await client_bot.send_message(chat_id=tg_id, text=txt, reply_markup=markup)

                await uc_notify_slot_waitlist(trainer_id, display_name, session, _send, kb)
            finally:
                await client_bot.session.close()
    except Exception:
        # Non-critical — slot creation already succeeded
        pass


async def _bg_notify_trainer_client_request_immediate(request_id: int) -> None:
    """
    Immediate trainer DM for a personalized client_request (pass order, certificate order, etc.).
    Avoids gaps when the batch notifier is delayed.
    """
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from src.bot.notification_loops import process_request_notifications_batch
    from src.infrastructure.db.session import async_session_factory

    settings = Settings()
    bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        async with async_session_factory() as session:
            await process_request_notifications_batch(
                bot,
                session,
                only_request_id=request_id,
                bypass_quiet_hours_for_that_request=True,
            )
    except Exception:
        logger.exception(
            "Background client_request trainer notify failed (request_id=%s)",
            request_id,
        )
    finally:
        await bot.session.close()


class ClientRequestCreateBody(BaseModel):
    """Create request from catalog Mini App: city, service, optional comment and trainer_id."""
    city_id: int
    service_id: int
    comment: str | None = None
    trainer_id: int | None = None
    first_name: str | None = None
    last_name: str | None = None


@router.post("/client/request")
async def post_client_request(
    body: ClientRequestCreateBody,
    cred: MiniappCredentialIn = Depends(require_miniapp_credential_in),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Create a client request (from catalog Mini App). Auth: client initData. Returns request_id so UI can show success before closing."""
    telegram_id = client_catalog_telegram_key(principal)
    client_id = await _ensure_client_for_webapp_miniapp(
        session,
        principal,
        cred.raw,
        phone=None,
        first_name=body.first_name,
        last_name=body.last_name,
    )
    comment = (body.comment or "").strip() or None
    request_id = await create_client_request(
        session, client_id, body.city_id, body.service_id, comment=comment, trainer_id=body.trainer_id
    )
    return {"success": True, "request_id": request_id}


@router.get("/client/requests")
async def get_client_requests(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """List my requests with responses. Auth: client bot initData."""
    telegram_id = client_catalog_telegram_key(principal)
    return await _client_requests_list_payload(session, telegram_id)


# --- Client pass products (buy) and my passes ---


@router.get("/client/pass-products")
async def get_client_pass_products(
    trainer_id: int = Query(..., description="Trainer whose products to list"),
    session: AsyncSession = Depends(get_session),
    _principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """List active pass products for a trainer (for purchase). Enriched with savings using covered service prices."""
    # Only trainers with online tier expose pass products in catalog (clients can book)
    if not await trainer_allows_online_booking(session, trainer_id):
        raise HTTPException(status_code=404, detail="Trainer not found")
    items = await list_pass_products(session, trainer_id, active_only=True)

    r = await session.execute(
        text("SELECT service_id, price_cents FROM trainer_services WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    price_by_service = {row[0]: row[1] for row in r.fetchall() if row[1] is not None}
    default_single = min(price_by_service.values()) if price_by_service else None
    if default_single is None and items:
        pass_rates = [
            p["price_cents"] // p["sessions_total"]
            for p in items
            if p.get("sessions_total") and p.get("price_cents")
        ]
        if pass_rates:
            default_single = max(pass_rates)
    enrich_pass_items_with_catalog_reference_prices(
        items,
        price_by_service=price_by_service,
        default_single_reference=default_single,
    )
    return {"items": items}


class ClientPassOrderRequestBody(BaseModel):
    pass_product_id: int = Field(..., ge=1)


@router.get("/client/pass-order/catalog")
async def get_client_pass_order_catalog_endpoint(
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Active pass products for the client's derived primary trainer (order-via-request UX)."""
    telegram_id = client_catalog_telegram_key(principal)
    return await get_primary_pass_order_catalog(session, telegram_id)


@router.post("/client/pass-order/request")
async def post_client_pass_order_request(
    background_tasks: BackgroundTasks,
    body: ClientPassOrderRequestBody,
    cred: MiniappCredentialIn = Depends(require_miniapp_credential_in),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """Create a personalized «purchase pass» client_request to the primary trainer."""
    telegram_id = client_catalog_telegram_key(principal)
    ik = (idempotency_key or "").strip()
    idem_cache_key = (f"pop{telegram_id}_{ik}"[:64]) if ik else ""
    if idem_cache_key:
        cached = await get_idempotency_response(session, idem_cache_key)
        if isinstance(cached, dict) and cached.get("success") is True:
            return cached

    client_id = await _ensure_client_for_webapp_miniapp(
        session,
        principal,
        cred.raw,
        phone=None,
        first_name=None,
        last_name=None,
    )
    result = await submit_pass_product_order_request(
        session,
        client_id=client_id,
        telegram_id=telegram_id,
        pass_product_id=body.pass_product_id,
    )
    if result.get("ok"):
        out: dict[str, object] = {"success": True, "request_id": result["request_id"]}
        if idem_cache_key:
            await set_idempotency_response(session, idem_cache_key, dict(out))
        background_tasks.add_task(
            _bg_notify_trainer_client_request_immediate, int(result["request_id"])
        )
        return out
    err = str(result.get("error") or "unknown")
    mapping: dict[str, tuple[int, str]] = {
        "no_primary_trainer": (
            400,
            "Нет основного тренера — запишитесь к тренеру или добавьте его в избранное.",
        ),
        "product_not_found": (404, "Этот абонемент недоступен."),
        "trainer_city_missing": (
            422,
            "У тренера не заполнен город в профиле. Напишите ему в Telegram.",
        ),
        "trainer_service_missing": (
            422,
            "У тренера не настроены услуги. Напишите ему напрямую.",
        ),
        "duplicate_pending": (
            409,
            "Заявка на этот абонемент уже отправлена. Дождитесь ответа тренера.",
        ),
        "daily_limit": (
            429,
            "Заявка уже отправлена ранее.",
        ),
        "client_mismatch": (403, "Не удалось подтвердить аккаунт."),
    }
    status_code, detail = mapping.get(err, (400, "Не удалось отправить заявку."))
    raise HTTPException(status_code=status_code, detail=detail)


class ClientCertOrderRequestBody(BaseModel):
    certificate_product_id: int = Field(..., ge=1)
    recipient_email: str = Field(..., min_length=3, max_length=320)
    recipient_name: str = Field(..., min_length=1, max_length=200)
    nominal_byn: float | None = Field(
        None,
        gt=0,
        description="BYN face value when the certificate product has no fixed amount (any-amount product).",
    )


@router.get("/client/cert-order/catalog")
async def get_client_cert_order_catalog_endpoint(
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Active certificate products for the client's derived primary trainer (order-via-request UX)."""
    telegram_id = client_catalog_telegram_key(principal)
    return await get_primary_cert_order_catalog(session, telegram_id)


@router.post("/client/cert-order/request")
async def post_client_cert_order_request(
    background_tasks: BackgroundTasks,
    body: ClientCertOrderRequestBody,
    cred: MiniappCredentialIn = Depends(require_miniapp_credential_in),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """Create a personalized «order certificate» client_request to the primary trainer."""
    telegram_id = client_catalog_telegram_key(principal)
    ik = (idempotency_key or "").strip()
    idem_cache_key = (f"coc{telegram_id}_{ik}"[:64]) if ik else ""
    if idem_cache_key:
        cached = await get_idempotency_response(session, idem_cache_key)
        if isinstance(cached, dict) and cached.get("success") is True:
            return cached

    client_id = await _ensure_client_for_webapp_miniapp(
        session,
        principal,
        cred.raw,
        phone=None,
        first_name=None,
        last_name=None,
    )
    result = await submit_certificate_product_order_request(
        session,
        client_id=client_id,
        telegram_id=telegram_id,
        certificate_product_id=body.certificate_product_id,
        recipient_email=body.recipient_email,
        recipient_name=body.recipient_name,
        nominal_byn=body.nominal_byn,
    )
    if result.get("ok"):
        out: dict[str, object] = {"success": True, "request_id": result["request_id"]}
        if idem_cache_key:
            await set_idempotency_response(session, idem_cache_key, dict(out))
        background_tasks.add_task(
            _bg_notify_trainer_client_request_immediate, int(result["request_id"])
        )
        return out
    err = str(result.get("error") or "unknown")
    mapping: dict[str, tuple[int, str]] = {
        "no_primary_trainer": (
            400,
            "Нет основного тренера — запишитесь к тренеру или добавьте его в избранное.",
        ),
        "product_not_found": (404, "Этот сертификат недоступен."),
        "trainer_city_missing": (
            422,
            "У тренера не заполнен город в профиле. Напишите ему в Telegram.",
        ),
        "trainer_service_missing": (
            422,
            "У тренера не настроены услуги. Напишите ему напрямую.",
        ),
        "duplicate_pending": (
            409,
            "Заявка на этот сертификат уже отправлена. Дождитесь ответа тренера.",
        ),
        "daily_limit": (
            429,
            "Заявка уже отправлена ранее.",
        ),
        "client_mismatch": (403, "Не удалось подтвердить аккаунт."),
        "invalid_email": (422, "Укажите корректный email."),
        "recipient_name_required": (422, "Укажите имя получателя."),
        "nominal_required": (422, "Укажите сумму сертификата (номинал, " + BYR_SIGN + ")."),
        "nominal_invalid": (422, "Некорректная сумма. Укажите разумный номинал, " + BYR_SIGN + "."),
    }
    status_code, detail = mapping.get(err, (400, "Не удалось отправить заявку."))
    raise HTTPException(status_code=status_code, detail=detail)


@router.get("/client/bookings")
async def get_client_bookings(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """List client's upcoming bookings grouped by day. Arena + address + map_link. Auth: client initData."""
    telegram_id = client_catalog_telegram_key(principal)
    return await _client_bookings_days_payload(session, telegram_id)


@router.get("/client/family-access")
async def get_client_family_access(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Household Telegram members sharing one client card (bookings/passes). Owner manages invites."""
    telegram_id = client_catalog_telegram_key(principal)
    data = await list_family_access_members_api(session, viewer_telegram_id=telegram_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Клиент не найден. Завершите регистрацию в приложении.")
    return data


@router.post("/client/family-access/invite")
async def post_client_family_access_invite(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Primary Telegram holder creates a one-time invite link (t.me client bot welcome_t_*)."""
    telegram_id = client_catalog_telegram_key(principal)
    cid = await get_client_id_by_telegram_id(session, telegram_id)
    if cid is None:
        raise HTTPException(status_code=400, detail="Сначала завершите регистрацию.")
    url, err = await create_family_access_invite_token(
        session,
        primary_client_id=int(cid),
        inviter_telegram_id=int(telegram_id),
    )
    if err == "owner_only":
        raise HTTPException(status_code=403, detail="Приглашать может только основной аккаунт семьи.")
    if err == "limit_reached":
        raise HTTPException(status_code=409, detail="Достигнут лимит приглашённых для семейного доступа.")
    if err == "roster_required":
        raise HTTPException(
            status_code=400,
            detail="Сначала запишитесь к тренеру или добавьтесь в клиенты — нужна связь с тренером для ссылки.",
        )
    if err == "no_bot":
        raise HTTPException(status_code=503, detail="Сервис приглашений временно недоступен.")
    if not url:
        raise HTTPException(status_code=400, detail="Не удалось создать приглашение.")
    return {"invite_url": url}


@router.post("/client/family-access/revoke")
async def post_client_family_access_revoke(
    body: FamilyAccessRevokeBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Owner revokes an extra Telegram member from the shared client card."""
    telegram_id = client_catalog_telegram_key(principal)
    cid = await get_client_id_by_telegram_id(session, telegram_id)
    if cid is None:
        raise HTTPException(status_code=404, detail="Клиент не найден.")
    ok = await revoke_family_member(
        session,
        primary_client_id=int(cid),
        owner_telegram_id=int(telegram_id),
        member_telegram_id=int(body.member_telegram_id),
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Не удалось отозвать доступ. Проверьте права и id участника.")
    await session.commit()
    return {"ok": True}


@router.get("/client/activity-stats")
async def get_client_activity_stats(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> dict:
    """
    Client motivation dashboard: completed session totals, approximate time on mats,
    rolling 30-day rhythm vs prior window, upcoming count, next numeric milestone.
    """
    telegram_id = client_catalog_telegram_key(principal)
    client_id = await get_client_id_by_telegram_id(session, telegram_id)
    return await get_client_activity_snapshot(session, client_id=client_id)


@router.get("/client/hub/bootstrap")
async def get_client_hub_bootstrap(
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """
    Single round-trip for client home: bookings by day + requests + session edges + activity snippet.
    ``activity`` holds ``streak_weeks`` and ``completed_total`` for a small streak ribbon on the hub.
    """
    telegram_id = client_catalog_telegram_key(principal)

    async def _bookings() -> dict:
        async with async_session_factory() as s:
            return await _client_bookings_days_payload(s, telegram_id)

    async def _requests() -> dict:
        async with async_session_factory() as s:
            return await _client_requests_list_payload(s, telegram_id)

    async def _hub_session() -> dict[str, Any]:
        """Legacy: selected_trainer_id + edge graph fields + saved_trainers preview for home strip."""
        async with async_session_factory() as s:
            await reset_orphan_client_miniapp_trainer_pointers(s, telegram_id)
            row = await read_client_bot_session(telegram_id, s)
            tid = (row or {}).get("selected_trainer_id")
            edges = await get_all_trainer_edges(telegram_id, s)
            session_tid = int(tid) if tid is not None else None
            if session_tid is not None and await trainer_id_belongs_to_telegram(
                s, session_tid, telegram_id
            ):
                session_tid = None
            book_tid, book_svc = await client_latest_booking_primary_candidate(s, telegram_id)
            upcoming_tid, upcoming_svc = await client_upcoming_booking_primary_candidate(
                s, telegram_id
            )
            rebook_raw = await client_rebook_trainer_targets(s, telegram_id, limit=3)
            bp_tid, bp_svc = _hub_booking_primary_ids(
                upcoming_tid, upcoming_svc, book_tid, book_svc
            )
            primary_edge, primary_src = _compute_primary_edge_meta(
                edges,
                session_tid,
                booking_primary_trainer_id=bp_tid,
                booking_primary_service_id=bp_svc,
            )
            pid = int(primary_edge["trainer_id"]) if primary_edge else None
            hint_ids = sorted(
                {int(e["trainer_id"]) for e in edges}
                | ({pid} if pid else set())
                | {int(t[0]) for t in rebook_raw}
            )
            hints = await trainer_display_hints_by_ids(s, hint_ids)
            saved_edges = [e for e in edges if e.get("is_saved")]
            p_hint = hints.get(pid) if pid else None
            sess_svc = (row or {}).get("selected_service_id")
            raw_primary_svc = _resolve_primary_catalog_service_id(primary_edge, primary_src, sess_svc)
            primary_catalog_service_id: int | None = None
            primary_catalog_service_name: str | None = None
            if pid is not None:
                primary_catalog_service_id, primary_catalog_service_name = (
                    await coerce_service_id_and_name_for_trainer_catalog(s, pid, raw_primary_svc)
                )
            saved_preview = [
                {
                    "trainer_id": int(e["trainer_id"]),
                    "trainer_display_name": (hints.get(int(e["trainer_id"])) or {}).get(
                        "trainer_display_name", "Тренер"
                    ),
                    "trainer_list_photo_key": (hints.get(int(e["trainer_id"])) or {}).get(
                        "trainer_list_photo_key"
                    ),
                }
                for e in saved_edges
            ]
            rebook_targets: list[dict[str, Any]] = []
            for rt_tid, rt_svc in rebook_raw:
                h = hints.get(int(rt_tid)) or {}
                rt_name = ((h.get("trainer_display_name") or "Тренер").strip() or "Тренер")
                rebook_targets.append(
                    {
                        "trainer_id": int(rt_tid),
                        "service_id": int(rt_svc) if rt_svc is not None else None,
                        "trainer_display_name": rt_name,
                    }
                )
            return {
                "selected_trainer_id": int(tid) if tid is not None else None,
                "primary_trainer_id": pid,
                "primary_trainer_name": (
                    (p_hint or {}).get("trainer_display_name") if pid else None
                ),
                "primary_trainer_list_photo_key": (p_hint or {}).get("trainer_list_photo_key") if pid else None,
                "primary_catalog_service_id": primary_catalog_service_id,
                "primary_catalog_service_name": primary_catalog_service_name,
                "saved_trainer_ids": [e["trainer_id"] for e in saved_edges],
                "saved_trainers": saved_preview,
                "has_past_sessions": any(e.get("completed_count", 0) > 0 for e in edges),
                "last_booking_trainer_id": book_tid,
                "last_booking_service_id": book_svc,
                "rebook_targets": rebook_targets,
            }

    async def _activity() -> dict[str, Any]:
        """Light motivation snippet for hub ribbon (week streak + total completed)."""
        async with async_session_factory() as s:
            cid = await get_client_id_by_telegram_id(s, telegram_id)
            snap = await get_client_activity_snapshot(s, client_id=cid)
            return {
                "streak_weeks": int(snap.get("streak_weeks") or 0),
                "completed_total": int(snap.get("completed_total") or 0),
            }

    bookings, requests, client_session, activity = await asyncio.gather(
        _bookings(), _requests(), _hub_session(), _activity()
    )
    return {
        "bookings": bookings,
        "requests": requests,
        "client_session": client_session,
        "activity": activity,
    }


@router.get("/client/share-trainer/{trainer_id}")
async def get_client_share_trainer(
    trainer_id: int,
    share_context: str | None = Query(
        None,
        description=(
            "Где нажали «Поделиться»: my_trainer (основной на главной), catalog (карточка в каталоге), "
            "booking_success (после записи), next_booking (ближайшая тренировка на главной)."
        ),
    ),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> dict:
    """
    Готовое сообщение-рекомендация + deep link (в `share_text` ссылка первой строкой;
    для нативного «Поделиться» отдельно отдаём `share_url` + `share_body` без дубля URL).

    Текст шаринга одинаковый для любого share_context (хаб, каталог, после записи и т.д.).
    Структура в share_text: deep link первой строкой; затем opener, имя, услуги, локация.
    """
    hints = await trainer_display_hints_by_ids(session, [trainer_id])
    hint = hints.get(trainer_id)
    if not hint:
        raise HTTPException(status_code=404, detail="Trainer not found")

    settings = Settings()
    share_link, err = build_trainer_share_link(
        webapp_base_url=settings.webapp_base_url,
        client_bot_username=settings.client_bot_username,
        trainer_id=trainer_id,
    )
    if err or share_link is None:
        raise HTTPException(status_code=503, detail=f"Share link unavailable: {err}")

    deep_link = share_link.bot_deep_link.strip()

    city_row = await session.execute(
        text(
            """
            SELECT c.name FROM trainer_profiles tp
            LEFT JOIN cities c ON c.id = tp.city_id
            WHERE tp.trainer_id = :tid
            LIMIT 1
            """
        ),
        {"tid": trainer_id},
    )
    crow = city_row.fetchone()
    city_name = (str(crow[0]).strip() if crow and crow[0] is not None else "") or None

    name = hint.get("trainer_display_name") or "Тренер"
    services: list[str] = list(hint.get("services") or [])
    venue: str | None = hint.get("primary_arena_name")

    raw_ctx = (share_context or "").strip() if share_context else None
    share_text = compose_client_share_message(
        share_context=raw_ctx or "",
        trainer_display_name=str(name),
        service_names=services,
        city_name=city_name,
        primary_arena_name=venue,
        deep_link=deep_link,
    )

    service_line = services[0] if services else None

    share_body = share_body_for_native_share_dialog(share_text, deep_link)

    return {
        "share_url": deep_link,
        "share_body": share_body,
        "share_text": share_text,
        "trainer_name": name,
        "trainer_service": service_line,
        "trainer_venue": venue,
        "trainer_city": city_name,
        "share_context": raw_ctx or "catalog",
    }


@router.get("/client/passes")
async def get_client_passes(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> dict:
    """List current client's pass instances (my passes). Auth: client initData. One query with JOINs."""
    telegram_id = client_catalog_telegram_key(principal)
    client_id = await get_client_id_by_telegram_id(session, telegram_id)
    if not client_id:
        return {"items": []}
    items = await list_client_pass_instances(session, client_id)
    return {"items": items}


@router.get("/client/certificates")
async def get_client_certificates(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> dict:
    """List current client's certificate instances (my certificates). Auth: client initData."""
    telegram_id = client_catalog_telegram_key(principal)
    client_id = await get_client_id_by_telegram_id(session, telegram_id)
    if not client_id:
        return {"items": []}
    items = await list_client_certificate_instances(session, client_id)
    return {"items": items}


@router.get("/client/certificates/sample-pdf")
async def get_client_certificate_sample_pdf(
    _principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
) -> Response:
    """
    PDF preview with synthetic data (same layout as email attachment).
    Validates client Mini App credentials; CRM client profile is optional.
    """
    from src.application.certificate_pdf import build_certificate_pdf

    issued = date.today()
    expires_at = issued + timedelta(days=365)
    _s = Settings()
    bot_username = (_s.client_bot_username or "").strip().lstrip("@")
    activation_url = f"https://t.me/{bot_username}?start=cert_PREVIEW-DEMO" if bot_username else None
    client_bot_display = f"@{bot_username}" if bot_username else None
    pdf = build_certificate_pdf(
        trainer_name="Анна Примерова",
        product_name="Подарочный сертификат",
        amount_cents=10000,
        code="CERT-SAMPLE-PREVIEW",
        recipient_name="Имя получателя (пример)",
        purchased_by_name="Покупатель (пример)",
        issued_at=issued,
        expires_at=expires_at,
        activation_url=activation_url,
        client_bot_display_name=client_bot_display,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="certificate-sample.pdf"',
            "Cache-Control": "private, max-age=300",
        },
    )


class ClientCertificateActivateBody(BaseModel):
    code: str


@router.post("/client/certificates/activate")
async def post_client_certificate_activate(
    body: ClientCertificateActivateBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """
    Client activates a certificate by code.
    - Binds certificate to this client (activated_client_id) and marks status=activated.
    - Returns basic info (trainer_id, amount_cents, product_id, expires_at).
    Auth: client initData.
    """
    client_tid = client_catalog_telegram_key(principal)
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
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Cancel own booking with optional reason. Auth: client initData. Notifies trainer immediately."""
    telegram_id = client_catalog_telegram_key(principal)
    payload = await cancel_booking_by_client(
        session, booking_id, telegram_id, reason=body.reason
    )
    if not payload:
        raise HTTPException(status_code=400, detail="Booking not found or already cancelled")
    slot_date = payload.get("slot_date")
    start_time = payload.get("start_time")
    date_str = slot_date.strftime("%d.%m") if hasattr(slot_date, "strftime") else str(slot_date)
    day_label = CLIENT_DAYS[slot_date.weekday()] if hasattr(slot_date, "weekday") else ""
    time_str = start_time.strftime("%H:%M") if hasattr(start_time, "strftime") else str(start_time)[:5]
    # Notify trainer right away (async in same flow, no polling)
    trainer_tid = payload.get("trainer_telegram_id")
    if trainer_tid:
        client_name = (payload.get("client_name") or "Клиент").strip() or "Клиент"
        client_name_safe = html.escape(client_name)
        reason = payload.get("reason")
        reason_safe = html.escape(reason) if reason else ""
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
            reply_markup = None
            ex_cid = payload.get("client_id")
            slot_id_raw = payload.get("slot_id")
            c_tid = payload.get("client_telegram_id")
            if (
                slot_id_raw is not None
                and ex_cid is not None
            ):
                reply_markup = msg.build_trainer_client_cancel_notification_keyboard(
                    webapp_base_url=Settings().webapp_base_url,
                    slot_id=int(slot_id_raw),
                    exclude_client_id=int(ex_cid),
                    client_telegram_id=int(c_tid) if c_tid is not None else None,
                )
            await trainer_bot.send_message(
                chat_id=trainer_tid, text=text, reply_markup=reply_markup
            )
        finally:
            await trainer_bot.session.close()
    settings_client = Settings()
    reply_markup_client = msg.build_client_rebook_catalog_keyboard(
        webapp_base_url=settings_client.webapp_base_url,
        trainer_id=payload.get("trainer_id"),
        service_id=payload.get("service_id"),
    )
    cancel_tpl = (
        msg.CLIENT_BOOKING_CANCELLED_BY_SELF
        if reply_markup_client is not None
        else msg.CLIENT_BOOKING_CANCELLED_BY_SELF_MENU
    )
    text_client = cancel_tpl.format(date=date_str, day=day_label, time=time_str)
    client_bot = Bot(
        token=settings_client.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        if principal.platform == MiniAppPlatform.TELEGRAM:
            await client_bot.send_message(
                chat_id=int(principal.user_id), text=text_client, reply_markup=reply_markup_client
            )
    finally:
        await client_bot.session.close()
    return {"success": True}


class ClientRequestPatchBody(BaseModel):
    comment: str | None = None


@router.patch("/client/requests/{request_id}")
async def patch_client_request(
    request_id: int,
    body: ClientRequestPatchBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Replace request with new comment (re-create so trainers get new notification). Auth: client initData."""
    from src.application.client_request_comment_display import client_request_comment_editable
    from src.application.client_use_cases import get_client_id_by_telegram_id

    telegram_id = client_catalog_telegram_key(principal)
    cid = await get_client_id_by_telegram_id(session, telegram_id)
    if cid is None:
        raise HTTPException(status_code=403, detail="Client not found")
    r = await session.execute(
        text(
            "SELECT comment FROM client_requests WHERE id = :rid AND client_id = :cid"
        ),
        {"rid": request_id, "cid": int(cid)},
    )
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    if not client_request_comment_editable(row[0]):
        raise HTTPException(
            status_code=400,
            detail="Заявки на абонемент и сертификат пока нельзя редактировать. Удалите заявку и оформите новую.",
        )
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
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Delete my request. Auth: client initData."""
    telegram_id = client_catalog_telegram_key(principal)
    ok = await delete_client_request(session, request_id, telegram_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Request not found")
    return {"success": True}


# --- Trainer bookings Mini App (initData validated with trainer bot token) ---

TRAINER_DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def _serialize_booking(b: dict, *, problem_flow_enabled: bool | None = None) -> dict:
    """Booking dict to JSON-safe (date/time as string)."""
    slot_date = b.get("slot_date")
    start_time = b.get("start_time")
    end_time = b.get("end_time")
    out = {
        "id": b["id"],
        "slot_id": b.get("slot_id"),
        "client_id": b.get("client_id"),
        "client_telegram_id": b.get("client_telegram_id"),
        "client_telegram_username": (b.get("client_telegram_username") or "").strip() or None,
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
        "service_id": b.get("service_id"),
        "service_price_variant_id": b.get("service_price_variant_id"),
        "arena_id": b.get("arena_id"),
        "status": (b.get("status") or "confirmed").strip(),
        "slot_capacity": max(1, int(b.get("slot_capacity") or 1)),
        "slot_active_bookings": max(0, int(b.get("slot_active_bookings") or 0)),
        "hub_in_session": bool(b.get("hub_in_session")),
        "problem_reported": bool(b.get("problem_reported")),
        "client_no_show_recorded": bool(b.get("client_no_show_recorded")),
        "first_client_online_pending": bool(b.get("first_client_online_pending")),
        "is_sandbox": bool(b.get("is_sandbox")),
    }
    bpc = b.get("booking_price_cents")
    out["booking_price_cents"] = int(bpc) if bpc is not None else None
    ptl = b.get("price_tier_label")
    out["price_tier_label"] = (str(ptl).strip() if ptl else "") or None
    if problem_flow_enabled is not None:
        out["problem_flow_enabled"] = bool(problem_flow_enabled)
    return out


async def _trainer_bookings_grouped_days_payload(
    session: AsyncSession,
    trainer_id: int,
    *,
    limit: int,
) -> dict[str, Any]:
    """GET /trainer/bookings shape: ``days``, ``today_sessions``, ``week_sessions`` (hub-aligned SQL counts)."""
    flow_ok = booking_problem_api_allowed_for_trainer(trainer_id)
    lim = max(1, min(100, limit))
    summary_counts = await get_trainer_hub_session_summary_counts(session, trainer_id)
    hub_summary = {
        "today_sessions": {
            "total": summary_counts["today_total"],
            "remaining": summary_counts["today_remaining"],
        },
        "week_sessions": {
            "total": summary_counts["week_total"],
            "remaining": summary_counts["week_remaining"],
        },
    }
    bookings = await list_bookings_for_trainer(session, trainer_id, limit=lim)
    if not bookings:
        return {"days": [], **hub_summary}
    await enrich_booking_dicts_with_client_telegram_usernames(session, bookings)
    days_list: list[dict[str, Any]] = []
    for slot_date, group in groupby(bookings, key=lambda b: b["slot_date"]):
        day_bookings = list(group)
        date_str = slot_date.isoformat() if hasattr(slot_date, "isoformat") else str(slot_date)
        dow = slot_date.weekday() if hasattr(slot_date, "weekday") else 0
        day_label = TRAINER_DAYS[dow] if dow < len(TRAINER_DAYS) else ""
        days_list.append(
            {
                "date": date_str,
                "day_label": day_label,
                "bookings": [_serialize_booking(b, problem_flow_enabled=flow_ok) for b in day_bookings],
            }
        )
    return {"days": days_list, **hub_summary}


def _serialize_trainer_dashboard(data: dict) -> dict:
    """JSON-serializable dashboard: dates to ISO strings."""
    out = {**data}
    for key in ("week_start", "week_end", "month_start", "month_end", "busiest_date"):
        if key in out and hasattr(out[key], "isoformat"):
            out[key] = out[key].isoformat()
    return out


@router.get("/trainer/stats")
async def get_trainer_stats_api(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Full stats dashboard for trainer Mini App: KPIs, trends, by-day, insights. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_analytics_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_ANALYTICS_REQUIRED)
    data = await get_trainer_stats_dashboard(session, trainer_id)
    return _serialize_trainer_dashboard(data)


@router.get("/trainer/stats/revenue-range")
async def get_trainer_revenue_range_api(
    period_from: date = Query(..., alias="from"),
    period_to: date = Query(..., alias="to"),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Accrual revenue breakdown for an arbitrary inclusive date range (Mini App «Бухгалтерия»)."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_analytics_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_ANALYTICS_REQUIRED)
    try:
        return await get_trainer_revenue_breakdown_for_range(session, trainer_id, period_from, period_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


async def build_trainer_lifecycle_payload(
    session: AsyncSession,
    trainer_id: int,
) -> dict[str, Any]:
    """Lifecycle snapshot + demand recap for trainer-home Lead Mode banner / recap card.

    For Lead Mode trainers the recap window starts at last_subscription_expires_at so the loss
    framing ("23 views since trial ended") is grounded in real numbers. For other stages the
    recap falls back to the standard 14-day window — still useful as a presence proof for ACTIVE
    trainers without exposing Lead Mode mechanics.
    """
    snap: LifecycleSnapshot = await resolve_lifecycle_snapshot(session, trainer_id)
    now = datetime.now(timezone.utc)

    if snap.is_lead_mode and snap.last_subscription_expires_at is not None:
        # Anchor the recap to the exact moment Lead Mode started so loss framing matches reality.
        anchored_since = max(snap.last_subscription_expires_at, now - timedelta(days=90))
        recap: SignalsRecap = await get_signals_since(
            session, trainer_id=trainer_id, since=anchored_since, now=now
        )
        recap_dict = recap.as_dict()
        recap_dict["window"] = "since_lead_mode"
    else:
        recap = await get_signals_recap(
            session, trainer_id=trainer_id, window_days=RECAP_WINDOW_14D, now=now
        )
        recap_dict = recap.as_dict()
        recap_dict["window"] = f"{RECAP_WINDOW_14D}d"

    days_in_lead_mode: int | None = None
    if snap.is_lead_mode and snap.last_subscription_expires_at is not None:
        delta = now - snap.last_subscription_expires_at
        days_in_lead_mode = max(0, int(delta.total_seconds() // 86400))

    payload: dict[str, Any] = snap.as_dict()
    payload["lead_mode_since"] = (
        snap.last_subscription_expires_at.isoformat()
        if snap.is_lead_mode and snap.last_subscription_expires_at is not None
        else None
    )
    payload["days_in_lead_mode"] = days_in_lead_mode
    payload["signals_recap"] = recap_dict
    return payload


@router.get("/trainer/lifecycle")
async def get_trainer_lifecycle(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """
    Trainer lifecycle snapshot + demand signals recap. Drives Lead Mode banner / recap card on
    trainer-home. Safe to poll: read-only, no side effects beyond the demand signal recap query.
    """
    trainer_id = await get_trainer_id_linked_any_status_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked")
    return await build_trainer_lifecycle_payload(session, trainer_id)


@router.get("/trainer/hub/revenue-mtd")
async def get_trainer_hub_revenue_mtd(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Hub KPI: accrual revenue from the 1st of the current month through today (Europe/Minsk). No analytics module gate."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    return await get_trainer_hub_revenue_month_to_date(session, trainer_id)


@router.get("/trainer/hub/bootstrap")
async def get_trainer_hub_bootstrap(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    bookings_limit: int = Query(32, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """
    Single round-trip for trainer hub home: access + profile + onboarding + requests + revenue + bookings + subscription.
    Profile is a minimal slice (hub gates), not the full GET /trainer/profile aggregate.
    Returns null for sections that do not apply (e.g. active-only APIs when account not active).
    ``partial_errors`` lists non-fatal failures so the client can fall back to legacy GETs.
    """
    from src.api.routes.webapp_trainer_profile import build_trainer_hub_profile_bootstrap_payload

    partial_errors: dict[str, str] = {}

    state, trainer_row = await get_trainer_access_state_from_principal(session, principal)
    if trainer_row and trainer_row.get("id") is not None:
        await ensure_trainer_welcome_trial(session, int(trainer_row["id"]))
    tid = int(trainer_row["id"]) if trainer_row and trainer_row.get("id") is not None else None
    norm_status = normalize_trainer_status_value(trainer_row.get("status") if trainer_row else None)
    is_active = (state == TrainerAccessState.ACTIVE) or (norm_status == TRAINER_STATUS_ACTIVE)
    schedule_unlocked = state in (TrainerAccessState.ACTIVE, TrainerAccessState.BOOKING_READY)
    access: dict[str, Any] = {
        "access_state": state.value,
        "trainer_id": tid,
        "trainer_status": norm_status,
        "is_active": is_active,
        "schedule_unlocked": schedule_unlocked,
        "force_client_chat_relay": bool(Settings().trainer_webapp_force_client_chat_relay),
    }

    # Same semantics as get_trainer_id_linked_any_status / get_trainer_id_by_telegram_id without extra queries
    # (get_trainer_access_state already resolved the trainer row).
    trainer_id_linked = tid
    trainer_id_active = tid if norm_status == TRAINER_STATUS_ACTIVE else None

    profile: dict[str, Any] | None = None
    onboarding_checklist: dict[str, Any] | None = None
    requests_summary: dict[str, Any] | None = None
    revenue_mtd: dict[str, Any] | None = None
    bookings: dict[str, Any] | None = None
    subscription_status: dict[str, Any] | None = None
    lifecycle: dict[str, Any] | None = None

    if trainer_id_linked:
        tid_l = trainer_id_linked

        # Parallel reads use separate sessions: one AsyncSession must not run concurrent operations.
        async def _hub_profile() -> dict[str, Any]:
            async with async_session_factory() as s:
                return await build_trainer_hub_profile_bootstrap_payload(s, tid_l)

        async def _hub_onboarding() -> dict[str, Any] | None:
            async with async_session_factory() as s:
                od = await get_trainer_onboarding_checklist(s, tid_l)
                return od if od else None

        async def _hub_lifecycle() -> dict[str, Any]:
            async with async_session_factory() as s:
                return await build_trainer_lifecycle_payload(s, tid_l)

        if trainer_id_active:
            tid_act = trainer_id_active

            async def _hub_req_count() -> int:
                async with async_session_factory() as s:
                    return await count_unanswered_requests_for_trainer(s, tid_act)

            async def _hub_revenue() -> dict[str, Any]:
                async with async_session_factory() as s:
                    return await get_trainer_hub_revenue_month_to_date(s, tid_act)

            async def _hub_bookings() -> dict[str, Any]:
                async with async_session_factory() as s:
                    return await _trainer_bookings_grouped_days_payload(s, tid_act, limit=bookings_limit)

            async def _hub_subscription() -> dict[str, Any]:
                async with async_session_factory() as s:
                    return await get_trainer_subscription_status(s, tid_act)

            p_res, o_res, r_req, r_rev, r_book, r_sub, r_life = await asyncio.gather(
                _hub_profile(),
                _hub_onboarding(),
                _hub_req_count(),
                _hub_revenue(),
                _hub_bookings(),
                _hub_subscription(),
                _hub_lifecycle(),
                return_exceptions=True,
            )
            if isinstance(p_res, BaseException):
                if isinstance(p_res, HTTPException):
                    det = p_res.detail
                    partial_errors["profile"] = det if isinstance(det, str) else str(det)
                else:
                    raise p_res
            else:
                profile = p_res
            if isinstance(o_res, BaseException):
                partial_errors["onboarding_checklist"] = str(o_res)
            else:
                onboarding_checklist = o_res
            if isinstance(r_req, BaseException):
                partial_errors["requests_summary"] = str(r_req)
            else:
                requests_summary = {"unanswered_count": r_req}
            if isinstance(r_rev, BaseException):
                partial_errors["revenue_mtd"] = str(r_rev)
            else:
                revenue_mtd = r_rev
            if isinstance(r_book, BaseException):
                partial_errors["bookings"] = str(r_book)
            else:
                bookings = r_book
                bookings["force_client_chat_relay"] = bool(Settings().trainer_webapp_force_client_chat_relay)
            if isinstance(r_sub, BaseException):
                partial_errors["subscription_status"] = str(r_sub)
            else:
                subscription_status = r_sub
            if isinstance(r_life, BaseException):
                partial_errors["lifecycle"] = str(r_life)
            else:
                lifecycle = r_life
        else:
            p_res, o_res, r_life = await asyncio.gather(
                _hub_profile(),
                _hub_onboarding(),
                _hub_lifecycle(),
                return_exceptions=True,
            )
            if isinstance(p_res, BaseException):
                if isinstance(p_res, HTTPException):
                    det = p_res.detail
                    partial_errors["profile"] = det if isinstance(det, str) else str(det)
                else:
                    raise p_res
            else:
                profile = p_res
            if isinstance(o_res, BaseException):
                partial_errors["onboarding_checklist"] = str(o_res)
            else:
                onboarding_checklist = o_res
            if isinstance(r_life, BaseException):
                partial_errors["lifecycle"] = str(r_life)
            else:
                lifecycle = r_life
            if state == TrainerAccessState.BOOKING_READY and trainer_id_linked:

                async def _hub_sub_ttv() -> dict[str, Any]:
                    async with async_session_factory() as s:
                        return await get_trainer_subscription_status(s, trainer_id_linked)

                r_sub_ttv = await _hub_sub_ttv()
                if isinstance(r_sub_ttv, BaseException):
                    partial_errors["subscription_status"] = str(r_sub_ttv)
                else:
                    subscription_status = r_sub_ttv

    return {
        "access": access,
        "profile": profile,
        "onboarding_checklist": onboarding_checklist,
        "requests_summary": requests_summary,
        "revenue_mtd": revenue_mtd,
        "bookings": bookings,
        "subscription_status": subscription_status,
        "lifecycle": lifecycle,
        "partial_errors": partial_errors or None,
    }


@router.get("/trainer/hub/fill-slots-invites")
async def get_trainer_hub_fill_slots_invites(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(3, ge=1, le=250),
    include_with_upcoming: bool = Query(
        True,
        description="When true (default), all CRM-scoped clients linked to Telegram; ranked with «no upcoming» first. "
        "Set false for legacy focused list (only without a future session).",
    ),
    slot_id: int | None = Query(None, description="When set, validate freed slot for «offer this window» copy."),
    exclude_client_id: int | None = Query(
        None, description="Omit this CRM client from the list (e.g. who just cancelled)."
    ),
):
    """
    Ranked clients for «free slots next week» rhythm hint: pre-invite workflow in the hub.
    Auth: trainer initData (same as /trainer/clients).
    """
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    clients = await list_trainer_fill_slots_invite_candidates(
        session,
        trainer_id,
        limit=limit,
        include_with_upcoming=include_with_upcoming,
    )
    if exclude_client_id is not None:
        ex = int(exclude_client_id)
        clients = [c for c in clients if int(c.get("id") or 0) != ex]
    slot_payload: dict | None = None
    if slot_id is not None:
        slot = await get_trainer_slot_for_mass_client_invite(session, trainer_id, int(slot_id))
        if not slot:
            raise HTTPException(
                status_code=404,
                detail="Слот не найден, уже занят или прошёл.",
            )
        sd = slot["slot_date"]
        st = slot["start_time"]
        en = slot["end_time"]
        date_str = sd.strftime("%d.%m") if hasattr(sd, "strftime") else str(sd)[:10]
        dow_i = int(sd.weekday()) if hasattr(sd, "weekday") else 0
        dlabel = (
            CLIENT_DAYS[dow_i] if 0 <= dow_i < len(CLIENT_DAYS) else ""
        )
        t1 = st.strftime("%H:%M") if hasattr(st, "strftime") else str(st)[:5]
        t2 = en.strftime("%H:%M") if hasattr(en, "strftime") else str(en)[:5]
        label = f"{date_str} ({dlabel}) · {t1}–{t2}"
        sn = (slot.get("service_name") or "").strip()
        an = (slot.get("arena_name") or "").strip()
        if sn and an:
            label += f" · {sn} · {an}"
        elif sn:
            label += f" · {sn}"
        elif an:
            label += f" · {an}"
        slot_payload = {"id": int(slot["id"]), "label": label}
    return {"clients": clients, "slot": slot_payload}


class TrainerFillSlotsInviteSendBody(BaseModel):
    client_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=250,
        description="Clients to notify via client bot (must be in trainer CRM and linked to Telegram).",
    )
    slot_id: int | None = Field(
        None, description="When set, message and book button target this concrete slot."
    )
    exclude_client_id: int | None = Field(
        None, description="Optional: never message this client (e.g. who freed the slot)."
    )


@router.post("/trainer/hub/fill-slots-invites/send")
async def post_trainer_hub_fill_slots_invites_send(
    body: TrainerFillSlotsInviteSendBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Trainer hub: send ranked-slot-invite pushes from the **client** bot with a «Записаться» WebApp button.
    """
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    out = await send_trainer_fill_slots_invites(
        session,
        trainer_id,
        body.client_ids,
        slot_id=body.slot_id,
        exclude_client_id=body.exclude_client_id,
    )
    err = out.get("error")
    if err == "slot_unavailable":
        raise HTTPException(status_code=400, detail=out.get("detail") or "Slot unavailable")
    if err == "no_recipients":
        raise HTTPException(status_code=400, detail=out.get("detail") or "No recipients")
    return out


# --- Support: client/trainer send message; admin list and reply ---

class SupportCreateBody(BaseModel):
    message: str
    role: str = "client"  # client | trainer


class SupportReplyBody(BaseModel):
    reply_text: str


@router.post("/support")
async def post_support(
    body: SupportCreateBody,
    cred: MiniappCredentialIn = Depends(require_miniapp_credential_in),
    session: AsyncSession = Depends(get_session),
):
    """Create support ticket from client or trainer Mini App. Auth: client or trainer initData; role in body."""
    reject_unsupported_miniapp_platform(cred.platform)
    role = (body.role or "client").strip().lower()
    if cred.platform == MiniAppPlatform.MAX.value:
        secret = (Settings().vk_mini_app_protected_key or "").strip()
        if not secret:
            raise HTTPException(status_code=503, detail="VK Mini App not configured")
        try:
            principal = verify_vk_miniapp_launch_principal(cred.raw, secret)
        except InitDataAuthError:
            raise miniapp_credential_http_exception() from None
        if role == "trainer":
            telegram_id = trainer_legacy_telegram_id_for_storage(principal)
        else:
            role = "client"
            telegram_id = client_catalog_telegram_key(principal)
    else:
        if role == "trainer":
            token = Settings().telegram_bot_token_trainer
            if not token:
                raise HTTPException(status_code=503, detail="Trainer Mini App not configured")
        else:
            token = Settings().telegram_bot_token_client
            if not token:
                raise HTTPException(status_code=503, detail="Client Mini App not configured")
            role = "client"
        try:
            telegram_id = verify_telegram_init_data_principal(cred.raw, token).user_id
        except InitDataAuthError:
            raise miniapp_credential_http_exception() from None
    from src.infrastructure.db.models import SUPPORT_FROM_CLIENT, SUPPORT_FROM_TRAINER
    from_role = SUPPORT_FROM_TRAINER if role == "trainer" else SUPPORT_FROM_CLIENT
    if from_role == SUPPORT_FROM_TRAINER:
        admin_tag = (
            "хаб тренера (MAX)" if cred.platform == MiniAppPlatform.MAX.value else "хаб тренера (Mini App)"
        )
    else:
        admin_tag = (
            "клиентское приложение (MAX)"
            if cred.platform == MiniAppPlatform.MAX.value
            else "клиентское приложение (Mini App)"
        )
    result = await create_support_message(
        session,
        telegram_id,
        from_role,
        body.message or "",
        admin_notify_source_tag=admin_tag,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="Empty message")
    return result


@router.get("/admin/stats")
async def get_admin_stats(
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Platform stats + alerts for admin Mini App. Auth: admin bot initData."""
    data = await get_platform_stats(session)
    # Serialize dates for JSON
    return {
        **data,
        "week_start": data["week_start"].isoformat() if hasattr(data["week_start"], "isoformat") else str(data["week_start"]),
        "week_end": data["week_end"].isoformat() if hasattr(data["week_end"], "isoformat") else str(data["week_end"]),
        "today": data["today"].isoformat() if hasattr(data["today"], "isoformat") else str(data["today"]),
        "prev_week_start": data["prev_week_start"].isoformat()
        if hasattr(data["prev_week_start"], "isoformat")
        else str(data["prev_week_start"]),
        "prev_week_end": data["prev_week_end"].isoformat()
        if hasattr(data["prev_week_end"], "isoformat")
        else str(data["prev_week_end"]),
    }


@router.get("/admin/stats/money")
async def get_admin_stats_money(
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Money tab: MRR/ARR, GMV trend, revenue, top paying trainers, pending invoices, subscription mix."""
    return await get_admin_money_stats(session)


@router.get("/admin/stats/growth")
async def get_admin_stats_growth(
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Growth tab: new trainer cohorts, trial→paid conversion, time-to-first-paid, referral program."""
    return await get_admin_growth_stats(session)


@router.get("/admin/stats/retention")
async def get_admin_stats_retention(
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Retention tab: churn rate, expiring subs, sleeping trainers, revival, retention curve by cohort."""
    return await get_admin_retention_stats(session)


@router.get("/admin/stats/engagement")
async def get_admin_stats_engagement(
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Engagement tab: DAU/WAU/MAU, feature adoption, top active trainers, day-of-week heat."""
    return await get_admin_engagement_stats(session)


@router.get("/admin/stats/clients")
async def get_admin_stats_clients(
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Clients tab: funnel, repeat rate, top cities/trainers, recent client requests."""
    return await get_admin_clients_stats(session)


@router.get("/admin/stats/product")
async def get_admin_stats_product(
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Product analytics: activation funnel, proof-of-value, marketplace, monetization, correlation."""
    return await get_admin_product_analytics(session)


@router.get("/admin/support")
async def get_admin_support(
    status: str | None = Query(None, description="Filter: new, replied, closed"),
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """List support tickets for admin. Auth: admin initData."""
    items = await list_support_messages(session, limit=50, status=status)
    return {"items": items}


@router.post("/admin/support/{support_id:int}/reply")
async def post_admin_support_reply(
    support_id: int,
    body: SupportReplyBody,
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Admin replies to support ticket. Auth: admin initData."""
    admin_tid = principal.user_id
    ok = await reply_support_message(session, support_id, admin_tid, body.reply_text or "")
    if not ok:
        raise HTTPException(status_code=404, detail="Ticket not found or already replied")
    return {"ok": True}


@router.get("/trainer/subscription-plans")
async def get_trainer_subscription_plans(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """List paid subscription plans for trainer to choose (Месяц, 3 месяца, Год, 1.5 года). Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    plans = await list_paid_subscription_plans(session)
    return {"plans": plans}


@router.get("/trainer/subscription-payment-url")
async def get_trainer_subscription_payment_url(
    plan_id: int | None = Query(None, description="Chosen plan id; if omitted, use pending invoice or default plan"),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Create (or reuse pending) invoice and return payment_url. When plan_id is set, create invoice for that plan
    (period: next after current subscription or from now). Response includes plan_name, period for clarity.
    """
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    plan_name: str | None = None
    period_start = period_end = None
    referral_bonus_days_applied = 0
    amount_cents_before_referral: int | None = None
    if plan_id is not None:
        inv = await create_subscription_invoice(session, trainer_id, plan_id)
        if not inv:
            raise HTTPException(status_code=400, detail="Invalid plan or could not create invoice")
        invoice_id = inv["invoice_id"]
        amount_cents = inv["amount_cents"]
        period_start = inv["period_start"]
        period_end = inv["period_end"]
        plan_name = inv.get("plan_name")
        referral_bonus_days_applied = int(inv.get("referral_bonus_days_applied") or 0)
        amount_cents_before_referral = inv.get("amount_cents_before_referral")
    else:
        pending = await get_pending_subscription_invoice(session, trainer_id)
        if pending:
            invoice_id = pending["invoice_id"]
            amount_cents = pending["amount_cents"]
            period_start = pending["period_start"]
            period_end = pending["period_end"]
            plan_name = pending.get("plan_name")
            referral_bonus_days_applied = int(pending.get("referral_bonus_days_applied") or 0)
            amount_cents_before_referral = pending.get("amount_cents_before_referral")
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
            referral_bonus_days_applied = int(inv.get("referral_bonus_days_applied") or 0)
            amount_cents_before_referral = inv.get("amount_cents_before_referral")
    settings = Settings()
    webapp_base = (settings.webapp_base_url or "").rstrip("/")
    api_base = (settings.api_base_url or webapp_base).rstrip("/")
    return_url = f"{webapp_base}/webapp/trainer-pay-subscription?payment_success=1"
    notification_url = f"{api_base}/api/webhooks/bepaid"
    tracking_id = f"inv_{invoice_id}"

    def _date_str(d):
        if d is None:
            return None
        return d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]

    base_out: dict = {
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "plan_name": plan_name or "Подписка",
        "period_start": _date_str(period_start),
        "period_end": _date_str(period_end),
        "referral_bonus_days_applied": referral_bonus_days_applied,
        "amount_cents_before_referral": amount_cents_before_referral,
        "referral_fully_covered": bool(amount_cents <= 0 and referral_bonus_days_applied > 0),
    }
    if amount_cents <= 0:
        base_out["payment_url"] = None
        return base_out

    result = await create_checkout(
        amount_cents=amount_cents,
        currency="BYN",
        description=(plan_name or "Подписка")[:255],
        tracking_id=tracking_id,
        return_url=return_url,
        notification_url=notification_url,
        success_url=return_url,
    )
    base_out["payment_url"] = result["payment_url"]
    return base_out


class SubscriptionStubConfirmBody(BaseModel):
    invoice_id: int


@router.post("/trainer/subscription-stub-confirm")
async def post_trainer_subscription_stub_confirm(
    body: SubscriptionStubConfirmBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    In sandbox/stub mode: gateway returns to front with payment_stub=1&tracking_id=inv_XXX
    and does not send webhook. Front calls this to confirm the subscription invoice.

    When not in sandbox: allows confirming invoices with amount_cents == 0 that are fully
    covered by referral bonus days (no card payment).
    """
    settings = Settings()
    # Linked Telegram enough: API-created trainers stay pending_profile until moderation;
    # zero-amount referral invoices must still be confirmable in production.
    trainer_id = await get_trainer_id_linked_any_status_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    from sqlalchemy import text

    r = await session.execute(
        text("""
            SELECT trainer_id, amount_cents, COALESCE(referral_bonus_days_applied, 0)
            FROM trainer_invoices WHERE id = :iid
        """),
        {"iid": body.invoice_id},
    )
    row = r.fetchone()
    if not row or row[0] != trainer_id:
        raise HTTPException(status_code=403, detail="Invoice not found or not yours")
    if not settings.payment_sandbox:
        if int(row[1] or 0) != 0 or int(row[2] or 0) <= 0:
            raise HTTPException(status_code=404, detail="Not available when payment_sandbox is false")
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
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    List subscription tiers with pricing for catalog display.
    
    Returns CRM, Online, Analytics tiers with prices, periods, and descriptions.
    Auth: trainer initData.
    """
    trainer_id = await get_trainer_id_linked_any_status_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    await ensure_trainer_welcome_trial(session, trainer_id)
    
    tiers = await get_subscription_tier_catalog(session)
    constructor = await get_subscription_constructor_catalog(session)
    # Same flag as stub-confirm: no free activation when real payments are enforced.
    settings_cat = Settings()
    mock_enabled = settings_cat.payment_sandbox
    checkout_mode = settings_cat.resolved_trainer_subscription_checkout_mode()
    return {
        "tiers": tiers,
        "constructor": constructor,
        "mock_checkout_enabled": mock_enabled,
        "checkout_mode": checkout_mode,
    }


@router.get("/trainer/subscription/status")
async def get_trainer_subscription_tier_status(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Get trainer's current subscription status.
    
    Returns effective tier, expiration date, and unlocked features.
    Auth: trainer initData.
    """
    trainer_id = await get_trainer_id_linked_any_status_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    await ensure_trainer_welcome_trial(session, trainer_id)

    status = await get_trainer_subscription_status(session, trainer_id)
    return status


class SubscriptionConstructorCheckoutBody(BaseModel):
    """Either legacy `tier` bundle or independent `modules` (crm base is always included)."""

    period_months: Literal[1, 3, 12]
    tier: str | None = None
    modules: dict | None = None


@router.post("/trainer/subscription/bepaid-checkout")
async def post_trainer_subscription_bepaid_checkout(
    body: SubscriptionConstructorCheckoutBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    bePaid: create catalog invoice for tier bundle or CRM+modules constructor, return gateway checkout URL.
    Mini App uses this instead of trainer-pay-subscription (legacy plan_id list) when checkout_mode=bepaid.
    """
    settings = Settings()
    if settings.payment_sandbox:
        raise HTTPException(
            status_code=400,
            detail="Режим песочницы: оплата через демо на странице подписки, не через bePaid.",
        )
    if settings.resolved_trainer_subscription_checkout_mode() != "bepaid":
        raise HTTPException(
            status_code=400,
            detail="Оплата картой (bePaid) сейчас недоступна — проверьте режим подписки в настройках.",
        )
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)

    if body.tier is not None and body.modules is not None:
        raise HTTPException(status_code=400, detail="Send either tier or modules, not both")
    if body.tier is None and body.modules is None:
        raise HTTPException(status_code=400, detail="Specify tier or modules")

    inv = await create_catalog_subscription_invoice_for_trainer(
        session,
        trainer_id,
        tier=body.tier,
        modules=body.modules,
        period_months=int(body.period_months),
    )
    if not inv:
        raise HTTPException(status_code=400, detail="Could not create payment for this selection")

    invoice_id = int(inv["invoice_id"])
    amount_cents = int(inv["amount_cents"])
    period_start = inv["period_start"]
    period_end = inv["period_end"]
    plan_name = str(inv.get("plan_name") or "Подписка")
    referral_bonus_days_applied = int(inv.get("referral_bonus_days_applied") or 0)
    amount_cents_before_referral = inv.get("amount_cents_before_referral")

    webapp_base = (settings.webapp_base_url or "").rstrip("/")
    api_base = (settings.api_base_url or webapp_base).rstrip("/")
    return_url = f"{webapp_base}/webapp/trainer-pay-subscription?payment_success=1"
    notification_url = f"{api_base}/api/webhooks/bepaid"
    tracking_id = f"inv_{invoice_id}"

    def _date_str(d):
        if d is None:
            return None
        return d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]

    out: dict = {
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "plan_name": plan_name,
        "period_start": _date_str(period_start),
        "period_end": _date_str(period_end),
        "referral_bonus_days_applied": referral_bonus_days_applied,
        "amount_cents_before_referral": amount_cents_before_referral,
        "referral_fully_covered": bool(amount_cents <= 0 and referral_bonus_days_applied > 0),
    }
    if amount_cents <= 0:
        out["payment_url"] = None
        return out

    result = await create_checkout(
        amount_cents=amount_cents,
        currency="BYN",
        description=plan_name[:255],
        tracking_id=tracking_id,
        return_url=return_url,
        notification_url=notification_url,
        success_url=return_url,
    )
    out["payment_url"] = result["payment_url"]
    return out


@router.post("/trainer/subscription/invoice-request")
async def post_trainer_subscription_invoice_request(
    body: SubscriptionConstructorCheckoutBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    ERIP / manual: create unpaid catalog invoice (tier or constructor) and notify admins.
    Mini App calls this when checkout_mode=invoice (not bePaid, not sandbox demo).
    """
    settings = Settings()
    if settings.resolved_trainer_subscription_checkout_mode() != "invoice":
        raise HTTPException(
            status_code=400,
            detail="Запрос счёта доступен только в режиме «счёт / ЕРИП» (invoice).",
        )
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)

    if body.tier is not None and body.modules is not None:
        raise HTTPException(status_code=400, detail="Send either tier or modules, not both")
    if body.tier is None and body.modules is None:
        raise HTTPException(status_code=400, detail="Specify tier or modules")

    inv = await create_catalog_subscription_invoice_for_trainer(
        session,
        trainer_id,
        tier=body.tier,
        modules=body.modules,
        period_months=int(body.period_months),
    )
    if not inv:
        raise HTTPException(status_code=400, detail="Could not create invoice for this selection")

    invoice_id = int(inv["invoice_id"])
    try:
        await notify_admins_new_catalog_subscription_invoice(invoice_id)
    except Exception:
        logger.exception("subscription invoice-request: admin notify failed invoice_id=%s", invoice_id)

    return {
        "ok": True,
        "invoice_id": invoice_id,
        "amount_cents": int(inv["amount_cents"]),
        "plan_name": str(inv.get("plan_name") or "Подписка"),
        "referral_bonus_days_applied": int(inv.get("referral_bonus_days_applied") or 0),
        "amount_cents_before_referral": inv.get("amount_cents_before_referral"),
        "referral_fully_covered": bool(int(inv["amount_cents"]) <= 0 and int(inv.get("referral_bonus_days_applied") or 0) > 0),
    }


@router.post("/trainer/subscription/mock-checkout")
async def post_trainer_subscription_mock_checkout(
    body: SubscriptionConstructorCheckoutBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Mock checkout: legacy tier bundle OR CRM + module constructor.

    Disabled when payment_sandbox is false (production real payments); use bePaid flow instead.
    Auth: trainer initData.
    """
    if not Settings().payment_sandbox:
        raise HTTPException(
            status_code=404,
            detail="Mock checkout is not available when payment_sandbox is disabled",
        )
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)

    if body.tier is not None and body.modules is not None:
        raise HTTPException(status_code=400, detail="Send either tier or modules, not both")

    if body.tier is not None:
        if body.tier not in SUBSCRIPTION_TIERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tier. Must be one of: {', '.join(SUBSCRIPTION_TIERS)}",
            )
        result = await set_subscription_after_mock_payment(
            session, trainer_id, body.tier, body.period_months
        )
    elif body.modules is not None:
        result = await set_subscription_constructor_after_mock_payment(
            session, trainer_id, normalize_modules_dict(body.modules), body.period_months
        )
    else:
        raise HTTPException(status_code=400, detail="Specify tier or modules")

    if not result:
        raise HTTPException(status_code=400, detail="Could not activate tier subscription")

    out: dict = {
        "ok": True,
        "tier": result["tier"],
        "expires_at": result["expires_at"],
        "price_cents": result["price_cents"],
        "currency": result["currency"],
        "period_days": result["period_days"],
        "period_months": result["period_months"],
    }
    if "modules" in result:
        out["modules"] = result["modules"]
    return out


# --- Trainer pass products (subscription products for sale) ---


@router.get("/trainer/pass-products")
async def get_trainer_pass_products(
    active_only: bool = Query(False, description="If true, return only is_active=true"),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """List trainer's pass products. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED)
    items = await list_pass_products(session, trainer_id, active_only=active_only)
    return {"items": items}


class PassProductCreateBody(BaseModel):
    name: str
    sessions_total: int
    price_cents: int
    service_ids: list[int] = Field(default_factory=list)
    sort_order: int = 0


@router.post("/trainer/pass-products")
async def post_trainer_pass_product(
    body: PassProductCreateBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Create a pass product. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED)
    try:
        product_id = await create_pass_product(
            session,
            trainer_id,
            name=body.name,
            sessions_total=body.sessions_total,
            price_cents=body.price_cents,
            service_ids=list(body.service_ids or []),
            sort_order=body.sort_order,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"success": True, "id": product_id}


class PassProductPatchBody(BaseModel):
    name: str | None = None
    sessions_total: int | None = None
    price_cents: int | None = None
    service_ids: list[int] | None = None
    is_active: bool | None = None
    sort_order: int | None = None


@router.patch("/trainer/pass-products/{product_id:int}")
async def patch_trainer_pass_product(
    product_id: int,
    body: PassProductPatchBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Update pass product. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED)
    patch = body.model_dump(exclude_unset=True)
    try:
        ok = await update_pass_product(session, product_id, trainer_id, **patch)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"success": True}


@router.delete("/trainer/pass-products/{product_id:int}")
async def delete_trainer_pass_product(
    product_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Delete pass product only if no purchases. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED)
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
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """List cities for admin: id, name, sort_order, arenas_count, is_active."""
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
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Create city (for catalog). Admin only."""
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
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Update city name/sort_order. Admin only."""
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
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """List arenas for a city: id, name, address, lat/lon, sort_order, is_active."""
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
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Create arena in a city. Admin only."""
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
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Update arena fields. Admin only."""
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
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
):
    """Resolve address to coordinates (Nominatim/OSM). Admin only. For Belarus/global addresses."""
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
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    List all subscription tier pricing records for admin editing.
    
    Returns CRM, Online, Analytics tiers with prices, descriptions, active status.
    Auth: admin initData.
    """
    
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
    principal: MiniAppPrincipal = Depends(get_admin_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Update subscription tier pricing. Changes are logged to audit table.
    
    Auth: admin initData. Tier must be one of: crm, online, analytics.
    """
    admin_tid = principal.user_id
    
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
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """List trainer's certificate products. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    items = await list_certificate_products(session, trainer_id, active_only=active_only)
    return {"items": items}


class CertificateProductCreateBody(BaseModel):
    name: str | None = None  # optional display title; server picks default from amount if omitted
    description: str | None = None
    amount_cents: int | None = None  # None = "любая сумма"
    expires_in_days: int | None = None
    sort_order: int = 0


@router.post("/trainer/certificate-products")
async def post_trainer_certificate_product(
    body: CertificateProductCreateBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Create certificate product. amount_cents=null means 'any amount'. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    product_id = await create_certificate_product(
        session,
        trainer_id,
        name=body.name,
        description=body.description,
        amount_cents=body.amount_cents,
        sort_order=body.sort_order,
        expires_in_days=body.expires_in_days,
    )
    return {"success": True, "id": product_id}


class CertificateProductPatchBody(BaseModel):
    name: str | None = None
    description: str | None = None  # null or "" clears; omit = do not change
    amount_cents: int | None = None  # None = "любая сумма"; omit = do not change
    expires_in_days: int | None = None
    is_active: bool | None = None
    sort_order: int | None = None


@router.patch("/trainer/certificate-products/{product_id:int}")
async def patch_trainer_certificate_product(
    product_id: int,
    body: CertificateProductPatchBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Update certificate product. Auth: trainer initData. Use model_dump(exclude_unset=True) to only send changed fields."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    payload = body.model_dump(exclude_unset=True)
    name = payload.get("name") if "name" in payload else None
    description = (
        payload.get("description") if "description" in payload else DESCRIPTION_UNSET
    )
    amount_cents = payload.get("amount_cents") if "amount_cents" in payload else AMOUNT_CENTS_UNSET
    expires_in_days = payload.get("expires_in_days") if "expires_in_days" in payload else None
    is_active = payload.get("is_active") if "is_active" in payload else None
    sort_order = payload.get("sort_order") if "sort_order" in payload else None
    ok = await update_certificate_product(
        session,
        product_id,
        trainer_id,
        name=name,
        description=description,
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
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Delete certificate product. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    ok = await delete_certificate_product(session, product_id, trainer_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"success": True}


@router.get("/trainer/certificates")
async def get_trainer_certificates(
    active_only: bool = Query(True, description="If true, return only active (for redeem list)"),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """List certificate instances issued by this trainer. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
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
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
):
    """Issue a certificate: create instance, generate PDF, save file_url; optionally send PDF to recipient_email. Idempotent by Idempotency-Key. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
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
            client_bot_display_name=f"@{_un}" if _un else None,
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
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Download certificate PDF. Auth: trainer initData; certificate must belong to trainer."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
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

@router.get("/trainer/welcome-link/eligibility")
async def get_trainer_welcome_link_eligibility(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Services list and whether trainer must pick one for generic welcome link."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    services = await list_trainer_services_for_welcome_link(session, trainer_id)
    return {
        "require_service_choice": len(services) > 1,
        "services": services,
    }


@router.get("/trainer/public-booking-link/eligibility")
async def get_trainer_public_booking_link_eligibility(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Services list for reusable public booking link. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_allows_online_booking(session, trainer_id):
        raise HTTPException(
            status_code=403,
            detail="Публичная ссылка доступна только на тарифе с онлайн-записью.",
        )
    services = await list_trainer_services_for_welcome_link(session, trainer_id)
    city_id, _ = await get_trainer_default_city_and_service(session, trainer_id)
    return {
        "require_service_choice": len(services) > 1,
        "services": services,
        "city_configured": city_id is not None,
    }


@router.get("/trainer/public-booking-link")
async def get_trainer_public_booking_link(
    service_id: int | None = Query(
        None, description="Required when trainer has multiple services; pins booking to service"
    ),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Reusable public link for Instagram/social posts.
    Deep-link payload matches client bot /start client_{city}_{service_or_0}_{trainer}.
    When service_id is omitted, client first chooses service in the booking flow.
    """
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_allows_online_booking(session, trainer_id):
        raise HTTPException(
            status_code=403,
            detail="Публичная ссылка доступна только на тарифе с онлайн-записью.",
        )
    services = await list_trainer_services_for_welcome_link(session, trainer_id)
    service_ids = {int(s["id"]) for s in services if s.get("id") is not None}
    if not service_ids:
        raise HTTPException(
            status_code=400,
            detail="В профиле нет услуг — добавьте услугу в профиле.",
        )
    if service_id is not None and int(service_id) not in service_ids:
        raise HTTPException(status_code=400, detail="Неверная услуга.")
    resolved_service_id = int(service_id) if service_id is not None else None
    city_id, _ = await get_trainer_default_city_and_service(session, trainer_id)
    if city_id is None:
        raise HTTPException(
            status_code=400,
            detail="Укажите город в профиле, чтобы сформировать публичную ссылку.",
        )
    settings = Settings()
    links, build_err = build_trainer_invite_links(
        webapp_base_url=settings.webapp_base_url,
        client_bot_username=settings.client_bot_username,
        city_id=city_id,
        service_id=resolved_service_id,
        trainer_id=trainer_id,
    )
    if build_err == "missing_username":
        return {"booking_link": None}
    if build_err == "missing_city_or_service":
        raise HTTPException(
            status_code=400,
            detail="Укажите город и услугу в профиле, чтобы сформировать публичную ссылку.",
        )
    assert links is not None
    return {
        "booking_link": links.client_bot_deep_link,
        "service_id": resolved_service_id,
    }


@router.get("/trainer/welcome-link")
async def get_trainer_welcome_link(
    service_id: int | None = Query(
        None,
        description="Optional; pins catalog prefill. If omitted with several services, first catalog service is used.",
    ),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Generic one-time invite link. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    resolved_service_id, err = await resolve_service_id_for_generic_welcome_link(
        session, trainer_id, service_id
    )
    if err == "no_services":
        raise HTTPException(
            status_code=400,
            detail="В профиле нет услуг — добавьте услугу в профиле.",
        )
    if err == "invalid_service":
        raise HTTPException(status_code=400, detail="Неверная услуга.")
    assert resolved_service_id is not None
    settings = Settings()
    if not settings.client_bot_username:
        return {"welcome_link": None}
    token_id = await create_welcome_link_token(
        session,
        WELCOME_TOKEN_TYPE_GENERIC,
        trainer_id,
        service_id=resolved_service_id,
    )
    link = (
        f"https://t.me/{settings.client_bot_username.lstrip('@')}?start=welcome_t_{token_id}"
    )
    return {"welcome_link": link}


@router.post("/trainer/welcome-link/first-copy")
async def post_trainer_welcome_link_first_copy(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Idempotent: record first time trainer copied a client-facing link (welcome, bind, public booking, pass).
    Fire-and-forget from Mini App after successful clipboard write.
    """
    from src.application.trainer_client_invite_tracking import record_trainer_client_invite_link_first_copy

    trainer_id = await get_trainer_id_linked_any_status_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    ts = await record_trainer_client_invite_link_first_copy(session, trainer_id)
    return {"first_copied_at": ts.isoformat() if ts else None}


@router.get("/trainer/clients/{client_id:int}/welcome-link")
async def get_trainer_client_welcome_link(
    client_id: int,
    service_id: int | None = Query(
        None,
        description="Optional; pins catalog prefill. If omitted with several services, first catalog service is used.",
    ),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    One-time welcome link that binds the opening Telegram account to this existing client row
    (trainer-created client without telegram_id). Same service_id rules as generic welcome link.
    """
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    client = await get_trainer_client_for_card(session, trainer_id, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Клиент не найден или нет доступа")
    if client.get("telegram_id") is not None:
        raise HTTPException(
            status_code=400,
            detail="Клиент уже подключён к Telegram — персональная ссылка не нужна.",
        )
    resolved_service_id, err = await resolve_service_id_for_generic_welcome_link(
        session, trainer_id, service_id
    )
    if err == "no_services":
        raise HTTPException(
            status_code=400,
            detail="В профиле нет услуг — добавьте услугу в профиле.",
        )
    if err == "invalid_service":
        raise HTTPException(status_code=400, detail="Неверная услуга.")
    assert resolved_service_id is not None
    settings = Settings()
    if not settings.client_bot_username:
        return {"welcome_link": None}
    token_id = await create_welcome_link_token(
        session,
        WELCOME_TOKEN_TYPE_CLIENT_BIND,
        trainer_id,
        service_id=resolved_service_id,
        client_id=client_id,
    )
    link = (
        f"https://t.me/{settings.client_bot_username.lstrip('@')}?start=welcome_t_{token_id}"
    )
    return {"welcome_link": link}


@router.get("/trainer/hub/universal-invite-link")
async def get_trainer_hub_universal_invite_link(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Permanent universal invite link for trainer's hub share button.
    Returns welcome_ref_{trainer_id} deep link — works for all clients regardless of subscription tier.
    Unknown clients are routed to the self-registration Mini App form.

    Auth: any linked trainer row (same as hub lifecycle / onboarding), not catalog ``active`` —
    trainers waiting moderation must still share invite links from the hub.
    """
    trainer_id = await get_trainer_id_linked_any_status_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    settings = Settings()
    if not settings.client_bot_username:
        return {"link": None}
    username = settings.client_bot_username.lstrip("@")
    link = f"https://t.me/{username}?start=welcome_ref_{trainer_id}"
    return {"link": link}


class ClientSelfRegisterBody(BaseModel):
    """Self-registration payload from the client-register Mini App."""

    trainer_id: int
    phone: str
    first_name: str
    last_name: str | None = None


@router.post("/client/self-register")
async def post_client_self_register(
    body: ClientSelfRegisterBody,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Client self-registration via the trainer's universal invite link.
    Looks up by phone: links Telegram ID to existing trainer-created client,
    or creates a new client row and adds them to the trainer's roster.
    """
    telegram_id = client_catalog_telegram_key(principal)

    phone_norm = normalize_phone(body.phone)
    if not phone_norm or len(phone_norm) < 9:
        raise HTTPException(status_code=422, detail="Некорректный номер телефона.")
    # Belarus: +375 + 9 digits = 12 normalized digits
    if not phone_norm.startswith("375") or len(phone_norm) != 12:
        raise HTTPException(
            status_code=422,
            detail="Введите номер Беларуси в формате +375 XX XXX-XX-XX.",
        )

    first_name = (body.first_name or "").strip()[:64]
    if not first_name:
        raise HTTPException(status_code=422, detail="Укажите имя.")

    trainer = await get_trainer(session, body.trainer_id)
    if not trainer:
        raise HTTPException(status_code=404, detail="Тренер не найден.")

    existing_by_phone = await get_client_by_phone(session, body.phone)
    if (
        existing_by_phone
        and existing_by_phone.get("telegram_id") is not None
        and int(existing_by_phone["telegram_id"]) != telegram_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Этот номер уже используется другим аккаунтом Telegram.",
        )

    existing_phone_client_id = int(existing_by_phone["id"]) if existing_by_phone else None
    had_roster_before = (
        await trainer_client_roster_link_exists(session, body.trainer_id, existing_phone_client_id)
        if existing_phone_client_id is not None
        else False
    )
    prior_tid_client_id = await get_client_id_by_telegram_id(session, telegram_id)
    last_name = (body.last_name or "").strip()[:64] or None
    client_id = await get_or_create_client(
        session,
        telegram_id,
        phone=body.phone,
        first_name=first_name,
        last_name=last_name,
    )
    roster_link_created = await link_trainer_client_roster(session, body.trainer_id, client_id)
    await session.commit()

    notify_event = None
    if roster_link_created:
        notify_event = "new_client"
    elif (
        existing_by_phone
        and existing_phone_client_id == client_id
        and existing_by_phone.get("telegram_id") is None
        and had_roster_before
    ):
        notify_event = "telegram_linked"

    if notify_event is not None:
        await notify_trainer_client_registered_from_invite(
            session=session,
            trainer_id=body.trainer_id,
            client_id=client_id,
            event=notify_event,
        )

    if existing_by_phone and int(existing_by_phone["id"]) == client_id:
        if existing_by_phone.get("telegram_id") is None:
            status = "linked"
        else:
            status = "already_registered"
    elif prior_tid_client_id is None and existing_by_phone is None:
        status = "created"
    else:
        status = "already_registered"

    return {"status": status, "client_id": client_id}


@router.get("/client/register/trainer-info/{trainer_id}")
async def get_client_register_trainer_info(
    trainer_id: int,
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Public trainer info for the self-registration form (name + photo).
    Auth: client initData (unregistered users are allowed — no client row required).
    """
    hints = await trainer_display_hints_by_ids(session, [trainer_id])
    hint = hints.get(trainer_id)
    if not hint:
        raise HTTPException(status_code=404, detail="Тренер не найден.")
    name = hint.get("trainer_display_name") or "Тренер"
    return {"id": trainer_id, "name": name}


@router.get("/trainer/welcome-link/pass")
async def get_trainer_welcome_link_pass(
    pass_product_id: int = Query(..., description="Pass product id (must belong to trainer)"),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """One-time pass invite link. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
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
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """One-time cert welcome link: issue cert (no recipient name/phone), create token, return link. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
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
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Redeem certificate by code. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
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
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Redeem certificate by instance id. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    result = await redeem_certificate(session, trainer_id, certificate_instance_id=certificate_id)
    if not result:
        raise HTTPException(status_code=404, detail="Certificate not found or already redeemed")
    return result


@router.get("/client/certificate-products")
async def get_client_certificate_products(
    trainer_id: int = Query(..., description="Trainer whose certificate products to list"),
    session: AsyncSession = Depends(get_session),
    _principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """List active certificate products for a trainer (info only for client). Auth: client initData."""
    items = await list_certificate_products(session, trainer_id, active_only=True)
    return {"items": items}


@router.get("/trainer/bookings")
async def get_trainer_bookings(
    limit: int = Query(100, ge=1, le=500),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """List trainer's upcoming bookings grouped by day. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)

    payload = await _trainer_bookings_grouped_days_payload(session, trainer_id, limit=limit)
    payload["force_client_chat_relay"] = bool(Settings().trainer_webapp_force_client_chat_relay)
    return payload


@router.get("/trainer/slots/{slot_id:int}/group-hub")
async def get_trainer_group_slot_hub_api(
    slot_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Group slot summary + booking rows (trainer hub modal). Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    hub = await get_trainer_group_slot_hub(session, trainer_id, slot_id)
    if not hub:
        raise HTTPException(status_code=404, detail="Slot not found or not a group slot")
    return hub


@router.get("/trainer/bookings/{booking_id:int}")
async def get_trainer_booking_detail(
    booking_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """One booking detail with recurring info. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)

    b = await get_trainer_booking_detail_payload(session, booking_id, trainer_id)
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    await enrich_booking_dicts_with_client_telegram_usernames(session, [b])
    flow_ok = booking_problem_api_allowed_for_trainer(trainer_id)
    detail = _serialize_booking(b, problem_flow_enabled=flow_ok)
    slot_date = b.get("slot_date")
    if hasattr(slot_date, "weekday"):
        detail["day_label"] = TRAINER_DAYS[slot_date.weekday()]
    else:
        detail["day_label"] = ""
    booking = await get_booking_with_slot(session, booking_id, trainer_id)
    if booking:
        detail["client_id"] = booking["client_id"]
    recurring = None
    if booking:
        recurring = await get_active_recurring_for_booking(
            session, trainer_id, booking["client_id"],
            b["slot_date"].weekday(), b["start_time"],
        )
    detail["recurring_id"] = recurring["id"] if recurring else None
    ppc = await classify_booking_problem_payment_class(session, booking_id, trainer_id)
    detail["problem_payment_class"] = ppc
    if ppc == "PASS":
        detail["pass_cert_instrument_hint"] = "абонемент"
    elif ppc == "CERT":
        detail["pass_cert_instrument_hint"] = "сертификат"
    else:
        detail["pass_cert_instrument_hint"] = None

    edit_ctx = await load_booking_service_edit_context(session, booking_id, trainer_id)
    detail["service_edit"] = (
        await resolve_booking_service_edit_ui_flags(session, trainer_id, edit_ctx)
        if edit_ctx
        else {
            "allowed": False,
            "reason": None,
            "service_locked": False,
            "can_edit_service": False,
            "can_edit_tier": False,
        }
    )

    return detail


class TrainerBookingServicePatchBody(BaseModel):
    service_id: int
    service_price_variant_id: int | None = None


_PATCH_BOOKING_SERVICE_HTTP: dict[str, tuple[int, str]] = {
    "not_found": (404, "Запись не найдена"),
    "not_editable": (400, "Для этой записи услугу и тариф изменить нельзя"),
    "group_service_locked": (400, "У группового слота услуга зафиксирована"),
    "invalid_service": (400, "Услуга не найдена в вашем профиле"),
    "invalid_tier": (400, "Тариф не подходит к выбранной услуге"),
    "tier_required": (400, "Выберите тариф"),
}


@router.patch("/trainer/bookings/{booking_id:int}/service")
async def patch_trainer_booking_service(
    booking_id: int,
    body: TrainerBookingServicePatchBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Update service and price tier snapshot on a pending/confirmed individual booking.

    Does not notify the client; standard reminders pick up the new service/price when they fire.
    """
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)

    detail, err = await update_trainer_booking_service(
        session,
        booking_id,
        trainer_id,
        int(body.service_id),
        body.service_price_variant_id,
    )
    if err:
        status, msg = _PATCH_BOOKING_SERVICE_HTTP.get(err, (400, "Не удалось обновить запись"))
        edit_ctx = await load_booking_service_edit_context(session, booking_id, trainer_id)
        if edit_ctx and err == "not_editable":
            policy = await resolve_booking_service_edit_ui_flags(session, trainer_id, edit_ctx)
            if policy.get("reason"):
                msg = policy["reason"]
        raise HTTPException(status_code=status, detail=msg)
    if not detail:
        raise HTTPException(status_code=404, detail="Запись не найдена")

    await enrich_booking_dicts_with_client_telegram_usernames(session, [detail])
    flow_ok = booking_problem_api_allowed_for_trainer(trainer_id)
    out = _serialize_booking(detail, problem_flow_enabled=flow_ok)
    slot_date = detail.get("slot_date")
    if hasattr(slot_date, "weekday"):
        out["day_label"] = TRAINER_DAYS[slot_date.weekday()]
    else:
        out["day_label"] = ""
    out["recurring_id"] = None
    booking = await get_booking_with_slot(session, booking_id, trainer_id)
    if booking:
        out["client_id"] = booking["client_id"]
        slot_date = detail.get("slot_date")
        start_time = detail.get("start_time")
        recurring = await get_active_recurring_for_booking(
            session,
            trainer_id,
            booking["client_id"],
            slot_date.weekday() if hasattr(slot_date, "weekday") else 0,
            start_time,
        )
        out["recurring_id"] = recurring["id"] if recurring else None
    ppc = await classify_booking_problem_payment_class(session, booking_id, trainer_id)
    out["problem_payment_class"] = ppc
    if ppc == "PASS":
        out["pass_cert_instrument_hint"] = "абонемент"
    elif ppc == "CERT":
        out["pass_cert_instrument_hint"] = "сертификат"
    else:
        out["pass_cert_instrument_hint"] = None
    edit_ctx = await load_booking_service_edit_context(session, booking_id, trainer_id)
    out["service_edit"] = (
        await resolve_booking_service_edit_ui_flags(session, trainer_id, edit_ctx)
        if edit_ctx
        else {
            "allowed": False,
            "reason": None,
            "service_locked": False,
            "can_edit_service": False,
            "can_edit_tier": False,
        }
    )
    return out


@router.get("/trainer/bookings/{booking_id:int}/client-no-show-options")
async def get_trainer_booking_client_no_show_options_route(
    booking_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """PASS/CERT: copy for «Клиент не пришёл» modal (no booking_problem_reports)."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not booking_problem_api_allowed_for_trainer(trainer_id):
        raise HTTPException(status_code=403, detail="booking_problem_rollout")
    data = await get_trainer_booking_client_no_show_options(session, booking_id, trainer_id)
    if not data:
        raise HTTPException(status_code=404, detail="Not found")
    return data


class TrainerClientNoShowBody(BaseModel):
    choice: str = Field(..., min_length=8, max_length=32)
    source: str | None = Field(None, max_length=32)


@router.post("/trainer/bookings/{booking_id:int}/client-no-show")
async def post_trainer_booking_client_no_show_route(
    booking_id: int,
    body: TrainerClientNoShowBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not booking_problem_api_allowed_for_trainer(trainer_id):
        raise HTTPException(status_code=403, detail="booking_problem_rollout")
    err, msg = await submit_trainer_booking_client_no_show(
        session,
        booking_id,
        trainer_id,
        body.choice,
        source=body.source or "mini_app",
    )
    if err == "not_found":
        raise HTTPException(status_code=404, detail=msg or "Not found")
    if err == "bad_state":
        raise HTTPException(status_code=400, detail=msg or "Invalid state")
    if err == "conflict":
        raise HTTPException(status_code=409, detail=msg or "Conflict")
    if err == "bad_request":
        raise HTTPException(status_code=400, detail=msg or "Bad request")
    await send_booking_client_no_show_telegram_notifications(session, booking_id)
    return {"success": True}


class TrainerBookingProblemBody(BaseModel):
    preset_id: str = Field(..., min_length=1, max_length=32)
    note: str | None = Field(None, max_length=4000)
    source: str | None = Field(None, max_length=32)
    # PASS/CERT + B1: explicit redeem|skip from Mini App (overrides trainer default when sent).
    pass_cert_no_show_choice: str | None = Field(None, max_length=16)
    # Preset A1 only: attention | blacklist | absence_only (how to reflect no-show on the client).
    client_action: str | None = Field(None, max_length=24)


@router.get("/trainer/bookings/{booking_id:int}/problem-options")
async def get_trainer_booking_problem_options_route(
    booking_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Presets + payment class + pass/cert no-show policy (PRD E3); copy for trainer consent (E2)."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not booking_problem_api_allowed_for_trainer(trainer_id):
        raise HTTPException(status_code=403, detail="booking_problem_rollout")
    data = await get_trainer_booking_problem_options(session, booking_id, trainer_id)
    if not data:
        raise HTTPException(status_code=404, detail="Booking not found")
    return data


@router.post("/trainer/bookings/{booking_id:int}/problem")
async def post_trainer_booking_problem_route(
    booking_id: int,
    body: TrainerBookingProblemBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not booking_problem_api_allowed_for_trainer(trainer_id):
        raise HTTPException(status_code=403, detail="booking_problem_rollout")
    err, msg = await submit_trainer_booking_problem(
        session,
        booking_id,
        trainer_id,
        body.preset_id,
        body.note,
        body.source or "mini_app",
        pass_cert_no_show_choice=body.pass_cert_no_show_choice,
        client_action=body.client_action,
    )
    if err == "not_found":
        raise HTTPException(status_code=404, detail=msg or "Not found")
    if err == "bad_state":
        raise HTTPException(status_code=400, detail=msg or "Invalid state")
    if err == "conflict":
        raise HTTPException(status_code=409, detail=msg or "Already reported")
    if err == "bad_preset":
        raise HTTPException(status_code=400, detail=msg or "Invalid preset")
    if err == "bad_request":
        raise HTTPException(status_code=400, detail=msg or "Bad request")
    await send_booking_problem_telegram_notifications(session, booking_id)
    return {"success": True}


class DeclineBody(BaseModel):
    comment: str


@router.post("/trainer/bookings/{booking_id:int}/confirm")
async def post_trainer_booking_confirm(
    booking_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
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
            trainer_first_booking_milestone=bool(info.get("first_booking_milestone")),
        )
        reply_markup = msg.build_client_booking_confirmed_inline_keyboard(
            map_url=info.get("map_link"),
            trainer_telegram_id=info.get("trainer_telegram_id"),
        )
        try:
            await client_bot.send_message(
                chat_id=client_tid,
                text=text_client,
                reply_markup=reply_markup,
            )
        finally:
            await client_bot.session.close()
    return {
        "success": True,
        "first_booking_milestone": bool(info.get("first_booking_milestone")),
        "share_catalog_tip": bool(info.get("share_catalog_tip")),
    }


@router.post("/trainer/bookings/{booking_id:int}/decline")
async def post_trainer_booking_decline(
    booking_id: int,
    body: DeclineBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
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
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    ok = await cancel_booking(session, booking_id, trainer_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Cancel failed")
    settings = Settings()
    client_bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await send_trainer_cancel_notification_for_booking_now(
            client_bot, session, booking_id
        )
    finally:
        await client_bot.session.close()
    return {"success": True}


@router.delete("/trainer/bookings/{booking_id:int}/schedule-history")
async def delete_trainer_booking_schedule_history(
    booking_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Remove a past booking from schedule and trainer-facing aggregates (soft status).
    Only allowed after slot end (Europe/Minsk). Restores pass/cert ledger when applicable.
    """
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    ok, code = await purge_past_booking_from_schedule_history(session, trainer_id, booking_id)
    if ok:
        return {"success": True}
    if code == "not_found":
        raise HTTPException(status_code=404, detail="Запись не найдена")
    raise HTTPException(
        status_code=400,
        detail="Можно убрать только прошедшие записи (время слота уже должно закончиться).",
    )


@router.post("/trainer/bookings/{booking_id:int}/complete")
async def post_trainer_booking_complete(
    booking_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Mark booking as conducted (completed). Redeems one pass session if client has a matching pass. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    result = await mark_booking_completed_by_trainer(session, booking_id, trainer_id)
    if not result:
        raise HTTPException(status_code=400, detail="Booking not found or not confirmed")
    return result


class TrainerCreateBookingBody(BaseModel):
    """Create booking from schedule: trainer picks slot + client + service; optional venue (non-primary)."""
    slot_id: int
    client_id: int
    service_id: int
    arena_id: int | None = None
    service_price_variant_id: int | None = None  # individual slot: optional tier; ignored for group slots (capacity>1)
    allow_overbook: bool = False  # trainer-only: group slot (capacity>1) may exceed nominal capacity


class TrainerQuickBookingBody(BaseModel):
    """Trainer quick book: slot_date + start_time creates individual slot if missing, then books client."""
    slot_date: str  # YYYY-MM-DD
    start_time: str | None = Field(default=None, description="HH:MM (15 min grid; preferred)")
    start_hour: int | None = Field(default=None, ge=0, le=23, description="legacy: same as HH:00")
    duration_minutes: int = Field(default=45, ge=15, le=24 * 60)
    client_id: int
    service_id: int
    arena_id: int | None = None
    service_price_variant_id: int | None = None
    #: Onboarding «пример»: excluded from stats/milestones; no reminders / post-booking bot nudge.
    is_sandbox: bool = False


class TrainerCreateClientBody(BaseModel):
    """Create or update client by phone (no telegram_id); link to trainer CRM roster."""

    phone: str
    first_name: str = Field(min_length=1, max_length=64)
    last_name: str = Field(default="", max_length=64)
    middle_name: str = Field(default="", max_length=64)
    #: Sandbox client (onboarding demo): server overrides phone with deterministic per-trainer phantom,
    #: and sets ``clients.is_sandbox=true`` so the row is excluded from CRM scope, stats and rhythm hints.
    is_sandbox: bool = False

    @field_validator("phone", mode="before")
    @classmethod
    def _phone_belarus_by(cls, v: object) -> str:
        return coerce_required_belarus_phone(v)

    @field_validator("first_name", "last_name", "middle_name", mode="before")
    @classmethod
    def _strip_names(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()


class TrainerBookingInviteClientBody(BaseModel):
    booking_id: int


@router.get("/trainer/my-services")
async def get_trainer_my_services(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """List services offered by this trainer (for booking: choose service). Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    r = await session.execute(
        text("""
            SELECT s.id, s.name, ts.description, ts.ui_accent
            FROM trainer_services ts
            JOIN services s ON s.id = ts.service_id
            WHERE ts.trainer_id = :tid
            ORDER BY s.sort_order, s.id
        """),
        {"tid": trainer_id},
    )
    rows = r.fetchall()
    service_ids = [row[0] for row in rows]
    tiers_by_sid: dict[int, list[dict]] = {}
    if service_ids:
        rv = await session.execute(
            text(
                f"""
                SELECT service_id, id, label, price_cents, sort_order, tier_kind
                FROM trainer_service_price_variants
                WHERE trainer_id = :tid
                ORDER BY service_id,
                  {sql_order_case_tier_kind("tier_kind")},
                  sort_order
                """
            ),
            {"tid": trainer_id},
        )
        for vrow in rv.fetchall():
            sid_v, vid, lab, pc, so = int(vrow[0]), int(vrow[1]), vrow[2], int(vrow[3]), int(vrow[4])
            tk = normalize_price_tier_kind(vrow[5]) or "adult"
            tiers_by_sid.setdefault(sid_v, []).append(
                {
                    "id": vid,
                    "tier_kind": tk,
                    "label": price_tier_label_ru(tk) or ((lab or "").strip() or "—"),
                    "price_byn": round(pc / 100, 2),
                    "sort_order": so,
                }
            )
    def _service_row_description(row: tuple[Any, ...]) -> str | None:
        if len(row) < 3 or row[2] is None:
            return None
        s = str(row[2]).strip()
        return s if s else None

    def _service_row_ui_accent(row: tuple[Any, ...]) -> str | None:
        if len(row) < 4 or row[3] is None:
            return None
        u = str(row[3]).strip().lower()
        return u if u else None

    services = [
        {
            "id": row[0],
            "name": (row[1] or "").strip() or "—",
            "description": _service_row_description(row),
            "ui_accent": _service_row_ui_accent(row),
            "price_tiers": tiers_by_sid.get(int(row[0]), []),
        }
        for row in rows
    ]

    primary_aid = await get_trainer_primary_arena_resolved(session, trainer_id)
    r2 = await session.execute(
        text(
            """
            SELECT a.id, a.name
            FROM trainer_arenas ta
            JOIN arenas a ON a.id = ta.arena_id
            WHERE ta.trainer_id = :tid
            ORDER BY
              CASE WHEN a.id = :primary_id THEN 0 ELSE 1 END,
              a.name
            """
        ),
        {"tid": trainer_id, "primary_id": primary_aid if primary_aid is not None else -1},
    )
    arena_rows = r2.fetchall()
    arenas = [
        {
            "id": row[0],
            "name": (row[1] or "").strip() or "—",
            "is_primary": primary_aid is not None and row[0] == primary_aid,
        }
        for row in arena_rows
    ]
    return {"services": services, "arenas": arenas}


@router.get("/trainer/clients")
async def get_trainer_clients(
    q: str | None = Query(None, description="Search by name or phone (optional)"),
    recurring_only: bool = Query(False, description="Only clients with at least one active recurring weekly slot"),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """List clients linked to this trainer (bookings, groups, or manual roster). Optional search by name/phone. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    clients = await list_trainer_clients(session, trainer_id, limit=100, recurring_only=recurring_only)
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
    urows: list[dict[str, Any]] = []
    owners: list[dict] = []
    for c in clients:
        if c.get("telegram_id") is None:
            continue
        if (c.get("telegram_username") or "").strip():
            continue
        urows.append(
            {
                "client_telegram_id": c.get("telegram_id"),
                "client_telegram_username": None,
            }
        )
        owners.append(c)
    if urows:
        await enrich_booking_dicts_with_client_telegram_usernames(session, urows)
        for i, c_own in enumerate(owners):
            u_val = urows[i].get("client_telegram_username")
            if u_val:
                c_own["telegram_username"] = u_val
    return {"clients": clients}


async def _trainer_miniapp_client_card_enriched_payload(session: AsyncSession, client: dict) -> dict:
    """Attach freshest telegram username when possible (same as bare card row)."""
    u_row = {
        "client_telegram_id": client.get("telegram_id"),
        "client_telegram_username": (client.get("telegram_username") or "").strip() or None,
    }
    if u_row.get("client_telegram_id") is not None:
        await enrich_booking_dicts_with_client_telegram_usernames(session, [u_row])
        if u_row.get("client_telegram_username"):
            client["telegram_username"] = u_row["client_telegram_username"]
    return {"client": client}


class TrainerClientIdentityPatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, max_length=64)
    last_name: str | None = Field(default=None, max_length=64)
    middle_name: str | None = Field(default=None, max_length=64)


@router.get("/trainer/clients/{client_id:int}/card")
async def get_trainer_client_card(
    client_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Single client summary for card UI (booking roster or active/trial training group member)."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    client = await get_trainer_client_for_card(session, trainer_id, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Клиент не найден или нет доступа")
    return await _trainer_miniapp_client_card_enriched_payload(session, client)


def _parse_trainer_miniapp_hhmm(raw: str) -> time:
    s = (raw or "").strip()
    parts = s.replace(".", ":").split(":")
    if len(parts) < 2:
        raise ValueError("Ожидается время в формате ЧЧ:ММ")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("Некорректное время")
    return time(h, m, 0)


async def _require_trainer_service_for_recurring_materialization(
    session: AsyncSession,
    trainer_id: int,
) -> None:
    """Recurring auto-bookings need a catalog service row to attach prices."""
    if not await get_first_service_id_for_trainer(session, trainer_id):
        raise HTTPException(
            status_code=400,
            detail="Добавьте хотя бы одну услугу в профиль — автозаписи создаются с привязкой к услуге.",
        )


async def _rollback_recurring_unless_full_materialization(
    session: AsyncSession,
    trainer_id: int,
    recurring_id: int,
    *,
    materialized: int,
    horizon_weeks: int,
) -> None:
    """
    Trainer-facing flows are all-or-nothing: if we could not place the full forward window,
    drop the new rule and any bookings created for it, then surface a conflict error.
    """
    hw = max(1, int(horizon_weeks))
    if materialized >= hw:
        return
    await cancel_recurring_client_slot(session, trainer_id, recurring_id)
    raise HTTPException(
        status_code=409,
        detail=(
            f"Создано только {materialized} из {hw} автозаписей: на часть недель это время занято "
            "или пересекается с другим слотом. Закрепление не сохранено — освободите интервалы и попробуйте снова."
        ),
    )


class TrainerClientRecurringCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday .. 6=Sunday")
    start_time: str = Field(..., max_length=8, description="HH:MM")
    end_time: str = Field(..., max_length=8, description="HH:MM")


@router.get("/trainer/clients/{client_id:int}/recurring")
async def get_trainer_client_recurring(
    client_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Active weekly recurring slots + upcoming auto-bookings for this client (trainer CRM)."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    client = await get_trainer_client_for_card(session, trainer_id, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Клиент не найден или нет доступа")
    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover
        from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]
    today = datetime.now(ZoneInfo(NOTIFICATION_TZ)).date()
    slots = await list_active_recurring_slots_for_trainer_client(session, trainer_id, client_id)
    upcoming = await list_upcoming_recurring_bookings_for_trainer_client(
        session, trainer_id, client_id, from_date=today, limit=20
    )
    booking_suggestions = await list_recurring_booking_suggestions_for_trainer_client(
        session, trainer_id, client_id, limit=10
    )
    settings = Settings()
    return {
        "slots": slots,
        "upcoming_bookings": upcoming,
        "booking_suggestions": booking_suggestions,
        "materialization_horizon_weeks": int(settings.recurring_materialization_horizon_weeks),
    }


@router.post("/trainer/clients/{client_id:int}/recurring")
async def post_trainer_client_recurring(
    client_id: int,
    body: TrainerClientRecurringCreateBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Add weekly recurring slot; materializes forward bookings like «Сделать постоянным» from a booking."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    client = await get_trainer_client_for_card(session, trainer_id, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Клиент не найден или нет доступа")
    if bool(client.get("is_sandbox")):
        raise HTTPException(status_code=400, detail="Недоступно для демо-клиента")
    try:
        st = _parse_trainer_miniapp_hhmm(body.start_time)
        et = _parse_trainer_miniapp_hhmm(body.end_time)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if st >= et:
        raise HTTPException(status_code=400, detail="Время окончания должно быть позже начала")
    if await has_other_active_recurring(
        session, trainer_id, body.day_of_week, st, exclude_client_id=client_id
    ):
        raise HTTPException(
            status_code=409,
            detail="На это время уже закреплён другой постоянный клиент.",
        )
    await _require_trainer_service_for_recurring_materialization(session, trainer_id)
    recurring_id = await create_recurring_client_slot(
        session, trainer_id, client_id, body.day_of_week, st, et
    )
    if not recurring_id:
        raise HTTPException(status_code=409, detail="Этот слот уже закреплён для клиента.")
    settings = Settings()
    hw = int(settings.recurring_materialization_horizon_weeks)
    materialized = await materialize_recurring_horizon(
        session,
        trainer_id,
        horizon_weeks=hw,
        recurring_ids=[recurring_id],
    )
    await _rollback_recurring_unless_full_materialization(
        session,
        trainer_id,
        recurring_id,
        materialized=materialized,
        horizon_weeks=hw,
    )
    return {
        "success": True,
        "recurring_id": recurring_id,
        "materialized_bookings": materialized,
    }


class TrainerClientRecurringFromBookingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    booking_id: int = Field(..., ge=1)
    first_week: Literal["this_week", "next_week"] | None = Field(
        default=None,
        description="When the same-week slot is still ahead, trainer chooses where to start the horizon.",
    )


@router.post("/trainer/clients/{client_id:int}/recurring/from-booking")
async def post_trainer_client_recurring_from_booking(
    client_id: int,
    body: TrainerClientRecurringFromBookingBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create weekly recurring rule from an existing booking's weekday and time (trainer CRM mini-app)."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    client = await get_trainer_client_for_card(session, trainer_id, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Клиент не найден или нет доступа")
    if bool(client.get("is_sandbox")):
        raise HTTPException(status_code=400, detail="Недоступно для демо-клиента")
    booking = await get_booking_with_slot(session, int(body.booking_id), trainer_id)
    if not booking or int(booking["client_id"]) != int(client_id):
        raise HTTPException(status_code=404, detail="Запись не найдена")
    st = booking["start_time"]
    et = booking["end_time"]
    day_of_week = int(booking["slot_date"].weekday())
    if await has_other_active_recurring(
        session, trainer_id, day_of_week, st, exclude_client_id=client_id
    ):
        raise HTTPException(
            status_code=409,
            detail="На это время уже закреплён другой постоянный клиент.",
        )
    await _require_trainer_service_for_recurring_materialization(session, trainer_id)
    recurring_id = await create_recurring_client_slot(
        session, trainer_id, client_id, day_of_week, st, et
    )
    if not recurring_id:
        raise HTTPException(status_code=409, detail="Этот слот уже закреплён для клиента.")
    mono = this_week_monday()
    slot_this_iso = mono + timedelta(days=day_of_week)
    needs_first_week_choice = not is_slot_start_in_past_local(slot_this_iso, st)
    if needs_first_week_choice:
        if body.first_week not in ("this_week", "next_week"):
            raise HTTPException(
                status_code=400,
                detail="Выберите: автозаписи с этой недели или со следующей.",
            )
        min_week_index = 0 if body.first_week == "this_week" else 1
    else:
        min_week_index = 0

    settings = Settings()
    hw = int(settings.recurring_materialization_horizon_weeks)
    materialized = await materialize_recurring_horizon(
        session,
        trainer_id,
        horizon_weeks=hw,
        recurring_ids=[recurring_id],
        min_week_index=min_week_index,
    )
    await _rollback_recurring_unless_full_materialization(
        session,
        trainer_id,
        recurring_id,
        materialized=materialized,
        horizon_weeks=hw,
    )

    def _wall_hhmm(t: object) -> str:
        if hasattr(t, "strftime"):
            return t.strftime("%H:%M")  # type: ignore[union-attr]
        s = str(t)
        return s[:5] if len(s) >= 5 else s

    time_range = f"{_wall_hhmm(st)}–{_wall_hhmm(et)}"
    day_short = TRAINER_DAYS[day_of_week] if 0 <= day_of_week < len(TRAINER_DAYS) else "—"

    detail_row = await get_trainer_booking_detail_payload(session, int(body.booking_id), trainer_id)
    client_tid: int | None = None
    if detail_row and detail_row.get("client_telegram_id") is not None:
        client_tid = int(detail_row["client_telegram_id"])
    elif booking.get("client_telegram_id") is not None:
        client_tid = int(booking["client_telegram_id"])

    if client_tid:
        trainer_obj = await get_trainer(session, trainer_id) or {}
        profile = (trainer_obj.get("profile") or {})
        trainer_name = ((profile.get("first_name") or "") + " " + (profile.get("last_name") or "")).strip() or "Тренер"
        trainer_tid_raw = trainer_obj.get("telegram_id")
        trainer_tid = int(trainer_tid_raw) if trainer_tid_raw is not None else None

        svc = (detail_row.get("services_str") if detail_row else None) or booking.get("service_name")
        arena_disp = (detail_row.get("arenas_str") if detail_row else None) or None
        tier = (detail_row.get("price_tier_label") if detail_row else None) or None
        bpc = (detail_row.get("booking_price_cents") if detail_row else None) or None

        text_client = msg.format_client_recurring_set_by_trainer_notification_html(
            trainer_name=trainer_name,
            weekday_short=day_short,
            time_range=time_range,
            service_name=svc,
            booking_price_cents=bpc,
            price_tier_label=tier,
            arena_display=arena_disp,
            materialized_count=int(materialized),
        )
        reply_markup = msg.build_client_recurring_set_inline_keyboard(
            trainer_telegram_id=trainer_tid,
            webapp_base_url=settings.webapp_base_url,
        )
        client_bot = Bot(
            token=settings.telegram_bot_token_client,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            await client_bot.send_message(
                chat_id=client_tid,
                text=text_client,
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.warning(
                "recurring from-booking: client notify failed booking_id=%s client_id=%s: %s",
                body.booking_id,
                client_id,
                e,
            )
        finally:
            await client_bot.session.close()

    return {
        "success": True,
        "recurring_id": recurring_id,
        "materialized_bookings": materialized,
    }


@router.patch("/trainer/clients/{client_id:int}/identity")
async def patch_trainer_client_identity(
    client_id: int,
    body: TrainerClientIdentityPatchBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Trainer-editable CRM identity (имя / фамилия / отчество). Booking forms stay unchanged elsewhere."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="Укажите хотя бы одно поле")
    try:
        client = await patch_trainer_client_identity_for_card(session, trainer_id, client_id, updates=payload)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректные данные")
    if not client:
        raise HTTPException(status_code=404, detail="Клиент не найден или нет доступа")
    return await _trainer_miniapp_client_card_enriched_payload(session, client)


@router.post("/trainer/clients/{client_id:int}/detach")
async def post_trainer_client_detach_from_roster(
    client_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Remove manual roster link + cancel trainer's upcoming bookings with this client.
    Refused while the client is active/trial in a group operated by this trainer.
    """
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    try:
        result = await detach_trainer_client_from_roster_miniapp(session, trainer_id, client_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if result is None:
        raise HTTPException(status_code=404, detail="Клиент не найден или нет доступа")
    return {"success": True, **result}


@router.get("/trainer/clients/{client_id:int}/booking-defaults")
async def get_trainer_client_booking_defaults(
    client_id: int,
    from_booking_id: int | None = Query(
        None,
        ge=1,
        description="When set (e.g. post-session «Записать снова»), presets from this booking row instead of latest by created_at.",
    ),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Defaults for quick book: last booking by created_at, or a specific booking when from_booking_id is set."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    client = await get_trainer_client_for_card(session, trainer_id, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Клиент не найден или нет доступа")
    if from_booking_id is not None:
        preset = await get_trainer_client_booking_defaults_from_booking_id(
            session, trainer_id, client_id, int(from_booking_id)
        )
        if preset is None:
            raise HTTPException(
                status_code=404,
                detail="Запись не найдена или недоступна для пресетов",
            )
        sid, vid, arena_id, tier_kind = preset
    else:
        sid, vid, arena_id, tier_kind = await get_trainer_client_last_booking_service_defaults(
            session, trainer_id, client_id
        )
    return {
        "service_id": sid,
        "service_price_variant_id": vid,
        "arena_id": arena_id,
        "price_tier_kind": tier_kind,
        "client_first_name": (client.get("first_name") or "").strip() or None,
        "client_last_name": (client.get("last_name") or "").strip() or None,
    }


@router.get("/trainer/clients/{client_id:int}/history")
async def get_trainer_client_history(
    client_id: int,
    limit: int = Query(20, ge=1, le=100),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Last bookings for this client with this trainer. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    items = await list_trainer_client_history(session, trainer_id, client_id, limit=limit)
    total = await count_trainer_client_sessions(session, trainer_id, client_id)
    return {"items": items, "total": total}


@router.get("/trainer/clients/{client_id:int}/next-booking")
async def get_trainer_client_next_booking_route(
    client_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Next upcoming booking for this client with this trainer, or null. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    next_booking = await get_trainer_client_next_booking(session, trainer_id, client_id)
    upcoming_count = await count_trainer_client_upcoming(session, trainer_id, client_id)
    return {"next_booking": next_booking, "upcoming_count": upcoming_count}


@router.get("/trainer/clients/{client_id:int}/passes")
async def get_trainer_client_passes(
    client_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List pass instances for this client (issued by this trainer). Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    items = await list_pass_instances_for_trainer_client(session, trainer_id, client_id)
    return {"items": items}


@router.get("/trainer/clients/{client_id:int}/certificates")
async def get_trainer_client_certificates(
    client_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List certificate instances for this client (issued by this trainer). Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    items = await list_certificate_instances_for_trainer_client(session, trainer_id, client_id)
    return {"items": items}


class TrainerPassIssueBody(BaseModel):
    pass_product_id: int


@router.post("/trainer/clients/{client_id:int}/pass-issue")
async def post_trainer_client_pass_issue(
    client_id: int,
    body: TrainerPassIssueBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Issue a pass to this client (trainer recorded external payment). Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
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
            text = msg.format_client_pass_issued_html(
                product_name=instance["product_name"],
                sessions_total=instance["sessions_total"],
                sessions_remaining=instance["sessions_remaining"],
                trainer_name=trainer_name,
                service_names=instance.get("service_names"),
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


class TrainerRelayMessageBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


@router.post("/trainer/clients/{client_id:int}/relay-messages")
async def trainer_post_client_relay_message_route(
    client_id: int,
    body: TrainerRelayMessageBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Send a relay message from trainer to client's bot chat (fallback when Telegram DM lacks @username)."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    c_row, err = await assert_trainer_may_use_relay(session, trainer_id=trainer_id, client_id=client_id)
    if err == "not_found":
        raise HTTPException(status_code=404, detail="Клиент не найден")
    if err == "forbidden":
        raise HTTPException(status_code=403, detail="Нет доступа к клиенту")
    if err == "sandbox":
        raise HTTPException(status_code=400, detail="Для примера-клиента переписка не используется")
    if err == "no_telegram":
        raise HTTPException(status_code=400, detail="У клиента не привязан Telegram")
    assert c_row is not None
    body_text = sanitize_relay_body(body.text)
    if body_text is None:
        raise HTTPException(status_code=400, detail="Введите текст сообщения")

    await sweep_idle_relay_sessions_and_notify()

    display = await trainer_public_display_name(session, trainer_id=trainer_id)
    c_tg = int(c_row["telegram_id"])
    sess_id: int | None = None
    try:
        sess_id = await open_relay_session(session, trainer_id=trainer_id, client_id=int(client_id))
        await insert_relay_message(session, session_id=sess_id, sender_role=RELAY_SENDER_TRAINER, body_text=body_text)
        await session.flush()
        await send_client_relay_from_trainer(
            client_telegram_id=c_tg,
            trainer_display_name=display,
            body_text=body_text,
            session_id=int(sess_id),
        )
        await session.commit()
    except TelegramForbiddenError as e:
        await session.rollback()
        logger.warning(
            "trainer relay outbound forbidden trainer_id=%s client_id=%s client_tg=%s: %s",
            trainer_id,
            client_id,
            c_tg,
            e,
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "Не удалось доставить сообщение: клиент не открывал бота записи или заблокировал его. "
                "Попросите клиента зайти в этого бота и нажать «Главная» или отправить /start, затем повторите."
            ),
        ) from None
    except TelegramBadRequest as e:
        await session.rollback()
        em = str(e).lower()
        logger.warning(
            "trainer relay outbound bad_request trainer_id=%s client_id=%s client_tg=%s: %s",
            trainer_id,
            client_id,
            c_tg,
            e,
        )
        if any(
            x in em
            for x in (
                "chat not found",
                "chat_id is empty",
                "peer_id",
                "user not found",
                "have no access",
            )
        ):
            detail = "Не найден чат клиента в Telegram. Проверьте, что клиент пользуется тем же аккаунтом в боте записи."
        elif "message is too long" in em:
            detail = "Сообщение слишком длинное для Telegram."
        elif "parse entities" in em or "can't parse" in em:
            detail = "Текст содержит символы, которые Telegram не принял. Упростите сообщение."
        else:
            detail = "Telegram отклонил сообщение. Попробуйте позже или упростите текст."
        raise HTTPException(status_code=400, detail=detail) from None
    except TelegramUnauthorizedError as e:
        await session.rollback()
        logger.error("trainer relay client bot TELEGRAM_BOT_TOKEN_CLIENT rejected: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Сервер не может обратиться к боту записи. Проверьте конфигурацию токена бота клиента.",
        ) from None
    except TelegramNetworkError as e:
        await session.rollback()
        logger.warning("trainer relay telegram network trainer_id=%s client_id=%s: %s", trainer_id, client_id, e)
        raise HTTPException(
            status_code=503,
            detail="Не удаётся связаться с Telegram с сервера. Повторите через минуту.",
        ) from None
    except TelegramRetryAfter:
        await session.rollback()
        logger.warning(
            "trainer relay telegram retry_after trainer_id=%s client_id=%s",
            trainer_id,
            client_id,
        )
        raise HTTPException(
            status_code=429,
            detail="Telegram просит подождать перед следующей отправкой. Попробуйте через минуту.",
        ) from None
    except TelegramServerError as e:
        await session.rollback()
        logger.warning("trainer relay telegram server_error: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Telegram временно недоступен. Попробуйте через минуту.",
        ) from None
    except IntegrityError as e:
        await session.rollback()
        logger.exception(
            "trainer relay db integrity trainer_id=%s client_id=%s (migrations?): %s",
            trainer_id,
            client_id,
            e,
        )
        raise HTTPException(
            status_code=503,
            detail="Ошибка сохранения переписки на сервере. Проверьте обновление БД и повторите.",
        ) from None
    except Exception:
        await session.rollback()
        logger.exception("trainer relay outbound failed trainer_id=%s client_id=%s", trainer_id, client_id)
        raise HTTPException(status_code=502, detail="Не удалось отправить сообщение в бот клиента. Попробуйте позже.")
    assert sess_id is not None
    return {"ok": True, "session_id": int(sess_id)}


@router.post("/trainer/clients/{client_id:int}/relay/close")
async def trainer_close_client_relay_route(
    client_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    sid = await get_open_session_id(session, trainer_id=trainer_id, client_id=int(client_id))
    if sid is None:
        return {"closed": False}
    await close_relay_session(session, session_id=int(sid), trainer_id=int(trainer_id))
    await session.commit()
    return {"closed": True}


class TrainerClientNoteBody(BaseModel):
    note: str


@router.get("/trainer/clients/{client_id:int}/note")
async def get_trainer_client_note_route(
    client_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get trainer's private note about this client. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    note = await get_trainer_client_note(session, trainer_id, client_id)
    return {"note": (note or {}).get("note", "")}


@router.post("/trainer/clients/{client_id:int}/note")
async def post_trainer_client_note_route(
    client_id: int,
    body: TrainerClientNoteBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create or update trainer's private note about this client. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    result = await upsert_trainer_client_note(session, trainer_id, client_id, body.note)
    return {"note": result.get("note", "")}


# --- Client Dossier (structured notes) ---

from src.application.client_dossier_use_cases import (
    get_full_client_dossier,
    upsert_client_dossier_profile,
    list_client_entries,
    add_client_entry,
    delete_client_entry,
    list_client_tags,
    add_client_tag,
    remove_client_tag,
    SUGGESTED_TAGS,
)


class DossierProfileBody(BaseModel):
    note: str | None = None
    goals: str | None = None
    limitations: str | None = None
    level: str | None = None
    season_goal: str | None = None


class DossierEntryBody(BaseModel):
    content: str


class DossierTagBody(BaseModel):
    tag: str
    category: str | None = None


@router.get("/trainer/clients/{client_id:int}/dossier")
async def get_client_dossier_route(
    client_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get full client dossier: profile, tags, entries. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    return await get_full_client_dossier(session, trainer_id, client_id)


@router.post("/trainer/clients/{client_id:int}/dossier/profile")
async def update_client_dossier_profile_route(
    client_id: int,
    body: DossierProfileBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Update client profile fields. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    return await upsert_client_dossier_profile(
        session, trainer_id, client_id,
        note=body.note,
        goals=body.goals,
        limitations=body.limitations,
        level=body.level,
        season_goal=body.season_goal,
    )


@router.get("/trainer/clients/{client_id:int}/dossier/entries")
async def list_client_entries_route(
    client_id: int,
    limit: int = Query(50, ge=1, le=100),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List timeline entries for a client. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    entries = await list_client_entries(session, trainer_id, client_id, limit=limit)
    return {"entries": entries}


@router.post("/trainer/clients/{client_id:int}/dossier/entries")
async def add_client_entry_route(
    client_id: int,
    body: DossierEntryBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Add a timeline entry. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    try:
        entry = await add_client_entry(session, trainer_id, client_id, body.content)
        return {"entry": entry}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/trainer/clients/{client_id:int}/dossier/entries/{entry_id:int}")
async def delete_client_entry_route(
    client_id: int,
    entry_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete a timeline entry. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    deleted = await delete_client_entry(session, trainer_id, entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"success": True}


@router.get("/trainer/clients/{client_id:int}/dossier/tags")
async def list_client_tags_route(
    client_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List tags for a client. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    tags = await list_client_tags(session, trainer_id, client_id)
    return {"tags": tags, "suggested": SUGGESTED_TAGS}


@router.post("/trainer/clients/{client_id:int}/dossier/tags")
async def add_client_tag_route(
    client_id: int,
    body: DossierTagBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Add a tag to a client. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    try:
        tag = await add_client_tag(session, trainer_id, client_id, body.tag, body.category)
        if tag is None:
            raise HTTPException(status_code=409, detail="Tag already exists")
        return {"tag": tag}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/trainer/clients/{client_id:int}/dossier/tags/{tag_id:int}")
async def remove_client_tag_route(
    client_id: int,
    tag_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Remove a tag from a client. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    deleted = await remove_client_tag(session, trainer_id, tag_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tag not found")
    return {"success": True}


@router.post("/trainer/clients")
async def post_trainer_clients(
    body: TrainerCreateClientBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Create or get client by phone (no telegram_id) and attach to trainer CRM. Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    try:
        if body.is_sandbox:
            # Sandbox path: ignore the user-supplied phone — we use a deterministic per-trainer
            # phantom so two trainers' demos never collide and a sandbox identity can never silently
            # become a real client (see ``sandbox_phone_for_trainer``).
            client_id = await get_or_create_sandbox_client_for_trainer(
                session,
                trainer_id,
                first_name=body.first_name or None,
                last_name=body.last_name or None,
            )
        else:
            client_id = await get_or_create_client_by_phone(
                session,
                body.phone,
                first_name=body.first_name,
                last_name=body.last_name or None,
                middle_name=body.middle_name or None,
            )
        await link_trainer_client_roster(session, trainer_id, client_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await session.commit()
    return {"client_id": client_id, "is_sandbox": bool(body.is_sandbox)}


@router.delete("/trainer/clients/{client_id}/sandbox")
async def delete_trainer_sandbox_client(
    client_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Hard-delete a sandbox client + every booking/slot it touched (FK cascade).

    Only works on rows where ``clients.is_sandbox = true`` AND every booking is sandbox — this
    guarantees the endpoint can never wipe a real CRM client even if a caller passes the wrong id.
    """
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    r = await session.execute(
        text("SELECT is_sandbox FROM clients WHERE id = :cid"),
        {"cid": int(client_id)},
    )
    row = r.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    if not bool(row[0]):
        raise HTTPException(status_code=403, detail="Удалить можно только тестового клиента")
    # Defence in depth: refuse if any non-sandbox booking touches this client (paranoid guard).
    r_real = await session.execute(
        text(
            "SELECT EXISTS(SELECT 1 FROM bookings WHERE client_id = :cid AND NOT is_sandbox)"
        ),
        {"cid": int(client_id)},
    )
    if bool(r_real.scalar()):
        raise HTTPException(status_code=409, detail="У клиента есть реальные записи — удаление запрещено")
    from src.application.client_trainer_edge_use_cases import (
        purge_client_trainer_hub_signals_on_roster_detach,
    )

    await purge_client_trainer_hub_signals_on_roster_detach(
        session, int(trainer_id), int(client_id)
    )
    # Free up slots that the sandbox bookings occupied (status='booked' → 'available') before delete.
    await session.execute(
        text(
            """
            UPDATE slots SET status = 'available'
            WHERE id IN (
                SELECT slot_id FROM bookings
                WHERE client_id = :cid AND is_sandbox AND slot_id IS NOT NULL
            )
            AND status = 'booked'
            """
        ),
        {"cid": int(client_id)},
    )
    await session.execute(
        text("DELETE FROM bookings WHERE client_id = :cid AND is_sandbox"),
        {"cid": int(client_id)},
    )
    await session.execute(
        text("DELETE FROM trainer_client_roster WHERE client_id = :cid AND trainer_id = :tid"),
        {"cid": int(client_id), "tid": trainer_id},
    )
    await session.execute(
        text("DELETE FROM clients WHERE id = :cid AND is_sandbox"),
        {"cid": int(client_id)},
    )
    await session.commit()
    return {"deleted": True}


@router.post("/trainer/booking")
async def post_trainer_booking(
    body: TrainerCreateBookingBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Create booking: trainer assigns client to slot (from schedule). Auth: trainer initData."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED)
    notify_tid = _trainer_bot_notify_telegram_id(principal)
    slot = await get_slot(session, body.slot_id)
    if not slot or slot.get("trainer_id") != trainer_id:
        raise HTTPException(status_code=400, detail="Slot not found or not available")
    st_raw = (slot.get("status") or "").strip().lower()
    cap_slot = max(1, int(slot.get("capacity") or 1))
    allow_ob = bool(body.allow_overbook) and cap_slot > 1
    if st_raw == "cancelled":
        raise HTTPException(status_code=400, detail="Slot not found or not available")
    # Group slots: status may be 'booked' while seats remain (sync semantics); allow both until create_booking checks capacity.
    if cap_slot > 1:
        if st_raw not in ("available", "booked"):
            raise HTTPException(status_code=400, detail="Slot not found or not available")
    elif st_raw != "available":
        if not (allow_ob and st_raw == "booked"):
            raise HTTPException(status_code=400, detail="Slot not found or not available")
    arena_id: int | None = body.arena_id
    if arena_id is not None:
        rchk = await session.execute(
            text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
            {"tid": trainer_id, "aid": arena_id},
        )
        if not rchk.fetchone():
            raise HTTPException(status_code=400, detail="Площадка не привязана к вашему профилю")
    booking_id, (first_booking_milestone, share_catalog_tip) = await create_booking(
        session,
        slot_id=body.slot_id,
        trainer_id=trainer_id,
        client_id=body.client_id,
        service_id=body.service_id,
        client_comment=None,
        client_request_id=None,
        created_by_trainer=True,
        arena_id=arena_id,
        service_price_variant_id=body.service_price_variant_id,
        strict_service_price_variant=False,
        allow_overbook=allow_ob,
    )
    if not booking_id:
        detail_ru = await explain_trainer_booking_failure(session, trainer_id, body.slot_id, body.service_id)
        raise HTTPException(status_code=400, detail=detail_ru)
    if not is_slot_end_in_past_local(slot.get("slot_date"), slot.get("end_time")):
        await generate_reminders_for_booking(session, booking_id)
    await _send_trainer_post_booking_feedback(
        session=session,
        trainer_id=trainer_id,
        trainer_telegram_id=notify_tid,
        booking_id=int(booking_id),
        client_id=int(body.client_id),
        slot_date=(slot or {}).get("slot_date"),
        start_time=(slot or {}).get("start_time"),
        first_booking_milestone=first_booking_milestone,
        share_catalog_tip=share_catalog_tip,
    )
    return {
        "success": True,
        "booking_id": booking_id,
        "first_booking_milestone": first_booking_milestone,
        "share_catalog_tip": share_catalog_tip,
    }


@router.post("/trainer/booking/quick")
async def post_trainer_booking_quick(
    body: TrainerQuickBookingBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Create individual slot at date/hour if needed, then booking. Requires CRM (same as creating slots)."""
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED)
    notify_tid = _trainer_bot_notify_telegram_id(principal)
    try:
        slot_date = date.fromisoformat(body.slot_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slot_date") from None
    if body.start_time is not None and str(body.start_time).strip():
        try:
            start_minutes = next(iter(_hhmm_strings_to_minutes([body.start_time.strip()])))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    elif body.start_hour is not None:
        start_minutes = int(body.start_hour) * 60
    else:
        raise HTTPException(status_code=400, detail="Укажите время начала (start_time или start_hour).")

    # Sandbox identity invariant: a sandbox booking can only target a sandbox client and vice versa.
    # Without this guard a real client could end up with a sandbox booking (or a sandbox client with a
    # real booking) — both cases would leak the demo identity into rhythm hints, stats, and reminders.
    r_sb = await session.execute(
        text("SELECT is_sandbox FROM clients WHERE id = :cid"),
        {"cid": int(body.client_id)},
    )
    row_sb = r_sb.fetchone()
    if not row_sb:
        raise HTTPException(status_code=400, detail="Клиент не найден")
    client_is_sandbox = bool(row_sb[0])
    if client_is_sandbox != bool(body.is_sandbox):
        raise HTTPException(
            status_code=400,
            detail="Sandbox-запись возможна только на тестового клиента",
        )

    try:
        result = await create_trainer_quick_booking(
            session,
            trainer_id=trainer_id,
            slot_date=slot_date,
            start_minutes=start_minutes,
            duration_minutes=body.duration_minutes,
            client_id=body.client_id,
            service_id=body.service_id,
            arena_id=body.arena_id,
            service_price_variant_id=body.service_price_variant_id,
            is_sandbox=bool(body.is_sandbox),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ServicePriceVariantRequired:
        await session.rollback()
        raise HTTPException(
            status_code=400,
            detail="Выберите категорию цены (тариф) для этой услуги.",
        ) from None
    if result is None:
        raise HTTPException(status_code=400, detail="Не удалось создать запись")
    booking_id, slot_id, first_booking_milestone, share_catalog_tip = result
    slot = await get_slot(session, slot_id)
    if not body.is_sandbox:
        if slot and not is_slot_end_in_past_local(slot.get("slot_date"), slot.get("end_time")):
            await generate_reminders_for_booking(session, booking_id)
    # Sandbox: no client reminders; trainer still gets the same first-booking celebration when applicable.
    await _send_trainer_post_booking_feedback(
        session=session,
        trainer_id=trainer_id,
        trainer_telegram_id=notify_tid,
        booking_id=int(booking_id),
        client_id=int(body.client_id),
        slot_date=(slot or {}).get("slot_date"),
        start_time=(slot or {}).get("start_time"),
        first_booking_milestone=first_booking_milestone,
        share_catalog_tip=share_catalog_tip,
        is_sandbox=bool(body.is_sandbox),
    )
    return {
        "success": True,
        "booking_id": booking_id,
        "slot_id": slot_id,
        "first_booking_milestone": first_booking_milestone,
        "share_catalog_tip": share_catalog_tip,
    }


class TrainerSandboxBookingBody(BaseModel):
    """Onboarding sandbox: one-field body for demo quick-booking (no client selection needed)."""
    slot_date: str
    start_time: str
    duration_minutes: int = 45


@router.post("/trainer/onboarding/sandbox-booking")
async def post_trainer_onboarding_sandbox_booking(
    body: TrainerSandboxBookingBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """
    Create a sandbox (demo) booking for onboarding TTV step 2.
    Auto-creates or reuses a phantom client per trainer. Excluded from stats/revenue like other
    sandbox rows, but the trainer still receives the same first-booking Telegram celebration when
    this is their first confirmed slot (onboarding aha moment).
    The trainer can delete the booking afterward via the normal cancel endpoint.
    """
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED)
    notify_tid = _trainer_bot_notify_telegram_id(principal)
    try:
        slot_date = date.fromisoformat(body.slot_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slot_date") from None
    try:
        start_minutes = next(iter(_hhmm_strings_to_minutes([body.start_time.strip()])))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    client_id = await get_or_create_sandbox_client_for_trainer(
        session, trainer_id, first_name="Пример", last_name="К."
    )
    await link_trainer_client_roster(session, trainer_id, client_id)
    await session.commit()

    r_svc = await session.execute(
        text("SELECT service_id FROM trainer_services WHERE trainer_id = :tid LIMIT 1"),
        {"tid": trainer_id},
    )
    row_svc = r_svc.fetchone()
    if not row_svc:
        raise HTTPException(
            status_code=400,
            detail="Добавьте хотя бы одну услугу в профиле, чтобы сделать пробную запись.",
        )
    service_id = row_svc[0]

    try:
        result = await create_trainer_quick_booking(
            session,
            trainer_id=trainer_id,
            slot_date=slot_date,
            start_minutes=start_minutes,
            duration_minutes=body.duration_minutes,
            client_id=client_id,
            service_id=service_id,
            is_sandbox=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if result is None:
        raise HTTPException(status_code=400, detail="Не удалось создать пробную запись")
    booking_id, slot_id, first_booking_milestone, share_catalog_tip = result
    slot = await get_slot(session, slot_id)
    await _send_trainer_post_booking_feedback(
        session=session,
        trainer_id=trainer_id,
        trainer_telegram_id=notify_tid,
        booking_id=int(booking_id),
        client_id=int(client_id),
        slot_date=(slot or {}).get("slot_date"),
        start_time=(slot or {}).get("start_time"),
        first_booking_milestone=first_booking_milestone,
        share_catalog_tip=share_catalog_tip,
        is_sandbox=True,
    )
    return {
        "success": True,
        "booking_id": booking_id,
        "slot_id": slot_id,
        "first_booking_milestone": first_booking_milestone,
        "share_catalog_tip": share_catalog_tip,
    }


@router.post("/trainer/bookings/{booking_id:int}/make_regular")
async def post_trainer_booking_make_regular(
    booking_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    booking = await get_booking_with_slot(session, booking_id, trainer_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    await _require_trainer_service_for_recurring_materialization(session, trainer_id)
    recurring_id = await create_recurring_client_slot(
        session, trainer_id, booking["client_id"],
        booking["slot_date"].weekday(), booking["start_time"], booking["end_time"],
    )
    materialized = 0
    settings = Settings()
    hw = int(settings.recurring_materialization_horizon_weeks)
    if recurring_id:
        materialized = await materialize_recurring_horizon(
            session,
            trainer_id,
            horizon_weeks=hw,
            recurring_ids=[recurring_id],
        )
        await _rollback_recurring_unless_full_materialization(
            session,
            trainer_id,
            recurring_id,
            materialized=materialized,
            horizon_weeks=hw,
        )
    return {"success": True, "recurring_id": recurring_id, "materialized_bookings": materialized}


@router.post("/trainer/recurring/{recurring_id:int}/remove")
async def post_trainer_recurring_remove(
    recurring_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    trainer_id = await get_trainer_id_for_webapp_trainer_operations_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    ok, removed_fwd = await cancel_recurring_client_slot(session, trainer_id, recurring_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Recurring not found")
    return {"success": True, "removed_forward_bookings": removed_fwd}


# --- Trainer client requests Mini App (list, respond, decline, remind, book client) ---


def _format_certificate_amount_label_ru(amount_cents: int | None) -> str:
    """Short label for trainer UI: fixed nominal vs «any amount» certificate products."""
    if amount_cents is None:
        return "Любая сумма"
    v = int(amount_cents) / 100
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return f"{s} {BYR_SIGN}"


async def _enrich_trainer_request_certificate_products(
    session: AsyncSession, trainer_id: int, items: list[dict],
) -> None:
    """Fill certificate_product_name + certificate_amount_label for certificate order requests."""
    cache: dict[int, dict | None] = {}

    async def _prod(pid: int) -> dict | None:
        if pid not in cache:
            cache[pid] = await get_certificate_product(session, pid, trainer_id)
        return cache[pid]

    for it in items:
        if it.get("request_subtype") != "certificate_product_order":
            continue
        raw_pid = it.get("certificate_product_id")
        if raw_pid is None:
            continue
        try:
            pid = int(raw_pid)
        except (TypeError, ValueError):
            continue
        product = await _prod(pid)
        if product:
            name = (product.get("name") or "").strip()
            it["certificate_product_name"] = name or "Подарочный сертификат"
            fixed = product.get("amount_cents")
            req_cents = it.get("cert_requested_nominal_cents")
            if fixed is None and req_cents is not None:
                it["certificate_amount_label"] = _format_certificate_amount_label_ru(int(req_cents))
            elif fixed is None:
                it["certificate_amount_label"] = "Любая сумма (клиент не указал — старая заявка)"
            else:
                it["certificate_amount_label"] = _format_certificate_amount_label_ru(fixed)
        else:
            it["certificate_product_name"] = "Сертификат (продукт недоступен)"
            it["certificate_amount_label"] = "—"


def _serialize_trainer_request(req: dict) -> dict:
    """Request dict to JSON-safe for trainer requests list/detail."""
    created_at = req.get("created_at")
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    elif created_at is not None:
        created_at = str(created_at)
    comment_raw = req.get("comment")
    _pid_marked, comment_body_pass = split_pass_order_comment(comment_raw)
    if _pid_marked is not None:
        return {
            "id": req["id"],
            "city_id": req["city_id"],
            "service_id": req["service_id"],
            "comment": comment_raw,
            "comment_body": comment_body_pass,
            "created_at": created_at,
            "city_name": req.get("city_name"),
            "service_name": req.get("service_name"),
            "is_personalized": bool(req.get("is_personalized")),
            "has_responded": bool(req.get("has_responded")),
            "remind_slots_pending": bool(req.get("remind_slots_pending")),
            "client_id": req.get("client_id"),
            "client_telegram_id": req.get("client_telegram_id"),
            "client_telegram_username": (req.get("client_telegram_username") or "").strip() or None,
            "client_first_name": req.get("client_first_name"),
            "client_last_name": req.get("client_last_name"),
            "request_subtype": "pass_product_order",
            "pass_product_id": _pid_marked,
            "certificate_product_id": None,
            "cert_recipient_email": None,
            "cert_recipient_name": None,
            "cert_purchased_by_name": None,
        }
    _cid_marked, cert_meta, comment_body_cert = split_cert_order_comment(comment_raw)
    if _cid_marked is not None:
        _req_nom = cert_meta.get("requested_nominal_cents")
        _req_nom_int: int | None
        try:
            _req_nom_int = int(_req_nom) if _req_nom is not None else None
        except (TypeError, ValueError):
            _req_nom_int = None
        return {
            "id": req["id"],
            "city_id": req["city_id"],
            "service_id": req["service_id"],
            "comment": comment_raw,
            "comment_body": comment_body_cert,
            "created_at": created_at,
            "city_name": req.get("city_name"),
            "service_name": req.get("service_name"),
            "is_personalized": bool(req.get("is_personalized")),
            "has_responded": bool(req.get("has_responded")),
            "remind_slots_pending": bool(req.get("remind_slots_pending")),
            "client_id": req.get("client_id"),
            "client_telegram_id": req.get("client_telegram_id"),
            "client_telegram_username": (req.get("client_telegram_username") or "").strip() or None,
            "client_first_name": req.get("client_first_name"),
            "client_last_name": req.get("client_last_name"),
            "request_subtype": "certificate_product_order",
            "pass_product_id": None,
            "certificate_product_id": _cid_marked,
            "cert_recipient_email": cert_meta.get("recipient_email"),
            "cert_recipient_name": cert_meta.get("recipient_name"),
            "cert_purchased_by_name": cert_meta.get("purchased_by_name"),
            "cert_requested_nominal_cents": _req_nom_int,
        }
    return {
        "id": req["id"],
        "city_id": req["city_id"],
        "service_id": req["service_id"],
        "comment": comment_raw,
        "comment_body": (comment_raw or "").strip() or None,
        "created_at": created_at,
        "city_name": req.get("city_name"),
        "service_name": req.get("service_name"),
        "is_personalized": bool(req.get("is_personalized")),
        "has_responded": bool(req.get("has_responded")),
        "remind_slots_pending": bool(req.get("remind_slots_pending")),
        "client_id": req.get("client_id"),
        "client_telegram_id": req.get("client_telegram_id"),
        "client_telegram_username": (req.get("client_telegram_username") or "").strip() or None,
        "client_first_name": req.get("client_first_name"),
        "client_last_name": req.get("client_last_name"),
        "request_subtype": None,
        "pass_product_id": None,
        "certificate_product_id": None,
        "cert_recipient_email": None,
        "cert_recipient_name": None,
        "cert_purchased_by_name": None,
    }


@router.get("/trainer/onboarding/moderation-readiness")
async def webapp_trainer_moderation_readiness(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Submission + full-profile completeness for Mini App (same dict as embedded profile moderation_readiness)."""
    trainer_id = await get_trainer_id_linked_any_status_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Telegram not linked to a trainer")
    data = await get_trainer_moderation_readiness(session, trainer_id)
    if not data:
        raise HTTPException(status_code=404, detail="Trainer not found")
    return data


@router.get("/trainer/onboarding/checklist")
async def webapp_trainer_onboarding_checklist(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Profile / slots / optional booking flag for the «Первые шаги» strip (trainer hub Mini App)."""
    trainer_id = await get_trainer_id_linked_any_status_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Telegram not linked to a trainer")
    data = await get_trainer_onboarding_checklist(session, trainer_id)
    if not data:
        raise HTTPException(status_code=404, detail="Trainer not found")
    return data


@router.post("/trainer/onboarding/submit-for-moderation")
async def webapp_trainer_submit_for_moderation(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """422 if submission tier (8 criteria) incomplete; otherwise same rules as REST submit-for-moderation."""
    trainer_id = await get_trainer_id_linked_any_status_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Telegram not linked to a trainer")
    result = await try_submit_trainer_for_moderation_review(session, trainer_id)
    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="Trainer not found")
    if not result.get("ok"):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Profile incomplete for moderation submission (8 criteria)",
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


@router.get("/trainer/requests/summary")
async def get_trainer_requests_summary(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Lightweight hub: count of requests the trainer has not answered yet. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    n = await count_unanswered_requests_for_trainer(session, trainer_id)
    return {"unanswered_count": n}


@router.get("/trainer/requests")
async def get_trainer_requests(
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """List client requests for this trainer (city+service match). New first, then in progress. Auth: trainer initData."""
    logger.info("GET /trainer/requests authenticated")
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    items = await list_requests_for_trainer(session, trainer_id)
    if not items:
        logger.info("trainer_requests_empty trainer_id=%s (profile city+service may not match any request)", trainer_id)
    new_list = [r for r in items if not r.get("has_responded")]
    in_progress_list = [r for r in items if r.get("has_responded")]
    combined = new_list + in_progress_list
    serialized = [_serialize_trainer_request(r) for r in combined]
    await _enrich_trainer_request_certificate_products(session, trainer_id, serialized)
    return {"items": serialized}


class TrainerRespondBody(BaseModel):
    trainer_comment: str | None = None


@router.post("/trainer/requests/{request_id:int}/respond")
async def post_trainer_request_respond(
    request_id: int,
    body: TrainerRespondBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Respond to request (optional comment). Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    comment = (body.trainer_comment or "").strip() or None
    resp_id = await create_request_response(session, request_id, trainer_id, trainer_comment=comment)
    if resp_id is None:
        raise HTTPException(status_code=400, detail="Already responded or request not found")
    return {"success": True, "response_id": resp_id}


@router.post("/trainer/requests/{request_id:int}/decline")
async def post_trainer_request_decline(
    request_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Decline request (hide from trainer list). Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    ok = await create_request_decline(session, request_id, trainer_id)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="Не удалось скрыть заявку (нет доступа или заявка уже закрыта).",
        )
    return {"success": True}


@router.post("/trainer/requests/{request_id:int}/remind-slots")
async def post_trainer_request_remind_slots(
    request_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Set 'remind me when I have slots' for this request. Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    was_new = await add_trainer_pending_request_booking(session, trainer_id, request_id)
    return {"success": True, "remind_slots_pending": True, "was_new": was_new}


@router.get("/trainer/requests/{request_id:int}/slots")
async def get_trainer_request_slots(
    request_id: int,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Available slots for next 2 weeks (for booking client from request). Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
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
    service_price_variant_id: int | None = None


@router.post("/trainer/requests/{request_id:int}/book")
async def post_trainer_request_book(
    request_id: int,
    body: TrainerBookRequestBody,
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    session: AsyncSession = Depends(get_session),
):
    """Create booking for client from request (trainer books client). Auth: trainer initData."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    client_info = await get_request_client_for_trainer_booking(session, request_id, trainer_id)
    if not client_info:
        raise HTTPException(status_code=404, detail="Request not found or not responded")
    booking_id, (first_booking_milestone, share_catalog_tip) = await create_booking(
        session,
        slot_id=body.slot_id,
        trainer_id=trainer_id,
        client_id=client_info["client_id"],
        service_id=client_info["service_id"],
        client_comment=None,
        client_request_id=request_id,
        created_by_trainer=True,
        service_price_variant_id=body.service_price_variant_id,
        strict_service_price_variant=False,
    )
    if not booking_id:
        raise HTTPException(status_code=400, detail="Slot not available")
    await clear_trainer_pending_request_booking(session, trainer_id, request_id)
    slot_row = await get_slot(session, body.slot_id)
    if slot_row and not is_slot_end_in_past_local(slot_row.get("slot_date"), slot_row.get("end_time")):
        await generate_reminders_for_booking(session, booking_id)
    return {
        "success": True,
        "booking_id": booking_id,
        "first_booking_milestone": first_booking_milestone,
        "share_catalog_tip": share_catalog_tip,
    }


# --- Referral program (B2B: trainer invites trainer) ---

from src.application.referral_use_cases import (
    ensure_trainer_referral_code,
    get_referral_stats_for_trainer,
    list_referred_trainers,
    REFERRAL_CREDIT_DAYS_PER_REFERRAL,
    REFERRAL_ATTRIBUTION_WINDOW_DAYS,
)


@router.get("/trainer/referral")
async def get_trainer_referral_info(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
) -> dict[str, Any]:
    """Get referral info for trainer: code, link, stats, balance."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked")
    code = await ensure_trainer_referral_code(session, trainer_id)
    if not code:
        raise HTTPException(status_code=500, detail="Failed to generate referral code")
    stats = await get_referral_stats_for_trainer(session, trainer_id)
    bot_username = Settings().trainer_bot_username or "trainer_bot"
    referral_link = f"https://t.me/{bot_username}?start=ref_{code}"
    return {
        "referral_code": code,
        "referral_link": referral_link,
        "credit_per_referral_days": REFERRAL_CREDIT_DAYS_PER_REFERRAL,
        "attribution_window_days": REFERRAL_ATTRIBUTION_WINDOW_DAYS,
        **stats,
    }


@router.get("/trainer/referral/referred")
async def get_trainer_referred_list(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
    limit: int = Query(50, ge=1, le=100),
) -> list[dict[str, Any]]:
    """List trainers referred by this trainer."""
    trainer_id = await get_trainer_id_by_telegram_id_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Trainer not linked")
    return await list_referred_trainers(session, trainer_id, limit=limit)


from src.api.routes.webapp_client_trainer_edges import router as _webapp_client_trainer_edges_router
from src.api.routes.webapp_training_groups import router as _webapp_training_groups_router

router.include_router(_webapp_client_trainer_edges_router)
router.include_router(_webapp_training_groups_router)
