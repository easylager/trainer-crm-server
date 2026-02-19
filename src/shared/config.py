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
    # For client bot: API base (e.g. http://localhost:8000 or https://your-api.railway.app)
    api_base_url: str = "http://localhost:8000"
    # Optional: base URL for photos. If not set, bot uses api_base_url + /api/public/photos (backend proxies S3)
    photo_base_url: str | None = None
