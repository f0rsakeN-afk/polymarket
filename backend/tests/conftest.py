"""
Production-grade pytest configuration.
Set env vars BEFORE any app imports so settings singletons get correct values.
Each test gets a completely fresh database (tables recreated).
"""
import asyncio
import gc
import os
import uuid

# MUST be before any app imports
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5433/mydatabase_test"
os.environ["REDIS_URL"] = "redis://localhost:6380/15"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.base import Base


TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://myuser:mypassword@localhost:5435/mydatabase_test",
)

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSessionFactory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

# Patch session makers BEFORE app import so test engine is used
import app.database as db_module

db_module._async_session_maker = TestSessionFactory
db_module._replica_session_maker = TestSessionFactory
# Clear getter caches so they don't override our direct assignments
db_module._get_async_session_maker.cache_clear()
db_module._get_replica_session_maker.cache_clear()
db_module._get_engine.cache_clear()
db_module._get_replica_engine.cache_clear()


# ── Fresh DB per test ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function", autouse=True)
async def _fresh_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


# ── Reset Redis global state between tests ────────────────────────────────────
# Modules like rate_limit_service.py and deps.py do `from app.redis import get_redis`
# at import time, binding directly to the original function. Simply patching
# app.redis.get_redis won't update those cached references. Instead, reset the
# actual _redis_client and _redis_client_sync globals and rely on the fact that
# get_redis recreates them on next call.

@pytest_asyncio.fixture(scope="function", autouse=True)
async def _reset_redis():
    import app.redis as rm

    old_client = rm._redis_client
    old_client_sync = rm._redis_client_sync

    # Null out so get_redis() creates fresh ones in this test's event loop
    rm._redis_client = None
    rm._redis_client_sync = None

    # Reset circuit breaker state
    rm.redis_cb._state = "closed"
    rm.redis_cb._failures = 0

    yield

    # Close clients from this test
    if rm._redis_client is not None:
        try:
            await rm._redis_client.aclose()
        except Exception:
            pass
    if rm._redis_client_sync is not None:
        try:
            rm._redis_client_sync.aclose()
        except Exception:
            pass

    # Restore previous clients (from the module's original init)
    rm._redis_client = old_client
    rm._redis_client_sync = old_client_sync


@pytest_asyncio.fixture
async def db_session():
    async with TestSessionFactory() as session:
        yield session


# ── HTTP client ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncClient:
    from app.app import app
    from app.database import get_db

    async def override_get_db():
        yield db_session

    # Override primary DB — replica is patched at the module level
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Model factories ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession):
    from app.models.user import User
    from app.models.wallet import Wallet
    from app.deps import hash_password

    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"admin_{uid}@example.com",
        username=f"admin_{uid}",
        password_hash=hash_password("Admin!Pass1"),
        is_email_verified=True,
        is_active=True,
        is_admin=True,
    )
    db_session.add(user)
    await db_session.flush()

    wallet = Wallet(user_id=user.id, balance="10000.00", locked_balance="0", currency="USDC")
    db_session.add(wallet)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession):
    from app.models.user import User
    from app.models.wallet import Wallet
    from app.deps import hash_password

    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"user_{uid}@example.com",
        username=f"user_{uid}",
        password_hash=hash_password("User!Pass1"),
        is_email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    wallet = Wallet(user_id=user.id, balance="1000.00", locked_balance="0", currency="USDC")
    db_session.add(wallet)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_market(db_session: AsyncSession, admin_user):
    from datetime import datetime, timezone
    from app.models.market import Market, Outcome
    from app.models.liquidity import LiquidityPool

    slug = f"test-mkt-{uuid.uuid4().hex[:8]}"
    market = Market(
        slug=slug,
        question="Will it rain tomorrow?",
        description="Test market",
        category="weather",
        status="active",
        created_by=admin_user.id,
        closes_at=datetime(2099, 12, 31, tzinfo=timezone.utc),
        total_liquidity="100.00",
        total_volume="50.00",
    )
    db_session.add(market)
    await db_session.flush()

    yes_outcome = Outcome(market_id=market.id, name="Yes", outcome_index=0)
    no_outcome = Outcome(market_id=market.id, name="No", outcome_index=1)
    db_session.add_all([yes_outcome, no_outcome])
    await db_session.flush()

    pool = LiquidityPool(
        market_id=market.id,
        yes_shares="50.0",
        no_shares="50.0",
        collateral="100.0",
        lp_token_supply="200.0",
    )
    db_session.add(pool)
    await db_session.commit()
    await db_session.refresh(market)
    await db_session.refresh(market, ["outcomes"])
    return market


@pytest_asyncio.fixture
async def resolved_market(db_session: AsyncSession, admin_user):
    from datetime import datetime, timezone
    from app.models.market import Market, Outcome

    slug = f"resolved-{uuid.uuid4().hex[:8]}"
    market = Market(
        slug=slug,
        question="Did it rain yesterday?",
        description="Resolved market",
        category="weather",
        status="resolved",
        created_by=admin_user.id,
        closes_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        total_liquidity="100.00",
        total_volume="50.00",
    )
    db_session.add(market)
    await db_session.flush()

    yes_outcome = Outcome(market_id=market.id, name="Yes", outcome_index=0)
    no_outcome = Outcome(market_id=market.id, name="No", outcome_index=1)
    db_session.add_all([yes_outcome, no_outcome])
    await db_session.flush()

    market.winning_outcome_id = yes_outcome.id
    await db_session.commit()
    await db_session.refresh(market)
    await db_session.refresh(market, ["outcomes"])
    return market


# ── Auth helpers ─────────────────────────────────────────────────────────────

def _token(user_id: str) -> str:
    from app.deps import create_access_token
    t, _ = create_access_token(str(user_id))
    return t
