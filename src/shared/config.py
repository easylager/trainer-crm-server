"""
App settings loaded from env (.env + os.environ). Single entry point for config.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
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
    # Optional: one-time token for trainer link from site (dev stub; later from DB)
    trainer_link_token: str | None = None

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

    # Payment (bePaid): checkout token API. When not set, adapter returns stub URL for tests.
    bepaid_shop_id: str | None = None
    bepaid_secret_key: str | None = None
    # Checkout API base, e.g. https://checkout.bepaid.by (sandbox may differ)
    bepaid_checkout_base_url: str = "https://checkout.bepaid.by"
    payment_sandbox: bool = True

    # Group cohort RSVP: hours before slot to ask «Буду?» in client bot (disabled if unset or 0).
    group_attendance_prompt_hours: int | None = None

    # Trainer subscription: trial and reminders
    # Trial: if set, overrides DB platform_settings.welcome_trial_period_days and subscription_plans.period_days
    trial_period_days: int | None = None
    # Reminder: send "subscription ending soon" this many days before expires_at (default 3)
    subscription_reminder_days_ahead: int = 3

    # Client bot: username for deep links (e.g. t.me/<username>?start=cert_XXX). Required for certificate email links.
    client_bot_username: str | None = None
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
    trainer_bot_benchmark_log: bool = False
    # If set, also log WARNING for updates with total_ms >= threshold (can use without full log).
    trainer_bot_benchmark_slow_ms: int | None = None

    # Trainer webapp benchmark (FastAPI): logger ``trainer_webapp.bench``, grep ``BENCH trainer_webapp``.
    # Logs kind=api (trainer JSON API), kind=page (GET /webapp/* HTML), kind=asset (GET js/css/fonts/… under /webapp/ + /static/webapp/).
    trainer_webapp_benchmark_log: bool = False
    trainer_webapp_benchmark_slow_ms: int | None = None
