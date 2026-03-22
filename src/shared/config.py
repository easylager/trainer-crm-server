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

    # Trainer subscription: trial and reminders
    # Trial: if set, overrides subscription_plans.period_days for the trial plan when creating trial
    trial_period_days: int | None = None
    # Reminder: send "subscription ending soon" this many days before expires_at (default 3)
    subscription_reminder_days_ahead: int = 3

    # Client bot: username for deep links (e.g. t.me/<username>?start=cert_XXX). Required for certificate email links.
    client_bot_username: str | None = None
    # SMTP for sending certificate link emails. When any is missing, email sending is disabled.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
