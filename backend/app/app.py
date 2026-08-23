import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.api.admin import router as admin_router
from app.api.alerts import router as alerts_router
from app.api.auth import router as auth_router
from app.api.comments import router as comments_router
from app.api.disputes import router as disputes_router
from app.api.exceptions import AppException
from app.api.flags import router as flags_router
from app.api.handlers import (
    app_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    integrity_error_handler,
    validation_exception_handler,
)
from app.api.liquidity import router as liquidity_router
from app.api.market_activity import router as market_activity_router
from app.api.markets import router as markets_router
from app.api.middleware import (
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from app.api.notifications import router as notifications_router
from app.api.orders import router as orders_router
from app.api.positions import router as positions_router
from app.api.referrals import router as referrals_router
from app.api.split_merge import router as split_merge_router
from app.api.trades import router as trades_router
from app.api.treasury import router as treasury_router
from app.api.wallet import router as wallet_router
from app.api.webhooks import router as webhook_router
from app.config import settings
from app.database import _get_engine, _get_replica_engine
from app.middleware.request_id import RequestIDMiddleware
from app.models import Base
from app.websocket.manager import redis_pubsub
from app.websocket.routes import router as ws_router

# Structured logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("polymarket")


def json_log(record: logging.LogRecord, **extra: object) -> str:
    """Format a log record as a JSON string with standard fields plus any extra fields."""
    out = {
        "timestamp": record.created,
        "level": record.levelname,
        "logger": record.name,
        "message": record.getMessage(),
    }
    out.update(extra)
    return json.dumps(out, default=str)


class JSONFormatter(logging.Formatter):
    """Format log records as JSON strings when not in debug mode."""

    def format(self, record: logging.LogRecord) -> str:
        return json_log(record)


if not settings.debug:
    _json_handler = logging.StreamHandler()
    _json_handler.setFormatter(JSONFormatter())
    logger.addHandler(_json_handler)
    logger.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")

    # Fail fast: all secrets must be set via environment variables
    if settings.totp_encryption_key == "change-me-in-production":
        raise RuntimeError(
            "totp_encryption_key is using its default placeholder value. "
            "Set TOTP_ENCRYPTION_KEY environment variable to a secure random value before deploying."
        )
    if settings.jwt_secret == "change-me-in-production":
        raise RuntimeError(
            "jwt_secret is using its default placeholder value. "
            "Set JWT_SECRET environment variable to a secure random value before deploying."
        )
    if settings.secret_key == "change-me-in-production":
        raise RuntimeError(
            "secret_key is using its default placeholder value. "
            "Set SECRET_KEY environment variable to a secure random value before deploying."
        )

    # Warn if TRUSTED_PROXY_IPS is not set — IP-based rate limiting can be spoofed
    # behind an untrusted proxy (the direct connection IP will be the proxy's IP, not the real client)
    import os
    if not settings.debug and not os.environ.get("TRUSTED_PROXY_IPS", "").strip():
        logger.warning(
            "TRUSTED_PROXY_IPS is not set. X-Forwarded-For will be ignored for IP identification. "
            "Set TRUSTED_PROXY_IPS if running behind a reverse proxy (e.g. nginx, caddy, cloudflare). "
            "Example: TRUSTED_PROXY_IPS=10.0.0.0/8,172.16.0.0/12"
        )

    async with _get_engine().begin() as conn:
        existing_tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
        if not existing_tables:
            await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn))
            logger.info("Database tables created")
        else:
            logger.info("Database tables already exist; skipping automatic schema creation")

    # Start Redis pub/sub listener
    try:
        await redis_pubsub.connect()
        await redis_pubsub.start_listener()
        logger.info("Redis pub/sub listener started")
    except Exception as e:
        logger.warning(f"Redis pub/sub not available: {e}")

    yield

    logger.info("Shutting down...")
    await redis_pubsub.close()
    await _get_engine().dispose()
    await _get_replica_engine().dispose()


app = FastAPI(
    title=settings.app_name,
    description="Polymarket-style prediction market API with AMM trading, real-time prices, and Stripe deposits.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

origins = [o.strip() for o in settings.cors_origins.split(",")]
if "*" in origins:
    raise ValueError(
        "CORS_ORIGINS cannot contain '*' when allow_credentials=True. "
        "Set explicit origins in CORS_ORIGINS (e.g. CORS_ORIGINS=http://localhost:3000)"
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(RateLimitMiddleware, enabled=settings.rate_limit_enabled)

# Exception handlers
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(IntegrityError, integrity_error_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# Routes
app.include_router(auth_router, prefix="/api/v1")
app.include_router(markets_router, prefix="/api/v1")
app.include_router(orders_router, prefix="/api/v1")
app.include_router(positions_router, prefix="/api/v1")
app.include_router(alerts_router, prefix="/api/v1")
app.include_router(wallet_router, prefix="/api/v1")
app.include_router(webhook_router, prefix="/api/v1")
app.include_router(liquidity_router, prefix="/api/v1")
app.include_router(comments_router, prefix="/api/v1")
app.include_router(trades_router, prefix="/api/v1")
app.include_router(referrals_router, prefix="/api/v1")
app.include_router(market_activity_router, prefix="/api/v1")
app.include_router(split_merge_router, prefix="/api/v1")
app.include_router(disputes_router, prefix="/api/v1")
app.include_router(flags_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(treasury_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready():
    """Readiness probe — verifies DB and Redis connectivity."""
    import time

    checks = {}
    unhealthy = False

    # Check DB
    try:
        from sqlalchemy import text
        t0 = time.perf_counter()
        async with _get_engine().begin() as conn:
            await conn.execute(text("SELECT 1"))
        latency_ms = (time.perf_counter() - t0) * 1000
        checks["db"] = {"status": "ok", "latency_ms": round(latency_ms, 2)}
    except Exception as e:
        checks["db"] = {"status": "error", "latency_ms": None, "error": str(e)}
        unhealthy = True

    # Check Redis
    try:
        from app.redis import get_redis, redis_cb
        t0 = time.perf_counter()
        r = await get_redis()
        await redis_cb.call(lambda: r.ping())
        latency_ms = (time.perf_counter() - t0) * 1000
        checks["redis"] = {"status": "ok", "latency_ms": round(latency_ms, 2)}
    except Exception as e:
        checks["redis"] = {"status": "error", "latency_ms": None, "error": str(e)}
        unhealthy = True

    return {
        "status": "ok" if not unhealthy else "degraded",
        "checks": checks,
        "version": app.version,
    }


@app.get("/")
async def root():
    return {"message": settings.app_name}
