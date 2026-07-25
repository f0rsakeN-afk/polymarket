import redis.asyncio as redis
from redis.asyncio import ConnectionPool

from config.settings import get_settings

settings = get_settings()

pool = ConnectionPool.from_url(
    settings.redis_url,
    max_connections=settings.redis_max_connections,
    decode_responses=True,
)


def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=pool)


async def get_redis_session() -> redis.Redis:
    client = redis.Redis(connection_pool=pool)
    try:
        yield client
    finally:
        await client.aclose()
