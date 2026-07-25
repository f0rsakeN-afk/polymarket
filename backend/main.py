import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
import redis.asyncio as redis

from config import get_settings
from config.database import engine, async_session, get_db
from config.redis import get_redis

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("polymarket")


redis_client: redis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    logger.info("Starting up...")

    redis_client = get_redis()
    await redis_client.ping()
    logger.info(f"Redis connected: {settings.redis_url}")

    async with engine.begin() as conn:
        await conn.run_sync(lambda _: None)
    logger.info(f"PostgreSQL connected: {settings.database_url}")

    yield

    logger.info("Shutting down...")
    if redis_client:
        await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/health")
async def health(redis: redis.Redis = Depends(get_redis)):
    pong = await redis.ping()
    return {"status": "ok", "redis": pong}


@app.get("/")
async def root():
    return {"message": settings.app_name}
