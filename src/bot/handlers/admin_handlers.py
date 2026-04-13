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
from src.application.stats_use_cases import get_platform_stats
from src.application.support_use_cases import (
    get_support_message,
    list_support_messages,
    reply_support_message,
)
from src.application.trainer_profile_completeness import is_profile_complete_for_moderation
from src.application.booking_problem_admin_use_cases import (
    count_booking_problem_reports_for_admin,
    list_booking_problem_reports_for_admin,
)
from src.application.platform_settings_use_cases import (
    WELCOME_TRIAL_PERIOD_DAYS_KEY,
    set_platform_int,
)
from src.application.subscription_use_cases import get_resolved_welcome_trial_days_for_display
from src.application.trainer_link_token_use_cases import (
    DEFAULT_TRAINER_LINK_EXPIRE_DAYS,
    create_trainer_and_issue_welcome_link_token,
    issue_trainer_welcome_link_token,
)
from src.application.trainer_profile_pending import (
    build_trainer_profile_for_moderation_card,
    trainer_has_pending_text_revision,
    trainer_has_photo_pending_revision,
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
from src.bot.handlers.trainer_handlers import _trainer_profile_footer_hint, _trainer_profile_keyboard
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
    bot = Bot(token=settings.telegram_bot_token_trainer)
    try:
        if decision == "approved":
            text = msg.TRAINER_EDUCATION_MODERATION_APPROVED
        else:
            text = msg.TRAINER_EDUCATION_MODERATION_REJECTED.format(reason=html.escape((reason or "").strip() or "Причина не указана"))
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


async def _notify_trainer_moderation_approved(trainer: dict | None) -> None:
    """Notify trainer that the profile passed moderation (catalog visible)."""
    if not trainer:
        return
    telegram_id = trainer.get("telegram_id")
    if not telegram_id:
        return
    await _trainer_bot_send_html_with_profile_button(int(telegram_id), msg.TRAINER_MODERATION_PROFILE_APPROVED)


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
    # No keyboard: all actions via menu commands (/pending, /stats, /support, /dicts)
    await message.answer(
        msg.ADMIN_START
        + "\n\nИспользуйте команды из меню (слева от поля ввода):\n/pending — модерация\n/stats — статистика\n/support — поддержка\n/dicts — города и арены\n/problem_reports — аудит отчётов о проблемах"
    )


def _admin_stats_message(s: dict) -> str:
    """Build full admin stats message: current state, 7d, 30d, trainers, signals."""
    parts = [msg.ADMIN_STATS_TITLE]

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
    """Open platform stats Mini App."""
    if not _is_admin(message.from_user.id if message.from_user else 0):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    base = Settings().webapp_base_url or ""
    url = f"{base.rstrip('/')}/webapp/admin-stats" if base else ""
    tiers_url = f"{base.rstrip('/')}/webapp/admin-subscription-tiers" if base else ""
    if not url:
        async with async_session_factory() as session:
            s = await get_platform_stats(session)
        await message.answer(_admin_stats_message(s))
        return
    stats_kb = [[InlineKeyboardButton(text="Открыть дашборд", web_app=WebAppInfo(url=url))]]
    if tiers_url:
        stats_kb.append([InlineKeyboardButton(text="Тарифы подписки", web_app=WebAppInfo(url=tiers_url))])
    await message.answer(
        "📊 Статистика платформы",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=stats_kb),
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


@router.message(Command("pending"))
async def cmd_pending(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    async with async_session_factory() as session:
        repo = TrainerRepository(session)
        queue_ids = await repo.list_trainer_ids_for_moderation_queue()
        eligible_ids: list[int] = []
        for tid in queue_ids:
            full = await get_trainer(session, tid)
            if not full:
                continue
            st = (full.get("status") or "").strip()
            if st == TRAINER_STATUS_ACTIVE:
                sub_at = full.get("moderation_submitted_at")
                has_queue = bool(sub_at) and (
                    trainer_has_pending_text_revision(full) or trainer_has_photo_pending_revision(full)
                )
                if has_queue:
                    eligible_ids.append(int(tid))
            elif st == TRAINER_STATUS_PENDING_PROFILE and is_profile_complete_for_moderation(full):
                eligible_ids.append(int(tid))
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
            bot = Bot(token=token)
            try:
                reply_text = f"📩 <b>Ответ поддержки:</b>\n\n{html.escape(text)}"
                await bot.send_message(chat_id=ticket["from_telegram_id"], text=reply_text)
            except Exception:
                pass
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

