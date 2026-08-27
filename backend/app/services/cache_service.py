"""
Cache service with tag-based invalidation.

Pattern: tag each cache key with market/user scopes so we can invalidate
just the affected keys — not blanket invalidate everything.

Usage:
    await cache_set_market(market_id, data, ttl=300)
    await cache_invalidate_market(market_id)     # invalidates all market_id scopes
    await cache_invalidate_user(user_id)         # invalidates all user_id scopes
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import Outcome
from app.models.order import Order
from app.redis import get_redis, redis_cb

# ── Market-scoped caches ────────────────────────────────────────────────────────


async def cache_set_market(market_id: str, data: dict, *, ttl: int = 300):
    """Cache market detail, keyed by market_id. Also track in market:{id}:keys set."""
    r = await get_redis()
    key = f"cm:market:{market_id}"
    tag_key = f"ct:market:{market_id}"

    async def _op():
        pipe = r.pipeline()
        pipe.set(f"cache:{key}", _dumps(data), ex=ttl)
        pipe.sadd(f"cache:{tag_key}", key)
        pipe.expire(f"cache:{tag_key}", ttl + 10)
        await pipe.execute()

    await redis_cb.call(_op)


async def cache_get_market(market_id: str) -> dict | None:
    r = await get_redis()
    raw = await redis_cb.call(lambda: r.get(f"cache:cm:market:{market_id}"))
    return _loads(raw) if raw else None


async def cache_invalidate_market(market_id: str):
    """Delete all cache entries tagged with this market_id (detail, orderbook, etc)."""
    r = await get_redis()
    tag_key = f"ct:market:{market_id}"

    async def _op():
        raw_keys = await r.smembers(f"cache:{tag_key}")
        if not raw_keys:
            return
        # Redis returns bytes; decode to string for correct cache key construction
        keys = [k.decode() if isinstance(k, bytes) else k for k in raw_keys]
        pipe = r.pipeline()
        pipe.delete(*[f"cache:{k}" for k in keys])
        pipe.delete(f"cache:{tag_key}")
        await pipe.execute()

    try:
        await redis_cb.call(_op)
    except Exception:
        pass  # non-critical


# ── Market list caches ──────────────────────────────────────────────────────────


async def cache_set_market_list(cache_key: str, data: dict, *, ttl: int = 60):
    r = await get_redis()

    async def _op():
        pipe = r.pipeline()
        pipe.set(f"cache:ml:{cache_key}", _dumps(data), ex=ttl)
        pipe.sadd("ct:market_lists", f"ml:{cache_key}")
        pipe.expire("ct:market_lists", ttl + 10)
        await pipe.execute()

    await redis_cb.call(_op)


async def cache_get_market_list(cache_key: str) -> dict | None:
    r = await get_redis()
    raw = await redis_cb.call(lambda: r.get(f"cache:ml:{cache_key}"))
    return _loads(raw) if raw else None


async def cache_invalidate_market_lists():
    """Invalidate all market list caches. Called when a market is created/resolved."""
    r = await get_redis()

    async def _op():
        keys = await r.smembers("ct:market_lists")
        if not keys:
            return
        pipe = r.pipeline()
        pipe.delete(*[f"cache:ml:{k.removeprefix('ml:')}" for k in keys])
        pipe.delete("ct:market_lists")
        await pipe.execute()

    try:
        await redis_cb.call(_op)
    except Exception:
        pass


# ── Orderbook caches ───────────────────────────────────────────────────────────


async def cache_set_orderbook(market_id: str, data: dict, *, ttl: int = 60):
    r = await get_redis()
    key = f"cm:ob:{market_id}"
    tag_key = f"ct:ob:{market_id}"

    async def _op():
        pipe = r.pipeline()
        pipe.set(f"cache:{key}", _dumps(data), ex=ttl)
        pipe.sadd(f"cache:{tag_key}", key)
        pipe.expire(f"cache:{tag_key}", ttl + 10)
        await pipe.execute()

    await redis_cb.call(_op)


async def cache_get_orderbook(market_id: str) -> dict | None:
    r = await get_redis()
    raw = await redis_cb.call(lambda: r.get(f"cache:cm:ob:{market_id}"))
    return _loads(raw) if raw else None


async def build_orderbook(db: AsyncSession, market_id: str) -> dict:
    """Build orderbook dict from pending limit orders. Single source of truth for all orderbook data."""
    outcomes_result = await db.execute(
        select(Outcome).where(Outcome.market_id == market_id).order_by(Outcome.outcome_index)
    )
    outcomes = outcomes_result.scalars().all()
    outcome_names = {str(o.id): o.name.lower() for o in outcomes}

    orderbook: dict[str, dict[str, list[dict]]] = {
        o.name.lower(): {"bids": [], "asks": []} for o in outcomes
    }

    pending = await db.execute(
        select(
            Order.outcome_id,
            Order.side,
            Order.price,
            func.sum(Order.remaining_amount).label("total_size"),
        )
        .where(
            Order.market_id == market_id,
            Order.status == "pending",
            Order.order_type.in_(["limit", "fill_or_kill"]),
        )
        .group_by(Order.outcome_id, Order.side, Order.price)
        .order_by(Order.outcome_id, Order.side, Order.price.desc())
    )
    for row in pending.all():
        outcome_name = outcome_names.get(str(row.outcome_id), "unknown")
        if outcome_name not in orderbook:
            continue
        entry = {"price": str(row.price), "size": str(row.total_size)}
        if row.side == "buy":
            orderbook[outcome_name]["bids"].append(entry)
        else:
            orderbook[outcome_name]["asks"].append(entry)

    return {"outcomes": orderbook}


# ── User-scoped caches ─────────────────────────────────────────────────────────


async def cache_invalidate_user(user_id: str):
    """Invalidate all caches for a specific user (positions, orders, wallet)."""
    r = await get_redis()
    tag_key = f"ct:user:{user_id}"

    async def _op():
        raw_keys = await r.smembers(f"cache:{tag_key}")
        if not raw_keys:
            return
        # Redis returns bytes; decode to string for correct cache key construction
        keys = [k.decode() if isinstance(k, bytes) else k for k in raw_keys]
        pipe = r.pipeline()
        pipe.delete(*[f"cache:{k}" for k in keys])
        pipe.delete(f"cache:{tag_key}")
        await pipe.execute()

    try:
        await redis_cb.call(_op)
    except Exception:
        pass


# ── JSON helpers ────────────────────────────────────────────────────────────────


def _dumps(obj) -> str:
    import json

    return json.dumps(obj, default=str)


def _loads(raw: str | bytes | None) -> dict | list | None:
    if not raw:
        return None
    import json

    try:
        return json.loads(raw)
    except Exception:
        return None
