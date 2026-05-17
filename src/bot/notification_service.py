"""
Notification service: standalone process that runs all notification loops.
Sends reminders, booking/cancel/complete/request notifications via client and trainer bots.
Run: python -m src.bot.notification_service

Control independently: start/stop this process; bots (client_app, trainer_app) only handle polling.
"""
import asyncio
import logging
import signal

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.bot.notification_loops import (
    run_booking_complete_loop,
    run_trainer_session_wrapup_loop,
    run_booking_notifier_loop,
    run_cancel_notifier_loop,
    run_certificate_email_outbox_loop,
    run_completed_feedback_loop,
    run_daily_morning_digest_loop,
    run_group_attendance_prompt_loop,
    run_inactive_client_loop,
    run_lead_mode_recovery_loop,
    run_no_response_reminder_loop,
    run_recurring_materialization_loop,
    run_reminder_loop,
    run_request_notifier_loop,
    run_response_notifier_loop,
    run_subscription_expire_and_reminder_loop,
    run_trainer_booked_notifier_loop,
    run_weekly_sunday_digest_loop,
)
from src.shared.config import Settings
from src.shared.notification_hours import set_notification_quiet_hours_bypass
from src.shared.sentry_init import init_sentry

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _configure_logging_from_settings(settings: Settings) -> None:
    """Honor LOG_LEVEL from Settings on root handlers (basicConfig runs before Settings load)."""
    level = getattr(logging, (settings.log_level or "INFO").strip().upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        handler.setLevel(level)


async def main() -> None:
    settings = Settings()
    _configure_logging_from_settings(settings)
    set_notification_quiet_hours_bypass(settings.notification_disable_quiet_hours)
    if settings.notification_disable_quiet_hours:
        logger.warning(
            "notification_disable_quiet_hours=True: pushes run 24/7 (no 08:00–22:00 Europe/Minsk pause). "
            "Unset NOTIFICATION_DISABLE_QUIET_HOURS and restart for normal behavior."
        )
    init_sentry(settings, "notification-service")
    logger.info(
        "Trainer booking Telegram delivery logs use prefixes booking_pending_notify_* / booking_confirm_reminder_* "
        "(telegram markup retries at DEBUG)."
    )
    client_bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    trainer_bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Client-facing loops
    client_tasks = [
        asyncio.create_task(run_reminder_loop(client_bot), name="reminder"),
        asyncio.create_task(run_group_attendance_prompt_loop(client_bot), name="group_attendance_rsvp"),
        asyncio.create_task(run_booking_complete_loop(client_bot, trainer_bot), name="booking_complete"),
        asyncio.create_task(run_cancel_notifier_loop(client_bot), name="cancel_notifier"),
        asyncio.create_task(run_response_notifier_loop(client_bot), name="response_notifier"),
        asyncio.create_task(run_no_response_reminder_loop(client_bot), name="no_response_reminder"),
        asyncio.create_task(run_trainer_booked_notifier_loop(client_bot), name="trainer_booked"),
        asyncio.create_task(run_inactive_client_loop(client_bot), name="inactive_client"),
    ]
    # Trainer-facing loops
    trainer_tasks = [
        asyncio.create_task(run_trainer_session_wrapup_loop(trainer_bot), name="trainer_session_wrapup"),
        asyncio.create_task(run_booking_notifier_loop(trainer_bot), name="booking_notifier"),
        asyncio.create_task(run_request_notifier_loop(trainer_bot), name="request_notifier"),
        asyncio.create_task(run_completed_feedback_loop(trainer_bot), name="completed_feedback"),
        # daily_request_reminder replaced by morning digest (lite when 0 sessions + open requests).
        asyncio.create_task(run_daily_morning_digest_loop(trainer_bot), name="daily_morning_digest"),
        asyncio.create_task(run_weekly_sunday_digest_loop(trainer_bot), name="weekly_sunday_digest"),
        asyncio.create_task(run_subscription_expire_and_reminder_loop(trainer_bot), name="subscription_expire_reminder"),
        asyncio.create_task(run_lead_mode_recovery_loop(trainer_bot), name="lead_mode_recovery"),
    ]
    # Background jobs (no bot)
    other_tasks = [
        asyncio.create_task(run_certificate_email_outbox_loop(), name="certificate_email_outbox"),
        asyncio.create_task(run_recurring_materialization_loop(), name="recurring_materialization"),
    ]
    all_tasks = client_tasks + trainer_tasks + other_tasks

    shutdown = asyncio.Event()

    def _on_shutdown(*_args: object) -> None:
        logger.info("Received shutdown signal, stopping notification service...")
        shutdown.set()

    try:
        signal.signal(signal.SIGINT, _on_shutdown)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _on_shutdown)
    except (ValueError, OSError):
        pass  # e.g. not main thread or Windows

    logger.info(
        "Notification service started (client=%s, trainer=%s, other=%s). Press Ctrl+C to stop.",
        len(client_tasks),
        len(trainer_tasks),
        len(other_tasks),
    )
    try:
        await shutdown.wait()
    finally:
        for t in all_tasks:
            t.cancel()
        await asyncio.gather(*all_tasks, return_exceptions=True)
        await client_bot.session.close()
        await trainer_bot.session.close()
        logger.info("Notification service stopped.")


if __name__ == "__main__":
    asyncio.run(main())
