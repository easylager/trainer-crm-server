"""
Admin bot: moderation of trainers (approve / reject), platform stats Mini App, support inbox, referral management.
"""
import html
import logging

from aiogram import Bot, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from src.application.referral_use_cases import (
    admin_adjust_referral_credit,
    get_referral_credit_balance,
    get_referral_stats_for_trainer,
)
from src.application.stats_use_cases import ACTIVATION_STAGE_LABEL_RU, ACTIVATION_STAGE_ORDER, get_platform_stats
from src.application.support_use_cases import (
    get_support_message,
    list_support_messages,
    reply_support_message,
)
from src.application.admin_moderation_queue import list_trainer_ids_eligible_for_admin_moderation
from src.application.booking_problem_admin_use_cases import (
    count_booking_problem_reports_for_admin,
    list_booking_problem_reports_for_admin,
)
from src.application.platform_settings_use_cases import (
    WELCOME_TRIAL_PERIOD_DAYS_KEY,
    set_platform_int,
)
from src.application.subscription_invoice_admin_notify import (
    build_admin_subscription_invoice_keyboard,
    format_catalog_modules_short,
    load_subscription_invoice_admin_view,
    trainer_contact_link_html,
    trainer_contact_url,
)
from src.application.subscription_tier_use_cases import (
    SUBSCRIPTION_BILLING_PERIOD_MONTHS,
    SUBSCRIPTION_MODULE_ANALYTICS,
    SUBSCRIPTION_MODULE_GROUPS,
    SUBSCRIPTION_MODULE_ONLINE,
    SUBSCRIPTION_MODULES,
    SUBSCRIPTION_TIER_CRM,
    default_modules_dict,
    format_subscription_label,
    get_module_period_pricing,
    get_tier_period_pricing,
)
from src.application.subscription_use_cases import (
    admin_cancel_pending_subscription_invoice,
    admin_grant_subscription_for_invoice,
    admin_merge_modules_into_current_subscription,
    compute_prorated_module_addon_cost_cents,
    create_catalog_subscription_invoice_for_trainer,
    get_active_paid_subscription_for_merge,
    get_resolved_welcome_trial_days_for_display,
    list_pending_catalog_subscription_invoices,
)
from src.application.trainer_link_token_use_cases import (
    DEFAULT_TRAINER_LINK_EXPIRE_DAYS,
    create_trainer_and_issue_welcome_link_token,
    issue_trainer_welcome_link_token,
)
from src.bot.admin_bot_commands import register_admin_bot_commands
from src.application.collective_use_cases import (
    admin_confirm_collective_invoice,
    admin_grant_collective_subscription,
    create_collective_draft,
    get_collective_ops_status,
    get_collective_subscription_status,
    issue_collective_claim_token,
    list_collective_org_format_presets,
    parse_admin_collective_draft_body,
)
from src.application.trainer_profile_pending import (
    build_trainer_profile_for_moderation_card,
    trainer_photo_file_key_for_moderation_ui,
)
from src.application.trainer_use_cases import (
    apply_photo_pending_to_published,
    apply_trainer_profile_pending_to_published,
    discard_active_trainer_text_revision_with_feedback,
    get_trainer,
    list_trainer_education,
    moderate_trainer_education_for_profile,
    set_trainer_moderation_feedback,
    update_trainer_status,
)
from src.bot import messages as msg
from src.bot.admin_moderation_card import (
    fetch_city_name,
    format_admin_trainer_moderation_caption,
    split_photo_caption_if_needed,
)
from src.bot.admin_health import fetch_api_health, format_admin_version_message
from src.bot.client_api import resolve_trainer_photo_bytes
from src.bot.handlers.trainer_handlers import (
    _trainer_moderation_profile_approved_reply_markup,
    _trainer_profile_footer_hint,
    _trainer_profile_keyboard,
)
from sqlalchemy import text

from src.infrastructure.db import async_session_factory
from src.infrastructure.repositories import TrainerRepository
from src.infrastructure.db.models import TRAINER_STATUS_ACTIVE, TRAINER_STATUS_DEACTIVATED, TRAINER_STATUS_PENDING_PROFILE
from src.shared.audit import ACTOR_ADMIN_BOT, audit_log
from src.shared.config import Settings
from src.shared.validation import safe_parse_id


router = Router(name="admin")

logger = logging.getLogger(__name__)

ADMIN_APPROVE_PREFIX = "admin:approve:"
ADMIN_REJECT_PREFIX = "admin:reject:"
ADMIN_NEEDS_EDIT_PREFIX = "admin:needs_edit:"

# Human-readable trainer status for stats
TRAINER_STATUS_LABELS = {
    "pending_profile": "На модерации",
    "pending_contract": "Ожидает договор",
    "pending_payment": "Ожидает оплату",
    "active": "Активные",
    "deactivated": "Деактивированы",
}

# In-memory state: admin user_id -> trainer_id (awaiting moderation feedback text)
_admin_awaiting_feedback: dict[int, int] = {}
# admin user_id -> support_id (awaiting reply text)
_admin_awaiting_support_reply: dict[int, int] = {}
ADMIN_SUPPORT_REPLY_PREFIX = "admin:support:reply:"


def _is_admin(user_id: int | None) -> bool:
    if not user_id:
        return False
    settings = Settings()
    ids = settings.admin_telegram_ids or []
    return user_id in ids


async def _notify_trainer_education_moderation(
    trainer: dict | None,
    *,
    decision: str,
    reason: str | None = None,
) -> None:
    """Notify trainer in Telegram about education moderation result."""
    if not trainer:
        return
    telegram_id = trainer.get("telegram_id")
    if not telegram_id:
        return
    settings = Settings()
    if not settings.telegram_bot_token_trainer:
        return
    bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        if decision == "approved":
            text = msg.TRAINER_EDUCATION_MODERATION_APPROVED
        else:
            text = msg.TRAINER_EDUCATION_MODERATION_REJECTED.format(
                reason=html.escape((reason or "").strip() or "Причина не указана")
            )
        await bot.send_message(chat_id=telegram_id, text=text)
    except Exception:
        pass
    finally:
        await bot.session.close()


async def _trainer_bot_send_html_with_profile_button(telegram_id: int, html_body: str) -> None:
    """Send HTML to trainer bot with the same «Профиль» Web App button as /profile (no raw URL links)."""
    settings = Settings()
    if not settings.telegram_bot_token_trainer:
        return
    kb = _trainer_profile_keyboard()
    if kb is None:
        html_body = html_body + _trainer_profile_footer_hint()
    bot = Bot(token=settings.telegram_bot_token_trainer, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await bot.send_message(chat_id=telegram_id, text=html_body, reply_markup=kb)
    except Exception:
        pass
    finally:
        await bot.session.close()


async def _notify_trainer_profile_moderation_feedback(trainer: dict | None, feedback_text: str) -> None:
    """Notify trainer in Telegram when admin leaves profile moderation comment (needs edit)."""
    if not trainer:
        return
    text = (feedback_text or "").strip()
    if not text:
        return
    telegram_id = trainer.get("telegram_id")
    if not telegram_id:
        return
    safe_feedback = html.escape(text)
    body = msg.TRAINER_PROFILE_MODERATION_FEEDBACK_PUSH.format(feedback=safe_feedback)
    body += msg.TRAINER_PROFILE_MODERATION_FEEDBACK_PUSH_FOOTER
    await _trainer_bot_send_html_with_profile_button(int(telegram_id), body)


async def _trainer_bot_send_moderation_profile_approved(telegram_id: int) -> None:
    """HTML push: celebratory catalog approval + WebApp row «Профиль» + «Статистика»."""
    settings = Settings()
    if not settings.telegram_bot_token_trainer:
        return
    html_body = msg.TRAINER_MODERATION_PROFILE_APPROVED
    kb = _trainer_moderation_profile_approved_reply_markup()
    if kb is None:
        html_body = html_body + _trainer_profile_footer_hint()
    bot = Bot(token=settings.telegram_bot_token_trainer, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await bot.send_message(chat_id=telegram_id, text=html_body, reply_markup=kb)
    except Exception:
        pass
    finally:
        await bot.session.close()


async def _notify_trainer_moderation_approved(trainer: dict | None) -> None:
    """Notify trainer of first-time catalog approval only (not silent re-approval of profile edits)."""
    if not trainer:
        return
    telegram_id = trainer.get("telegram_id")
    if not telegram_id:
        return
    await _trainer_bot_send_moderation_profile_approved(int(telegram_id))


async def _notify_trainer_moderation_rejected(trainer: dict | None) -> None:
    """Notify trainer that the profile was rejected (deactivated / not in catalog)."""
    if not trainer:
        return
    telegram_id = trainer.get("telegram_id")
    if not telegram_id:
        return
    await _trainer_bot_send_html_with_profile_button(int(telegram_id), msg.TRAINER_MODERATION_PROFILE_REJECTED)


async def _send_trainer_for_moderation(message: Message, trainer_id: int) -> None:
    async with async_session_factory() as session:
        trainer = await get_trainer(session, trainer_id)
        education_items = await list_trainer_education(session, trainer_id, public_only=False)
        city_name = None
        if trainer:
            city_name = await fetch_city_name(session, (trainer.get("profile") or {}).get("city_id"))
    if not trainer:
        await message.answer(f"Тренер #{trainer_id} не найден.")
        return
    caption = format_admin_trainer_moderation_caption(trainer, education_items or [], city_name=city_name)
    trainer_named = build_trainer_profile_for_moderation_card(dict(trainer))
    profile = trainer_named.get("profile") or {}
    name_plain = ((profile.get("first_name") or "") + " " + (profile.get("last_name") or "")).strip() or "—"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=msg.ADMIN_BUTTON_APPROVE,
                callback_data=f"{ADMIN_APPROVE_PREFIX}{trainer_id}",
            ),
            InlineKeyboardButton(
                text=msg.ADMIN_BUTTON_REJECT,
                callback_data=f"{ADMIN_REJECT_PREFIX}{trainer_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text=msg.ADMIN_BUTTON_NEEDS_EDIT,
                callback_data=f"{ADMIN_NEEDS_EDIT_PREFIX}{trainer_id}",
            ),
        ],
    ])

    # Staged photo (active) or published trainer_photos
    file_key = trainer_photo_file_key_for_moderation_ui(trainer)
    body = await resolve_trainer_photo_bytes(file_key) if file_key else None
    if not body and file_key:
        logger.warning(
            "admin moderation: resolve_trainer_photo_bytes empty trainer_id=%s file_key=%s",
            trainer_id,
            file_key,
        )
    if body:
        photo_caption, continuation = split_photo_caption_if_needed(
            caption, trainer_id=trainer_id, name_plain=name_plain
        )
        try:
            if continuation:
                await message.answer_photo(
                    BufferedInputFile(body, filename="photo.jpg"),
                    caption=photo_caption,
                )
                await message.answer(continuation, reply_markup=keyboard)
            else:
                await message.answer_photo(
                    BufferedInputFile(body, filename="photo.jpg"),
                    caption=photo_caption,
                    reply_markup=keyboard,
                )
            return
        except Exception as e:
            logger.warning(
                "admin moderation photo send failed trainer_id=%s: %s",
                trainer_id,
                e,
            )
    # Text-only or photo path failed
    text_out = caption
    if len(text_out) > 4090:
        text_out = text_out[:4070] + "\n\n<i>…сообщение обрезано (лимит Telegram)</i>"
    await message.answer(text_out, reply_markup=keyboard)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    try:
        await register_admin_bot_commands(message.bot)
    except Exception:
        pass
    await message.answer(msg.ADMIN_START)


def _admin_stats_message(s: dict) -> str:
    """Build full admin stats message: current state, 7d, 30d, trainers, signals."""
    parts = [msg.ADMIN_STATS_TITLE]

    ws, we = s["week_start"], s["week_end"]
    d0 = ws.isoformat() if hasattr(ws, "isoformat") else str(ws)
    d1 = we.isoformat() if hasattr(we, "isoformat") else str(we)
    ns_lines = [
        msg.ADMIN_STATS_NORTH_STAR_CURRENT.format(
            d0=d0,
            d1=d1,
            n=s.get("north_star_completed_booking_cycles_week", 0),
        ),
        msg.ADMIN_STATS_NORTH_STAR_PREV.format(n=s.get("north_star_completed_booking_cycles_prev_week", 0)),
    ]
    parts.append(msg.ADMIN_STATS_SECTION_NORTH_STAR.format(lines="\n".join(ns_lines)))

    # Section: Сейчас
    now_lines = [
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_NOW_BOOKINGS_TODAY, value=s["bookings_today"]),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_NOW_BOOKINGS_WEEK, value=s["bookings_upcoming_week"]),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_NOW_REQUESTS_OPEN, value=s["requests_open_now"]),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_NOW_PENDING_MOD, value=s["trainers_pending_moderation"]),
    ]
    parts.append(msg.ADMIN_STATS_SECTION_NOW.format(lines="\n".join(now_lines)))

    # Section: За 7 дней
    week_lines = [
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_7D_BOOKINGS, value=s["bookings_7d"]),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_7D_REQUESTS, value=s["requests_7d"]),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_7D_RESPONSES, value=s["responses_7d"]),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_7D_TRAINERS, value=s["trainers_created_7d"]),
    ]
    parts.append(msg.ADMIN_STATS_SECTION_7D.format(lines="\n".join(week_lines)))

    # Section: За 30 дней
    conv_str = f"{s['requests_with_response_30d']} ({int(s['conversion_pct'])}%)" if s["conversion_pct"] is not None else str(s["requests_with_response_30d"])
    month_lines = [
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_30D_BOOKINGS, value=s["bookings_30d"]),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_30D_REQUESTS, value=s["requests_30d"]),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_30D_REQUESTS_NEW, value=s["requests_new_30d"]),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_30D_RESPONSES, value=s["responses_30d"]),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_30D_CONVERSION, value=conv_str),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_30D_TRAINERS, value=s["trainers_created_30d"]),
    ]
    parts.append(msg.ADMIN_STATS_SECTION_30D.format(lines="\n".join(month_lines)))

    # Section: Тренеры
    by_status = s["trainers_by_status"]
    status_lines = [
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_TRAINERS_TOTAL, value=s["trainers_total"]),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_TRAINERS_ACTIVE_LINKED, value=s["trainers_with_telegram"]),
    ]
    status_lines += [msg.ADMIN_STATS_ROW.format(label=TRAINER_STATUS_LABELS.get(k, k), value=v) for k, v in sorted(by_status.items())]
    parts.append(msg.ADMIN_STATS_SECTION_TRAINERS.format(lines="\n".join(status_lines)))

    act_counts = s.get("activation_stage_counts") or {}
    labels = s.get("activation_stage_labels_ru") or ACTIVATION_STAGE_LABEL_RU
    act_lines = [
        msg.ADMIN_STATS_ACTIVATION_STAGE.format(label=labels.get(k, k), n=int(act_counts.get(k, 0) or 0))
        for k in ACTIVATION_STAGE_ORDER
    ]
    act_lines.append(msg.ADMIN_STATS_ACTIVATION_HINT)
    parts.append(msg.ADMIN_STATS_SECTION_ACTIVATION.format(lines="\n".join(act_lines)))

    # Section: Абонементы и сертификаты
    cert_byn = (s.get("cert_balance_cents_total") or 0) / 100
    cert_byn_str = f"{cert_byn:.0f}" if cert_byn == int(cert_byn) else f"{cert_byn:.2f}"
    pass_cert_lines = [
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_PASSES_ACTIVE, value=s.get("passes_active_total", 0)),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_PASSES_ISSUED_30D, value=s.get("passes_issued_30d_total", 0)),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_CERTS_ISSUED, value=s.get("certs_issued_total", 0)),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_CERTS_WITH_BALANCE, value=s.get("certs_with_balance_total", 0)),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_CERTS_BALANCE_BYN, value=cert_byn_str),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_CERTS_REDEEMED_30D, value=s.get("certs_redeemed_30d_total", 0)),
    ]
    parts.append(msg.ADMIN_STATS_SECTION_PASSES_CERTS.format(lines="\n".join(pass_cert_lines)))

    # Section: Подписки (tier)
    sub_lines = [
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_SUB_TIER_CRM, value=s.get("subscription_tier_crm", 0)),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_SUB_TIER_ONLINE, value=s.get("subscription_tier_online", 0)),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_SUB_TIER_ANALYTICS, value=s.get("subscription_tier_analytics", 0)),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_SUB_TOTAL_WITH_TIER, value=s.get("subscription_trainers_with_tier", 0)),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_SUB_EXPIRING_7D, value=s.get("subscription_expiring_7d", 0)),
        msg.ADMIN_STATS_ROW.format(label=msg.ADMIN_STATS_SUB_ACTIVE_NO_TIER, value=s.get("subscription_active_trainers_no_tier", 0)),
    ]
    parts.append(msg.ADMIN_STATS_SECTION_SUBSCRIPTIONS.format(lines="\n".join(sub_lines)))

    # Section: Сигналы (что проверить)
    signal_lines = []
    if s["trainers_pending_moderation"] > 0:
        signal_lines.append(msg.ADMIN_STATS_SIGNAL_PENDING.format(n=s["trainers_pending_moderation"]))
    if s["requests_open_now"] > 0:
        signal_lines.append(msg.ADMIN_STATS_SIGNAL_REQUESTS_OPEN.format(n=s["requests_open_now"]))
    if s["requests_stale"] > 0:
        signal_lines.append(msg.ADMIN_STATS_SIGNAL_REQUESTS_STALE.format(n=s["requests_stale"]))
    if s["bookings_7d"] == 0 and s["trainers_active"] > 0:
        signal_lines.append(msg.ADMIN_STATS_SIGNAL_NO_BOOKINGS.format(active=s["trainers_active"]))
    if s["conversion_pct"] is not None and s["requests_30d"] >= 3 and s["conversion_pct"] < 50:
        signal_lines.append(msg.ADMIN_STATS_SIGNAL_LOW_CONVERSION.format(pct=int(s["conversion_pct"])))
    if signal_lines:
        parts.append(msg.ADMIN_STATS_SECTION_SIGNALS.format(lines="\n".join(signal_lines)))

    return "\n".join(parts)


@router.callback_query(lambda c: c.data == "admin:menu:pending")
async def admin_menu_pending(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id if callback.from_user else 0):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer("Используйте команду /pending для очереди тренеров на модерацию.")


@router.callback_query(lambda c: c.data == "admin:menu:support")
async def admin_menu_support(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id if callback.from_user else 0):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    async with async_session_factory() as session:
        items = await list_support_messages(session, limit=15, status=None)
    if not items:
        await callback.message.answer(msg.ADMIN_SUPPORT_EMPTY)
        return
    parts = [msg.ADMIN_SUPPORT_LIST_TITLE]
    kb_rows = []
    for it in items:
        role = "тренер" if it.get("from_role") == "trainer" else "клиент"
        date_str = (it.get("created_at") or "")[:10] if it.get("created_at") else ""
        text_preview = (it.get("message_text") or "")[:80].replace("\n", " ")
        if len((it.get("message_text") or "")) > 80:
            text_preview += "..."
        parts.append(msg.ADMIN_SUPPORT_ITEM.format(id=it["id"], role=role, date=date_str, text=text_preview))
        kb_rows.append([InlineKeyboardButton(
            text=f"Ответить #{it['id']}",
            callback_data=f"{ADMIN_SUPPORT_REPLY_PREFIX}{it['id']}",
        )])
    await callback.message.answer(
        "\n".join(parts),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )


@router.callback_query(lambda c: c.data and c.data.startswith(ADMIN_SUPPORT_REPLY_PREFIX))
async def admin_support_reply_start(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id if callback.from_user else 0):
        await callback.answer("Нет доступа", show_alert=True)
        return
    support_id = safe_parse_id(callback.data[len(ADMIN_SUPPORT_REPLY_PREFIX) :])
    if support_id is None:
        await callback.answer("Ошибка", show_alert=True)
        return
    await callback.answer()
    _admin_awaiting_support_reply[callback.from_user.id] = support_id  # type: ignore[union-attr]
    await callback.message.answer(msg.ADMIN_SUPPORT_REPLY_PROMPT)


@router.message(Command("support"))
async def cmd_support(message: Message) -> None:
    """List support tickets and allow reply."""
    if not _is_admin(message.from_user.id if message.from_user else 0):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    async with async_session_factory() as session:
        items = await list_support_messages(session, limit=15, status=None)
    if not items:
        await message.answer(msg.ADMIN_SUPPORT_EMPTY)
        return
    parts = [msg.ADMIN_SUPPORT_LIST_TITLE]
    kb_rows = []
    for it in items:
        role = "тренер" if it.get("from_role") == "trainer" else "клиент"
        date_str = (it.get("created_at") or "")[:10] if it.get("created_at") else ""
        text_preview = (it.get("message_text") or "")[:80].replace("\n", " ")
        if len((it.get("message_text") or "")) > 80:
            text_preview += "..."
        parts.append(msg.ADMIN_SUPPORT_ITEM.format(id=it["id"], role=role, date=date_str, text=text_preview))
        kb_rows.append([InlineKeyboardButton(
            text=f"Ответить #{it['id']}",
            callback_data=f"{ADMIN_SUPPORT_REPLY_PREFIX}{it['id']}",
        )])
    await message.answer(
        "\n".join(parts),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )


@router.message(Command("version"))
async def cmd_version(message: Message) -> None:
    """Deploy label + GET /health (API + DB + S3)."""
    if not _is_admin(message.from_user.id if message.from_user else 0):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    settings = Settings()
    health = await fetch_api_health()
    text = format_admin_version_message(settings, health)
    await message.answer(text, parse_mode=ParseMode.HTML)


def _admin_problem_report_slot_and_created(it: dict) -> tuple[str, str]:
    sd, st, et = it.get("slot_date"), it.get("start_time"), it.get("end_time")
    slot_s = "—"
    if sd is not None:
        dpart = sd.strftime("%d.%m.%y") if hasattr(sd, "strftime") else str(sd)
        t1 = st.strftime("%H:%M") if st and hasattr(st, "strftime") else ""
        t2 = et.strftime("%H:%M") if et and hasattr(et, "strftime") else ""
        slot_s = f"{dpart} {t1}–{t2}".strip()
    ca = it.get("created_at")
    if ca is not None and hasattr(ca, "isoformat"):
        created_s = ca.isoformat(timespec="seconds")
    else:
        created_s = str(ca or "—")
    return slot_s, created_s


@router.message(Command("problem_reports"))
async def cmd_problem_reports(message: Message) -> None:
    """E6 T6.2: list immutable problem reports (optional blacklist candidates, offset pagination)."""
    if not _is_admin(message.from_user.id if message.from_user else 0):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    parts = (message.text or "").split()
    blacklist_only = False
    offset = 0
    if len(parts) >= 2:
        if parts[1].lower() == "blacklist":
            blacklist_only = True
            if len(parts) >= 3:
                try:
                    offset = max(0, int(parts[2]))
                except ValueError:
                    await message.answer("Смещение: целое число, напр. <code>/problem_reports blacklist 15</code>.")
                    return
        else:
            try:
                offset = max(0, int(parts[1]))
            except ValueError:
                await message.answer("Некорректный аргумент. См. <code>/problem_reports</code>.")
                return

    page_limit = 12
    async with async_session_factory() as session:
        total = await count_booking_problem_reports_for_admin(session, blacklist_only=blacklist_only)
        items = await list_booking_problem_reports_for_admin(
            session,
            limit=page_limit,
            offset=offset,
            blacklist_only=blacklist_only,
        )

    head = msg.ADMIN_PROBLEM_REPORTS_TITLE
    if blacklist_only:
        head += msg.ADMIN_PROBLEM_REPORTS_FILTER_BLACKLIST
    if not items:
        await message.answer(
            head + msg.ADMIN_PROBLEM_REPORTS_EMPTY,
            parse_mode=ParseMode.HTML,
        )
        return

    audit_log(
        "admin_problem_reports_list_viewed",
        ACTOR_ADMIN_BOT,
        message.from_user.id if message.from_user else 0,
        payload={
            "blacklist_only": blacklist_only,
            "offset": offset,
            "rows_returned": len(items),
        },
    )

    lines: list[str] = [head]
    for i, it in enumerate(items, start=1):
        bl_lbl = "канд. blacklist" if it.get("blacklist_candidate") else "—"
        pol = (it.get("policy_breach_code") or "").strip()
        bl_extra = f"{bl_lbl} ({pol})" if pol else bl_lbl
        slot_s, created_s = _admin_problem_report_slot_and_created(it)
        lines.append(
            msg.ADMIN_PROBLEM_REPORTS_LINE.format(
                n=i,
                rid=it["id"],
                bid=it["booking_id"],
                tid=it["trainer_id"],
                preset=html.escape(it.get("preset_id") or ""),
                pclass=html.escape(it.get("payment_class") or ""),
                bl=html.escape(bl_extra),
                status=html.escape(it.get("booking_status") or ""),
                slot=html.escape(slot_s),
                created=html.escape(created_s),
            )
        )
    footer = msg.ADMIN_PROBLEM_REPORTS_FOOTER.format(shown=len(items), total=total)
    out = "".join(lines) + footer
    if len(out) > 4090:
        out = out[:4070] + "\n\n<i>…обрезано (лимит Telegram)</i>"
    await message.answer(out, parse_mode=ParseMode.HTML)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Open platform analytics — menu of Mini Apps (overview + five dashboards).

    Each button opens a focused dashboard. Drilldown happens inside each app
    (tap a card to expand details about a specific trainer/invoice/request).
    """
    if not _is_admin(message.from_user.id if message.from_user else 0):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    base = (Settings().webapp_base_url or "").rstrip("/")
    if not base:
        async with async_session_factory() as session:
            s = await get_platform_stats(session)
        await message.answer(_admin_stats_message(s), parse_mode=ParseMode.HTML)
        return

    def _wa(label: str, slug: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=label, web_app=WebAppInfo(url=f"{base}/webapp/{slug}"))

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [_wa("📊 Обзор", "admin-stats"),       _wa("💰 Деньги", "admin-money")],
        [_wa("📈 Рост", "admin-growth"),       _wa("🔁 Удержание", "admin-retention")],
        [_wa("🎯 Активность", "admin-engagement"), _wa("👥 Клиенты", "admin-clients")],
        [_wa("🕓 История", "admin-activity")],
    ])
    await message.answer(
        "📊 <b>Аналитика платформы</b>\n\n"
        "Выберите раздел — каждый открывается отдельным мини-приложением.\n"
        "Внутри карточки можно тапнуть, чтобы развернуть детали по конкретному тренеру/счёту.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


@router.message(Command("dicts"))
async def cmd_dicts(message: Message) -> None:
    """Open cities & arenas Mini App."""
    if not _is_admin(message.from_user.id if message.from_user else 0):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    base = Settings().webapp_base_url or ""
    url = f"{base.rstrip('/')}/webapp/admin-dicts" if base else ""
    if not url:
        await message.answer("Не настроен webapp_base_url. Укажите в .env.")
        return
    await message.answer(
        "🏙 Города и арены",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Открыть справочники", web_app=WebAppInfo(url=url))],
        ]),
    )


@router.message(Command("subscription_tiers"))
async def cmd_subscription_tiers(message: Message) -> None:
    """Open admin Mini App to edit subscription tier pricing."""
    if not _is_admin(message.from_user.id if message.from_user else 0):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    base = Settings().webapp_base_url or ""
    url = f"{base.rstrip('/')}/webapp/admin-subscription-tiers" if base else ""
    if not url:
        await message.answer("Не настроен webapp_base_url. Укажите в .env.")
        return
    await message.answer(
        f"{msg.ADMIN_SUBSCRIPTION_TIERS_TITLE}\n\n{msg.ADMIN_SUBSCRIPTION_TIERS_HINT}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Открыть тарифы", web_app=WebAppInfo(url=url))],
        ]),
    )


@router.message(Command("subscription_invoices"))
async def cmd_subscription_invoices(message: Message) -> None:
    """List unpaid catalog subscription invoices (ERIP / manual checkout). One actionable card per item."""
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    async with async_session_factory() as session:
        items = await list_pending_catalog_subscription_invoices(session, limit=40)
    audit_log(
        "admin_subscription_invoices_list_viewed",
        ACTOR_ADMIN_BOT,
        user_id,
        payload={"rows_returned": len(items)},
    )
    if not items:
        await message.answer(
            msg.ADMIN_SUBSCRIPTION_INVOICES_TITLE + msg.ADMIN_SUBSCRIPTION_INVOICES_EMPTY,
            parse_mode=ParseMode.HTML,
        )
        return
    await message.answer(msg.ADMIN_SUBSCRIPTION_INVOICES_TITLE, parse_mode=ParseMode.HTML)
    for i, it in enumerate(items, start=1):
        tid = int(it["trainer_id"])
        fn = (it.get("first_name") or "").strip()
        ln = (it.get("last_name") or "").strip()
        name_plain = " ".join([fn, ln]).strip() or f"id{tid}"
        bundle = it.get("checkout_bundle_tier")
        bpm = it.get("checkout_billing_period_months")
        if bundle:
            plan_short = html.escape(f"пакет {bundle} · {bpm} мес.")
        else:
            plan_short = html.escape(
                f"конструктор · {bpm} мес. · {format_catalog_modules_short(it.get('checkout_modules'))}"
            )
        amt = int(it["amount_cents"]) / 100
        amt_s = str(int(amt)) if amt == int(amt) else f"{amt:.2f}"
        ps = it.get("period_start")
        pe = it.get("period_end")
        ps_s = ps.strftime("%d.%m.%y") if hasattr(ps, "strftime") else str(ps)[:10]
        pe_s = pe.strftime("%d.%m.%y") if hasattr(pe, "strftime") else str(pe)[:10]
        link = trainer_contact_link_html(it.get("telegram_id"), it.get("telegram_username"))
        card = msg.ADMIN_SUBSCRIPTION_INVOICES_LINE.format(
            n=i,
            iid=it["invoice_id"],
            tid=tid,
            name=html.escape(name_plain),
            plan_short=plan_short,
            amt=amt_s,
            ps=html.escape(ps_s),
            pe=html.escape(pe_s),
            st=html.escape(str(it.get("status") or "")),
            link=link,
        )
        kb = build_admin_subscription_invoice_keyboard(int(it["invoice_id"]))
        await message.answer(card, parse_mode=ParseMode.HTML, reply_markup=kb)


# ---------------------------------------------------------------------------
# Admin: grant / edit / cancel subscription invoices via inline buttons.
#
# Callback grammar (kept under Telegram's 64-byte limit). `mode` in {s, m}:
#   s = stack    — new subscription period (extends after current, or starts now)
#   m = merge    — add modules to the trainer's current paid subscription in place,
#                  pro-rated to the remaining days (no period extension)
#
#   as:act:{iid}                                        one-tap activate as requested
#   as:cancel:{iid}                                     decline the request
#   as:edit:{iid}                                       open editor seeded from invoice
#   as:mode:{iid}:{flags}:{months}:{mode}               switch editor mode
#   as:tog:{iid}:{flags}:{months}:{mode}:{module}       toggle a module bit
#   as:setper:{iid}:{flags}:{months}:{mode}             apply chosen period (stack only)
#   as:apply:{iid}:{flags}:{months}:{mode}              commit edits and activate
#
# `flags` packs the three module bits: 1=online, 2=analytics, 4=groups.
# ---------------------------------------------------------------------------

ADMIN_SUBSCRIPTION_GRANT_PREFIX = "as:"

_MODULE_BITS = {
    SUBSCRIPTION_MODULE_ONLINE: 1,
    SUBSCRIPTION_MODULE_ANALYTICS: 2,
    SUBSCRIPTION_MODULE_GROUPS: 4,
}
_MODULE_LABELS = {
    SUBSCRIPTION_MODULE_ONLINE: "Онлайн-запись",
    SUBSCRIPTION_MODULE_ANALYTICS: "Аналитика",
    SUBSCRIPTION_MODULE_GROUPS: "Группы",
}


def _flags_to_modules(flags: int) -> dict[str, bool]:
    return {k: bool(int(flags) & bit) for k, bit in _MODULE_BITS.items()}


def _modules_to_flags(modules: dict | None) -> int:
    f = 0
    if not isinstance(modules, dict):
        return f
    for k, bit in _MODULE_BITS.items():
        if modules.get(k):
            f |= bit
    return f


async def _calc_total_byn(session, flags: int, months: int) -> tuple[int | None, int | None]:
    """Return (total_cents, period_days) for current editor state, or (None, None) if pricing missing."""
    base = await get_tier_period_pricing(session, SUBSCRIPTION_TIER_CRM, months)
    if not base:
        return None, None
    total = int(base["price_cents"])
    period_days = int(base["period_days"])
    mods = _flags_to_modules(flags)
    for key in SUBSCRIPTION_MODULES:
        if not mods.get(key):
            continue
        mp = await get_module_period_pricing(session, key, months)
        if not mp:
            return None, None
        total += int(mp["price_cents"])
    return total, period_days


_MODE_STACK = "s"
_MODE_MERGE = "m"


def _fmt_amount_byn(cents: int | None) -> str:
    if cents is None:
        return "—"
    v = int(cents) / 100
    return str(int(v)) if v == int(v) else f"{v:.2f}"


def _fmt_date_ru(d) -> str:
    return d.strftime("%d.%m.%Y") if d and hasattr(d, "strftime") else "—"


async def _build_editor_keyboard(
    session,
    invoice_id: int,
    trainer_id: int,
    flags: int,
    months: int,
    mode: str,
) -> InlineKeyboardMarkup:
    """
    Editor keyboard. In merge mode the period row is replaced by a lock, module toggles
    for modules ALREADY active on the current sub are marked (cannot remove them), and
    the activate button reflects pro-rated add-on pricing.
    """
    current = await get_active_paid_subscription_for_merge(session, trainer_id)
    can_merge = current is not None
    effective_mode = mode if (mode == _MODE_STACK or (mode == _MODE_MERGE and can_merge)) else _MODE_STACK

    rows: list[list[InlineKeyboardButton]] = []

    # Row 1: mode toggle (only shown if trainer has an active paid subscription).
    if can_merge:
        expires_str = _fmt_date_ru(current["expires_at"])
        stack_marker = "✅ " if effective_mode == _MODE_STACK else ""
        merge_marker = "✅ " if effective_mode == _MODE_MERGE else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{stack_marker}🔄 Продлить",
                callback_data=f"as:mode:{invoice_id}:{int(flags)}:{int(months)}:{_MODE_STACK}",
            ),
            InlineKeyboardButton(
                text=f"{merge_marker}➕ Добавить (до {expires_str})",
                callback_data=f"as:mode:{invoice_id}:{int(flags)}:{int(months)}:{_MODE_MERGE}",
            ),
        ])

    # CRM base indicator. In merge mode it stays on (can't remove), in stack mode also on.
    rows.append([InlineKeyboardButton(text="✅ CRM (база — всегда включена)", callback_data="as:noop")])

    for code in SUBSCRIPTION_MODULES:
        bit = _MODULE_BITS[code]
        is_on_in_editor = bool(int(flags) & bit)
        already_active = bool(effective_mode == _MODE_MERGE and current and current["modules"].get(code))
        if already_active:
            # In merge mode we don't allow removing modules the trainer already paid for.
            rows.append([
                InlineKeyboardButton(
                    text=f"✅ {_MODULE_LABELS[code]} (уже активен)",
                    callback_data="as:noop",
                )
            ])
        else:
            prefix = "✅" if is_on_in_editor else "➕"
            rows.append([
                InlineKeyboardButton(
                    text=f"{prefix} {_MODULE_LABELS[code]}",
                    callback_data=f"as:tog:{invoice_id}:{int(flags)}:{int(months)}:{effective_mode}:{code}",
                )
            ])

    if effective_mode == _MODE_STACK:
        period_row: list[InlineKeyboardButton] = []
        for m in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
            marker = "✅ " if int(months) == m else ""
            period_row.append(
                InlineKeyboardButton(
                    text=f"{marker}{m} мес.",
                    callback_data=f"as:setper:{invoice_id}:{int(flags)}:{m}:{_MODE_STACK}",
                )
            )
        rows.append(period_row)
        rows.append([
            InlineKeyboardButton(
                text=f"✅ Активировать на {int(months)} мес.",
                callback_data=f"as:apply:{invoice_id}:{int(flags)}:{int(months)}:{_MODE_STACK}",
            )
        ])
    else:
        # Merge mode: period is dictated by remaining days of current sub, not editable.
        expires_str = _fmt_date_ru(current["expires_at"]) if current else "—"
        rows.append([
            InlineKeyboardButton(
                text=f"✅ Добавить к текущей (до {expires_str})",
                callback_data=f"as:apply:{invoice_id}:{int(flags)}:{int(months)}:{_MODE_MERGE}",
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="❌ Отклонить заявку",
            callback_data=f"as:cancel:{invoice_id}",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _format_editor_body(
    session,
    invoice_view: dict,
    flags: int,
    months: int,
    mode: str = _MODE_STACK,
) -> str:
    tid = int(invoice_view["trainer_id"])
    fn = (invoice_view.get("first_name") or "").strip()
    ln = (invoice_view.get("last_name") or "").strip()
    name_plain = " ".join([fn, ln]).strip() or f"id{tid}"
    contact_url = trainer_contact_url(invoice_view.get("telegram_id"), invoice_view.get("telegram_username"))
    contact_block = (
        f'<a href="{html.escape(contact_url)}">Открыть контакт тренера в Telegram</a>'
        if contact_url
        else "<i>Нет @username / id — ищите по internal id.</i>"
    )

    editor_flags_modules = _flags_to_modules(flags)

    if mode == _MODE_MERGE:
        current = await get_active_paid_subscription_for_merge(session, tid)
        if current:
            added_codes = [k for k in SUBSCRIPTION_MODULES if editor_flags_modules.get(k) and not current["modules"].get(k)]
            total_modules = dict(current["modules"])
            for k in added_codes:
                total_modules[k] = True
            final_label = format_subscription_label(total_modules)
            cost_cents = await compute_prorated_module_addon_cost_cents(session, added_codes, current["remaining_days"])
            amount_str = _fmt_amount_byn(cost_cents)
            added_label = ", ".join(_MODULE_LABELS[c] for c in added_codes) or "—"
            plan_line = (
                f"Режим: <b>Добавить модули к текущей</b>\n"
                f"До: <b>{_fmt_date_ru(current['expires_at'])}</b> "
                f"(осталось {current['remaining_days']} дн.)\n"
                f"Добавляем: <b>{html.escape(added_label)}</b>\n"
                f"После активации: <b>{html.escape(final_label)}</b>"
            )
            return msg.ADMIN_SUBSCRIPTION_GRANT_EDIT_TITLE.format(
                invoice_id=int(invoice_view["invoice_id"]),
                trainer_name=html.escape(name_plain),
                trainer_id=tid,
                plan_line=plan_line,
                amount_byn=amount_str,
                months=f"пропорц. {current['remaining_days']} дн.",
                trainer_contact_block=contact_block,
            )
        # Fall through to stack rendering if no current paid sub (shouldn't happen, but safe).

    total_cents, _ = await _calc_total_byn(session, flags, months)
    plan_label = format_subscription_label(editor_flags_modules)
    amount_str = _fmt_amount_byn(total_cents)
    plan_line = f"Режим: <b>Новый период</b>\nСостав: <b>{html.escape(plan_label)}</b>"
    return msg.ADMIN_SUBSCRIPTION_GRANT_EDIT_TITLE.format(
        invoice_id=int(invoice_view["invoice_id"]),
        trainer_name=html.escape(name_plain),
        trainer_id=tid,
        plan_line=plan_line,
        amount_byn=amount_str,
        months=f"{int(months)} мес.",
        trainer_contact_block=contact_block,
    )


async def _notify_trainer_subscription_granted(
    trainer_id: int,
    label: str,
    expires_iso: str | None,
) -> None:
    """Push to trainer bot when admin activates their subscription."""
    settings = Settings()
    if not settings.telegram_bot_token_trainer:
        return
    async with async_session_factory() as session:
        r = await session.execute(
            text("SELECT telegram_id FROM trainers WHERE id = :id"),
            {"id": int(trainer_id)},
        )
        row = r.fetchone()
    if not row or not row[0]:
        return
    expires_date = "—"
    if expires_iso:
        s = str(expires_iso)[:10]
        try:
            y, m, d = s.split("-")
            expires_date = f"{d}.{m}.{y}"
        except ValueError:
            expires_date = s
    body = msg.TRAINER_SUBSCRIPTION_GRANTED_BY_ADMIN.format(
        label=html.escape(label),
        expires_date=html.escape(expires_date),
    )
    bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        try:
            await bot.send_message(chat_id=int(row[0]), text=body)
        except Exception:
            logger.exception(
                "trainer subscription grant notification failed trainer_id=%s",
                trainer_id,
            )
    finally:
        await bot.session.close()


async def _notify_trainer_subscription_invoice_declined(trainer_id: int) -> None:
    settings = Settings()
    if not settings.telegram_bot_token_trainer:
        return
    async with async_session_factory() as session:
        r = await session.execute(
            text("SELECT telegram_id FROM trainers WHERE id = :id"),
            {"id": int(trainer_id)},
        )
        row = r.fetchone()
    if not row or not row[0]:
        return
    bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        try:
            await bot.send_message(
                chat_id=int(row[0]),
                text=msg.TRAINER_SUBSCRIPTION_INVOICE_DECLINED,
            )
        except Exception:
            logger.exception(
                "trainer subscription decline notification failed trainer_id=%s",
                trainer_id,
            )
    finally:
        await bot.session.close()


@router.callback_query(lambda c: c.data == "as:noop")
async def on_admin_sub_invoice_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("cs:act:"))
async def on_admin_collective_invoice_activate(callback: CallbackQuery) -> None:
    """One-tap: confirm studio pool invoice (ERIP / manual)."""
    user_id = callback.from_user.id if callback.from_user else 0
    if not _is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    iid = safe_parse_id(callback.data[len("cs:act:"):])
    if iid is None:
        await callback.answer()
        return
    async with async_session_factory() as session:
        result = await admin_confirm_collective_invoice(session, iid, admin_id=user_id)
    if not result:
        await callback.answer("Счёт не найден или уже обработан", show_alert=True)
        return
    await callback.answer("Pool-подписка активирована")
    if callback.message:
        await callback.message.answer(
            msg.ADMIN_COLLECTIVE_INVOICE_CONFIRMED.format(
                invoice_id=result["invoice_id"],
                display_name=html.escape(result["display_name"]),
                slug=html.escape(result["slug"]),
            ),
            parse_mode=ParseMode.HTML,
        )


@router.callback_query(lambda c: c.data and c.data.startswith("as:act:"))
async def on_admin_sub_invoice_activate(callback: CallbackQuery) -> None:
    """One-tap: activate the trainer's invoice exactly as they requested."""
    user_id = callback.from_user.id if callback.from_user else 0
    if not _is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    iid = safe_parse_id(callback.data[len("as:act:"):])
    if iid is None:
        await callback.answer()
        return
    async with async_session_factory() as session:
        view = await load_subscription_invoice_admin_view(session, iid)
        if not view:
            await callback.answer(msg.ADMIN_SUBSCRIPTION_GRANT_NOT_FOUND, show_alert=True)
            return
        result = await admin_grant_subscription_for_invoice(
            session, iid, modules=None, period_months=None, admin_id=user_id
        )
    if not result:
        await callback.answer(msg.ADMIN_SUBSCRIPTION_GRANT_FAILED, show_alert=True)
        return
    await _send_grant_success(callback, view, result)


@router.callback_query(lambda c: c.data and c.data.startswith("as:cancel:"))
async def on_admin_sub_invoice_cancel(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    if not _is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    iid = safe_parse_id(callback.data[len("as:cancel:"):])
    if iid is None:
        await callback.answer()
        return
    async with async_session_factory() as session:
        result = await admin_cancel_pending_subscription_invoice(session, iid)
    if not result:
        await callback.answer(msg.ADMIN_SUBSCRIPTION_GRANT_NOT_FOUND, show_alert=True)
        return
    audit_log(
        "admin_subscription_invoice_cancelled",
        ACTOR_ADMIN_BOT,
        user_id,
        payload={"invoice_id": int(iid), "trainer_id": int(result["trainer_id"])},
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        msg.ADMIN_SUBSCRIPTION_GRANT_CANCELLED.format(invoice_id=int(iid)),
        parse_mode=ParseMode.HTML,
    )
    await _notify_trainer_subscription_invoice_declined(int(result["trainer_id"]))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("as:edit:"))
async def on_admin_sub_invoice_edit(callback: CallbackQuery) -> None:
    """Open the module/period editor seeded from the invoice's current state."""
    user_id = callback.from_user.id if callback.from_user else 0
    if not _is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    iid = safe_parse_id(callback.data[len("as:edit:"):])
    if iid is None:
        await callback.answer()
        return
    async with async_session_factory() as session:
        view = await load_subscription_invoice_admin_view(session, iid)
        if not view:
            await callback.answer(msg.ADMIN_SUBSCRIPTION_GRANT_NOT_FOUND, show_alert=True)
            return
        flags = _modules_to_flags(view.get("checkout_modules"))
        months = int(view.get("checkout_billing_period_months") or 1)
        if months not in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
            months = SUBSCRIPTION_BILLING_PERIOD_MONTHS[0]
        # Default mode: stack. Admin can flip to merge via the mode button if applicable.
        mode = _MODE_STACK
        body = await _format_editor_body(session, view, flags, months, mode)
        kb = await _build_editor_keyboard(session, int(iid), int(view["trainer_id"]), flags, months, mode)
    await callback.message.answer(body, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()


async def _re_render_editor(callback: CallbackQuery, iid: int, flags: int, months: int, mode: str) -> None:
    async with async_session_factory() as session:
        view = await load_subscription_invoice_admin_view(session, iid)
        if not view:
            await callback.answer(msg.ADMIN_SUBSCRIPTION_GRANT_NOT_FOUND, show_alert=True)
            return
        body = await _format_editor_body(session, view, flags, months, mode)
        kb = await _build_editor_keyboard(session, int(iid), int(view["trainer_id"]), flags, months, mode)
    try:
        await callback.message.edit_text(body, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(body, reply_markup=kb, parse_mode=ParseMode.HTML)


def _parse_mode(part: str) -> str:
    return _MODE_MERGE if part == _MODE_MERGE else _MODE_STACK


@router.callback_query(lambda c: c.data and c.data.startswith("as:mode:"))
async def on_admin_sub_invoice_mode(callback: CallbackQuery) -> None:
    """Flip editor between stack (new period) and merge (add modules to current)."""
    user_id = callback.from_user.id if callback.from_user else 0
    if not _is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 6:
        await callback.answer()
        return
    try:
        iid = int(parts[2]); flags = int(parts[3]); months = int(parts[4])
    except ValueError:
        await callback.answer()
        return
    mode = _parse_mode(parts[5])
    # When switching TO merge: pre-fill editor flags from current sub's modules + requested delta,
    # so all existing modules show as selected (admin can only add, not remove in merge mode).
    if mode == _MODE_MERGE:
        async with async_session_factory() as session:
            view = await load_subscription_invoice_admin_view(session, iid)
            if view:
                current = await get_active_paid_subscription_for_merge(session, int(view["trainer_id"]))
                if current:
                    current_flags = _modules_to_flags(current["modules"])
                    flags = int(flags) | current_flags
    await _re_render_editor(callback, iid, flags, months, mode)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("as:tog:"))
async def on_admin_sub_invoice_toggle(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    if not _is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 7:
        await callback.answer()
        return
    try:
        iid = int(parts[2]); flags = int(parts[3]); months = int(parts[4])
    except ValueError:
        await callback.answer()
        return
    mode = _parse_mode(parts[5])
    code = parts[6]
    bit = _MODULE_BITS.get(code)
    if bit is None:
        await callback.answer()
        return
    flags ^= bit
    await _re_render_editor(callback, iid, flags, months, mode)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("as:setper:"))
async def on_admin_sub_invoice_setper(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    if not _is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 6:
        await callback.answer()
        return
    try:
        iid = int(parts[2]); flags = int(parts[3]); months = int(parts[4])
    except ValueError:
        await callback.answer()
        return
    mode = _parse_mode(parts[5])
    if months not in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
        await callback.answer()
        return
    await _re_render_editor(callback, iid, flags, months, mode)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("as:apply:"))
async def on_admin_sub_invoice_apply(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    if not _is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 6:
        await callback.answer()
        return
    try:
        iid = int(parts[2]); flags = int(parts[3]); months = int(parts[4])
    except ValueError:
        await callback.answer()
        return
    mode = _parse_mode(parts[5])
    if mode == _MODE_STACK and months not in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
        await callback.answer(msg.ADMIN_SUBSCRIPTION_GRANT_FAILED, show_alert=True)
        return
    new_modules = _flags_to_modules(flags)
    async with async_session_factory() as session:
        view = await load_subscription_invoice_admin_view(session, iid)
        if not view:
            await callback.answer(msg.ADMIN_SUBSCRIPTION_GRANT_NOT_FOUND, show_alert=True)
            return
        if mode == _MODE_MERGE:
            result = await admin_merge_modules_into_current_subscription(
                session, iid, add_modules=new_modules, admin_id=user_id
            )
        else:
            result = await admin_grant_subscription_for_invoice(
                session, iid, modules=new_modules, period_months=int(months), admin_id=user_id
            )
    if not result:
        await callback.answer(msg.ADMIN_SUBSCRIPTION_GRANT_FAILED, show_alert=True)
        return
    await _send_grant_success(callback, view, result)


async def _send_grant_success(callback: CallbackQuery, view: dict, result: dict) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    iid = int(result["invoice_id"])
    tid = int(result["trainer_id"])
    label = format_subscription_label(result.get("modules") or default_modules_dict())
    months = int(result.get("period_months") or 0)
    is_merge = bool(result.get("merged"))
    amount_cents = result.get("amount_cents") or 0
    amt = amount_cents / 100
    amount_byn = str(int(amt)) if amt == int(amt) else f"{amt:.2f}"
    period_end = result.get("period_end")
    if hasattr(period_end, "strftime"):
        expires_date = period_end.strftime("%d.%m.%Y")
        expires_iso = period_end.isoformat()
    else:
        expires_date = str(period_end)[:10] if period_end else "—"
        expires_iso = str(period_end) if period_end else None
    fn = (view.get("first_name") or "").strip()
    ln = (view.get("last_name") or "").strip()
    name_plain = " ".join([fn, ln]).strip() or f"id{tid}"
    audit_log(
        "admin_subscription_invoice_granted" if not is_merge else "admin_subscription_modules_merged",
        ACTOR_ADMIN_BOT,
        user_id,
        payload={
            "invoice_id": iid,
            "trainer_id": tid,
            "modules": result.get("modules"),
            "added_modules": result.get("added_modules"),
            "period_months": months,
            "amount_cents": int(amount_cents),
            "merged": is_merge,
        },
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    # In merge mode we spell out that we extended the existing subscription, not started a new one.
    period_str = f"{months} мес." if not is_merge else f"пропорц. {int(result.get('remaining_days') or 0)} дн."
    await callback.message.answer(
        msg.ADMIN_SUBSCRIPTION_GRANT_ACTIVATED.format(
            invoice_id=iid,
            trainer_name=html.escape(name_plain),
            label=html.escape(label),
            months=period_str,
            amount_byn=amount_byn,
            expires_date=html.escape(expires_date),
        ),
        parse_mode=ParseMode.HTML,
    )
    await _notify_trainer_subscription_granted(tid, label, expires_iso)
    await callback.answer("Активировано")


@router.message(Command("grant_subscription"))
async def cmd_grant_subscription(message: Message) -> None:
    """Ad-hoc grant: open the editor for any trainer (creates a draft CRM invoice first)."""
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer(msg.ADMIN_SUBSCRIPTION_GRANT_HELP, parse_mode=ParseMode.HTML)
        return
    tid = safe_parse_id(parts[1])
    if tid is None:
        await message.answer(msg.ADMIN_SUBSCRIPTION_GRANT_HELP, parse_mode=ParseMode.HTML)
        return
    async with async_session_factory() as session:
        trainer = await get_trainer(session, int(tid))
        if not trainer:
            await message.answer(
                msg.ADMIN_SUBSCRIPTION_GRANT_NO_TRAINER.format(tid=int(tid)),
                parse_mode=ParseMode.HTML,
            )
            return
        draft = await create_catalog_subscription_invoice_for_trainer(
            session,
            int(tid),
            tier=None,
            modules=default_modules_dict(),
            period_months=1,
        )
        if not draft:
            await message.answer(msg.ADMIN_SUBSCRIPTION_GRANT_DRAFT_FAILED, parse_mode=ParseMode.HTML)
            return
        view = await load_subscription_invoice_admin_view(session, int(draft["invoice_id"]))
        if not view:
            await message.answer(msg.ADMIN_SUBSCRIPTION_GRANT_NOT_FOUND, parse_mode=ParseMode.HTML)
            return
        flags = _modules_to_flags(view.get("checkout_modules"))
        months = int(view.get("checkout_billing_period_months") or 1)
        mode = _MODE_STACK
        body = await _format_editor_body(session, view, flags, months, mode)
        kb = await _build_editor_keyboard(
            session, int(draft["invoice_id"]), int(tid), flags, months, mode
        )
    audit_log(
        "admin_subscription_grant_started",
        ACTOR_ADMIN_BOT,
        user_id,
        payload={"trainer_id": int(tid), "invoice_id": int(draft["invoice_id"])},
    )
    await message.answer(body, reply_markup=kb, parse_mode=ParseMode.HTML)


@router.message(Command("welcome_trial_days"))
async def cmd_welcome_trial_days(message: Message) -> None:
    """Show or set welcome-link trial length (days, max tier). Env TRIAL_PERIOD_DAYS overrides."""
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        async with async_session_factory() as session:
            days = await get_resolved_welcome_trial_days_for_display(session)
        await message.answer(
            msg.ADMIN_WELCOME_TRIAL_DAYS_CURRENT.format(days=days),
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        d = int(parts[1].strip())
    except ValueError:
        await message.answer(msg.ADMIN_WELCOME_TRIAL_DAYS_INVALID, parse_mode=ParseMode.HTML)
        return
    if d < 1 or d > 365:
        await message.answer(msg.ADMIN_WELCOME_TRIAL_DAYS_INVALID, parse_mode=ParseMode.HTML)
        return
    async with async_session_factory() as session:
        await set_platform_int(session, WELCOME_TRIAL_PERIOD_DAYS_KEY, d)
    await message.answer(
        msg.ADMIN_WELCOME_TRIAL_DAYS_SET.format(days=d),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("trainer_welcome_link"))
async def cmd_trainer_welcome_link(message: Message) -> None:
    """Issue a one-time trainer bot deep link; without args creates a new trainer draft + link."""
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    parts = (message.text or "").split()
    if len(parts) >= 2 and parts[1].lower() in ("help", "?", "помощь"):
        await message.answer(msg.ADMIN_TRAINER_WELCOME_LINK_HELP, parse_mode=ParseMode.HTML)
        return

    expire_days = DEFAULT_TRAINER_LINK_EXPIRE_DAYS
    trainer_id: int | None = None
    new_trainer_flow = False

    if len(parts) == 1:
        new_trainer_flow = True
    elif len(parts) >= 2 and parts[1].lower() == "new":
        new_trainer_flow = True
        if len(parts) >= 3:
            try:
                expire_days = int(parts[2].strip())
            except ValueError:
                await message.answer(msg.ADMIN_TRAINER_WELCOME_LINK_BAD_ARGS, parse_mode=ParseMode.HTML)
                return
            if expire_days < 1 or expire_days > 365:
                await message.answer(msg.ADMIN_TRAINER_WELCOME_LINK_BAD_ARGS, parse_mode=ParseMode.HTML)
                return
    else:
        try:
            trainer_id = int(parts[1].strip())
        except ValueError:
            await message.answer(msg.ADMIN_TRAINER_WELCOME_LINK_BAD_ARGS, parse_mode=ParseMode.HTML)
            return
        if trainer_id < 1:
            await message.answer(msg.ADMIN_TRAINER_WELCOME_LINK_BAD_ARGS, parse_mode=ParseMode.HTML)
            return
        if len(parts) >= 3:
            try:
                expire_days = int(parts[2].strip())
            except ValueError:
                await message.answer(msg.ADMIN_TRAINER_WELCOME_LINK_BAD_ARGS, parse_mode=ParseMode.HTML)
                return
            if expire_days < 1 or expire_days > 365:
                await message.answer(msg.ADMIN_TRAINER_WELCOME_LINK_BAD_ARGS, parse_mode=ParseMode.HTML)
                return

    async with async_session_factory() as session:
        if new_trainer_flow:
            result = await create_trainer_and_issue_welcome_link_token(session, expire_days=expire_days)
        else:
            assert trainer_id is not None
            result = await issue_trainer_welcome_link_token(session, trainer_id, expire_days=expire_days)
            if result is None:
                await message.answer(msg.ADMIN_TRAINER_WELCOME_LINK_NO_TRAINER)
                return

    tid = int(result["trainer_id"])
    audit_log(
        "admin.trainer_welcome_link_issued",
        ACTOR_ADMIN_BOT,
        user_id,
        {
            "trainer_id": tid,
            "expire_days": expire_days,
            "new_trainer": bool(result.get("created_new_trainer")),
        },
    )
    exp = result["expires_at"]
    expires_str = exp.strftime("%d.%m.%Y %H:%M UTC") if hasattr(exp, "strftime") else str(exp)
    dl = result.get("deep_link")
    if dl:
        link_block = (
            f'<a href="{html.escape(dl)}">Открыть в Telegram</a>\n\n'
            f"<code>{html.escape(dl)}</code>"
        )
    else:
        link_block = msg.ADMIN_TRAINER_WELCOME_LINK_BLOCK_NO_USERNAME.format(
            start_payload=html.escape(result["start_payload"]),
        )
    intro = ""
    if result.get("created_new_trainer"):
        intro = msg.ADMIN_TRAINER_WELCOME_LINK_NEW_INTRO.format(trainer_id=tid)
    await message.answer(
        intro
        + msg.ADMIN_TRAINER_WELCOME_LINK_ISSUED.format(
            trainer_id=tid,
            expires=expires_str,
            link_block=link_block,
        ),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@router.message(Command("collective_draft"))
async def cmd_collective_draft(message: Message) -> None:
    """Create draft studio + owner claim link (Wave P0)."""
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or parts[1].lower() in ("help", "?", "помощь"):
        await message.answer(msg.ADMIN_COLLECTIVE_DRAFT_HELP, parse_mode=ParseMode.HTML)
        return
    body = parts[1].strip()
    if body.lower().startswith("status"):
        slug_parts = body.split(maxsplit=1)
        if len(slug_parts) < 2 or not slug_parts[1].strip():
            await message.answer(msg.ADMIN_COLLECTIVE_DRAFT_STATUS_HELP, parse_mode=ParseMode.HTML)
            return
        slug = slug_parts[1].strip().split()[0]
        async with async_session_factory() as session:
            ops = await get_collective_ops_status(session, slug=slug)
        if ops is None:
            await message.answer(
                msg.ADMIN_COLLECTIVE_DRAFT_STATUS_NOT_FOUND.format(slug=html.escape(slug)),
                parse_mode=ParseMode.HTML,
            )
            return
        owner_line = (
            f"<code>{ops['owner_trainer_id']}</code>"
            + (f" · {html.escape(ops['owner_display_name'])}" if ops.get("owner_display_name") else "")
            if ops.get("owner_trainer_id") is not None
            else "— (не claimed)"
        )
        await message.answer(
            msg.ADMIN_COLLECTIVE_DRAFT_STATUS.format(
                slug=html.escape(ops["slug"]),
                display_name=html.escape(ops["display_name"]),
                collective_status=html.escape(ops["status"]),
                claim_state=html.escape(ops["claim_state_label"]),
                organization_format=html.escape(str(ops["organization_format"])),
                schedule_mode=html.escape(str(ops["schedule_mode"])),
                owner_mode_label=html.escape(str(ops["owner_studio_access_mode_label"])),
                owner_line=owner_line,
                active_count=ops["active_member_count"],
                seat_limit=ops["seat_limit"],
                pending_invites=ops["pending_invite_count"],
                pending_claims=ops["pending_claim_count"],
            ),
            parse_mode=ParseMode.HTML,
        )
        return
    if body.lower() in ("formats", "format", "форматы", "формат"):
        lines = [
            "<b>Форматы организации (Collective draft)</b>",
            "",
            "<code>/collective_draft slug|Название|format|места|owner</code>",
            "",
        ]
        for preset in list_collective_org_format_presets():
            lines.append(
                f"• <code>{html.escape(preset.key)}</code> — {html.escape(preset.label_ru)}"
                f" · мест по умолч. {preset.seat_limit_default}"
            )
        lines.extend(
            [
                "",
                "<b>Алиасы format</b> (см. also legacy):",
                "• studio → ice, coworking, lanes, rental…",
                "• center → manager, facility, operator…",
                "• center_hybrid → hybrid, throwing, studio_central",
                "• legacy: format <code>center</code> + owner <code>trainer</code> → center_hybrid",
                "",
                "Owner: <code>trainer</code> (личный CRM) или <code>manager</code> (только студия).",
                "",
                "Ops: <code>/collective_draft status slug</code>",
                "",
                "Таблица format → UX: <code>docs/adr/003-appendix-organization-format-ux.md</code>",
                "Runbook: <code>docs/ops/onboard-collective-formats.md</code>",
                "",
                "Примеры:",
                "<code>/collective_draft broski|Broski Center|center_hybrid|8</code>",
                "<code>/collective_draft ice-yoga|Ice Yoga Lane|studio</code>",
                "<code>/collective_draft fit-hub|Fit Hub|studio|12</code>",
                "<code>/collective_draft ops|Ops Desk|center</code>",
            ]
        )
        await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)
        return
    if "|" not in body:
        await message.answer(msg.ADMIN_COLLECTIVE_DRAFT_BAD_ARGS, parse_mode=ParseMode.HTML)
        return
    spec = parse_admin_collective_draft_body(body)
    if isinstance(spec, str):
        err_map = {
            "missing_fields": msg.ADMIN_COLLECTIVE_DRAFT_BAD_ARGS,
            "invalid_slug": msg.ADMIN_COLLECTIVE_DRAFT_BAD_ARGS,
            "invalid_format": msg.ADMIN_COLLECTIVE_DRAFT_INVALID_FORMAT,
            "invalid_seats": msg.ADMIN_COLLECTIVE_DRAFT_INVALID_SEATS,
            "invalid_owner_mode": msg.ADMIN_COLLECTIVE_DRAFT_INVALID_OWNER,
        }
        await message.answer(
            err_map.get(spec, msg.ADMIN_COLLECTIVE_DRAFT_BAD_ARGS),
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        async with async_session_factory() as session:
            collective = await create_collective_draft(
                session,
                slug=spec.slug,
                display_name=spec.display_name,
                seat_limit=spec.seat_limit,
                schedule_mode=spec.schedule_mode,
                owner_studio_access_mode=spec.owner_studio_access_mode,
                organization_format=spec.organization_format,
            )
            claim = await issue_collective_claim_token(session, int(collective["id"]))
    except ValueError as exc:
        if str(exc) == "slug_invalid":
            await message.answer(msg.ADMIN_COLLECTIVE_DRAFT_BAD_ARGS, parse_mode=ParseMode.HTML)
        else:
            await message.answer(f"Ошибка: {html.escape(str(exc))}", parse_mode=ParseMode.HTML)
        return
    except Exception as exc:
        err = str(exc).lower()
        if "unique" in err and "slug" in err:
            await message.answer("Студия с таким slug уже существует.", parse_mode=ParseMode.HTML)
            return
        raise
    if claim is None:
        await message.answer("Не удалось выпустить claim-ссылку.", parse_mode=ParseMode.HTML)
        return
    audit_log(
        "admin.collective_draft_created",
        ACTOR_ADMIN_BOT,
        user_id,
        {
            "collective_id": collective["id"],
            "slug": collective["slug"],
            "organization_format": collective.get("organization_format"),
            "schedule_mode": collective.get("schedule_mode"),
            "owner_studio_access_mode": collective.get("owner_studio_access_mode"),
        },
    )
    exp = claim["expires_at"]
    expires_str = exp[:16].replace("T", " ") if isinstance(exp, str) else str(exp)
    dl = claim.get("deep_link")
    if dl:
        link_block = (
            f'<a href="{html.escape(dl)}">Открыть claim в Telegram</a>\n\n'
            f"<code>{html.escape(dl)}</code>"
        )
    else:
        link_block = msg.ADMIN_TRAINER_WELCOME_LINK_BLOCK_NO_USERNAME.format(
            start_payload=html.escape(claim["start_payload"]),
        )
    owner_label = (
        "менеджер (без личного CRM)"
        if collective.get("owner_studio_access_mode") == "studio_admin_only"
        else "тренер (полный CRM)"
    )
    schedule_label = (
        "центр (studio_central)"
        if collective.get("schedule_mode") == "studio_central"
        else "автономные тренеры"
    )
    await message.answer(
        msg.ADMIN_COLLECTIVE_DRAFT_ISSUED.format(
            collective_id=collective["id"],
            slug=html.escape(collective["slug"]),
            display_name=html.escape(collective["display_name"]),
            seat_limit=collective["seat_limit"],
            org_format=html.escape(str(collective.get("organization_format") or "studio")),
            schedule_label=html.escape(schedule_label),
            owner_label=html.escape(owner_label),
            expires=html.escape(expires_str),
            link_block=link_block,
        ),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def _parse_collective_sub_modules(tokens: list[str]) -> dict[str, bool] | None:
    """Optional trailing module flags; None = full studio pool."""
    if not tokens:
        return None
    allowed = {"online", "analytics", "groups"}
    unknown = [t for t in tokens if t.lower() not in allowed]
    if unknown:
        return {}
    mods = default_modules_dict()
    for t in tokens:
        mods[t.lower()] = True
    return mods


@router.message(Command("collective_sub"))
async def cmd_collective_sub(message: Message) -> None:
    """Grant or inspect collective subscription pool (Wave P1.5-A)."""
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return

    parts = (message.text or "").split()
    if len(parts) < 2 or parts[1].lower() in ("help", "?", "помощь"):
        await message.answer(msg.ADMIN_COLLECTIVE_SUB_HELP, parse_mode=ParseMode.HTML)
        return

    action = parts[1].lower()
    if action == "status":
        if len(parts) < 3:
            await message.answer(msg.ADMIN_COLLECTIVE_SUB_HELP, parse_mode=ParseMode.HTML)
            return
        slug = parts[2].strip()
        async with async_session_factory() as session:
            status = await get_collective_subscription_status(session, slug=slug)
        if status is None:
            await message.answer(
                msg.ADMIN_COLLECTIVE_SUB_NOT_FOUND.format(slug=html.escape(slug)),
                parse_mode=ParseMode.HTML,
            )
            return
        active = status.get("active_subscription")
        if active:
            exp = active.get("expires_at") or "—"
            exp_disp = exp[:16].replace("T", " ") if isinstance(exp, str) else str(exp)
            mods = active.get("modules") or {}
            mod_parts = ["CRM"]
            for key in ("online", "analytics", "groups"):
                if mods.get(key):
                    mod_parts.append(key)
            sub_block = (
                f"Активна до <b>{html.escape(exp_disp)}</b>\n"
                f"Модули: <code>{html.escape(', '.join(mod_parts))}</code>"
            )
        else:
            sub_block = "Активной подписки нет — members используют только solo-тариф."
        await message.answer(
            msg.ADMIN_COLLECTIVE_SUB_STATUS.format(
                slug=html.escape(status["slug"]),
                display_name=html.escape(status["display_name"]),
                collective_status=html.escape(status["status"]),
                seat_limit=status["seat_limit"],
                active_count=status["active_member_count"],
                sub_block=sub_block,
            ),
            parse_mode=ParseMode.HTML,
        )
        return

    if action != "grant" and action != "confirm":
        await message.answer(msg.ADMIN_COLLECTIVE_SUB_HELP, parse_mode=ParseMode.HTML)
        return

    if action == "confirm":
        if len(parts) < 3:
            await message.answer(msg.ADMIN_COLLECTIVE_SUB_BAD_ARGS, parse_mode=ParseMode.HTML)
            return
        try:
            invoice_id = int(parts[2].strip())
        except ValueError:
            await message.answer(msg.ADMIN_COLLECTIVE_SUB_BAD_ARGS, parse_mode=ParseMode.HTML)
            return
        async with async_session_factory() as session:
            result = await admin_confirm_collective_invoice(
                session, invoice_id, admin_id=user_id
            )
        if result is None:
            await message.answer(
                f"Счёт <code>{invoice_id}</code> не найден или уже обработан.",
                parse_mode=ParseMode.HTML,
            )
            return
        await message.answer(
            msg.ADMIN_COLLECTIVE_INVOICE_CONFIRMED.format(
                invoice_id=result["invoice_id"],
                display_name=html.escape(result["display_name"]),
                slug=html.escape(result["slug"]),
            ),
            parse_mode=ParseMode.HTML,
        )
        return

    if len(parts) < 4:
        await message.answer(msg.ADMIN_COLLECTIVE_SUB_BAD_ARGS, parse_mode=ParseMode.HTML)
        return

    slug = parts[2].strip()
    try:
        months = int(parts[3].strip())
    except ValueError:
        await message.answer(msg.ADMIN_COLLECTIVE_SUB_BAD_ARGS, parse_mode=ParseMode.HTML)
        return

    mod_tokens = parts[4:]
    modules = _parse_collective_sub_modules(mod_tokens)
    if modules == {}:
        await message.answer(msg.ADMIN_COLLECTIVE_SUB_BAD_ARGS, parse_mode=ParseMode.HTML)
        return

    async with async_session_factory() as session:
        result = await admin_grant_collective_subscription(
            session,
            slug=slug,
            period_months=months,
            modules=modules,
            admin_id=user_id,
        )

    if result is None:
        await message.answer(
            msg.ADMIN_COLLECTIVE_SUB_NOT_FOUND.format(slug=html.escape(slug)),
            parse_mode=ParseMode.HTML,
        )
        return
    if result.get("error") == "invalid_period":
        await message.answer(msg.ADMIN_COLLECTIVE_SUB_BAD_ARGS, parse_mode=ParseMode.HTML)
        return
    if result.get("error"):
        await message.answer(
            f"Не удалось выдать подписку: <code>{html.escape(str(result['error']))}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    exp = result.get("expires_at") or ""
    exp_disp = exp[:16].replace("T", " ") if isinstance(exp, str) else str(exp)
    extend_note = (
        " (продлено от текущего периода)"
        if result.get("extended_from_existing")
        else ""
    )
    await message.answer(
        msg.ADMIN_COLLECTIVE_SUB_GRANTED.format(
            slug=html.escape(result["slug"]),
            display_name=html.escape(result["display_name"]),
            months=result["period_months"],
            modules_label=html.escape(result["modules_label"]),
            expires=html.escape(exp_disp),
            extend_note=extend_note,
        ),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("pending"))
async def cmd_pending(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    async with async_session_factory() as session:
        eligible_ids = await list_trainer_ids_eligible_for_admin_moderation(session)
    if not eligible_ids:
        await message.answer(msg.ADMIN_PENDING_EMPTY)
        return
    for tid in eligible_ids:
        await _send_trainer_for_moderation(message, tid)


@router.callback_query(lambda c: c.data and c.data.startswith(ADMIN_APPROVE_PREFIX))
async def on_approve(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    if not _is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    trainer_id = safe_parse_id(callback.data[len(ADMIN_APPROVE_PREFIX) :])
    if trainer_id is None:
        await callback.answer()
        return
    trainer: dict | None = None
    ok = False
    # Only first-time catalog activation should get the celebratory push; re-approval of
    # pending edits (trainer already ACTIVE) is intentionally silent unless admin flags issues.
    notify_primary_catalog_approval = False
    async with async_session_factory() as session:
        t0 = await get_trainer(session, trainer_id)
        st = (t0.get("status") or "").strip() if t0 else ""
        if st == TRAINER_STATUS_ACTIVE:
            await session.execute(
                text("UPDATE trainers SET moderation_feedback = NULL WHERE id = :id"),
                {"id": trainer_id},
            )
            ok = await apply_trainer_profile_pending_to_published(session, trainer_id)
            ok_photo = await apply_photo_pending_to_published(session, trainer_id)
            ok = ok and ok_photo
            repo_ap = TrainerRepository(session)
            await repo_ap.clear_moderation_submitted_at(trainer_id)
            await session.flush()
            await moderate_trainer_education_for_profile(
                session,
                trainer_id,
                decision="approved",
                admin_id=user_id,
            )
            trainer = await get_trainer(session, trainer_id)
        else:
            notify_primary_catalog_approval = True
            await set_trainer_moderation_feedback(session, trainer_id, None)
            ok = await update_trainer_status(session, trainer_id, TRAINER_STATUS_ACTIVE)
            trainer = await get_trainer(session, trainer_id)
            await moderate_trainer_education_for_profile(
                session,
                trainer_id,
                decision="approved",
                admin_id=user_id,
            )
    if ok:
        audit_log("trainer.approved", ACTOR_ADMIN_BOT, user_id, {"trainer_id": trainer_id})
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(msg.ADMIN_APPROVED)
        if notify_primary_catalog_approval:
            await _notify_trainer_moderation_approved(trainer)
    else:
        await callback.message.answer(f"Не удалось одобрить тренера #{trainer_id}.")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith(ADMIN_REJECT_PREFIX))
async def on_reject(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    if not _is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    trainer_id = int(callback.data[len(ADMIN_REJECT_PREFIX) :])
    trainer: dict | None = None
    async with async_session_factory() as session:
        trainer = await get_trainer(session, trainer_id)
        if trainer and (trainer.get("status") or "").strip() == TRAINER_STATUS_ACTIVE:
            await callback.answer(
                "Для активного тренера не деактивируйте профиль — используйте «Нужны правки».",
                show_alert=True,
            )
            return
        ok = await update_trainer_status(session, trainer_id, TRAINER_STATUS_DEACTIVATED)
    if ok:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(msg.ADMIN_REJECTED)
        await _notify_trainer_moderation_rejected(trainer)
    else:
        await callback.message.answer(f"Не удалось отклонить тренера #{trainer_id}.")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith(ADMIN_NEEDS_EDIT_PREFIX))
async def on_needs_edit(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id if callback.from_user else 0
    if not _is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    trainer_id = safe_parse_id(callback.data[len(ADMIN_NEEDS_EDIT_PREFIX) :])
    if trainer_id is None:
        await callback.answer()
        return
    _admin_awaiting_feedback[user_id] = trainer_id
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(msg.ADMIN_NEEDS_EDIT_PROMPT)
    await callback.answer()


@router.message()
async def on_admin_message(message: Message) -> None:
    """Handle: 1) awaiting moderation feedback; 2) awaiting support reply."""
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id):
        return
    text = (message.text or "").strip()
    if text.lower() in ("/cancel", "отмена", "отменить"):
        _admin_awaiting_feedback.pop(user_id, None)
        support_id = _admin_awaiting_support_reply.pop(user_id, None)
        if support_id is not None:
            await message.answer(msg.ADMIN_SUPPORT_REPLY_CANCELLED)
        else:
            await message.answer(msg.ADMIN_NEEDS_EDIT_CANCELLED)
        return

    support_id = _admin_awaiting_support_reply.pop(user_id, None)
    if support_id is not None:
        async with async_session_factory() as session:
            ticket = await get_support_message(session, support_id)
            if not ticket:
                await message.answer("Обращение не найдено.")
                return
            ok = await reply_support_message(session, support_id, user_id, text)
            if not ok:
                await message.answer("Не удалось сохранить ответ.")
                return
        if ticket:
            settings = Settings()
            from_role = ticket.get("from_role") or "client"
            token = settings.telegram_bot_token_trainer if from_role == "trainer" else settings.telegram_bot_token_client
            bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            reply_html = msg.TRAINER_SUPPORT_REPLY_INTRO_HTML + html.escape(text)
            reply_kb: InlineKeyboardMarkup | None = None
            if from_role == "trainer":
                base = (settings.webapp_base_url or "").rstrip("/")
                if base.lower().startswith("https://"):
                    reply_kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=msg.TRAINER_SUPPORT_REPLY_GO_PAY,
                                    web_app=WebAppInfo(
                                        url=f"{base}/webapp/trainer-pay-subscription"
                                    ),
                                ),
                            ],
                        ]
                    )
            try:
                await bot.send_message(
                    chat_id=int(ticket["from_telegram_id"]),
                    text=reply_html,
                    reply_markup=reply_kb,
                )
            except Exception:
                pass
            finally:
                await bot.session.close()
        await message.answer(msg.ADMIN_SUPPORT_REPLY_SENT)
        return

    trainer_id = _admin_awaiting_feedback.pop(user_id, None)
    if trainer_id is None:
        return
    rejected_education = 0
    trainer: dict | None = None
    async with async_session_factory() as session:
        t0 = await get_trainer(session, trainer_id)
        st = (t0.get("status") or "").strip() if t0 else ""
        if st == TRAINER_STATUS_ACTIVE:
            await discard_active_trainer_text_revision_with_feedback(session, trainer_id, text or None)
            trainer = await get_trainer(session, trainer_id)
            try:
                rejected_education = await moderate_trainer_education_for_profile(
                    session,
                    trainer_id,
                    decision="rejected",
                    admin_id=user_id,
                    reason=text or "",
                )
            except ValueError:
                rejected_education = 0
        else:
            await set_trainer_moderation_feedback(session, trainer_id, text or None)
            await update_trainer_status(session, trainer_id, TRAINER_STATUS_PENDING_PROFILE)
            trainer = await get_trainer(session, trainer_id)
            try:
                rejected_education = await moderate_trainer_education_for_profile(
                    session,
                    trainer_id,
                    decision="rejected",
                    admin_id=user_id,
                    reason=text or "",
                )
            except ValueError:
                rejected_education = 0
    audit_log("trainer.needs_edit", ACTOR_ADMIN_BOT, user_id, {"trainer_id": trainer_id})
    await message.answer(msg.ADMIN_NEEDS_EDIT_DONE)
    feedback_stripped = (text or "").strip()
    if feedback_stripped:
        await _notify_trainer_profile_moderation_feedback(trainer, feedback_stripped)
    elif rejected_education > 0:
        await _notify_trainer_education_moderation(
            trainer,
            decision="rejected",
            reason=text or "",
        )


# --- Referral admin commands ---

@router.message(Command("referral_balance"))
async def cmd_referral_balance(message: Message) -> None:
    """Check referral balance for a trainer: /referral_balance <trainer_id>"""
    user_id = message.from_user.id if message.from_user else 0
    if user_id not in ADMIN_IDS:
        return
    text = (message.text or "").strip()
    parts = text.split()
    if len(parts) < 2:
        await message.answer("Использование: /referral_balance <trainer_id>")
        return
    try:
        trainer_id = int(parts[1])
    except ValueError:
        await message.answer("trainer_id должен быть числом")
        return
    async with async_session_factory() as session:
        stats = await get_referral_stats_for_trainer(session, trainer_id)
    await message.answer(
        f"📊 <b>Реферальная статистика тренера #{trainer_id}</b>\n\n"
        f"Баланс: <b>{stats['balance_days']}</b> дней\n"
        f"Всего заработано: <b>{stats['total_earned_days']}</b> дней\n"
        f"Приглашено: <b>{stats['total_referred']}</b>\n"
        f"Оплатили: <b>{stats['credited_count']}</b>",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("referral_adjust"))
async def cmd_referral_adjust(message: Message) -> None:
    """Adjust referral credit: /referral_adjust <trainer_id> <days> [note]"""
    user_id = message.from_user.id if message.from_user else 0
    if user_id not in ADMIN_IDS:
        return
    text = (message.text or "").strip()
    parts = text.split(maxsplit=3)
    if len(parts) < 3:
        await message.answer("Использование: /referral_adjust <trainer_id> <days> [note]\ndays может быть отрицательным")
        return
    try:
        trainer_id = int(parts[1])
        days = int(parts[2])
    except ValueError:
        await message.answer("trainer_id и days должны быть числами")
        return
    note = parts[3] if len(parts) > 3 else None
    async with async_session_factory() as session:
        new_balance = await admin_adjust_referral_credit(session, trainer_id, days, user_id, note)
    audit_log("referral.admin_adjust", ACTOR_ADMIN_BOT, user_id, {
        "trainer_id": trainer_id,
        "days": days,
        "note": note,
        "new_balance": new_balance,
    })
    sign = "+" if days > 0 else ""
    await message.answer(
        f"✅ Реферальный баланс тренера #{trainer_id} изменён на <b>{sign}{days}</b> дней.\n"
        f"Новый баланс: <b>{new_balance}</b> дней.",
        parse_mode=ParseMode.HTML,
    )

