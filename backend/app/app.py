import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect
from sqlalchemy.exc import DataError, IntegrityError

from app.api.account import router as account_router
from app.api.admin import router as admin_router
from app.api.alerts import router as alerts_router
from app.api.auth import router as auth_router
from app.api.comments import router as comments_router
from app.api.disputes import router as disputes_router
from app.api.exceptions import AppException
from app.api.flags import router as flags_router
from app.api.handlers import (
    app_exception_handler,
    data_error_handler,
    generic_exception_handler,
    http_exception_handler,
    integrity_error_handler,
    validation_exception_handler,
)
from app.api.health import mark_started
from app.api.health import router as health_router
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
from app.api.origin_check import OriginCheckMiddleware
from app.api.positions import router as positions_router
from app.api.referrals import router as referrals_router
from app.api.split_merge import router as split_merge_router
from app.api.trades import router as trades_router
from app.api.treasury import router as treasury_router
from app.api.wallet import router as wallet_router
from app.api.webhooks import router as webhook_router
from app.config import settings
from app.database import _get_engine, _get_replica_engine
from app.middleware.metrics import MetricsMiddleware, clean_multiproc_dir
from app.middleware.request_id import RequestIDMiddleware
from app.services.ops_signals import ops_loop
from app.websocket.manager import manager, redis_pubsub
from app.websocket.routes import router as ws_router

# Read APP_ENV early • logging is configured in lifespan() after settings loads,
# but this is used at module level to conditionally import/show docs.
# Never use this for security decisions • only for UI/information exposure.
_APP_ENV = os.environ.get("APP_ENV", "development")


def _configure_logging(app_env: str, log_level: str) -> None:
    """Configure root logger based on environment and log level.

    ## Why `extra` is rendered here at all

    A call site that writes `logger.info("Order filled", extra={"order_id": ...})`
    is only useful if something renders those fields. Both formatters below used to
    emit `message` and nothing else, so every `extra` in the codebase was silently
    discarded — which makes converting an f-string into structured fields a change
    that looks like an improvement and does nothing at all.

    So the renderers come first. Anything attached with `extra=` becomes a top-level
    field in production JSON and a `key=value` suffix in development, and the two
    are consistent with each other so a query written against one works on the
    other.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    handler = logging.StreamHandler()

    # Attributes that are already rendered elsewhere, or that describe the emitter
    # rather than the event. Emitting them again would duplicate every line and,
    # for `msg`/`args`, produce the *unformatted* template alongside the message.
    reserved = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
        "asctime",
        "message",
    }

    def _extras(record: logging.LogRecord) -> dict:
        return {k: v for k, v in record.__dict__.items() if k not in reserved}

    if app_env == "production":
        # Structured JSON in production • parseable by log aggregators (Datadog, Loki, ELK)
        class JSONFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                return json.dumps(
                    {
                        "timestamp": record.created,
                        "level": record.levelname,
                        "logger": record.name,
                        "message": record.getMessage(),
                        **_extras(record),
                    },
                    default=str,
                )

        handler.setFormatter(JSONFormatter())
    else:
        # `exc_info` is left to the formatter, which appends the traceback itself.
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        _base = handler.formatter

        class DevFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                line = _base.format(record)
                fields = _extras(record)
                return f"{line}  {fields}" if fields else line

        handler.setFormatter(DevFormatter())

    logging.basicConfig(level=level, handlers=[handler])


logger = logging.getLogger("PredictX")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Configure logging AFTER settings load • uses app_env (production → JSON, else human-readable)
    # and log_level (verbosity). This replaces the module-level basicConfig.
    _configure_logging(settings.app_env, settings.log_level)
    logger.info(f"Starting up (app_env={settings.app_env}, log_level={settings.log_level})")
    # Drop stale per-worker metric files from a previous run (multiproc mode).
    clean_multiproc_dir()

    # Error tracking • opt-in via SENTRY_DSN. No-op locally when unset.
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            profiles_sample_rate=settings.sentry_profiles_sample_rate,
            send_default_pii=False,
        )
        logger.info("Sentry error tracking enabled")

    # Fail fast: all secrets must be set via environment variables
    if settings.totp_encryption_key == "change-me-in-production":
        raise RuntimeError(
            "totp_encryption_key is using its default placeholder value. "
            "Set TOTP_ENCRYPTION_KEY environment variable to a secure random value before deploying."
        )
    if settings.jwt_secret == "change-me-in-production":  # noqa: S105 -- placeholder sentinel check, not a credential
        raise RuntimeError(
            "jwt_secret is using its default placeholder value. "
            "Set JWT_SECRET environment variable to a secure random value before deploying."
        )
    if settings.secret_key == "change-me-in-production":  # noqa: S105 -- placeholder sentinel check, not a credential
        raise RuntimeError(
            "secret_key is using its default placeholder value. "
            "Set SECRET_KEY environment variable to a secure random value before deploying."
        )

    # Warn if TRUSTED_PROXY_IPS is not set • IP-based rate limiting can be spoofed
    # behind an untrusted proxy (the direct connection IP will be the proxy's IP, not the real client)
    import os
    if settings.app_env == "production" and not os.environ.get("TRUSTED_PROXY_IPS", "").strip():
        logger.warning(
            "TRUSTED_PROXY_IPS is not set. X-Forwarded-For will be ignored for IP identification, "
            "so every request that arrives from the proxy shares ONE rate-limit bucket (the proxy's "
            "IP): one client can exhaust it for everyone, and per-IP limits cannot be enforced per "
            "user. Set TRUSTED_PROXY_IPS to the proxy address (e.g. 10.0.0.0/8,172.16.0.0/12)."
        )

    # The logout token blacklist lives in Redis. Outside production it fails
    # OPEN (a dev stack without Redis should still accept logins); in
    # production a Redis outage fails CLOSED and rejects every token. Make
    # that choice loud so nobody discovers it during an incident.
    if settings.app_env != "production":
        logger.warning(
            f"app_env={settings.app_env}: token blacklist checks FAIL OPEN if Redis is "
            "unreachable • a logged-out token stays usable until it expires (≤15 min). "
            "Set APP_ENV=production to fail closed."
        )

    # Wait for Postgres + Redis before accepting traffic.
    # Compose gates initial startup with depends_on:service_healthy, but that only
    # applies at `up` time • if either dependency restarts later, or when running
    # outside Compose, the app must block here instead of failing the first request.

    async def _wait_for_postgres(timeout_s: float = 60.0) -> None:
        from sqlalchemy import text

        deadline = asyncio.get_event_loop().time() + timeout_s
        last_err: Exception | None = None
        while True:
            try:
                async with _get_engine().begin() as conn:
                    await conn.execute(text("SELECT 1"))
                return
            except Exception as e:  # noqa: BLE001 • log and retry until timeout
                last_err = e
                if asyncio.get_event_loop().time() >= deadline:
                    raise RuntimeError(f"Postgres not ready after {timeout_s}s: {last_err}") from last_err
                logger.warning(f"Waiting for Postgres... ({last_err})")
                await asyncio.sleep(2)

    async def _wait_for_redis(timeout_s: float = 60.0) -> None:
        from app.redis import get_redis, redis_cb

        deadline = asyncio.get_event_loop().time() + timeout_s
        last_err: Exception | None = None
        while True:
            try:
                r = await get_redis()
                await redis_cb.call(lambda: r.ping())
                return
            except Exception as e:  # noqa: BLE001 • log and retry until timeout
                last_err = e
                if asyncio.get_event_loop().time() >= deadline:
                    raise RuntimeError(f"Redis not ready after {timeout_s}s: {last_err}") from last_err
                logger.warning(f"Waiting for Redis... ({last_err})")
                await asyncio.sleep(2)

    await _wait_for_postgres()
    await _wait_for_redis()
    logger.info("Postgres + Redis ready • starting API")

    async with _get_engine().begin() as conn:
        existing_tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
        if not existing_tables:
            logger.warning("Database is empty • run 'alembic upgrade head' before starting the API")
        else:
            logger.info("Database tables present; migrations own the schema (no auto create_all)")

    # Start Redis pub/sub listener
    try:
        await redis_pubsub.connect()
        await redis_pubsub.start_listener()
        logger.info("Redis pub/sub listener started")
    except Exception as e:
        logger.warning(f"Redis pub/sub not available: {e}")

    # Start the WebSocket heartbeat sweep. Without it a half-open socket (closed
    # laptop, NAT timeout, killed container) is never reaped: no FIN arrives, it
    # keeps its file descriptor and its per-IP counter slot, and `send_json`
    # keeps succeeding until the kernel buffer overflows. Broadcast-failure
    # detection only covers markets that actually trade, so a socket on a quiet
    # market would leak indefinitely. `_cleanup_dead` existed for this but
    # nothing ever called it.
    heartbeat_task = asyncio.create_task(manager.heartbeat_loop())
    logger.info("WebSocket heartbeat sweep started (30s)")

    # Grid price aggregation: one timer per worker flushing every grid socket's
    # buffered prices into a single combined frame. This is what keeps a list of
    # thirty live markets at one frame per tick instead of thirty.
    grid_task = asyncio.create_task(manager.grid_loop())
    logger.info("WebSocket grid flush started (250ms)")

    # Operational debt, refreshed on a timer: live worker count and how many
    # markets are past close and unresolved.
    #
    # This is the signal that would have caught a dead worker pool. Markets close
    # and settle in Celery, so a pool that stops leaves markets open indefinitely
    # - no winner announced, positions live, escrow locked - while every socket
    # stays connected and every page reports live. Counted and aged rather than
    # merely reported, because "a backlog exists" and "the backlog is six hours
    # old" call for different reactions.
    #
    # Started here rather than only in a worker because the *read* belongs with
    # the process that serves /metrics: a gauge nobody scrapes is storage.
    ops_task = asyncio.create_task(ops_loop())
    logger.info("Operational debt refresh started (30s)")

    # Everything is up. `/health/startup` reports success from here, so an
    # orchestrator does not restart a container that is merely booting slowly.
    mark_started()

    yield

    logger.info("Shutting down...")
    heartbeat_task.cancel()
    grid_task.cancel()
    ops_task.cancel()
    for task in (heartbeat_task, grid_task, ops_task):
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    await redis_pubsub.close()
    await _get_engine().dispose()
    await _get_replica_engine().dispose()


_is_prod = settings.app_env == "production"

app = FastAPI(
    title=settings.app_name,
    description="PredictX-style prediction market API with AMM trading, real-time prices, and Stripe deposits.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url="/redoc" if settings.app_env != "production" else None,
    openapi_url="/openapi.json" if settings.app_env != "production" else None,
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if not origins:
    raise ValueError(
        "CORS_ORIGINS cannot be empty. It is configuration, not a default - set it "
        "in .env (see .env.example) or the environment. It must list EVERY "
        "front-end origin: apps/web on :3000 and apps/admin on :3001. A missing "
        "origin does not degrade an app, it signs it out permanently - the "
        "preflight fails, /auth/me never returns, and the only clue is a console "
        "CORS error."
    )
if "*" in origins:
    raise ValueError(
        "CORS_ORIGINS cannot contain '*' when allow_credentials=True. "
        "Set explicit origins in CORS_ORIGINS (e.g. CORS_ORIGINS=http://localhost:3000)"
    )
# ── Auth cookie policy ──────────────────────────────────────────────────────
#
# The one configuration pair that cannot fail visibly. A wrong CORS origin prints
# to the console; a wrong SameSite prints nothing anywhere - the browser simply
# withholds the cookie, `/auth/me` 401s, and an operator is signed out of a tool
# that looks like it is working. So the invalid combinations are refused here,
# where the process refuses to start and says why.
_SAMESITE_VALUES = ("lax", "strict", "none")

if settings.cookie_samesite.strip().lower() not in _SAMESITE_VALUES:
    raise ValueError(
        f"COOKIE_SAMESITE must be one of {', '.join(_SAMESITE_VALUES)} - got "
        f"{settings.cookie_samesite!r}"
    )

if settings.cookie_samesite.strip().lower() == "none":
    # Browsers discard a SameSite=None cookie that is not Secure. That is
    # silent: login returns 200, Set-Cookie arrives, and the next request is
    # anonymous. Refusing to boot is the only place this can still be caught.
    if settings.app_env != "production":
        raise ValueError(
            "COOKIE_SAMESITE=none requires APP_ENV=production. Browsers discard a "
            "SameSite=None cookie without Secure, which leaves every request "
            "unauthenticated and produces no error to debug. Use COOKIE_SAMESITE=lax "
            "for local development - on localhost the front end and the API are the "
            "same site regardless of port, which is exactly why this is invisible in "
            "development and fatal in production."
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    # Explicit lists: with credentials allowed, "*" methods/headers would
    # let any origin's script drive state-changing endpoints via the
    # victim's cookies. Keep to what the frontend actually sends.
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID", "Stripe-Signature"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After"],
    max_age=600,
)
app.add_middleware(SecurityHeadersMiddleware)
# Registered here, which places it *inside* CORS: Starlette runs the
# last-registered middleware outermost, and CORS went on first. That is the right
# order — an unmatched origin's 403 is not readable by the rejected origin's
# script, because CORSMiddleware withholds the headers, and that is the outcome we
# want. Putting it outermost instead would mean it ran before request logging and
# metrics, so a refused request left no trace.
app.add_middleware(OriginCheckMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(RateLimitMiddleware, enabled=settings.rate_limit_enabled)

# Exception handlers
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(IntegrityError, integrity_error_handler)
app.add_exception_handler(DataError, data_error_handler)
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
app.include_router(account_router, prefix="/api/v1")
app.include_router(ws_router)
# Health has no prefix: `/health/ready` is already referenced by the compose
# healthchecks and the nginx config, and those paths must not move.
app.include_router(health_router)


@app.get("/metrics", include_in_schema=False)
async def metrics():
    """Prometheus scrape endpoint (aggregate across workers in multiprocess mode)."""
    from app.middleware.metrics import metrics_response

    return metrics_response()


@app.get("/")
async def root():
    return {"message": settings.app_name}
