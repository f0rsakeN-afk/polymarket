from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool

from config.settings import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
