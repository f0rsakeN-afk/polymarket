from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "Polymarket API"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://myuser:mypassword@localhost:5435/mydatabase"
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600

    # Redis
    redis_url: str = "redis://localhost:6382/0"
    redis_max_connections: int = 50

    # Resend
    resend_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
