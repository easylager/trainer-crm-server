"""
App settings loaded from env (.env + os.environ). Single entry point for config.
"""
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_bool_benchmark(v: Any) -> bool:
    """Railway/hosting sometimes exposes flags as strings; accept common truthy tokens."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(v)


BenchmarkLogFlag = Annotated[bool, BeforeValidator(_env_bool_benchmark)]
NotificationQuietHoursBypassFlag = Annotated[bool, BeforeValidator(_env_bool_benchmark)]

# Trainer «подходит к концу»: уведомление когда до конца слота осталось 2–3 минуты (не зависит от длительности слота).
TRAINER_SESSION_WRAPUP_REMAINING_SEC_MIN = 120  # inclusive — не слать ближе чем за 2 минуты до конца
TRAINER_SESSION_WRAPUP_REMAINING_SEC_MAX = 180  # inclusive — не слать раньше чем за 3 минуты до конца
TRAINER_SESSION_WRAPUP_POLL_INTERVAL_SEC = 8


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Telegram: two bots in one repo (client + trainer), separate processes
    telegram_bot_token_client: str
    telegram_bot_token_trainer: str
    # Optional: admin bot for moderation (separate process, can be disabled if token is not set)
    telegram_bot_token_admin: str | None = None
    # Mini App initData: reject if auth_date is older than this (seconds). Telegram sends Unix time when the Web App was opened.
    telegram_webapp_init_data_max_age_sec: int = 86400
    # Allow initData auth_date slightly in the future (clock skew, seconds).
    telegram_webapp_init_data_clock_skew_sec: int = 300
    # Comma-separated list of admin telegram IDs, e.g. "123,456"
    admin_telegram_ids: list[int] | None = None
    # When True: no Telegram getChat to backfill `clients.telegram_username` (temporary QA for relay / no-@username DMs).
    disable_client_telegram_username_enrich: Annotated[bool, BeforeValidator(_env_bool_benchmark)] = False
    # When True: trainer hub «Написать» always opens bot relay (never t.me), for QA when DM is blocked but @ exists.
    trainer_webapp_force_client_chat_relay: Annotated[bool, BeforeValidator(_env_bool_benchmark)] = False
    # When True: booking/confirm-reminder pushes use relay callback «Написать» if client's telegram_id equals trainer's
    # (tg://user?id=self triggers BUTTON_USER_INVALID — relay works for local QA same-account client+trainer).
    trainer_booking_self_client_relay_button: Annotated[bool, BeforeValidator(_env_bool_benchmark)] = False
    # Optional: one-time token for trainer link from site (dev stub; later from DB)
    trainer_link_token: str | None = None
    # VK Mini Apps / MAX: "Защищённый ключ" for launch-params HMAC (omit until product enables MAX).
    vk_mini_app_protected_key: str | None = None

    # Database
    database_url: str = "postgresql+asyncpg://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm"
    database_url_sync: str | None = None

    # S3-compatible storage (Railway Buckets, MinIO, AWS, etc.)
    s3_endpoint: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "trainer-crm-uploads"
    s3_region: str = "auto"
    s3_path_style: bool = True  # Railway and MinIO use path-style URLs
    # If S3 not set: save to local dir (dev). Example: LOCAL_STORAGE_PATH=./uploads
    local_storage_path: str | None = None

    # App
    debug: bool = False
    log_level: str = "INFO"
    # HTTP API (FastAPI): sliding-window rate limit per client IP for /api/* (webhooks excluded).
    api_rate_limit_enabled: bool = True
    api_rate_limit_public_max_requests: int = 120
    api_rate_limit_public_window_sec: float = 60.0
    api_rate_limit_webapp_max_requests: int = 800
    api_rate_limit_webapp_window_sec: float = 60.0
    api_rate_limit_upload_max_requests: int = 60
    api_rate_limit_upload_window_sec: float = 60.0
    api_rate_limit_default_max_requests: int = 200
    api_rate_limit_default_window_sec: float = 60.0
    # Max request body when Content-Length is set (multipart without length passes through; use reverse proxy limits in prod).
    api_max_body_bytes_default: int = 1_048_576  # 1 MiB JSON / small bodies
    api_max_body_bytes_upload: int = 26_214_400  # ~25 MiB (trainer/client photo uploads)
    api_max_body_bytes_webhook: int = 2_097_152  # 2 MiB bePaid JSON
    # Audit log level (logger "audit"); INFO = emit, WARNING+ = suppress
    audit_log_level: str = "INFO"
    # Bot rate limit: max N updates per user per window (seconds)
    rate_limit_requests: int = 30
    rate_limit_window_sec: float = 60.0
    # For client bot: API base (e.g. http://localhost:8000 or https://your-api.railway.app)
    api_base_url: str = "http://localhost:8000"
    # Cooldown (minutes) before sending "у вас заявки в обработке" again after schedule change. 0 = every time (for testing).
    schedule_reminder_cooldown_minutes: int = 180
    # Optional: base URL for photos. If not set, bot uses api_base_url + /api/public/photos (backend proxies S3)
    photo_base_url: str | None = None
    # Presigned GET URL expiry for catalog photos (seconds). When S3 is used, API returns these URLs so client loads from S3 directly.
    photo_presigned_expires_sec: int = 3600
    # Presigned PUT for trainer photo direct upload (seconds); keep short to limit abuse window.
    photo_upload_presign_expires_sec: int = 600
    # If unset, POST /api/upload/photo and related legacy routes are disabled (use Web App initData flows).
    internal_upload_api_key: str | None = None
    # CDN base URL for photos (e.g. https://cdn.yourdomain.com or R2 public URL). When set, API returns photo URLs as {photo_cdn_base_url}/{file_key} instead of presigned S3; client loads from CDN.
    photo_cdn_base_url: str | None = None
    # Optional: Telegram ID to send test notifications (e.g. "inactive client" push scripts)
    notify_telegram_id: int | None = None
    # Base URL for Telegram Web App (trainer schedule). Must be HTTPS in production. Example: https://api.yoursite.com
    webapp_base_url: str = "http://localhost:8000"

    # Plain-text suffix for amounts in bots, Telegram HTML, and Mini App UI (default BYN per ISO 4217).
    byr_display_sign: str = "BYN"

    # Payment (bePaid): checkout token API. When not set, adapter returns stub URL for tests.
    bepaid_shop_id: str | None = None
    bepaid_secret_key: str | None = None
    # Checkout API base, e.g. https://checkout.bepaid.by (sandbox may differ)
    bepaid_checkout_base_url: str = "https://checkout.bepaid.by"
    payment_sandbox: bool = True
    # Trainer subscription Mini App: auto | sandbox | bepaid | invoice
    # auto = sandbox if payment_sandbox; elif bePaid shop+secret then bepaid; else invoice (ERIP / manual confirm).
    trainer_subscription_checkout_mode: str = "auto"
    # Optional: shown in Mini App when checkout is invoice (client escapes HTML).
    subscription_invoice_legal_name: str | None = None
    subscription_invoice_unp: str | None = None
    subscription_invoice_iban: str | None = None
    subscription_invoice_bank_hint_ru: str | None = None
    subscription_invoice_extra_hint_ru: str | None = None
    subscription_support_url: str | None = None
    # Collective studio pool: BYN cents per seat per month (× seat_limit × period_months).
    collective_subscription_cents_per_seat_month: int = 2900

    # Group cohort RSVP: hours before slot to ask «Буду?» in client bot (disabled if unset or 0).
    group_attendance_prompt_hours: int | None = None

    # notification_service only: if True, send user-facing Telegram pushes 24/7 (default window is 08:00–22:00 Europe/Minsk).
    notification_disable_quiet_hours: NotificationQuietHoursBypassFlag = False
    # notification_service: interval between subscription expire + pre-expiry reminder ticks (seconds). Default 86400 (1d). Set e.g. 10 locally to debug trial expiry / past_due; production should keep default.
    notification_subscription_loop_interval_sec: int = 86400
    # notification_service: interval between Lead Mode recovery (D+0..D+30) ticks. Default 86400. Set e.g. 10 locally; production should keep default.
    notification_lead_mode_recovery_interval_sec: int = 86400
    # notification_service: poll for slot end → auto-complete booking + client completion push. Clamped to 15–600 s in worker.
    booking_complete_poll_interval_sec: int = 60
    # Recurring «постоянный клиент»: ISO weeks ahead to keep filled (rolling window from this Monday).
    # Background loop + on «Сделать постоянным» top up toward this horizon; as weeks pass, new weeks enter the window.
    recurring_materialization_horizon_weeks: int = 3
    # notification_service: top up recurring auto-bookings toward the horizon (seconds). Default 6h.
    recurring_materialization_loop_interval_sec: int = 21600

    # Trainer subscription: trial and reminders
    # Trial: if set, overrides DB platform_settings.welcome_trial_period_days and subscription_plans.period_days
    trial_period_days: int | None = None
    # Paid subscriptions: classic billing reminder N days before expires_at (default 3).
    subscription_reminder_days_ahead: int = 3
    # Trial loss reminder (D-1): single push the day before trial expiry, framed as what stops tomorrow.
    # Lives in its own setting so trial cadence (D-2 ROI → D-1 loss → D+0 downgrade) stays independent
    # of paid billing cadence.
    subscription_reminder_trial_days_ahead: int = 1
    # Trial ROI recap (D-2 by default): send BEFORE the trial loss reminder so the trainer
    # first anchors value, then on D-1 receives a decision-focused loss-framing nudge.
    trial_roi_recap_days_ahead: int = 2

    # Client bot: username for deep links (e.g. t.me/<username>?start=cert_XXX). Required for certificate email links.
    client_bot_username: str | None = None
    # Gift certificate PDF: client-facing branding (instructions reference the Telegram mini-app paths below).
    certificate_pdf_brand_display_name: str = "ICE STUDIO"
    certificate_pdf_brand_tagline_ru: str = (
        "Мы — ваш сервис записи на тренировки: абонементы и подарочные сертификаты в одном приложении. "
        "Документ сформирован официально. Сохраните PDF — по нему вы всегда сможете найти код, если понадобится."
    )
    # Trainer bot: username for deep links (t.me/<username>?start=link_<token>). Used by admin /trainer_welcome_link.
    trainer_bot_username: str | None = None
    # SMTP for sending certificate link emails. When any is missing, email sending is disabled.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None

    # Sentry (https://sentry.io). When DSN is unset, SDK is not initialized.
    sentry_dsn: str | None = None
    sentry_environment: str | None = None
    sentry_release: str | None = None
    sentry_traces_sample_rate: float = 0.0
    sentry_profiles_sample_rate: float = 0.0
    # Optional deploy label for admin /version (e.g. Railway: set to RAILWAY_GIT_COMMIT_SHA).
    app_deploy_version: str | None = None

    # PRD E7: «Проблема с клиентом» — поэтапный rollout (Mini App + API).
    # off = выключено; pilot = только BOOKING_PROBLEM_PILOT_TRAINER_IDS; full = все тренеры.
    booking_problem_rollout: str = "full"
    # JSON-массив internal trainer_id, например [12, 34] — при rollout=pilot.
    booking_problem_pilot_trainer_ids: list[int] | None = None

    # Trainer bot: performance (logger ``trainer_bot.bench``, grep ``BENCH trainer_``).
    # Full log: every update + inner gate/menu DB phase timings.
    trainer_bot_benchmark_log: BenchmarkLogFlag = False
    # If set, also log WARNING for updates with total_ms >= threshold (can use without full log).
    trainer_bot_benchmark_slow_ms: int | None = None

    # Trainer webapp benchmark (FastAPI): grep ``BENCH trainer_webapp`` (middleware module logger).
    # Logs kind=api (trainer JSON API), kind=page (GET /webapp/* HTML), kind=asset (GET js/css/fonts/… under /webapp/ + /static/webapp/).
    # Env must be set on the API process (not the Telegram bot). Redeploy after changing Railway variables.
    trainer_webapp_benchmark_log: BenchmarkLogFlag = False
    trainer_webapp_benchmark_slow_ms: int | None = None

    def resolved_trainer_subscription_checkout_mode(self) -> Literal["sandbox", "bepaid", "invoice"]:
        """How trainer-subscription Mini App should behave for paid checkout."""
        m = (self.trainer_subscription_checkout_mode or "auto").strip().lower()
        if m in ("sandbox", "bepaid", "invoice"):
            return m  # type: ignore[return-value]
        if self.payment_sandbox:
            return "sandbox"
        if self.bepaid_shop_id and str(self.bepaid_shop_id).strip() and self.bepaid_secret_key and str(
            self.bepaid_secret_key
        ).strip():
            return "bepaid"
        return "invoice"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton — load .env once per worker (notification_service, bots, API)."""
    return Settings()
