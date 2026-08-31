"""
Notification loops: read from DB and send Telegram messages.
Used by notification_service (standalone process). Client/trainer apps no longer run these.
"""
import asyncio
import html as html_lib
import logging
import math
import time as std_time
from datetime import date, datetime, time, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from src.application.booking_payment_notice import load_booking_deduction_snapshot
from src.application.booking_payment_notice import classify_booking_expected_payment_class
from src.application.booking_payment_notice import load_pass_sessions_remaining_after_booking
from src.application.client_trainer_booked_notify import try_send_client_trainer_booked_push
from src.application.booking_use_cases import (
    can_trainer_repeat_booking_same_time_next_week,
    claim_client_booking_completion_push_sent,
    claim_trainer_completed_sent,
    clear_client_booking_completion_push_sent,
    clear_trainer_completed_sent,
    get_bookings_pending_notification,
    get_clients_for_inactive_notification,
    get_pending_booking_cancel_notifications,
    get_pending_completed_for_trainer,
    get_pending_trainer_booked_notifications,
    get_trainer_telegram_id,
    INACTIVE_KIND_10_DAYS,
    INACTIVE_KIND_30_DAYS,
    list_bookings_pending_client_completion_push,
    list_bookings_for_trainer_session_wrapup,
    list_bookings_pending_confirm_reminder,
    list_bookings_to_complete,
    list_pending_reminders,
    mark_client_booking_completion_push_sent,
    mark_booking_completed_and_notify,
    mark_booking_notified,
    mark_confirm_reminder_sent,
    mark_trainer_session_wrapup_sent,
    mark_inactive_notification_sent,
    mark_reminder_failed,
    mark_reminder_sent,
    mark_trainer_completed_sent,
)
from src.application.client_stats_use_cases import get_client_activity_snapshot
from src.application.client_milestone_use_cases import (
    SESSION_MILESTONE_TARGETS,
    fetch_completed_session_effort_rows,
    fetch_engagement_percentile_vs_clients_below_threshold,
    release_session_milestone_claim,
    try_claim_session_milestone_notification,
)
from src.application.client_session_effort_estimates import (
    aggregate_effort_from_completed_sessions,
    format_compact_effort_display_html,
    round_kcal_for_display,
)
from src.application.client_use_cases import get_client_id_by_telegram_id
from src.application.client_request_use_cases import (
    get_pending_no_response_reminders,
    get_pending_request_notifications,
    get_pending_response_notifications,
    mark_no_response_reminder_sent,
    mark_request_trainer_notified,
    mark_response_notified,
)
from src.application.client_pass_order_use_cases import (
    split_pass_order_comment,
)
from src.application.client_cert_order_use_cases import split_cert_order_comment
from src.application.pass_product_use_cases import get_pass_product
from src.application.certificate_use_cases import (
    expire_certificates_past_expiry,
    get_certificate_product,
    process_certificate_email_outbox_batch,
)
from src.application.subscription_tier_use_cases import trainer_has_crm_access
from src.application.group_attendance_use_cases import (
    attendance_rsvp_sign,
    list_pending_attendance_prompts,
    mark_attendance_prompt_failed,
    mark_attendance_prompt_sent,
    rsvp_hmac_secret,
    sync_group_attendance_prompts,
)
from src.application.subscription_use_cases import (
    expire_subscriptions_to_past_due,
    get_subscriptions_reminder_due,
    mark_subscription_reminder_sent,
)
from src.application.lead_mode_recovery_use_cases import (
    DueRecoveryNudge,
    compute_due_nudges,
    mark_nudge_sent,
)
from src.application.trainer_onboarding_recovery_use_cases import (
    STAGE_EMPTY_FORM,
    STAGE_MISSING_FIELD,
    STAGE_NOT_SUBMITTED,
    STAGE_NO_BOOKING,
    STAGE_REJECTED_RESUBMIT,
    TRIAL_URGENCY_THRESHOLD_DAYS,
    DueOnboardingNudge,
    compute_due_onboarding_nudges,
    get_trial_days_remaining,
    mark_onboarding_nudge_sent,
)
from src.application.care_pulse_use_cases import (
    claim_care_pulse,
    is_within_care_pulse_window,
    list_due_care_pulses,
)
from src.application.trial_roi_recap_use_cases import (
    get_trial_roi_recap,
    list_trial_roi_recap_due,
    mark_trial_roi_recap_sent,
)
from src.infrastructure.db.models import (
    CARE_PULSE_AUDIENCE_CLIENT,
    CARE_PULSE_AUDIENCE_TRAINER,
    ONBOARDING_NUDGE_STEP_D1,
    ONBOARDING_NUDGE_STEP_D3,
    ONBOARDING_NUDGE_STEP_D7,
    RECOVERY_STEP_D0,
    RECOVERY_STEP_D3,
    RECOVERY_STEP_D14,
    RECOVERY_STEP_D30,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_TRIAL,
)
from src.bot import messages as msg
from src.bot.handlers.trainer_handlers import (
    BOOKING_ADD_NOTE_PREFIX,
    BOOKING_NOTIFY_RELAY_WRITE_PREFIX,
    REQUEST_DECLINE_PREFIX,
    REQUEST_RESPOND_PREFIX,
)
from src.bot.schedule_notifications import REQUESTS_CALLBACK
from src.bot.trainer_cancel_client_notify import send_cancel_notification_payload
from src.infrastructure.db import async_session_factory
from src.shared.config import (
    TRAINER_SESSION_WRAPUP_POLL_INTERVAL_SEC,
    TRAINER_SESSION_WRAPUP_REMAINING_SEC_MAX,
    TRAINER_SESSION_WRAPUP_REMAINING_SEC_MIN,
    Settings,
    get_settings,
)
from src.shared.map_links import build_yandex_by_map_url
from src.application.trainer_notification_prefs import is_trainer_push_allowed_now
from src.shared.notification_hours import NOTIFICATION_TZ, is_within_notification_hours

logger = logging.getLogger(__name__)

# Avoid log floods when Telegram repeatedly rejects delivery for the same booking (e.g. bot blocked).
_HARD_FAIL_LOG_INTERVAL_SEC = 300.0
_BOOKING_NOTIFY_HARD_FAIL_LAST_LOG_MONO: dict[str, float] = {}


def _telegram_error_blob(exc: BaseException) -> str:
    """Lowercase concat of str(exc) and aiogram DetailedAiogramError.message when present."""
    parts = [str(exc)]
    inner = getattr(exc, "message", None)
    if isinstance(inner, str):
        parts.append(inner)
    return " ".join(parts).lower()


def _is_telegram_inline_keyboard_bad_request(exc: BaseException) -> bool:
    """Telegram rejected reply_markup (e.g. tg://user?id=self → BUTTON_USER_INVALID)."""
    blob = _telegram_error_blob(exc)
    return any(
        token in blob
        for token in (
            "button_user_invalid",
            "button_user_privacy_restricted",
            "button_url_invalid",
            "reply_markup_invalid",
            "inline_keyboard_invalid",
        )
    )


def _is_telegram_timeout(exc: BaseException) -> bool:
    """True when the HTTP client timed out (message may already be delivered)."""
    blob = _telegram_error_blob(exc)
    return "timeout" in blob or "timed out" in blob


def _inline_keyboard_without_tg_user_urls(
    markup: InlineKeyboardMarkup | None,
) -> InlineKeyboardMarkup | None:
    """Drop tg://user buttons; keep callbacks / web_app / other urls."""
    if markup is None:
        return None
    try:
        kept: list[list[InlineKeyboardButton]] = []
        for row in markup.inline_keyboard or []:
            filtered = [
                btn
                for btn in row
                if not str(getattr(btn, "url", None) or "").startswith("tg://user")
            ]
            if filtered:
                kept.append(filtered)
        if not kept:
            return None
        return InlineKeyboardMarkup(inline_keyboard=kept)
    except Exception:
        return None


async def _send_message_with_markup_fallback(
    bot: Bot,
    *,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    parse_mode: str | None = None,
) -> None:
    """
    Send Telegram message; on markup BadRequest retry without tg://user, then plain text.
    Raises the last non-markup error (or plain-text failure).
    """
    kwargs: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        kwargs["parse_mode"] = parse_mode

    stripped: InlineKeyboardMarkup | None = None
    try:
        await bot.send_message(**kwargs, reply_markup=reply_markup)
        return
    except Exception as first_exc:
        if not _is_telegram_inline_keyboard_bad_request(first_exc):
            raise
        stripped = _inline_keyboard_without_tg_user_urls(reply_markup)
        logger.warning(
            "telegram markup rejected chat_id=%s tag=%s; retrying without tg://user buttons",
            chat_id,
            _telegram_markup_rejection_tag(first_exc),
        )

    if stripped is not None:
        try:
            await bot.send_message(**kwargs, reply_markup=stripped)
            return
        except Exception as second_exc:
            if not _is_telegram_inline_keyboard_bad_request(second_exc):
                raise
            logger.warning(
                "telegram markup still rejected chat_id=%s tag=%s; retrying without keyboard",
                chat_id,
                _telegram_markup_rejection_tag(second_exc),
            )

    await bot.send_message(**kwargs, reply_markup=None)


def _telegram_markup_rejection_tag(exc: BaseException) -> str:
    """Short stable token for logs/metrics (see Telegram Bad Request descriptions)."""
    blob = _telegram_error_blob(exc)
    for tag in (
        "button_user_invalid",
        "button_user_privacy_restricted",
        "button_url_invalid",
        "reply_markup_invalid",
        "inline_keyboard_invalid",
    ):
        if tag in blob:
            return tag
    return "markup_unknown"


def _emit_hard_fail_throttled(kind: str, booking_id: int) -> bool:
    """True if we should log a hard failure now (same booking/key kind at most once per interval)."""
    key = f"{kind}:{int(booking_id)}"
    now = std_time.monotonic()
    prev = _BOOKING_NOTIFY_HARD_FAIL_LAST_LOG_MONO.get(key)
    if prev is None or now - prev >= _HARD_FAIL_LOG_INTERVAL_SEC:
        _BOOKING_NOTIFY_HARD_FAIL_LAST_LOG_MONO[key] = now
        return True
    return False


def _clear_hard_fail_throttle(kind: str, booking_id: int) -> None:
    _BOOKING_NOTIFY_HARD_FAIL_LAST_LOG_MONO.pop(f"{kind}:{int(booking_id)}", None)


async def _deliver_trainer_booking_pending_notification(
    trainer_bot: Bot,
    *,
    chat_id: int,
    text: str,
    markup_full: InlineKeyboardMarkup,
    markup_confirm_decline_only: InlineKeyboardMarkup,
    booking_id: int,
    trainer_db_id: int,
    client_tid: object,
) -> bool:
    """Send pending-booking Telegram push; shrink keyboard on Telegram markup errors."""
    parse_mode = "HTML"

    async def _send(markup: InlineKeyboardMarkup | None) -> None:
        await trainer_bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup,
            parse_mode=parse_mode,
        )

    rej_full = ""
    try:
        await _send(markup_full)
        logger.info(
            "booking_pending_notify_sent booking_id=%s trainer_db_id=%s trainer_chat_id=%s client_tid=%s "
            "keyboard=full telegram_reason=-",
            booking_id,
            trainer_db_id,
            chat_id,
            client_tid,
        )
        _clear_hard_fail_throttle("pending", booking_id)
        return True
    except Exception as first_exc:
        if not _is_telegram_inline_keyboard_bad_request(first_exc):
            if _emit_hard_fail_throttled("pending_other", booking_id):
                logger.warning(
                    "booking_pending_notify_failed booking_id=%s trainer_db_id=%s trainer_chat_id=%s "
                    "client_tid=%s err=%s",
                    booking_id,
                    trainer_db_id,
                    chat_id,
                    client_tid,
                    first_exc,
                )
            return False
        rej_full = _telegram_markup_rejection_tag(first_exc)
        logger.debug(
            "booking_pending_notify_markup_attempt_failed booking_id=%s stage=full telegram_tag=%s detail=%s",
            booking_id,
            rej_full,
            first_exc,
        )

    rej_cd = rej_full
    try:
        await _send(markup_confirm_decline_only)
        logger.info(
            "booking_pending_notify_sent booking_id=%s trainer_db_id=%s trainer_chat_id=%s client_tid=%s "
            "keyboard=confirm_decline_only telegram_reason=%s",
            booking_id,
            trainer_db_id,
            chat_id,
            client_tid,
            rej_full,
        )
        _clear_hard_fail_throttle("pending", booking_id)
        return True
    except Exception as second_exc:
        if not _is_telegram_inline_keyboard_bad_request(second_exc):
            if _emit_hard_fail_throttled("pending_fallback", booking_id):
                logger.warning(
                    "booking_pending_notify_fallback_failed booking_id=%s trainer_chat_id=%s "
                    "stage=confirm_decline err=%s",
                    booking_id,
                    chat_id,
                    second_exc,
                )
            return False
        rej_cd = _telegram_markup_rejection_tag(second_exc)
        logger.debug(
            "booking_pending_notify_markup_attempt_failed booking_id=%s stage=confirm_decline telegram_tag=%s detail=%s",
            booking_id,
            rej_cd,
            second_exc,
        )

    try:
        await _send(None)
        logger.info(
            "booking_pending_notify_sent booking_id=%s trainer_db_id=%s trainer_chat_id=%s client_tid=%s "
            "keyboard=none telegram_reason=%s note=text_only_fallback",
            booking_id,
            trainer_db_id,
            chat_id,
            client_tid,
            rej_cd,
        )
        _clear_hard_fail_throttle("pending", booking_id)
        return True
    except Exception as third_exc:
        if _emit_hard_fail_throttled("pending", booking_id):
            logger.error(
                "booking_pending_notify_failed_totally booking_id=%s trainer_db_id=%s trainer_chat_id=%s "
                "client_tid=%s err=%s",
                booking_id,
                trainer_db_id,
                chat_id,
                client_tid,
                third_exc,
                exc_info=True,
            )
        return False


async def _deliver_trainer_confirm_reminder_notification(
    trainer_bot: Bot,
    *,
    chat_id: int,
    text: str,
    markup_full: InlineKeyboardMarkup,
    markup_confirm_only: InlineKeyboardMarkup,
    booking_id: int,
    trainer_db_id: int,
    client_tid: object,
) -> bool:
    """Confirm-reminder push with same Telegram markup fallback chain."""
    parse_mode = "HTML"

    async def _send(markup: InlineKeyboardMarkup | None) -> None:
        await trainer_bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup,
            parse_mode=parse_mode,
        )

    rej_full = ""
    try:
        await _send(markup_full)
        logger.info(
            "booking_confirm_reminder_sent booking_id=%s trainer_db_id=%s trainer_chat_id=%s client_tid=%s "
            "keyboard=full telegram_reason=-",
            booking_id,
            trainer_db_id,
            chat_id,
            client_tid,
        )
        _clear_hard_fail_throttle("reminder", booking_id)
        return True
    except Exception as first_exc:
        if not _is_telegram_inline_keyboard_bad_request(first_exc):
            if _emit_hard_fail_throttled("reminder_other", booking_id):
                logger.warning(
                    "booking_confirm_reminder_failed booking_id=%s trainer_db_id=%s trainer_chat_id=%s "
                    "client_tid=%s err=%s",
                    booking_id,
                    trainer_db_id,
                    chat_id,
                    client_tid,
                    first_exc,
                )
            return False
        rej_full = _telegram_markup_rejection_tag(first_exc)
        logger.debug(
            "booking_confirm_reminder_markup_attempt_failed booking_id=%s stage=full telegram_tag=%s detail=%s",
            booking_id,
            rej_full,
            first_exc,
        )

    rej_cd = rej_full
    try:
        await _send(markup_confirm_only)
        logger.info(
            "booking_confirm_reminder_sent booking_id=%s trainer_db_id=%s trainer_chat_id=%s client_tid=%s "
            "keyboard=confirm_only telegram_reason=%s",
            booking_id,
            trainer_db_id,
            chat_id,
            client_tid,
            rej_full,
        )
        _clear_hard_fail_throttle("reminder", booking_id)
        return True
    except Exception as second_exc:
        if not _is_telegram_inline_keyboard_bad_request(second_exc):
            if _emit_hard_fail_throttled("reminder_fallback", booking_id):
                logger.warning(
                    "booking_confirm_reminder_fallback_failed booking_id=%s trainer_chat_id=%s "
                    "stage=confirm_only err=%s",
                    booking_id,
                    chat_id,
                    second_exc,
                )
            return False
        rej_cd = _telegram_markup_rejection_tag(second_exc)
        logger.debug(
            "booking_confirm_reminder_markup_attempt_failed booking_id=%s stage=confirm_only telegram_tag=%s detail=%s",
            booking_id,
            rej_cd,
            second_exc,
        )

    try:
        await _send(None)
        logger.info(
            "booking_confirm_reminder_sent booking_id=%s trainer_db_id=%s trainer_chat_id=%s client_tid=%s "
            "keyboard=none telegram_reason=%s note=text_only_fallback",
            booking_id,
            trainer_db_id,
            chat_id,
            client_tid,
            rej_cd,
        )
        _clear_hard_fail_throttle("reminder", booking_id)
        return True
    except Exception as third_exc:
        if _emit_hard_fail_throttled("reminder", booking_id):
            logger.error(
                "booking_confirm_reminder_failed_totally booking_id=%s trainer_db_id=%s trainer_chat_id=%s "
                "client_tid=%s err=%s",
                booking_id,
                trainer_db_id,
                chat_id,
                client_tid,
                third_exc,
                exc_info=True,
            )
        return False


def _client_telegram_ok_for_write_button(client_tid: object, trainer_tid: int) -> bool:
    """tg://user?id= URL buttons fail with BUTTON_USER_INVALID when target equals recipient or ID is unusable."""
    try:
        cid = int(client_tid)
    except (TypeError, ValueError):
        return False
    return cid > 0 and cid != int(trainer_tid)


def _same_person_client_as_trainer(client_tid: object, trainer_tid: int) -> bool:
    """QA: client row linked to the same telegram user_id as the trainer (tg:// DM-to-self invalid)."""
    try:
        cid = int(client_tid)
        tid = int(trainer_tid)
    except (TypeError, ValueError):
        return False
    return cid > 0 and cid == tid


def _booking_pending_notify_keyboard(booking_id: int, *, client_tid: object, trainer_tid: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=msg.TRAINER_BOOKINGS_BUTTON_CONFIRM,
                callback_data=f"confirm_booking:{booking_id}",
            ),
            InlineKeyboardButton(
                text=msg.TRAINER_BOOKINGS_BUTTON_DECLINE,
                callback_data=f"decline_booking:{booking_id}",
            ),
        ],
    ]
    relay_self = bool(Settings().trainer_booking_self_client_relay_button)
    if _client_telegram_ok_for_write_button(client_tid, trainer_tid):
        rows.append(
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BOOKINGS_BUTTON_WRITE,
                    url=f"tg://user?id={int(client_tid)}",
                ),
            ],
        )
    elif relay_self and _same_person_client_as_trainer(client_tid, trainer_tid):
        rows.append(
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BOOKINGS_BUTTON_WRITE,
                    callback_data=f"{BOOKING_NOTIFY_RELAY_WRITE_PREFIX}{booking_id}",
                ),
            ],
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _booking_complete_poll_interval_sec() -> int:
    """Sleep between auto-complete scans; from Settings, clamped 15–600 s."""
    try:
        raw = int(Settings().booking_complete_poll_interval_sec)
    except (TypeError, ValueError):
        return 60
    return max(15, min(600, raw))


def _trainer_session_wrapup_poll_interval_sec() -> int:
    """Sleep between wrap-up rounds; from `TRAINER_SESSION_WRAPUP_POLL_INTERVAL_SEC`, clamped 10–60 s."""
    return max(10, min(60, int(TRAINER_SESSION_WRAPUP_POLL_INTERVAL_SEC)))


# Intervals (seconds)
REMINDER_INTERVAL_SEC = 60
CANCEL_NOTIFIER_INTERVAL_SEC = 15
RESPONSE_NOTIFIER_INTERVAL_SEC = 20
NO_RESPONSE_REMINDER_INTERVAL_SEC = 60 * 60
TRAINER_BOOKED_NOTIFIER_INTERVAL_SEC = 30
INACTIVE_CLIENT_INTERVAL_SEC = 60 * 60 * 6
BOOKING_NOTIFIER_INTERVAL_SEC = 15
REQUEST_NOTIFIER_INTERVAL_SEC = 20
COMPLETED_FEEDBACK_INTERVAL_SEC = 20
CERTIFICATE_OUTBOX_INTERVAL_SEC = 2 * 60  # every 2 min: retry failed certificate emails


def _subscription_loop_interval_sec() -> int:
    """Sleep between subscription expire/reminder ticks; clamped for safe local debugging."""
    try:
        v = int(Settings().notification_subscription_loop_interval_sec)
    except (TypeError, ValueError):
        v = 86400
    return max(5, min(v, 86400))


def _lead_mode_recovery_loop_interval_sec() -> int:
    """Sleep between Lead Mode recovery series ticks; clamped for safe local debugging."""
    try:
        v = int(Settings().notification_lead_mode_recovery_interval_sec)
    except (TypeError, ValueError):
        v = 86400
    return max(5, min(v, 86400))


def _onboarding_reactivation_loop_interval_sec() -> int:
    """Sleep between onboarding reactivation series ticks; clamped for safe local debugging."""
    try:
        v = int(Settings().notification_onboarding_reactivation_interval_sec)
    except (TypeError, ValueError):
        v = 86400
    return max(5, min(v, 86400))


def _recurring_materialization_loop_interval_sec() -> int:
    """Sleep between recurring horizon top-up ticks."""
    try:
        v = int(Settings().recurring_materialization_loop_interval_sec)
    except (TypeError, ValueError):
        v = 21600
    return max(300, min(v, 86400))
# Morning/weekly digest ritual: tick every minute so we hit per-trainer send_at with ≤60s jitter.
DIGEST_LOOP_INTERVAL_SEC = 60
# Grace window after a trainer's send_at during which we may still fire today's digest
# (covers service restarts, short outages). After this we skip until tomorrow.
DIGEST_SEND_GRACE_MIN = 120
# Care pulse: lunch window only; 5 min tick is enough for a 2-hour slot.
CARE_PULSE_INTERVAL_SEC = 5 * 60


def _slot_display_strings(slot_date, start_time):
    date_str = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
    day_str = msg.TRAINER_DAYS[slot_date.weekday()] if slot_date and hasattr(slot_date, "weekday") else ""
    time_str = start_time.strftime("%H:%M") if start_time and hasattr(start_time, "strftime") else "—"
    return date_str, day_str, time_str


def _reminder_duration_minutes(start_time, end_time) -> int:
    try:
        if start_time and end_time and hasattr(start_time, "hour") and hasattr(end_time, "hour"):
            delta = datetime.combine(date.today(), end_time) - datetime.combine(date.today(), start_time)
            return max(0, int(delta.total_seconds() // 60))
    except (TypeError, ValueError):
        pass
    return 45


def _requests_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "заявка"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "заявки"
    return "заявок"


async def _maybe_send_session_milestone_pushes(
    client_bot: Bot,
    session: AsyncSession,
    *,
    chat_id: int,
) -> None:
    """
    After a successful «session completed» push: celebrate 5/10/25 totals once per milestone.

    Claim row is released if Telegram send fails so the worker can retry later.
    """
    try:
        cid = await get_client_id_by_telegram_id(session, int(chat_id))
        if cid is None:
            return
        snap = await get_client_activity_snapshot(session, client_id=cid)
        total = int(snap.get("completed_total") or 0)
        rows = await fetch_completed_session_effort_rows(session, cid)
        agg = aggregate_effort_from_completed_sessions(rows)
        kcal_d = round_kcal_for_display(agg.total_kcal)
        effort_line = format_compact_effort_display_html(kcal_display=kcal_d, agg=agg)
        base_url = Settings().webapp_base_url or ""
        for m in SESSION_MILESTONE_TARGETS:
            if total < m:
                continue
            claimed = await try_claim_session_milestone_notification(
                session,
                client_id=cid,
                milestone_target=m,
                completed_total=total,
            )
            if not claimed:
                continue
            pct = await fetch_engagement_percentile_vs_clients_below_threshold(
                session,
                completed_sessions_threshold=m,
            )
            milestone_html = msg.format_client_session_milestone_notice_html(
                milestone=m,
                effort_compact_html_line=effort_line,
                percentile_more_active=pct,
            )
            kb = msg.build_client_session_milestone_inline_keyboard(webapp_base_url=base_url)
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    await client_bot.send_message(
                        chat_id=chat_id,
                        text=milestone_html,
                        reply_markup=kb,
                        parse_mode="HTML",
                    )
                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    await asyncio.sleep(0.35 * (attempt + 1))
            if last_exc is not None:
                logger.warning(
                    "session milestone push failed chat_id=%s milestone=%s after retries: %s",
                    chat_id,
                    m,
                    last_exc,
                )
                await release_session_milestone_claim(
                    session,
                    client_id=cid,
                    milestone_target=m,
                )
    except Exception as e:
        logger.warning("session milestone pipeline chat_id=%s: %s", chat_id, e)


async def _send_client_booking_completed_push(
    client_bot: Bot,
    session: AsyncSession,
    b: dict,
) -> None:
    """
    Send completion notice. Claim client_booking_completed_push_sent_at before Telegram send
    so timeouts / poison markup cannot retry forever (message may already be delivered).
    No telegram_id: mark sent so we do not spin on retries.
    """
    chat_id = b.get("client_telegram_id")
    booking_id = b["id"]
    if not chat_id:
        await mark_client_booking_completion_push_sent(session, booking_id)
        return
    if not await claim_client_booking_completion_push_sent(session, booking_id):
        return
    date_str, day_str, time_str = _slot_display_strings(
        b.get("slot_date"), b.get("start_time")
    )
    duration = _reminder_duration_minutes(b.get("start_time"), b.get("end_time"))
    streak_weeks: int | None = None
    try:
        cid = await get_client_id_by_telegram_id(session, int(chat_id))
        if cid is not None:
            snap = await get_client_activity_snapshot(session, client_id=cid)
            sw = int(snap.get("streak_weeks") or 0)
            if sw >= 2:
                streak_weeks = sw
    except Exception:
        streak_weeks = None
    deduction = await load_booking_deduction_snapshot(session, booking_id)
    text = msg.format_client_booking_completed_notice_html(
        date=date_str,
        day=day_str,
        time=time_str,
        duration_minutes=b.get("duration_minutes") if b.get("duration_minutes") is not None else duration,
        trainer_name=(b.get("trainer_name") or "Тренер"),
        service_name=b.get("service_name"),
        streak_weeks=streak_weeks,
        deduction_outcome=deduction.outcome if deduction.outcome in ("pass", "cert") else None,
        pass_sessions_remaining=deduction.pass_sessions_remaining,
        cert_amount_cents=deduction.cert_amount_cents,
        cert_remaining_cents=deduction.cert_remaining_cents,
    )
    kb = msg.build_client_booking_completed_inline_keyboard(
        webapp_base_url=(Settings().webapp_base_url or ""),
        trainer_id=b["trainer_id"],
        booking_id=booking_id,
        trainer_telegram_id=b.get("trainer_telegram_id"),
        recipient_telegram_id=int(chat_id),
        show_repeat_row=True,
    )
    try:
        await _send_message_with_markup_fallback(
            client_bot,
            chat_id=int(chat_id),
            text=text,
            reply_markup=kb,
            parse_mode="HTML",
        )
        await _maybe_send_session_milestone_pushes(client_bot, session, chat_id=int(chat_id))
    except Exception as e:
        if _is_telegram_timeout(e):
            logger.warning(
                "Completed notifier timeout to client %s (booking_id=%s); keeping claim to avoid duplicates: %s",
                chat_id,
                booking_id,
                e,
            )
            return
        await clear_client_booking_completion_push_sent(session, booking_id)
        logger.warning(
            "Completed notifier send to client %s (booking_id=%s): %s",
            chat_id,
            booking_id,
            e,
        )


async def process_booking_complete_round(client_bot: Bot, trainer_bot: Bot) -> None:
    """
    One pass: retry failed client completion pushes, then auto-complete past slots and notify.
    Client completion Telegram uses global quiet hours; trainer no-pass uses per-trainer window.
    Exposed for integration tests (notification_service worker runs this in a loop).
    """
    async with async_session_factory() as session:
        if is_within_notification_hours():
            pending_retry = await list_bookings_pending_client_completion_push(session)
            for b in pending_retry:
                await _send_client_booking_completed_push(client_bot, session, b)

        to_complete = await list_bookings_to_complete(session)
        if to_complete:
            logger.info(
                "booking_complete_loop: %s booking(s) to complete",
                len(to_complete),
            )
        for b in to_complete:
            await mark_booking_completed_and_notify(session, b["id"])
            if is_within_notification_hours():
                await _send_client_booking_completed_push(client_bot, session, b)


async def process_cancel_notifications_batch(client_bot: Bot, session: AsyncSession) -> None:
    pending = await get_pending_booking_cancel_notifications(session)
    for p in pending:
        await send_cancel_notification_payload(client_bot, session, p)


async def process_response_notifications_batch(client_bot: Bot, session: AsyncSession) -> None:
    pending = await get_pending_response_notifications(session)
    for p in pending:
        client_tid = p.get("client_telegram_id")
        if not client_tid:
            continue
        if p.get("trainer_comment"):
            text = msg.CLIENT_RESPONSE_NOTIFICATION_WITH_COMMENT.format(
                responder_name=html_lib.escape(str(p.get("responder_name") or "Тренер")),
                comment=html_lib.escape(str(p.get("trainer_comment") or "")),
            )
        else:
            text = msg.CLIENT_RESPONSE_NOTIFICATION
        request_id = p.get("request_id")
        kb = None
        if request_id is not None:
            base = (Settings().webapp_base_url or "").rstrip("/")
            if base.startswith("https://"):
                url = f"{base}/webapp/client-requests?request_id={request_id}"
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=msg.CLIENT_RESPONSE_BUTTON_VIEW,
                                web_app=WebAppInfo(url=url),
                            )
                        ],
                    ]
                )
            else:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=msg.CLIENT_RESPONSE_BUTTON_VIEW,
                                callback_data=f"my_request:{request_id}",
                            )
                        ],
                    ]
                )
        try:
            await client_bot.send_message(
                chat_id=client_tid, text=text, reply_markup=kb
            )
            await mark_response_notified(session, p["response_id"])
        except Exception as e:
            logger.warning(
                "Response notifier send to client %s: %s", client_tid, e
            )


async def _deliver_trainer_new_request_message(
    trainer_bot: Bot,
    session: AsyncSession,
    p: dict,
) -> None:
    """Send «new client request» DM to trainer; retry without keyboard if Telegram rejects inline markup."""
    tid = p.get("trainer_telegram_id")
    if not tid:
        raise ValueError("trainer has no telegram id")

    comment_raw = (p.get("comment") or "").strip()
    pass_product_id, _body = split_pass_order_comment(comment_raw)

    if pass_product_id is not None:
        text, kb = await _build_pass_order_notification(
            session,
            p=p,
            pass_product_id=pass_product_id,
        )
    else:
        certificate_product_id, cert_meta, _c_body = split_cert_order_comment(comment_raw)
        if certificate_product_id is not None:
            text, kb = await build_cert_order_trainer_notification(
                session,
                p=p,
                certificate_product_id=certificate_product_id,
                cert_meta=cert_meta,
            )
        else:
            if comment_raw:
                text = msg.TRAINER_REQUEST_NOTIFICATION.format(
                    city=html_lib.escape(str(p.get("city_name") or "")),
                    service=html_lib.escape(str(p.get("service_name") or "")),
                    comment=html_lib.escape(comment_raw),
                )
            else:
                text = msg.TRAINER_REQUEST_NOTIFICATION_NO_COMMENT.format(
                    city=html_lib.escape(str(p.get("city_name") or "")),
                    service=html_lib.escape(str(p.get("service_name") or "")),
                )
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=msg.TRAINER_BUTTON_RESPOND,
                            callback_data=f"{REQUEST_RESPOND_PREFIX}{p['request_id']}",
                        ),
                        InlineKeyboardButton(
                            text=msg.TRAINER_BUTTON_DECLINE,
                            callback_data=f"{REQUEST_DECLINE_PREFIX}{p['request_id']}",
                        ),
                    ],
                ]
            )

    try:
        await trainer_bot.send_message(chat_id=tid, text=text, reply_markup=kb)
    except Exception as e:
        err_l = str(e).lower()
        if kb and (
            "button" in err_l
            or "keyboard" in err_l
            or "inline" in err_l
            or "url" in err_l
        ):
            logger.warning(
                "Request notifier: retry without keyboard (trainer_tid=%s): %s",
                tid,
                e,
            )
            await trainer_bot.send_message(chat_id=tid, text=text)
            return
        raise


async def process_request_notifications_batch(
    trainer_bot: Bot,
    session: AsyncSession,
    *,
    only_request_id: int | None = None,
    bypass_quiet_hours_for_that_request: bool = False,
) -> None:
    pending = await get_pending_request_notifications(session)
    for p in pending:
        if only_request_id is not None and int(p["request_id"]) != only_request_id:
            continue

        enforce_quiet_hours = True
        if (
            bypass_quiet_hours_for_that_request
            and only_request_id is not None
            and int(p["request_id"]) == only_request_id
        ):
            enforce_quiet_hours = False

        if enforce_quiet_hours and not await is_trainer_push_allowed_now(session, int(p["trainer_id"])):
            continue
        tid = p.get("trainer_telegram_id")
        if not tid:
            continue

        try:
            await _deliver_trainer_new_request_message(trainer_bot, session, p)
            await mark_request_trainer_notified(
                session, p["request_id"], p["trainer_id"]
            )
        except Exception as e:
            logger.warning("Request notifier send to %s: %s", tid, e)


def _trainer_order_write_client_row(
    *,
    request_id: int,
    client_id: object | None,
    client_telegram_id: object | None,
) -> list[InlineKeyboardButton] | None:
    """
    «Написать клиенту»: deep-link в личный чат (без callback — работает без polling trainer_app).
    Второй тап «Через бота» — relay, если trainer_app запущен.
    """
    if client_id is None:
        return None
    rid = int(request_id)
    ctid: int | None = None
    if client_telegram_id is not None:
        try:
            cti = int(client_telegram_id)
        except (TypeError, ValueError):
            cti = 0
        if cti > 0:
            ctid = cti
    if ctid is not None:
        return [
            InlineKeyboardButton(
                text=msg.TRAINER_PASS_ORDER_BTN_WRITE,
                url=f"tg://user?id={ctid}",
            ),
            InlineKeyboardButton(
                text=msg.TRAINER_ORDER_WRITE_VIA_BOT_BTN,
                callback_data=f"{msg.CLIENT_REQUEST_RELAY_CHAT_PREFIX}{rid}",
            ),
        ]
    return [
        InlineKeyboardButton(
            text=msg.TRAINER_PASS_ORDER_BTN_WRITE,
            callback_data=f"{msg.CLIENT_REQUEST_RELAY_CHAT_PREFIX}{rid}",
        ),
    ]


async def _build_pass_order_notification(
    session: AsyncSession,
    *,
    p: dict,
    pass_product_id: int,
) -> tuple[str, InlineKeyboardMarkup]:
    """Text + keyboard for a pass-product order notification to the trainer."""
    settings = Settings()
    base = (settings.webapp_base_url or "").rstrip("/")
    webapp_https = base.lower().startswith("https://")

    product = await get_pass_product(session, pass_product_id, int(p["trainer_id"]))
    name_parts = [
        (p.get("client_first_name") or "").strip(),
        (p.get("client_middle_name") or "").strip(),
        (p.get("client_last_name") or "").strip(),
    ]
    client_name = " ".join(x for x in name_parts if x).strip() or "Клиент"

    if product:
        pass_name = product.get("name") or "Абонемент"
        label = (product.get("service_name") or "").strip()
        sids = product.get("service_ids") or []
        if not sids:
            service_line = "Любая"
        elif label:
            service_line = label
        else:
            service_line = "Несколько услуг"
    else:
        pass_name = "Абонемент"
        req_svc = (p.get("service_name") or "").strip()
        service_line = req_svc if req_svc else "Любая"

    text = msg.TRAINER_PASS_ORDER_NOTIFICATION.format(
        client_name=html_lib.escape(client_name),
        pass_name=html_lib.escape(pass_name),
        service_line=html_lib.escape(service_line),
    )

    client_id = p.get("client_id")
    rid = int(p["request_id"])
    rows: list[list[InlineKeyboardButton]] = []

    write_row = _trainer_order_write_client_row(
        request_id=rid,
        client_id=client_id,
        client_telegram_id=p.get("client_telegram_id"),
    )
    if write_row:
        rows.append(write_row)

    if webapp_https and client_id and pass_product_id:
        issue_url = (
            f"{base}/webapp/trainer-pass-products"
            f"?client_id={int(client_id)}&pass_product_id={int(pass_product_id)}"
        )
        rows.append([
            InlineKeyboardButton(
                text=msg.TRAINER_PASS_ORDER_BTN_ISSUE,
                web_app=WebAppInfo(url=issue_url),
            )
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=rows if rows else [[
        InlineKeyboardButton(
            text=msg.TRAINER_BUTTON_PASSES,
            callback_data="passes",
        )
    ]])
    return text, kb


async def build_cert_order_trainer_notification(
    session: AsyncSession,
    *,
    p: dict,
    certificate_product_id: int,
    cert_meta: dict,
) -> tuple[str, InlineKeyboardMarkup]:
    """
    Trainer push about certificate order.
    «Написать клиенту» — tg:// deep link; «Через бота» — relay (callback), если нужен лог в боте.
    """
    from urllib.parse import quote

    settings = Settings()
    base = (settings.webapp_base_url or "").rstrip("/")
    webapp_https = base.lower().startswith("https://")

    product = await get_certificate_product(session, certificate_product_id, int(p["trainer_id"]))
    name_parts = [
        (p.get("client_first_name") or "").strip(),
        (p.get("client_middle_name") or "").strip(),
        (p.get("client_last_name") or "").strip(),
    ]
    client_name = " ".join(x for x in name_parts if x).strip() or "Клиент"

    cert_name = (
        (product.get("name") or "").strip() or "Подарочный сертификат"
        if product
        else "Подарочный сертификат"
    )
    recipient_name = (cert_meta.get("recipient_name") or "").strip() or "—"
    recipient_email = (cert_meta.get("recipient_email") or "").strip() or "—"

    text = msg.TRAINER_CERT_ORDER_NOTIFICATION.format(
        client_name=html_lib.escape(client_name),
        cert_name=html_lib.escape(cert_name),
        recipient_name=html_lib.escape(recipient_name),
        recipient_email=html_lib.escape(recipient_email),
    )

    rid = int(p["request_id"])
    client_id = p.get("client_id")
    rows: list[list[InlineKeyboardButton]] = []

    write_row = _trainer_order_write_client_row(
        request_id=rid,
        client_id=client_id,
        client_telegram_id=p.get("client_telegram_id"),
    )
    if write_row:
        rows.append(write_row)

    if webapp_https and client_id and certificate_product_id:
        r_email = (cert_meta.get("recipient_email") or "").strip()
        r_name = (cert_meta.get("recipient_name") or "").strip()
        p_bn = (cert_meta.get("purchased_by_name") or "").strip()
        issue_url = (
            f"{base}/webapp/trainer-pass-products?tab=certs"
            f"&client_id={int(client_id)}"
            f"&certificate_product_id={int(certificate_product_id)}"
            f"&recipient_email={quote(r_email)}"
            f"&recipient_name={quote(r_name)}"
        )
        if p_bn:
            issue_url += f"&purchased_by_name={quote(p_bn)}"
        rows.append([
            InlineKeyboardButton(
                text=msg.TRAINER_CERT_ORDER_BTN_ISSUE,
                web_app=WebAppInfo(url=issue_url),
            ),
        ])

    kb = InlineKeyboardMarkup(
        inline_keyboard=rows
        if rows
        else [
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BUTTON_PASSES,
                    callback_data="passes",
                )
            ]
        ]
    )
    return text, kb


async def _build_trainer_post_session_keyboard(
    session: AsyncSession,
    p: dict,
    *,
    base: str,
    webapp_https: bool,
    include_client_dm: bool = True,
    recipient_telegram_id: int | None = None,
) -> InlineKeyboardMarkup:
    """Inline keyboard for trainer «session end» flows: quick rebook, repeat week, note to client card, optional DM, client card."""
    client_id = p.get("client_id")
    slot_date = p.get("slot_date")
    start_time = p.get("start_time")
    can_quick_rebook = (
        webapp_https
        and client_id is not None
        and await trainer_has_crm_access(session, p["trainer_id"])
    )
    rows: list[list[InlineKeyboardButton]] = []
    if can_quick_rebook:
        rows.append(
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BUTTON_BOOK_AGAIN,
                    web_app=WebAppInfo(
                        url=f"{base}/webapp/schedule-editor?flow=book&client_id={int(client_id)}"
                        f"&from_booking_id={int(p['booking_id'])}"
                    ),
                ),
            ],
        )
    if slot_date and start_time:
        st_norm = (
            start_time.replace(second=0, microsecond=0)
            if hasattr(start_time, "replace")
            else start_time
        )
        sd = slot_date.date() if hasattr(slot_date, "date") else slot_date
        if await can_trainer_repeat_booking_same_time_next_week(
            session,
            trainer_id=p["trainer_id"],
            slot_date=sd,
            start_time=st_norm,
            end_time=p.get("end_time"),
        ):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=msg.TRAINER_BUTTON_BOOK_SAME_TIME_NEXT_WEEK,
                        callback_data=f"trainer_repeat_week:{p['booking_id']}",
                    ),
                ],
            )
    rows.append(
        [
            InlineKeyboardButton(
                text=msg.TRAINER_BUTTON_ADD_BOOKING_NOTE,
                callback_data=f"{BOOKING_ADD_NOTE_PREFIX}{p['booking_id']}",
            ),
        ],
    )
    if include_client_dm and p.get("client_telegram_id"):
        recipient = recipient_telegram_id
        if recipient is None:
            raw = p.get("trainer_telegram_id")
            try:
                recipient = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                recipient = None
        if recipient is not None and _client_telegram_ok_for_write_button(
            p["client_telegram_id"], int(recipient)
        ):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=msg.TRAINER_BOOKING_CONFIRMED_BTN_WRITE,
                        url=f"tg://user?id={int(p['client_telegram_id'])}",
                    ),
                ],
            )
    if can_quick_rebook:
        rows.append(
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BUTTON_CLIENT_CARD_WEBAPP,
                    web_app=WebAppInfo(
                        url=f"{base}/webapp/trainer-clients?client_id={int(client_id)}"
                    ),
                ),
            ],
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def process_trainer_session_wrapup_round(
    trainer_bot: Bot,
    *,
    settings: Settings | None = None,
) -> None:
    """
    One pass: «Занятие подходит к концу» when remaining slot time is in the fixed band (Europe/Minsk).

    Band is ``TRAINER_SESSION_WRAPUP_REMAINING_SEC_MIN``–``TRAINER_SESSION_WRAPUP_REMAINING_SEC_MAX`` seconds
    before slot end (default 120–180 s = 2–3 minutes); independent of slot duration.

    Does **not** defer on per-trainer quiet windows — those skips caused wrap-up to be missed while «завершено» still fired.
    """
    cfg = settings or get_settings()
    rmin = int(TRAINER_SESSION_WRAPUP_REMAINING_SEC_MIN)
    rmax = int(TRAINER_SESSION_WRAPUP_REMAINING_SEC_MAX)
    if rmin <= 0 or rmax <= 0 or rmin >= rmax:
        return
    async with async_session_factory() as session:
        pending = await list_bookings_for_trainer_session_wrapup(
            session,
            remaining_seconds_min=rmin,
            remaining_seconds_max=rmax,
            limit=25,
        )
    base = (cfg.webapp_base_url or "").rstrip("/")
    webapp_https = base.startswith("https://")
    for p in pending:
        async with async_session_factory() as session:
            trainer_tid = await get_trainer_telegram_id(session, p["trainer_id"])
            if not trainer_tid:
                await mark_trainer_session_wrapup_sent(session, p["booking_id"])
                continue
            # Do not defer on per-trainer push windows — those deferrals caused wrap-up to miss entirely
            # (trainer then only saw «Занятие завершено»). Completed-push dedupe still avoids duplicate CTAs.
            slot_date = p.get("slot_date")
            start_time = p.get("start_time")
            date_str = (
                slot_date.strftime("%d.%m")
                if slot_date and hasattr(slot_date, "strftime")
                else "—"
            )
            day_str = (
                msg.TRAINER_DAYS[slot_date.weekday()]
                if slot_date and hasattr(slot_date, "weekday")
                else ""
            )
            time_str = (
                start_time.strftime("%H:%M")
                if start_time and hasattr(start_time, "strftime")
                else "—"
            )
            end_time = p.get("end_time")
            duration_done = _reminder_duration_minutes(start_time, end_time)
            client_id = p.get("client_id")
            can_quick_rebook = (
                webapp_https
                and client_id is not None
                and await trainer_has_crm_access(session, p["trainer_id"])
            )
            payment_class = await classify_booking_expected_payment_class(
                session, int(p["booking_id"]), int(p["trainer_id"])
            )
            pass_remaining: int | None = None
            if (payment_class or "").strip().upper() == "PASS":
                pass_remaining = await load_pass_sessions_remaining_after_booking(
                    session, int(p["booking_id"]), int(p["trainer_id"])
                )
            text = msg.format_trainer_booking_session_wrapup_html(
                client_name=p.get("client_name") or "Клиент",
                date=date_str,
                day=day_str,
                time=time_str,
                duration_minutes=duration_done,
                service_name=p.get("service_name"),
                price_tier_label=p.get("price_tier_label"),
                booking_price_cents=p.get("booking_price_cents"),
                arena_display=p.get("arenas_str"),
                include_quick_rebook_line=can_quick_rebook,
                expected_payment_class=payment_class,
                pass_sessions_remaining=pass_remaining,
            )
            kb = await _build_trainer_post_session_keyboard(
                session,
                p,
                base=base,
                webapp_https=webapp_https,
                include_client_dm=False,
            )
            try:
                await trainer_bot.send_message(
                    chat_id=trainer_tid, text=text, reply_markup=kb
                )
                tz = ZoneInfo(NOTIFICATION_TZ)
                sent_at_local = datetime.now(tz)
                slot_end_local = (
                    datetime.combine(slot_date, end_time).replace(tzinfo=tz)
                    if slot_date is not None
                    and end_time is not None
                    and hasattr(slot_date, "year")
                    and hasattr(end_time, "hour")
                    else None
                )
                remain_sec: float | None = None
                if slot_end_local is not None:
                    remain_sec = (slot_end_local - sent_at_local).total_seconds()
                logger.info(
                    "trainer_session_wrapup_sent booking_id=%s trainer_id=%s trainer_chat_id=%s "
                    "slot_end_local=%s sent_at_local=%s seconds_until_slot_end=%s timezone=%s",
                    p.get("booking_id"),
                    p.get("trainer_id"),
                    trainer_tid,
                    slot_end_local.isoformat() if slot_end_local else None,
                    sent_at_local.isoformat(),
                    round(remain_sec, 3) if remain_sec is not None else None,
                    NOTIFICATION_TZ,
                )
                await mark_trainer_session_wrapup_sent(session, p["booking_id"])
            except Exception as e:
                logger.warning(
                    "Session wrap-up send to trainer %s (booking_id=%s): %s",
                    trainer_tid,
                    p.get("booking_id"),
                    e,
                )


async def process_completed_feedback_batch(
    trainer_bot: Bot, session: AsyncSession
) -> None:
    pending = await get_pending_completed_for_trainer(session)
    settings = Settings()
    base = (settings.webapp_base_url or "").rstrip("/")
    webapp_https = base.startswith("https://")
    for p in pending:
        if not await is_trainer_push_allowed_now(session, int(p["trainer_id"])):
            continue
        trainer_tid = await get_trainer_telegram_id(session, p["trainer_id"])
        if not trainer_tid:
            await mark_trainer_completed_sent(session, p["id"])
            continue
        if not await claim_trainer_completed_sent(session, p["id"]):
            continue
        slot_date = p.get("slot_date")
        start_time = p.get("start_time")
        date_str = (
            slot_date.strftime("%d.%m")
            if slot_date and hasattr(slot_date, "strftime")
            else "—"
        )
        day_str = (
            msg.TRAINER_DAYS[slot_date.weekday()]
            if slot_date and hasattr(slot_date, "weekday")
            else ""
        )
        time_str = (
            start_time.strftime("%H:%M")
            if start_time and hasattr(start_time, "strftime")
            else "—"
        )
        end_time = p.get("end_time")
        duration_done = _reminder_duration_minutes(start_time, end_time)
        client_id = p.get("client_id")
        can_quick_rebook = (
            webapp_https
            and client_id is not None
            and await trainer_has_crm_access(session, p["trainer_id"])
        )
        deduction = await load_booking_deduction_snapshot(session, int(p["booking_id"]))
        text = msg.format_trainer_booking_completed_html(
            client_name=p.get("client_name") or "Клиент",
            date=date_str,
            day=day_str,
            time=time_str,
            duration_minutes=duration_done,
            service_name=p.get("service_name"),
            price_tier_label=p.get("price_tier_label"),
            arena_display=p.get("arenas_str"),
            include_quick_rebook_line=can_quick_rebook,
            deduction_outcome=deduction.outcome,
            pass_sessions_remaining=deduction.pass_sessions_remaining,
            cert_amount_cents=deduction.cert_amount_cents,
            cert_remaining_cents=deduction.cert_remaining_cents,
        )
        kb = await _build_trainer_post_session_keyboard(
            session,
            p,
            base=base,
            webapp_https=webapp_https,
            recipient_telegram_id=int(trainer_tid),
        )
        try:
            await _send_message_with_markup_fallback(
                trainer_bot,
                chat_id=int(trainer_tid),
                text=text,
                reply_markup=kb,
            )
        except Exception as e:
            if _is_telegram_timeout(e):
                logger.warning(
                    "Completed feedback timeout to trainer %s (notif_id=%s); "
                    "keeping claim to avoid duplicates: %s",
                    trainer_tid,
                    p["id"],
                    e,
                )
                continue
            await clear_trainer_completed_sent(session, p["id"])
            logger.warning(
                "Completed feedback send to trainer %s: %s",
                trainer_tid,
                e,
            )


# --- Client loops (use client_bot) ---


async def run_reminder_loop(client_bot: Bot) -> None:
    while True:
        await asyncio.sleep(REMINDER_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                pending = await list_pending_reminders(session)
                for p in pending:
                    chat_id = p.get("client_telegram_id")
                    if not chat_id:
                        continue
                    raw_sessions = p.get("sessions") or []
                    sessions_payload: list[dict] = []
                    for s in raw_sessions:
                        date_str, day_str, time_str = _slot_display_strings(
                            s.get("slot_date"), s.get("start_time")
                        )
                        dur = s.get("duration_minutes")
                        if dur is None:
                            dur = _reminder_duration_minutes(s.get("start_time"), s.get("end_time"))
                        sessions_payload.append(
                            {
                                "date": date_str,
                                "day": day_str,
                                "time": time_str,
                                "duration": int(dur or 0),
                                "service_name": s.get("service_name"),
                                "booking_price_cents": s.get("booking_price_cents"),
                                "expected_payment_class": s.get("expected_payment_class"),
                                "arena_name": s.get("arena_name"),
                                "arena_address": s.get("arena_address"),
                            }
                        )
                    kind = p.get("kind") or ""
                    text = msg.format_client_booking_reminder_text(
                        is_soon=(kind not in ("before_24h", "before_evening_prior")),
                        sessions=sessions_payload,
                    )
                    arena_payload = {
                        "latitude": p.get("arena_latitude"),
                        "longitude": p.get("arena_longitude"),
                        "address": p.get("arena_address"),
                    }
                    map_url = build_yandex_by_map_url(arena_payload)
                    # One button per row: side-by-side labels truncate on narrow phones.
                    kb_rows: list[list[InlineKeyboardButton]] = []
                    if p.get("trainer_telegram_id"):
                        kb_rows.append(
                            [
                                InlineKeyboardButton(
                                    text=msg.CLIENT_REMINDER_BTN_WRITE_TRAINER,
                                    url=f"tg://user?id={int(p['trainer_telegram_id'])}",
                                )
                            ]
                        )
                    if map_url:
                        kb_rows.append(
                            [
                                InlineKeyboardButton(
                                    text=msg.CLIENT_REMINDER_BTN_SHOW_ON_MAP,
                                    url=map_url,
                                )
                            ]
                        )
                    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None
                    try:
                        await client_bot.send_message(
                            chat_id=chat_id,
                            text=text,
                            reply_markup=kb,
                        )
                        await mark_reminder_sent(session, p["id"])
                    except Exception as e:
                        logger.warning("Reminder send to client %s (reminder_id=%s): %s", chat_id, p["id"], e)
                        await mark_reminder_failed(session, p["id"], str(e))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Reminder loop: %s", e)


async def run_group_attendance_prompt_loop(client_bot: Bot) -> None:
    """RSVP for cohort slots: sync prompt rows, send Telegram with inline buttons."""
    while True:
        await asyncio.sleep(REMINDER_INTERVAL_SEC)
        try:
            settings = Settings()
            hours = settings.group_attendance_prompt_hours
            if not hours or int(hours) <= 0:
                continue
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                await sync_group_attendance_prompts(session, int(hours))
            async with async_session_factory() as session:
                pending = await list_pending_attendance_prompts(session, limit=40)
            secret = rsvp_hmac_secret(settings.telegram_bot_token_client)
            for p in pending:
                chat_id = p.get("client_telegram_id")
                if not chat_id:
                    continue
                date_str, day_str, time_str = _slot_display_strings(
                    p.get("slot_date"), p.get("start_time")
                )
                duration = _reminder_duration_minutes(p.get("start_time"), p.get("end_time"))
                pid = int(p["id"])
                sig_y = attendance_rsvp_sign(pid, "y", secret)
                sig_n = attendance_rsvp_sign(pid, "n", secret)
                text = msg.CLIENT_GROUP_RSVP_INVITE.format(
                    group=html_lib.escape(p.get("group_name") or "Группа"),
                    date=date_str,
                    day=day_str,
                    time=time_str,
                    duration=duration,
                )
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=msg.GROUP_RSVP_BUTTON_YES,
                                callback_data=f"RSY:{pid}:{sig_y}",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=msg.GROUP_RSVP_BUTTON_NO,
                                callback_data=f"RSN:{pid}:{sig_n}",
                            )
                        ],
                    ]
                )
                try:
                    await client_bot.send_message(
                        chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML"
                    )
                    async with async_session_factory() as session:
                        await mark_attendance_prompt_sent(session, pid)
                except Exception as e:
                    logger.warning(
                        "Group RSVP send to client %s (prompt_id=%s): %s",
                        chat_id,
                        pid,
                        e,
                    )
                    async with async_session_factory() as session:
                        await mark_attendance_prompt_failed(session, pid, str(e))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Group attendance prompt loop: %s", e)


async def run_trainer_session_wrapup_loop(trainer_bot: Bot, settings: Settings) -> None:
    """Fast tick for pre-end trainer CTA; decoupled from `run_booking_complete_loop` for reliable narrow-window pickup."""
    logger.info("[trainer_session_wrapup_loop] started")
    while True:
        try:
            await asyncio.sleep(_trainer_session_wrapup_poll_interval_sec())
            await process_trainer_session_wrapup_round(trainer_bot, settings=settings)
        except asyncio.CancelledError:
            logger.info("[trainer_session_wrapup_loop] cancelled")
            break
        except Exception as e:
            logger.exception("Trainer session wrap-up loop: %s", e)


async def run_booking_complete_loop(client_bot: Bot, trainer_bot: Bot) -> None:
    logger.info("[booking_complete_loop] started")
    while True:
        try:
            await asyncio.sleep(_booking_complete_poll_interval_sec())
            await process_booking_complete_round(client_bot, trainer_bot)
        except asyncio.CancelledError:
            logger.info("[booking_complete_loop] cancelled")
            break
        except Exception as e:
            logger.exception("Booking complete loop: %s", e)


async def run_cancel_notifier_loop(client_bot: Bot) -> None:
    """Drain booking_cancel_notifications queue (retry if immediate send after cancel failed)."""
    while True:
        await asyncio.sleep(CANCEL_NOTIFIER_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                await process_cancel_notifications_batch(client_bot, session)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Cancel notifier: %s", e)


async def run_booking_party_notifier_loop(trainer_bot: Bot, client_bot: Bot) -> None:
    """Retry booking_party_notifications outbox (client↔trainer lifecycle pushes)."""
    from src.bot.booking_party_notify import process_booking_party_notifications_batch

    while True:
        await asyncio.sleep(CANCEL_NOTIFIER_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                n = await process_booking_party_notifications_batch(
                    session,
                    trainer_bot=trainer_bot,
                    client_bot=client_bot,
                )
                if n:
                    logger.info("booking_party_notifier delivered=%s", n)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Booking party notifier: %s", e)


async def run_response_notifier_loop(client_bot: Bot) -> None:
    while True:
        await asyncio.sleep(RESPONSE_NOTIFIER_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                await process_response_notifications_batch(client_bot, session)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Response notifier: %s", e)


async def run_no_response_reminder_loop(client_bot: Bot) -> None:
    while True:
        await asyncio.sleep(NO_RESPONSE_REMINDER_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                pending = await get_pending_no_response_reminders(session)
                for p in pending:
                    client_tid = p.get("client_telegram_id")
                    if not client_tid:
                        continue
                    try:
                        settings_nr = Settings()
                        kb_nr = msg.build_client_no_response_catalog_keyboard(
                            webapp_base_url=settings_nr.webapp_base_url,
                        )
                        await client_bot.send_message(
                            chat_id=client_tid,
                            text=msg.CLIENT_NO_RESPONSE_REMINDER,
                            reply_markup=kb_nr,
                        )
                        await mark_no_response_reminder_sent(session, p["request_id"])
                    except Exception as e:
                        logger.warning(
                            "No-response reminder send to client %s (request_id=%s): %s",
                            client_tid,
                            p.get("request_id"),
                            e,
                        )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("No-response reminder loop: %s", e)


async def run_trainer_booked_notifier_loop(client_bot: Bot) -> None:
    while True:
        await asyncio.sleep(TRAINER_BOOKED_NOTIFIER_INTERVAL_SEC)
        try:
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                pending = await get_pending_trainer_booked_notifications(session)
                settings_tb = Settings()
                for p in pending:
                    await try_send_client_trainer_booked_push(
                        session,
                        client_bot,
                        int(p["booking_id"]),
                        webapp_base_url=settings_tb.webapp_base_url,
                    )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Trainer-booked notifier: %s", e)


async def run_inactive_client_loop(client_bot: Bot) -> None:
    logger.info("[inactive_client_loop] started")
    while True:
        try:
            await asyncio.sleep(INACTIVE_CLIENT_INTERVAL_SEC)
            if not is_within_notification_hours():
                continue
            async with async_session_factory() as session:
                for kind in (INACTIVE_KIND_10_DAYS, INACTIVE_KIND_30_DAYS):
                    clients = await get_clients_for_inactive_notification(session, kind)
                    if not clients:
                        continue
                    text_template = (
                        msg.CLIENT_INACTIVE_10_DAYS
                        if kind == INACTIVE_KIND_10_DAYS
                        else msg.CLIENT_INACTIVE_30_DAYS
                    )
                    settings_ia = Settings()
                    base_ia = (settings_ia.webapp_base_url or "").rstrip("/")
                    if base_ia.lower().startswith("https://"):
                        inactive_label = (
                            msg.CLIENT_INACTIVE_BTN_BOOK_NOW
                            if kind == INACTIVE_KIND_10_DAYS
                            else msg.CLIENT_BUTTON_OPEN_CATALOG_WEBAPP
                        )
                        kb = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text=inactive_label,
                                        web_app=WebAppInfo(url=f"{base_ia}/webapp/catalog"),
                                    ),
                                ],
                            ]
                        )
                    else:
                        kb = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text=msg.CLIENT_BUTTON_BOOK,
                                        callback_data="catalog",
                                    )
                                ],
                            ]
                        )
                    for c in clients:
                        chat_id = c.get("telegram_id")
                        if not chat_id:
                            continue
                        name = (c.get("first_name") or "").strip()
                        name_placeholder = f", {name}" if name else ""
                        text = text_template.format(name=name_placeholder)
                        try:
                            await client_bot.send_message(
                                chat_id=chat_id, text=text, reply_markup=kb
                            )
                            await mark_inactive_notification_sent(
                                session, c["client_id"], kind
                            )
                        except Exception as e:
                            logger.warning(
                                "Inactive notify to client %s (kind=%s): %s",
                                chat_id,
                                kind,
                                e,
                            )
        except asyncio.CancelledError:
            logger.info("[inactive_client_loop] cancelled")
            break
        except Exception as e:
            logger.exception("Inactive client loop: %s", e)


# --- Trainer loops (use trainer_bot) ---


async def run_booking_notifier_loop(trainer_bot: Bot) -> None:
    while True:
        await asyncio.sleep(BOOKING_NOTIFIER_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                pending = await get_bookings_pending_notification(session)
                if pending:
                    logger.debug(
                        "Booking notifier: %s pending booking(s) queued for trainer(s)",
                        len(pending),
                    )
                for b in pending:
                    if not await is_trainer_push_allowed_now(session, int(b["trainer_id"])):
                        continue
                    trainer_tid = await get_trainer_telegram_id(session, b["trainer_id"])
                    if not trainer_tid:
                        await mark_booking_notified(session, b["id"])
                        continue
                    d = b["slot_date"]
                    date_str = d.strftime("%d.%m") if hasattr(d, "strftime") else str(d)
                    dow = msg.TRAINER_DAYS[d.weekday()] if hasattr(d, "weekday") else ""
                    time_str = (
                        f"{b['start_time'].strftime('%H:%M') if hasattr(b['start_time'], 'strftime') else b['start_time']}"
                        f"–{b['end_time'].strftime('%H:%M') if hasattr(b['end_time'], 'strftime') else b['end_time']}"
                    )
                    duration = _reminder_duration_minutes(
                        b.get("start_time"), b.get("end_time")
                    )
                    phone = b.get("client_phone") or "—"
                    comment = (b.get("client_comment") or "").strip()
                    client_name = b.get("client_name") or "Клиент"
                    service = b.get("service_name") or "—"
                    city = b.get("city_name") or "—"
                    arenas = b.get("arenas_str") or "—"
                    pl = (b.get("price_tier_label") or "").strip()
                    tariff_display = pl or "—"
                    if comment:
                        text = msg.TRAINER_BOOKING_NOTIFICATION.format(
                            date=html_lib.escape(date_str),
                            day=html_lib.escape(dow),
                            time=html_lib.escape(time_str),
                            duration=duration,
                            client_name=html_lib.escape(client_name),
                            phone=html_lib.escape(phone),
                            service=html_lib.escape(service),
                            city=html_lib.escape(city),
                            arenas=html_lib.escape(arenas),
                            tariff=html_lib.escape(tariff_display),
                            comment=html_lib.escape(comment),
                        )
                    else:
                        text = msg.TRAINER_BOOKING_NOTIFICATION_NO_COMMENT.format(
                            date=html_lib.escape(date_str),
                            day=html_lib.escape(dow),
                            time=html_lib.escape(time_str),
                            duration=duration,
                            client_name=html_lib.escape(client_name),
                            phone=html_lib.escape(phone),
                            service=html_lib.escape(service),
                            city=html_lib.escape(city),
                            arenas=html_lib.escape(arenas),
                            tariff=html_lib.escape(tariff_display),
                        )
                    if b.get("is_first_client_online_booking"):
                        text = msg.TRAINER_FIRST_ONLINE_BOOKING_NOTIFICATION_PREFIX + text
                    kb = _booking_pending_notify_keyboard(int(b["id"]), client_tid=b.get("client_telegram_id"), trainer_tid=int(trainer_tid))
                    kb_confirm_decline_only = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=msg.TRAINER_BOOKINGS_BUTTON_CONFIRM,
                                    callback_data=f"confirm_booking:{b['id']}",
                                ),
                                InlineKeyboardButton(
                                    text=msg.TRAINER_BOOKINGS_BUTTON_DECLINE,
                                    callback_data=f"decline_booking:{b['id']}",
                                ),
                            ],
                        ]
                    )
                    delivered = await _deliver_trainer_booking_pending_notification(
                        trainer_bot,
                        chat_id=int(trainer_tid),
                        text=text,
                        markup_full=kb,
                        markup_confirm_decline_only=kb_confirm_decline_only,
                        booking_id=int(b["id"]),
                        trainer_db_id=int(b["trainer_id"]),
                        client_tid=b.get("client_telegram_id"),
                    )
                    if delivered:
                        await mark_booking_notified(session, b["id"])

                remind_candidates = await list_bookings_pending_confirm_reminder(session)
                for r in remind_candidates:
                    if not await is_trainer_push_allowed_now(session, int(r["trainer_id"])):
                        continue
                    trainer_tid = await get_trainer_telegram_id(
                        session, r["trainer_id"]
                    )
                    if not trainer_tid:
                        await mark_confirm_reminder_sent(session, r["booking_id"])
                        continue
                    d2 = r["slot_date"]
                    date_str2 = d2.strftime("%d.%m") if hasattr(d2, "strftime") else str(d2)
                    dow2 = msg.TRAINER_DAYS[d2.weekday()] if hasattr(d2, "weekday") else ""
                    start_time2 = r["start_time"]
                    time_str2 = (
                        start_time2.strftime("%H:%M")
                        if hasattr(start_time2, "strftime")
                        else str(start_time2)[:5]
                    )
                    cn_rem = (r.get("client_name") or "").strip()
                    ph_rem = (r.get("client_phone") or "").strip()
                    if cn_rem and ph_rem:
                        client_display = f"{cn_rem} ({ph_rem})"
                    elif cn_rem:
                        client_display = cn_rem
                    else:
                        client_display = ph_rem or "клиент"
                    text2 = msg.TRAINER_BOOKING_CONFIRM_REMINDER.format(
                        client_display=html_lib.escape(str(client_display)),
                        date=html_lib.escape(date_str2),
                        day=html_lib.escape(dow2),
                        time=html_lib.escape(time_str2),
                    )
                    row_confirm = [
                        InlineKeyboardButton(
                            text=msg.TRAINER_BOOKINGS_BUTTON_CONFIRM,
                            callback_data=f"confirm_booking:{r['booking_id']}",
                        ),
                        InlineKeyboardButton(
                            text=msg.TRAINER_BOOKINGS_BUTTON_DECLINE,
                            callback_data=f"decline_booking:{r['booking_id']}",
                        ),
                    ]
                    rows2: list[list[InlineKeyboardButton]] = [row_confirm]
                    ctid_rem = r.get("client_telegram_id")
                    relay_self_rem = bool(Settings().trainer_booking_self_client_relay_button)
                    if ctid_rem and _client_telegram_ok_for_write_button(ctid_rem, int(trainer_tid)):
                        rows2.append(
                            [
                                InlineKeyboardButton(
                                    text=msg.TRAINER_BOOKING_CONFIRMED_BTN_WRITE,
                                    url=f"tg://user?id={int(ctid_rem)}",
                                ),
                            ],
                        )
                    elif ctid_rem and relay_self_rem and _same_person_client_as_trainer(ctid_rem, int(trainer_tid)):
                        rows2.append(
                            [
                                InlineKeyboardButton(
                                    text=msg.TRAINER_BOOKING_CONFIRMED_BTN_WRITE,
                                    callback_data=f"{BOOKING_NOTIFY_RELAY_WRITE_PREFIX}{r['booking_id']}",
                                ),
                            ],
                        )
                    kb2 = InlineKeyboardMarkup(inline_keyboard=rows2)
                    kb2_confirm_only = InlineKeyboardMarkup(inline_keyboard=[row_confirm])
                    reminder_ok = await _deliver_trainer_confirm_reminder_notification(
                        trainer_bot,
                        chat_id=int(trainer_tid),
                        text=text2,
                        markup_full=kb2,
                        markup_confirm_only=kb2_confirm_only,
                        booking_id=int(r["booking_id"]),
                        trainer_db_id=int(r["trainer_id"]),
                        client_tid=r.get("client_telegram_id"),
                    )
                    if reminder_ok:
                        await mark_confirm_reminder_sent(session, r["booking_id"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Booking notifier: %s", e)


async def run_request_notifier_loop(trainer_bot: Bot) -> None:
    while True:
        await asyncio.sleep(REQUEST_NOTIFIER_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                await process_request_notifications_batch(trainer_bot, session)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Request notifier: %s", e)


async def run_completed_feedback_loop(trainer_bot: Bot) -> None:
    while True:
        await asyncio.sleep(COMPLETED_FEEDBACK_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                await process_completed_feedback_batch(trainer_bot, session)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Completed feedback loop: %s", e)


async def run_subscription_expire_and_reminder_loop(trainer_bot: Bot) -> None:
    """Once per day: expire past subscriptions, then run the trial conversion cadence + paid billing reminder.

    Trial conversion cadence (per trainer, in chronological order):
      • D-2 — ROI recap (mental anchoring of value already received, no CTA)
      • D-1 — loss reminder (decision ask + what stops tomorrow, CTA enabled)
      • D+0 — graceful downgrade is owned by the Lead Mode recovery series, see
        ``run_lead_mode_recovery_loop`` (also handles D+3 / D+14 / D+30 with demand-numbers
        loss framing).

    Paid plans keep a separate billing reminder (default D-3) using ``subscription_reminder_days_ahead``.
    Trial cadence offsets are configured via ``trial_roi_recap_days_ahead`` and
    ``subscription_reminder_trial_days_ahead`` so cadences cannot poach each other.

    Work runs first on startup, then after each ``notification_subscription_loop_interval_sec`` sleep
    (default 24h; lower locally via Settings / env for debugging).
    """
    while True:
        try:
            async with async_session_factory() as session:
                # 1) Expire subscriptions that passed expires_at — pure state transition;
                #    the recovery loop will pick them up as Lead Mode candidates and send D+0.
                expired_rows = await expire_subscriptions_to_past_due(session)
                if expired_rows:
                    logger.info(
                        "Subscription expire: %d set to past_due (recovery series will pick up D+0)",
                        len(expired_rows),
                    )
                # 1b) Expire certificates past expires_at (issued/activated -> expired)
                cert_n = await expire_certificates_past_expiry(session)
                if cert_n:
                    logger.info("Certificate expire: %d set to expired", cert_n)
                # Trial conversion cadence: D-2 ROI anchor → D-1 loss reminder → D+0 graceful downgrade
                # (handled by the Lead Mode recovery loop, not here).
                settings = Settings()
                paid_days_ahead = max(1, settings.subscription_reminder_days_ahead)
                trial_days_ahead = max(1, settings.subscription_reminder_trial_days_ahead)
                # ROI window must end strictly after the trial loss-reminder window so D-2 fires before D-1.
                roi_days_ahead = max(trial_days_ahead + 1, settings.trial_roi_recap_days_ahead)
                base = (settings.webapp_base_url or "").rstrip("/")
                subscription_webapp_url = (
                    base + "/webapp/trainer-subscription?v=20260450" if base else None
                )
                webapp_kb_available = bool(
                    subscription_webapp_url and base.lower().startswith("https://")
                )

                def _build_subscription_kb() -> InlineKeyboardMarkup | None:
                    if not webapp_kb_available:
                        return None
                    return InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=msg.TRAINER_SUBSCRIPTION_PUSH_BTN_WEBAPP,
                                    web_app=WebAppInfo(url=subscription_webapp_url),
                                ),
                            ],
                        ]
                    )

                # 2) D-2: Trial ROI recap — facts about value already received. NO CTA: pure mental anchoring.
                trial_roi_due = await list_trial_roi_recap_due(
                    session,
                    roi_days_ahead=roi_days_ahead,
                    final_reminder_days_ahead=trial_days_ahead,
                )
                for sub in trial_roi_due:
                    if not await is_trainer_push_allowed_now(session, int(sub["trainer_id"])):
                        continue
                    tid = sub.get("trainer_telegram_id")
                    if not tid:
                        continue
                    expires_at = sub.get("expires_at")
                    expires_date = (
                        expires_at.strftime("%d.%m.%Y")
                        if hasattr(expires_at, "strftime")
                        else str(expires_at)[:10]
                    )
                    now_utc = datetime.now(timezone.utc)
                    if hasattr(expires_at, "tzinfo"):
                        delta_seconds = (expires_at - now_utc).total_seconds()
                        # Round up so the trainer never reads "1 день" while still inside D-2 window.
                        days_until_expiry = max(1, math.ceil(delta_seconds / 86400.0))
                    else:
                        days_until_expiry = roi_days_ahead
                    period_end = now_utc
                    period_start = sub.get("started_at") or (period_end - timedelta(days=14))
                    recap = await get_trial_roi_recap(
                        session,
                        trainer_id=int(sub["trainer_id"]),
                        period_start=period_start,
                        period_end=period_end,
                    )
                    text = msg.format_trainer_trial_roi_recap_html(
                        recap=recap,
                        expires_date=expires_date,
                        days_until_expiry=days_until_expiry,
                    )
                    try:
                        # No reply_markup on D-2 by design: the goal is anchoring, not the click.
                        # The decision ask comes on D-1 below.
                        await trainer_bot.send_message(chat_id=tid, text=text)
                        await mark_trial_roi_recap_sent(session, sub["id"])
                    except Exception as e:
                        logger.warning(
                            "Trial ROI recap to trainer %s (sub id=%s): %s",
                            tid,
                            sub.get("id"),
                            e,
                        )

                # 3) D-1: trial loss reminder — decision ask, what stops tomorrow. With CTA.
                trial_due = await get_subscriptions_reminder_due(
                    session,
                    days_ahead=trial_days_ahead,
                    statuses=(SUBSCRIPTION_STATUS_TRIAL,),
                )
                for sub in trial_due:
                    if not await is_trainer_push_allowed_now(session, int(sub["trainer_id"])):
                        continue
                    tid = sub.get("trainer_telegram_id")
                    if not tid:
                        continue
                    expires_at = sub.get("expires_at")
                    expires_date = (
                        expires_at.strftime("%d.%m.%Y")
                        if hasattr(expires_at, "strftime")
                        else str(expires_at)[:10]
                    )
                    text = msg.TRAINER_SUBSCRIPTION_REMINDER_TRIAL.format(expires_date=expires_date)
                    try:
                        await trainer_bot.send_message(
                            chat_id=tid,
                            text=text,
                            reply_markup=_build_subscription_kb(),
                        )
                        await mark_subscription_reminder_sent(session, sub["id"])
                    except Exception as e:
                        logger.warning(
                            "Trial loss reminder to trainer %s (sub id=%s): %s",
                            tid,
                            sub.get("id"),
                            e,
                        )

                # 4) Paid billing reminder — kept on its own cadence (default D-3) and own status filter.
                paid_due = await get_subscriptions_reminder_due(
                    session,
                    days_ahead=paid_days_ahead,
                    statuses=(SUBSCRIPTION_STATUS_ACTIVE,),
                )
                for sub in paid_due:
                    if not await is_trainer_push_allowed_now(session, int(sub["trainer_id"])):
                        continue
                    tid = sub.get("trainer_telegram_id")
                    if not tid:
                        continue
                    expires_at = sub.get("expires_at")
                    expires_date = (
                        expires_at.strftime("%d.%m.%Y")
                        if hasattr(expires_at, "strftime")
                        else str(expires_at)[:10]
                    )
                    text = msg.TRAINER_SUBSCRIPTION_REMINDER.format(expires_date=expires_date)
                    try:
                        await trainer_bot.send_message(
                            chat_id=tid,
                            text=text,
                            reply_markup=_build_subscription_kb(),
                        )
                        await mark_subscription_reminder_sent(session, sub["id"])
                    except Exception as e:
                        logger.warning(
                            "Paid subscription reminder to trainer %s (sub id=%s): %s",
                            tid,
                            sub.get("id"),
                            e,
                        )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Subscription expire/reminder loop: %s", e)
        await asyncio.sleep(_subscription_loop_interval_sec())


def _render_recovery_signals_line(*, views: int, clicks: int, favorites: int) -> str:
    """Pure: build the loss-framing sentence from real demand counts. Empty string if no demand."""
    parts: list[str] = []
    if views > 0 and clicks > 0:
        parts.append(msg.TRAINER_LEAD_MODE_SIGNALS_BOTH.format(views=views, clicks=clicks))
    elif views > 0:
        parts.append(msg.TRAINER_LEAD_MODE_SIGNALS_VIEWS_ONLY.format(views=views))
    if favorites > 0:
        parts.append(msg.TRAINER_LEAD_MODE_SIGNALS_FAVORITES.format(favorites=favorites))
    return "".join(parts) if parts else msg.TRAINER_LEAD_MODE_SIGNALS_NONE


def _render_recovery_text(nudge: DueRecoveryNudge, *, was_trial: bool) -> str:
    """Pure: pick the right template for this step + inject demand numbers (loss framing)."""
    signals_line = _render_recovery_signals_line(
        views=nudge.signals.profile_views,
        clicks=nudge.signals.contact_clicks,
        favorites=nudge.signals.catalog_favorites,
    )
    if nudge.step == RECOVERY_STEP_D0:
        # D+0 has no loss framing yet — nothing has accumulated in lead mode.
        return (
            msg.TRAINER_LEAD_MODE_RECOVERY_D0_TRIAL
            if was_trial
            else msg.TRAINER_LEAD_MODE_RECOVERY_D0_PAID
        )
    if nudge.step == RECOVERY_STEP_D3:
        return msg.TRAINER_LEAD_MODE_RECOVERY_D3.format(signals_line=signals_line)
    if nudge.step == RECOVERY_STEP_D14:
        return msg.TRAINER_LEAD_MODE_RECOVERY_D14.format(signals_line=signals_line)
    if nudge.step == RECOVERY_STEP_D30:
        return msg.TRAINER_LEAD_MODE_RECOVERY_D30.format(signals_line=signals_line)
    raise ValueError(f"Unknown recovery step: {nudge.step!r}")


async def _was_last_subscription_a_trial(
    session: AsyncSession, trainer_id: int
) -> bool:
    """D+0 copy: use plan.is_trial so rows already moved to past_due still get trial wording."""
    from sqlalchemy import text as _t

    r = await session.execute(
        _t(
            """
            SELECT COALESCE(sp.is_trial, false)
            FROM trainer_subscriptions ts
            JOIN subscription_plans sp ON sp.id = ts.plan_id
            WHERE ts.trainer_id = :tid
            ORDER BY ts.expires_at DESC
            LIMIT 1
            """
        ),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    return bool(row and row[0])


async def run_lead_mode_recovery_loop(trainer_bot: Bot) -> None:
    """
    Once per day: send the next due Lead Mode recovery nudge (D+0/D+3/D+14/D+30) to each
    trainer currently in LEAD_MODE that hasn't received it yet.

    Idempotency boundary: trainer_recovery_nudges (UNIQUE on trainer_id+step). Cancel-on-payment is
    implicit — trainers who reactivate disappear from `compute_due_nudges` candidate list.

    Work runs first on startup, then after each ``notification_lead_mode_recovery_interval_sec`` sleep.
    """
    while True:
        try:
            async with async_session_factory() as session:
                due_list = await compute_due_nudges(session)
                if due_list:
                    logger.info("Lead Mode recovery: %d due nudges", len(due_list))

                    base = (Settings().webapp_base_url or "").rstrip("/")
                    webapp_url = (
                        base + "/webapp/trainer-subscription?v=20260509"
                        if base and base.lower().startswith("https://")
                        else None
                    )
                    kb: InlineKeyboardMarkup | None = None
                    if webapp_url:
                        kb = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text=msg.TRAINER_SUBSCRIPTION_PUSH_BTN_WEBAPP,
                                        web_app=WebAppInfo(url=webapp_url),
                                    )
                                ]
                            ]
                        )

                    for nudge in due_list:
                        try:
                            if not await is_trainer_push_allowed_now(
                                session, nudge.trainer_id
                            ):
                                # Quiet hours / opt-out — skip this tick; the step stays "due" and will
                                # fire next day. After 30 days we cap at D+30 forever (idempotent).
                                continue
                            was_trial = (
                                await _was_last_subscription_a_trial(
                                    session, nudge.trainer_id
                                )
                                if nudge.step == RECOVERY_STEP_D0
                                else False
                            )
                            text_msg = _render_recovery_text(nudge, was_trial=was_trial)
                            await trainer_bot.send_message(
                                chat_id=nudge.trainer_telegram_id,
                                text=text_msg,
                                reply_markup=kb,
                                parse_mode="HTML",
                            )
                            # Persist after successful send so a Telegram error retries the step tomorrow.
                            await mark_nudge_sent(
                                session,
                                trainer_id=nudge.trainer_id,
                                step=nudge.step,
                                expires_at_anchor=nudge.last_expires_at,
                            )
                        except Exception as e:
                            logger.warning(
                                "Lead Mode recovery nudge failed (trainer=%s, step=%s): %s",
                                nudge.trainer_id,
                                nudge.step,
                                e,
                            )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Lead Mode recovery loop: %s", e)
        await asyncio.sleep(_lead_mode_recovery_loop_interval_sec())


_ONBOARDING_STAGE_BODY: dict[str, str] = {
    STAGE_EMPTY_FORM: msg.TRAINER_ONBOARDING_STAGE_EMPTY_FORM,
    STAGE_NOT_SUBMITTED: msg.TRAINER_ONBOARDING_STAGE_NOT_SUBMITTED,
    STAGE_REJECTED_RESUBMIT: msg.TRAINER_ONBOARDING_STAGE_REJECTED_RESUBMIT,
    STAGE_NO_BOOKING: msg.TRAINER_ONBOARDING_STAGE_NO_BOOKING,
}

_ONBOARDING_STEP_INTRO: dict[str, str] = {
    ONBOARDING_NUDGE_STEP_D1: msg.TRAINER_ONBOARDING_NUDGE_INTRO_D1,
    ONBOARDING_NUDGE_STEP_D3: msg.TRAINER_ONBOARDING_NUDGE_INTRO_D3,
    ONBOARDING_NUDGE_STEP_D7: msg.TRAINER_ONBOARDING_NUDGE_INTRO_D7,
}


def _render_onboarding_nudge_text(
    nudge: DueOnboardingNudge, *, trial_days_remaining: int | None
) -> str:
    """Pure: step intro + stage-specific body naming the concrete next action + trial urgency."""
    intro = _ONBOARDING_STEP_INTRO.get(nudge.step)
    if intro is None:
        raise ValueError(f"Unknown onboarding nudge step: {nudge.step!r}")

    if nudge.stage == STAGE_MISSING_FIELD:
        missing = ", ".join(nudge.missing_labels_ru) or "оставшиеся поля анкеты"
        body = msg.TRAINER_ONBOARDING_STAGE_MISSING_FIELD.format(missing=missing)
    else:
        body = _ONBOARDING_STAGE_BODY.get(nudge.stage)
        if body is None:
            raise ValueError(f"Unknown onboarding stage: {nudge.stage!r}")

    trial_suffix = ""
    if trial_days_remaining is not None and trial_days_remaining <= TRIAL_URGENCY_THRESHOLD_DAYS:
        trial_suffix = (
            msg.TRAINER_ONBOARDING_TRIAL_LAST_DAY
            if trial_days_remaining <= 0
            else msg.TRAINER_ONBOARDING_TRIAL_DAYS_LEFT.format(days=trial_days_remaining)
        )

    return intro + body + trial_suffix + msg.TRAINER_ONBOARDING_NUDGE_OUTRO


async def run_onboarding_reactivation_loop(trainer_bot: Bot) -> None:
    """
    Once per day: send the next due onboarding-reactivation nudge (D+1/D+3/D+7) to each
    telegram-linked trainer who stalled before finishing onboarding.

    Idempotency boundary: trainer_onboarding_nudges (UNIQUE on trainer_id+step). Cancel-on-progress
    is implicit — trainers who finish the relevant step disappear from the candidate list.

    Work runs first on startup, then after each ``notification_onboarding_reactivation_interval_sec`` sleep.
    """
    while True:
        try:
            async with async_session_factory() as session:
                due_list = await compute_due_onboarding_nudges(session)
                if due_list:
                    logger.info("Onboarding reactivation: %d due nudges", len(due_list))
                for nudge in due_list:
                    try:
                        if not await is_trainer_push_allowed_now(session, nudge.trainer_id):
                            # Quiet hours / opt-out — skip this tick; the step stays "due" and will
                            # fire next day. After D+7 we cap there forever (idempotent).
                            continue
                        trial_days_remaining = await get_trial_days_remaining(
                            session, nudge.trainer_id
                        )
                        text_msg = _render_onboarding_nudge_text(
                            nudge, trial_days_remaining=trial_days_remaining
                        )
                        await trainer_bot.send_message(
                            chat_id=nudge.trainer_telegram_id,
                            text=text_msg,
                            parse_mode="HTML",
                        )
                        # Persist after successful send so a Telegram error retries the step tomorrow.
                        await mark_onboarding_nudge_sent(
                            session,
                            trainer_id=nudge.trainer_id,
                            step=nudge.step,
                            stage_anchor=nudge.stage,
                        )
                    except Exception as e:
                        logger.warning(
                            "Onboarding reactivation nudge failed (trainer=%s, step=%s): %s",
                            nudge.trainer_id,
                            nudge.step,
                            e,
                        )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Onboarding reactivation loop: %s", e)
        await asyncio.sleep(_onboarding_reactivation_loop_interval_sec())


async def run_recurring_materialization_loop() -> None:
    """
    Periodically prune over-materialized futures and fill gaps inside
    ``recurring_materialization_horizon_weeks`` (rolling from this Monday; CRM tier only).
    """
    from sqlalchemy import text

    from src.application.recurring_use_cases import maintain_recurring_horizon

    while True:
        await asyncio.sleep(_recurring_materialization_loop_interval_sec())
        try:
            async with async_session_factory() as session:
                r = await session.execute(
                    text(
                        """
                        SELECT DISTINCT trainer_id FROM recurring_client_slots
                        WHERE status = 'active'
                        """
                    )
                )
                tids = [int(row[0]) for row in r.fetchall()]
                created_total = 0
                pruned_total = 0
                for tid in tids:
                    out = await maintain_recurring_horizon(
                        session,
                        tid,
                        horizon_weeks=Settings().recurring_materialization_horizon_weeks,
                        recurring_ids=None,
                    )
                    created_total += int(out.get("created") or 0)
                    pruned_total += int(out.get("pruned") or 0)
                if created_total or pruned_total:
                    logger.info(
                        "Recurring horizon: created=%s pruned=%s",
                        created_total,
                        pruned_total,
                    )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Recurring materialization loop: %s", e)


async def run_certificate_email_outbox_loop() -> None:
    """Every 2 min: process certificate_email_outbox (retry failed sends)."""
    while True:
        await asyncio.sleep(CERTIFICATE_OUTBOX_INTERVAL_SEC)
        try:
            async with async_session_factory() as session:
                n = await process_certificate_email_outbox_batch(session, limit=20)
                if n:
                    logger.info("Certificate email outbox: %d processed", n)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Certificate email outbox loop: %s", e)


# =============================================================================
# Morning + weekly digest ritual
# =============================================================================

_DIGEST_KIND_DAILY = "daily"
_DIGEST_KIND_WEEKLY = "weekly"


def _digest_overview_keyboard() -> "InlineKeyboardMarkup | None":
    """CTA 'Обзор' opens trainer hub (rhythm hints live there). None if webapp not configured."""
    base = (Settings().webapp_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_MENU_BUTTON_HUB,
                    web_app=WebAppInfo(url=f"{base}/webapp/trainer-home"),
                )
            ]
        ]
    )


async def _mark_digest_sent(
    session: AsyncSession, trainer_id: int, sent_date: date, kind: str
) -> None:
    """Idempotent insert into trainer_digest_sent (once per trainer-date-kind)."""
    from sqlalchemy import text as _text

    await session.execute(
        _text(
            """
            INSERT INTO trainer_digest_sent (trainer_id, sent_date, kind)
            VALUES (:tid, :d, :k)
            ON CONFLICT (trainer_id, sent_date, kind) DO NOTHING
            """
        ),
        {"tid": trainer_id, "d": sent_date, "k": kind},
    )
    await session.commit()


async def _list_digest_candidates_for_kind(
    session: AsyncSession, today_minsk: date, kind: str
) -> list[dict]:
    """
    Trainers eligible for today's digest (kind='daily' or 'weekly'):
    digest_enabled + telegram set + active + haven't received this kind today yet.
    Returns id, telegram_id, digest_send_time, push_notification_start_hour,
    push_notification_end_hour; caller resolves send_at + decides firing.
    """
    from sqlalchemy import text as _text

    r = await session.execute(
        _text(
            """
            SELECT t.id,
                   t.telegram_id,
                   t.digest_send_time,
                   t.push_notification_start_hour,
                   t.push_notification_end_hour
            FROM trainers t
            LEFT JOIN trainer_digest_sent ds
                ON ds.trainer_id = t.id
               AND ds.sent_date = :d
               AND ds.kind = :k
            WHERE t.digest_enabled = true
              AND t.telegram_id IS NOT NULL
              AND t.status = 'active'
              AND ds.id IS NULL
            """
        ),
        {"d": today_minsk, "k": kind},
    )
    rows = r.fetchall()
    return [
        {
            "trainer_id": int(row[0]),
            "telegram_id": int(row[1]),
            "digest_send_time": row[2],
            "push_window_start_hour": row[3],
            "push_window_end_hour": row[4],
        }
        for row in rows
    ]


def _time_diff_minutes(a: "time", b: "time") -> int:
    """a - b in minutes (walltime, ignoring date). Negative when a precedes b."""
    return (a.hour * 60 + a.minute) - (b.hour * 60 + b.minute)


async def run_daily_morning_digest_loop(trainer_bot: Bot) -> None:
    """
    Ticks every DIGEST_LOOP_INTERVAL_SEC. For each enabled trainer whose resolved send_at
    falls in ``[send_at, send_at + DIGEST_SEND_GRACE_MIN)`` Minsk-time window today AND who
    hasn't yet received today's digest, compute the aggregator and fire a message with an
    'Обзор' CTA to trainer-home.

    Suppression rules:
      - 0 sessions today AND 0 pending requests → stay silent.
      - 0 sessions today AND ≥1 pending catalog request → send a lite digest (owed line only).
      - ≥1 session today → send the full run-sheet.
    """
    from src.application.trainer_digest_use_cases import (
        get_trainer_daily_digest,
        now_minsk,
        resolve_digest_send_time,
    )
    from src.application.trainer_notification_prefs import (
        get_trainer_push_window_bounds,
    )
    from src.bot.trainer_digest_format import (
        format_morning_digest,
        format_morning_digest_lite_owed_only,
    )

    while True:
        try:
            now = now_minsk()
            today = now.date()
            now_t = now.time().replace(second=0, microsecond=0)

            async with async_session_factory() as session:
                candidates = await _list_digest_candidates_for_kind(
                    session, today, _DIGEST_KIND_DAILY
                )

                for cand in candidates:
                    tid = cand["trainer_id"]
                    tg = cand["telegram_id"]
                    try:
                        if cand["push_window_start_hour"] is not None and cand["push_window_end_hour"] is not None:
                            start_h = int(cand["push_window_start_hour"])
                            end_h = int(cand["push_window_end_hour"])
                        else:
                            start_h, end_h = await get_trainer_push_window_bounds(session, tid)

                        digest = await get_trainer_daily_digest(session, tid, today)

                        has_sessions = digest["sessions_count"] > 0
                        has_owed = digest["pending_requests_count"] > 0

                        send_at = resolve_digest_send_time(
                            digest_send_time=cand["digest_send_time"],
                            first_session_start=digest["first_session_start"],
                            push_window_start_hour=start_h,
                            push_window_end_hour=end_h,
                        )

                        if send_at is None:
                            continue

                        if not has_sessions and not has_owed:
                            continue

                        delta = _time_diff_minutes(now_t, send_at)
                        if delta < 0 or delta >= DIGEST_SEND_GRACE_MIN:
                            continue

                        if has_sessions:
                            text_body = format_morning_digest(digest, wall_time=now_t)
                        else:
                            lite = format_morning_digest_lite_owed_only(
                                digest, wall_time=now_t
                            )
                            if not lite:
                                continue
                            text_body = lite

                        kb = _digest_overview_keyboard()
                        try:
                            await trainer_bot.send_message(
                                chat_id=tg,
                                text=text_body,
                                parse_mode="HTML",
                                reply_markup=kb,
                                disable_web_page_preview=True,
                            )
                            await _mark_digest_sent(session, tid, today, _DIGEST_KIND_DAILY)
                        except Exception as e:
                            logger.warning(
                                "Morning digest to trainer %s (id=%s): %s", tg, tid, e
                            )
                    except Exception as e:
                        logger.exception(
                            "Morning digest eval for trainer id=%s: %s", tid, e
                        )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Morning digest loop: %s", e)

        try:
            await asyncio.sleep(DIGEST_LOOP_INTERVAL_SEC)
        except asyncio.CancelledError:
            break


async def run_weekly_sunday_digest_loop(trainer_bot: Bot) -> None:
    """
    Ticks every DIGEST_LOOP_INTERVAL_SEC, but only acts on Sundays. Sends the weekly digest in the
    evening (default 20:00 Minsk), independent of digest_send_time (which schedules only the daily digest).
    """
    from src.application.trainer_digest_use_cases import (
        get_trainer_weekly_digest,
        now_minsk,
        resolve_weekly_digest_send_time,
    )
    from src.application.trainer_notification_prefs import (
        get_trainer_push_window_bounds,
    )
    from src.bot.trainer_digest_format import format_weekly_digest

    while True:
        try:
            now = now_minsk()
            today = now.date()
            now_t = now.time().replace(second=0, microsecond=0)

            if today.weekday() != 6:  # 6 = Sunday
                await asyncio.sleep(DIGEST_LOOP_INTERVAL_SEC)
                continue

            async with async_session_factory() as session:
                candidates = await _list_digest_candidates_for_kind(
                    session, today, _DIGEST_KIND_WEEKLY
                )

                for cand in candidates:
                    tid = cand["trainer_id"]
                    tg = cand["telegram_id"]
                    try:
                        if cand["push_window_start_hour"] is not None and cand["push_window_end_hour"] is not None:
                            start_h = int(cand["push_window_start_hour"])
                            end_h = int(cand["push_window_end_hour"])
                        else:
                            start_h, end_h = await get_trainer_push_window_bounds(session, tid)

                        send_at = resolve_weekly_digest_send_time(
                            push_window_start_hour=start_h,
                            push_window_end_hour=end_h,
                        )

                        delta = _time_diff_minutes(now_t, send_at)
                        if delta < 0 or delta >= DIGEST_SEND_GRACE_MIN:
                            continue

                        weekly = await get_trainer_weekly_digest(session, tid, today)
                        text_body = format_weekly_digest(weekly)

                        kb = _digest_overview_keyboard()
                        try:
                            await trainer_bot.send_message(
                                chat_id=tg,
                                text=text_body,
                                parse_mode="HTML",
                                reply_markup=kb,
                                disable_web_page_preview=True,
                            )
                            await _mark_digest_sent(session, tid, today, _DIGEST_KIND_WEEKLY)
                        except Exception as e:
                            logger.warning(
                                "Weekly digest to trainer %s (id=%s): %s", tg, tid, e
                            )
                    except Exception as e:
                        logger.exception(
                            "Weekly digest eval for trainer id=%s: %s", tid, e
                        )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Weekly digest loop: %s", e)

        try:
            await asyncio.sleep(DIGEST_LOOP_INTERVAL_SEC)
        except asyncio.CancelledError:
            break


def _care_pulse_trainer_keyboard() -> InlineKeyboardMarkup | None:
    """Single CTA into trainer hub. None if webapp is not HTTPS."""
    base = (Settings().webapp_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_MENU_BUTTON_HUB,
                    web_app=WebAppInfo(url=f"{base}/webapp/trainer-home"),
                )
            ]
        ]
    )


def _care_pulse_client_keyboard(kind: str) -> InlineKeyboardMarkup | None:
    from src.infrastructure.db.models import CARE_PULSE_KIND_INVITE_BACK

    base = (Settings().webapp_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    if kind == CARE_PULSE_KIND_INVITE_BACK:
        url = f"{base}/webapp/catalog"
        label = msg.CARE_PULSE_CLIENT_BTN_CATALOG
    else:
        url = f"{base}/webapp/client-bookings"
        label = msg.CARE_PULSE_CLIENT_BTN_BOOKINGS
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))]
        ]
    )


async def run_care_pulse_loop(trainer_bot: Bot, client_bot: Bot) -> None:
    """
    Lunch-window presence check-in. Fills the quiet gap so bots stay in the chat
    without competing with digest / reminders / booking pushes.
    """
    from src.application.trainer_digest_use_cases import now_minsk
    from src.bot.care_pulse_format import format_care_pulse_html

    logger.info("[care_pulse_loop] started")
    while True:
        try:
            now = now_minsk()
            if is_within_care_pulse_window(now):
                async with async_session_factory() as session:
                    due = await list_due_care_pulses(session, now)
                    for pulse in due:
                        if pulse.audience == CARE_PULSE_AUDIENCE_TRAINER:
                            if not await is_trainer_push_allowed_now(session, pulse.recipient_id):
                                continue
                            bot = trainer_bot
                            kb = _care_pulse_trainer_keyboard()
                        elif pulse.audience == CARE_PULSE_AUDIENCE_CLIENT:
                            if not is_within_notification_hours():
                                continue
                            bot = client_bot
                            kb = _care_pulse_client_keyboard(pulse.kind)
                        else:
                            continue
                        text_body = format_care_pulse_html(
                            audience=pulse.audience,
                            kind=pulse.kind,
                            payload=pulse.payload,
                        )
                        if not text_body:
                            continue
                        claimed = await claim_care_pulse(
                            session,
                            audience=pulse.audience,
                            recipient_id=pulse.recipient_id,
                            kind=pulse.kind,
                            context_key=pulse.context_key,
                        )
                        if not claimed:
                            continue
                        try:
                            await bot.send_message(
                                chat_id=pulse.telegram_id,
                                text=text_body,
                                parse_mode="HTML",
                                reply_markup=kb,
                                disable_web_page_preview=True,
                            )
                        except Exception as e:
                            logger.warning(
                                "Care pulse %s to %s %s: %s",
                                pulse.kind,
                                pulse.audience,
                                pulse.telegram_id,
                                e,
                            )
        except asyncio.CancelledError:
            logger.info("[care_pulse_loop] cancelled")
            break
        except Exception as e:
            logger.exception("Care pulse loop: %s", e)

        try:
            await asyncio.sleep(CARE_PULSE_INTERVAL_SEC)
        except asyncio.CancelledError:
            break
