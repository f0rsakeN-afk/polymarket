from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.config import settings


@lru_cache
def _get_engine():
    return create_async_engine(
        settings.database_url,
        echo=settings.debug,
        poolclass=AsyncAdaptedQueuePool,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


@lru_cache
def _get_replica_engine():
    replica_url = settings.database_replica_url or settings.database_url
    return create_async_engine(
        replica_url,
        echo=False,
        poolclass=AsyncAdaptedQueuePool,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
    )


@lru_cache
def _get_async_session_maker():
    return async_sessionmaker(
        _get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@lru_cache
def _get_replica_session_maker():
    return async_sessionmaker(
        _get_replica_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


# Mutable refs so tests can patch these directly
# _async_session_maker and _replica_session_maker are derived from getters on first use
_async_session_maker = None
_replica_session_maker = None


def _ensure_session_makers():
    global _async_session_maker, _replica_session_maker
    if _async_session_maker is None:
        _async_session_maker = _get_async_session_maker()
    if _replica_session_maker is None:
        _replica_session_maker = _get_replica_session_maker()


# Aliases for backward compatibility — call as async_session() like a sessionmaker
def async_session():
    _ensure_session_makers()
    return _async_session_maker()


# Also expose as module-level session makers for direct use
async_session_maker = _get_async_session_maker
replica_session_maker = _get_replica_session_maker


async def get_db() -> AsyncSession:
    _ensure_session_makers()
    async with _async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_db_replica() -> AsyncSession:
    """Read-only replica session — use for list/get endpoints that don't modify data."""
    _ensure_session_makers()
    async with _replica_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
