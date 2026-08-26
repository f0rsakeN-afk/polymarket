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
    # Environment: development | staging | production
    # Controls OpenAPI docs visibility, HSTS, detailed error responses.
    # NEVER trust this for auth/security — use it only for UI/information leaks.
    app_env: str = "development"
    # Log level: DEBUG | INFO | WARNING | ERROR
    # independent of app_env — production can have DEBUG logs (piped to log aggregator).
    log_level: str = "INFO"
    debug: bool = False  # deprecated: use app_env + log_level instead

    # Frontend (Next.js) — used for magic link URLs
    frontend_url: str = "http://localhost:3000"

    # CORS — comma-separated, must NOT contain wildcards when credentials=True
    cors_origins: str = "http://localhost:3000"

    # Database
    database_url: str = "postgresql+asyncpg://myuser:mypassword@localhost:5435/mydatabase"
    database_replica_url: str = ""  # leave empty to use primary for reads
    db_pool_size: int = 100
    db_max_overflow: int = 50
    db_pool_timeout: int = 30  # seconds to wait for a connection from pool

    # Redis
    redis_url: str = "redis://localhost:6382/0"
    # Sentinel HA: comma-separated sentinel URLs, e.g. "redis://localhost:6380,redis://localhost:6381"
    # When set, app connects via Sentinel for automatic failover instead of direct redis_url.
    redis_sentinel_urls: str = ""
    redis_sentinel_service_name: str = "mymaster"  # Sentinel master group name
    redis_max_connections: int = 100
    celery_worker_redis_max_connections: int = 20

    # JWT
    jwt_secret: str = "change-me-in-production"
    secret_key: str = "change-me-in-production"
    jwt_access_expire: int = 900
    jwt_refresh_expire: int = 604800

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # Celery
    celery_broker_url: str = "redis://localhost:6382/1"

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_per_ip: int = 60          # general API per IP per minute
    rate_limit_per_email_ip: int = 5     # auth decisions per email+IP per minute
    rate_limit_auth_max_attempts: int = 5  # failed attempts before progressive friction
    rate_limit_auth_lockout_seconds: int = 900  # 15 min

    # Resend (email notifications)
    resend_api_key: str = ""
    notifications_from_email: str = "noreply@polymarket.example.com"

    # Mailtrap SMTP (dev fallback — set smtp_host to use instead of Resend)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from_email: str = "noreply@polymarket.example.com"

    # Referral
    referral_reward_amount: float = 1.0

    # 2FA
    totp_encryption_key: str = "change-me-in-production"
    totp_setup_expire_seconds: int = 900  # 15 minutes

    @field_validator("database_url", "database_replica_url", mode="before")
    @classmethod
    def normalize_async_database_url(cls, value: str | None) -> str | None:
        if not value:
            return value
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value


settings = Settings()
