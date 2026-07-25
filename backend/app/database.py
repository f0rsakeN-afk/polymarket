from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
)

# Replica engine for read-heavy endpoints — falls back to primary if no replica configured
replica_url = settings.database_replica_url or settings.database_url
replica_engine = create_async_engine(
    replica_url,
    echo=False,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Alias for backward compatibility — used by internal helpers like _get_market_prices_from_db
async_session = async_session_maker

replica_session_maker = async_sessionmaker(
    replica_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncSession:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_db_replica() -> AsyncSession:
    """Read-only replica session — use for list/get endpoints that don't modify data."""
    async with replica_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
