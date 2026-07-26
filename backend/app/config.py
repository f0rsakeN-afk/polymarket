from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "Polymarket API"
    debug: bool = False
    secret_key: str = "change-me-in-production"

    # CORS
    cors_origins: str = "*"  # comma-separated list of origins

    # Database
    database_url: str = "postgresql+asyncpg://myuser:mypassword@localhost:5435/mydatabase"
    database_replica_url: str = ""  # leave empty to use primary for reads
    db_pool_size: int = 50
    db_max_overflow: int = 30
    db_pool_timeout: int = 30  # seconds to wait for a connection from pool

    # Redis
    redis_url: str = "redis://localhost:6382/0"
    redis_max_connections: int = 100

    # JWT
    jwt_secret: str = "change-me-in-production"
    jwt_access_expire: int = 900
    jwt_refresh_expire: int = 604800

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # Celery
    celery_broker_url: str = "redis://localhost:6382/1"

    # Rate limiting
    rate_limit_enabled: bool = True

    # Resend (email notifications)
    resend_api_key: str = ""
    notifications_from_email: str = "noreply@polymarket.example.com"

    # Referral
    referral_reward_amount: float = 1.0

    @field_validator("database_url", "database_replica_url", mode="before")
    @classmethod
    def normalize_async_database_url(cls, value: str | None) -> str | None:
        if not value:
            return value
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value


settings = Settings()
