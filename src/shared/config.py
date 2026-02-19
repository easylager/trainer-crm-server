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

    # App
    debug: bool = False
    log_level: str = "INFO"
