import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import engine, replica_engine
from app.models import Base
from app.api.handlers import (
    http_exception_handler,
    app_exception_handler,
    validation_exception_handler,
    integrity_error_handler,
    generic_exception_handler,
)
from app.api.exceptions import AppException
from app.api.auth import router as auth_router
from app.api.alerts import router as alerts_router
from app.api.markets import router as markets_router
from app.api.orders import router as orders_router
from app.api.positions import router as positions_router
from app.api.wallet import router as wallet_router
from app.api.webhooks import router as webhook_router
from app.api.liquidity import router as liquidity_router
from app.api.comments import router as comments_router
from app.api.trades import router as trades_router
from app.api.referrals import router as referrals_router
from app.api.market_activity import router as market_activity_router
from app.websocket.routes import router as ws_router
from app.websocket.manager import redis_pubsub
from app.api.middleware import RequestLoggingMiddleware
from app.api.responses import error_response

# Structured logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("polymarket")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    async with engine.begin() as conn:
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
    await engine.dispose()
    await replica_engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="Polymarket-style prediction market API with AMM trading, real-time prices, and Stripe deposits.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

origins = [o.strip() for o in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)

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
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {"message": settings.app_name}
