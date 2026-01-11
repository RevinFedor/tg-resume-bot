import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Telegram Bot
    bot_token: str = os.getenv("BOT_TOKEN", "")

    # Telegram MTProto (for userbot)
    # Get from https://my.telegram.org/apps
    telegram_api_id: str = os.getenv("TELEGRAM_API_ID", "")
    telegram_api_hash: str = os.getenv("TELEGRAM_API_HASH", "")

    # Gemini
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")

    # OpenAI (for Whisper)
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")

    # Database
    database_url: str = os.getenv("DATABASE_URL", "")

    # Admin
    admin_password: str = os.getenv("ADMIN_PASSWORD", "admin123")
    secret_key: str = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")

    # Scheduler
    check_interval_minutes: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "5"))

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
