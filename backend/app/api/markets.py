import asyncio
import logging
import random
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_db_replica
from app.deps import get_current_user
from app.models.market import Market, Outcome
from app.models.liquidity import LiquidityPool
from app.models.faq import MarketFAQ
from app.schemas.market import (
    MarketResponse,
    MarketDetailResponse,
    MarketListResponse,
    CreateMarketRequest,
    OutcomeResponse,
)
from app.schemas.faq import FAQResponse
from app.api.responses import success_response
from app.api.exceptions import NotFoundError, ValidationError, ForbiddenError
from app.amm.engine import BinaryAMM
from app.workers.tasks import resolve_market
from app.websocket.manager import redis_pubsub

logger = logging.getLogger("polymarket")
router = APIRouter(prefix="/markets", tags=["markets"])


def market_to_response(market: Market, yes_price: float = 0.5, no_price: float = 0.5) -> MarketResponse:
    return MarketResponse(
        id=str(market.id),
        slug=market.slug,
        question=market.question,
        description=market.description,
        category=market.category,
        status=market.status,
        total_liquidity=float(market.total_liquidity or 0),
        total_volume=float(market.total_volume or 0),
        yes_price=yes_price,
        no_price=no_price,
        closes_at=market.closes_at,
        winning_outcome_id=str(market.winning_outcome_id) if market.winning_outcome_id else None,
        winning_outcome_name=None,  # resolved outcome name loaded separately when needed
    )


@router.get("/", response_model=MarketListResponse, summary="List markets", description="List all prediction markets with optional filters for category, status, and search query.")
async def list_markets(
    q: str | None = None,
    category: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_replica),
):
    base = select(Market, LiquidityPool)

    if q:
        base = base.where(Market.question.ilike(f"%{q}%"))
    if status:
        base = base.where(Market.status == status)
    if category:
        base = base.where(Market.category == category)

    query = (
        base.outerjoin(LiquidityPool, Market.id == LiquidityPool.market_id)
        .order_by(Market.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size + 1)
    )

    result = await db.execute(query)
    rows = result.all()

    # Detect has_more without COUNT(*)
    has_more = len(rows) > page_size
    if has_more:
        rows = rows[:page_size]

    market_responses = []
    for market, pool in rows:
        if pool:
            total_shares = float(pool.yes_shares) + float(pool.no_shares)
            yes_price = float(pool.no_shares) / total_shares if total_shares > 0 else 0.5
            no_price = float(pool.yes_shares) / total_shares if total_shares > 0 else 0.5
        else:
            yes_price, no_price = 0.5, 0.5
        market_responses.append(market_to_response(market, yes_price, no_price))

    return MarketListResponse(
        data=market_responses,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


async def _get_market_prices_from_db(market_id: str) -> tuple[float, float]:
    """Load prices from DB. Use only when cache miss."""
    from app.database import async_session
    async with async_session() as db:
        pool_result = await db.execute(
            select(LiquidityPool).where(LiquidityPool.market_id == market_id)
        )
        pool = pool_result.scalar_one_or_none()
        if pool:
            total = float(pool.yes_shares) + float(pool.no_shares)
            return (
                float(pool.no_shares) / total if total > 0 else 0.5,
                float(pool.yes_shares) / total if total > 0 else 0.5,
            )
    return 0.5, 0.5


async def _get_cached_market_prices(market_id: str):
    """Return (yes_price, no_price) from Redis cache, or None if circuit breaker is open."""
    import time
    try:
        import redis as redis_lib
        from app.redis import get_redis, redis_cb
        r = get_redis()
        key = f"market:{market_id}:price"

        async def _hgetall():
            return await r.hgetall(key)

        data = await redis_cb.call(_hgetall)
        if not data:
            return None
        if "yes_price" not in data or "no_price" not in data:
            return None
        updated_at = data.get("updated_at")
        if updated_at:
            try:
                if time.time() - float(updated_at) > 60:
                    return None
            except ValueError:
                pass
        return float(data["yes_price"]), float(data["no_price"])
    except redis_lib.RedisError:
        return None
    except Exception:
        return None


async def _get_market_prices(market_id: str) -> tuple[float, float]:
    """
    Distributed singleflight via Redis SETNX: only 1 request across ALL workers
    hits the DB for a given market_id on cache miss. Others wait via polling.
    """
    import time
    from app.redis import get_redis, redis_cb

    # Fast path: Redis cache hit
    cached = await _get_cached_market_prices(market_id)
    if cached:
        return cached

    # Distributed singleflight: use SETNX as a lock across all worker processes
    lock_key = f"lock:market:{market_id}"
    r = get_redis()

    try:
        # Try to acquire distributed lock (5s TTL so it auto-releases if holder crashes)
        acquired = await redis_cb.call(lambda: r.setnx(lock_key, "1"))
        if acquired:
            # We hold the lock — do DB query, then release
            try:
                prices = await _get_market_prices_from_db(market_id)
                # Write to Redis cache
                cache_key = f"market:{market_id}:price"
                async def _write_cache():
                    pipe = r.pipeline()
                    pipe.hset(cache_key, mapping={
                        "yes_price": str(prices[0]),
                        "no_price": str(prices[1]),
                        "updated_at": str(time.time()),
                    })
                    pipe.expire(cache_key, 300)
                    await pipe.execute()
                await redis_cb.call(_write_cache)
                # Release lock
                await r.delete(lock_key)
                return prices
            except Exception:
                await r.delete(lock_key)
                raise
        else:
            # Another worker holds the lock — wait for cache to be populated
            for _ in range(50):  # 5s max wait
                await asyncio.sleep(0.1)
                cached = await _get_cached_market_prices(market_id)
                if cached:
                    return cached
            # Timeout — fall through to DB
            return await _get_market_prices_from_db(market_id)
    except Exception:
        # Redis failure — fall back to DB directly (no singleflight)
        return await _get_market_prices_from_db(market_id)


@router.get("/{slug}", summary="Get market details", description="Get full details of a market including outcomes and current AMM prices.")
async def get_market(slug: str, db: AsyncSession = Depends(get_db_replica)):
    result = await db.execute(select(Market).where(Market.slug == slug))
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")

    # Singleflight: concurrent requests for same market share 1 DB/Redis query
    yes_price, no_price = await _get_market_prices(str(market.id))
    spread = abs(yes_price - no_price)

    outcomes_result = await db.execute(select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index))
    outcomes = outcomes_result.scalars().all()

    return success_response({
        **market_to_response(market, yes_price, no_price).model_dump(),
        "outcomes": [
            OutcomeResponse(id=str(o.id), name=o.name, outcome_index=o.outcome_index).model_dump()
            for o in outcomes
        ],
        "spread": spread,
        "created_at": market.created_at.isoformat() if market.created_at else None,
    })


@router.get("/{slug}/orderbook", summary="Get market order book", description="Aggregate pending limit orders by price level.")
async def get_orderbook(
    slug: str,
    depth: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db_replica),
):
    from app.models.order import Order

    result = await db.execute(select(Market).where(Market.slug == slug))
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")

    outcomes_result = await db.execute(select(Outcome).where(Outcome.market_id == market.id).order_by(Outcome.outcome_index))
    outcomes = {o.id: o.name.lower() for o in outcomes_result.scalars().all()}

    book_result = await db.execute(
        select(Order.outcome_id, Order.price, func.sum(Order.remaining_amount).label("depth"))
        .where(
            Order.market_id == market.id,
            Order.status == "pending",
        )
        .group_by(Order.outcome_id, Order.price)
        .order_by(Order.outcome_id, Order.price.desc())
    )
    rows = book_result.all()

    bids = []
    asks = []
    for outcome_id, price, row_depth in rows:
        entry = {"price": float(price), "depth": float(row_depth), "outcome": outcomes.get(outcome_id, "unknown")}
        if entry["outcome"] == "yes":
            if len(bids) < depth:
                bids.append(entry)
        else:
            if len(asks) < depth:
                asks.append(entry)

    return success_response({"bids": bids, "asks": asks})


@router.post("/", summary="Create a new market", description="Create a new prediction market with YES/NO outcomes. Admin access required.")
async def create_market(
    data: CreateMarketRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new prediction market. Admin only."""
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise ForbiddenError("Admin access required")

    if data.closes_at <= datetime.now(timezone.utc):
        raise ValidationError("closes_at must be in the future")

    # Check slug uniqueness
    existing = await db.execute(select(Market).where(Market.slug == data.slug))
    if existing.scalar_one_or_none():
        raise ValidationError(f"Market with slug '{data.slug}' already exists")

    # Create market
    market = Market(
        slug=data.slug,
        question=data.question,
        description=data.description,
        category=data.category,
        closes_at=data.closes_at,
        created_by=user.id,
    )
    db.add(market)
    await db.flush()

    # Create YES/NO outcomes
    yes_outcome = Outcome(market_id=market.id, name="Yes", outcome_index=0)
    no_outcome = Outcome(market_id=market.id, name="No", outcome_index=1)
    db.add(yes_outcome)
    db.add(no_outcome)

    # Create initial liquidity pool if provided
    if data.initial_liquidity > 0:
        pool = LiquidityPool(
            market_id=market.id,
            yes_shares=Decimal(str(data.initial_liquidity)),
            no_shares=Decimal(str(data.initial_liquidity)),
            collateral=Decimal("0"),
            fee_rate=Decimal("0.02"),
            lp_token_supply=Decimal("0"),
        )
        db.add(pool)
        market.total_liquidity = Decimal(str(data.initial_liquidity))

    await db.commit()

    logger.info(f"Market created: {data.slug} by user {user.id}")
    return success_response({"id": str(market.id), "slug": market.slug})


@router.patch("/{market_id}/resolve", summary="Resolve a market", description="Set the winning outcome for a market and trigger settlement. Admin access required.")
async def resolve_market(
    market_id: str,
    winning_outcome_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Resolve a market with a winning outcome. Admin only."""
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise ForbiddenError("Admin access required")

    result = await db.execute(
        select(Market).where(Market.id == market_id).with_for_update()
    )
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")

    if market.status != "active":
        raise ValidationError("Only active markets can be resolved")

    outcome_result = await db.execute(
        select(Outcome).where(Outcome.id == winning_outcome_id, Outcome.market_id == market.id)
    )
    outcome = outcome_result.scalar_one_or_none()
    if not outcome:
        raise ValidationError("Invalid outcome for this market")

    market.status = "resolved"
    market.winning_outcome_id = winning_outcome_id
    market.resolved_at = datetime.now(timezone.utc)
    await db.commit()

    # Dispatch settlement as Celery task
    resolve_market.delay(str(market.id), winning_outcome_id)

    # Broadcast resolution to WebSocket clients
    await redis_pubsub.publish_market_event(
        str(market.id), "market:resolved",
        {"winning_outcome_id": winning_outcome_id, "winning_outcome_name": outcome.name}
    )

    logger.info(f"Market {market_id} resolved with outcome {winning_outcome_id}")
    return success_response({"status": "resolved"})


@router.patch("/{market_id}/close", summary="Close a market", description="Halt trading on a market without resolving it. Admin only.")
async def close_market(
    market_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Close/halt a market for trading without resolving. Admin only."""
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise ForbiddenError("Admin access required")

    result = await db.execute(select(Market).where(Market.id == market_id))
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError("Market not found")

    if market.status == "resolved":
        raise ValidationError("Cannot close a resolved market")
    if market.status == "closed":
        raise ValidationError("Market is already closed")

    market.status = "closed"
    await db.commit()

    await redis_pubsub.publish_market_event(str(market.id), "market:closed", {})

    logger.info(f"Market {market_id} closed")
    return success_response({"status": "closed"})


@router.get("/{slug}/faqs", summary="Get market FAQs", description="Get frequently asked questions for a market.")
async def get_market_faqs(slug: str, db: AsyncSession = Depends(get_db_replica)):
    result = await db.execute(select(Market).where(Market.slug == slug))
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")

    faqs_result = await db.execute(
        select(MarketFAQ)
        .where(MarketFAQ.market_id == market.id)
        .order_by(MarketFAQ.display_order, MarketFAQ.created_at)
    )
    faqs = faqs_result.scalars().all()

    return success_response([
        FAQResponse(
            id=str(faq.id),
            question=faq.question,
            answer=faq.answer,
            display_order=faq.display_order or 0,
        ).model_dump()
        for faq in faqs
    ])


@router.get("/{slug}/related", summary="Get related markets", description="Get related markets based on category and subcategory.")
async def get_related_markets(
    slug: str,
    limit: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db_replica),
):
    result = await db.execute(select(Market).where(Market.slug == slug))
    market = result.scalar_one_or_none()
    if not market:
        raise NotFoundError(f"Market '{slug}' not found")

    # Find markets in same category or subcategory, excluding current
    query = (
        select(Market, LiquidityPool)
        .outerjoin(LiquidityPool, Market.id == LiquidityPool.market_id)
        .where(
            Market.id != market.id,
            Market.status == "active",
            (Market.category == market.category) | (Market.subcategory == market.subcategory),
        )
        .order_by(Market.total_volume.desc())
        .limit(limit + 1)
    )

    query_result = await db.execute(query)
    rows = query_result.all()

    related = []
    for m, pool in rows[:limit]:
        if pool:
            total_shares = float(pool.yes_shares) + float(pool.no_shares)
            yes_price = float(pool.no_shares) / total_shares if total_shares > 0 else 0.5
            no_price = float(pool.yes_shares) / total_shares if total_shares > 0 else 0.5
        else:
            yes_price, no_price = 0.5, 0.5
        related.append(market_to_response(m, yes_price, no_price).model_dump())

    return success_response(related)
