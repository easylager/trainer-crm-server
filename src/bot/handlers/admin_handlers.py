"""
Admin bot: moderation of trainers (approve / reject), platform stats Mini App, support inbox.
"""
import html
import logging

from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from src.application.stats_use_cases import get_platform_stats
from src.application.support_use_cases import (
    get_support_message,
    list_support_messages,
    reply_support_message,
)
from src.application.trainer_use_cases import (
    get_trainer,
    list_trainer_education,
    list_trainers,
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
from src.bot.client_api import build_photo_url, fetch_photo_bytes
from src.infrastructure.db import async_session_factory
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
    profile = trainer.get("profile") or {}
    name_plain = ((profile.get("first_name") or "") + " " + (profile.get("last_name") or "")).strip() or "—"
    photos = trainer.get("photos") or []
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

    # Trainer has at most one photo (new upload replaces previous)
    file_key = photos[0]["file_key"] if photos else None
    if file_key:
        url = build_photo_url(file_key)
        if not url:
            logger.warning(
                "admin moderation: build_photo_url returned None file_key=%s trainer_id=%s",
                file_key,
                trainer_id,
            )
        else:
            body = await fetch_photo_bytes(url)
            if not body:
                logger.warning(
                    "admin moderation: fetch_photo_bytes empty trainer_id=%s url=%s",
                    trainer_id,
                    url,
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
        msg.ADMIN_START + "\n\nИспользуйте команды из меню (слева от поля ввода):\n/pending — модерация\n/stats — статистика\n/support — поддержка\n/dicts — города и арены"
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


@router.message(Command("pending"))
async def cmd_pending(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    if not _is_admin(user_id):
        await message.answer(msg.ADMIN_NO_ACCESS)
        return
    async with async_session_factory() as session:
        trainers = await list_trainers(session, limit=20, offset=0, status=TRAINER_STATUS_PENDING_PROFILE)
    if not trainers:
        await message.answer(msg.ADMIN_PENDING_EMPTY)
        return
    for t in trainers:
        await _send_trainer_for_moderation(message, t["id"])


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
    approved_education = 0
    trainer: dict | None = None
    async with async_session_factory() as session:
        await set_trainer_moderation_feedback(session, trainer_id, None)
        ok = await update_trainer_status(session, trainer_id, TRAINER_STATUS_ACTIVE)
        trainer = await get_trainer(session, trainer_id)
        approved_education = await moderate_trainer_education_for_profile(
            session,
            trainer_id,
            decision="approved",
            admin_id=user_id,
        )
    if ok:
        audit_log("trainer.approved", ACTOR_ADMIN_BOT, user_id, {"trainer_id": trainer_id})
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(msg.ADMIN_APPROVED)
        if approved_education > 0:
            await _notify_trainer_education_moderation(trainer, decision="approved")
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
    async with async_session_factory() as session:
        ok = await update_trainer_status(session, trainer_id, TRAINER_STATUS_DEACTIVATED)
    if ok:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(msg.ADMIN_REJECTED)
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
    if rejected_education > 0:
        await _notify_trainer_education_moderation(
            trainer,
            decision="rejected",
            reason=text or "",
        )

