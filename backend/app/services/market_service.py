import asyncio
import logging
import time
from decimal import Decimal

from sqlalchemy import select

from app.models.liquidity import LiquidityPool
from app.redis import get_redis, redis_cb

logger = logging.getLogger("polymarket")


class MarketService:

    @staticmethod
    def compute_prices(pool: LiquidityPool | None) -> tuple[float, float]:
        if pool is None:
            return 0.5, 0.5
        total = pool.yes_shares + pool.no_shares
        if total == 0:
            return 0.5, 0.5
        return float(pool.yes_shares / total), float(pool.no_shares / total)

    @staticmethod
    def pool_price(pool: LiquidityPool) -> Decimal:
        total = pool.yes_shares + pool.no_shares
        if total == 0:
            return Decimal("0.5")
        return pool.yes_shares / total

    @staticmethod
    async def get_market_prices_batch(market_ids: list[str]) -> dict[str, tuple[float, float]]:
        """Fetch prices for many markets with O(1) round trips.

        Single Redis pipeline for cache reads, a single SELECT for all cache
        misses, one pipeline for cache writes. Replaces N sequential
        get_market_prices() calls (each opening its own DB session) that made
        cold list pages fan out and stall.
        """
        if not market_ids:
            return {}
        r = await get_redis()

        async def _read_all():
            pipe = r.pipeline()
            for mid in market_ids:
                pipe.hgetall(f"market:{mid}:price")
            return await pipe.execute()

        try:
            cached_rows = await redis_cb.call(_read_all)
        except Exception:
            cached_rows = [None] * len(market_ids)

        prices: dict[str, tuple[float, float]] = {}
        missing: list[str] = []
        for mid, data in zip(market_ids, cached_rows):
            if data and "yes_price" in data and "no_price" in data:
                try:
                    prices[str(mid)] = (float(data["yes_price"]), float(data["no_price"]))
                    continue
                except (ValueError, TypeError):
                    pass
            missing.append(str(mid))

        if missing:
            from app.database import async_session
            async with async_session() as db:
                pool_result = await db.execute(
                    select(LiquidityPool).where(LiquidityPool.market_id.in_(missing))
                )
                pools = {str(p.market_id): p for p in pool_result.scalars().all()}
            now = time.time()

            async def _write_all():
                pipe = r.pipeline()
                for mid in missing:
                    pool = pools.get(mid)
                    if pool is None:
                        continue
                    total = pool.yes_shares + pool.no_shares
                    y, n = (
                        (float(pool.yes_shares / total), float(pool.no_shares / total))
                        if total > 0 else (0.5, 0.5)
                    )
                    prices[mid] = (y, n)
                    key = f"market:{mid}:price"
                    pipe.hset(key, mapping={
                        "yes_price": str(y), "no_price": str(n),
                        "updated_at": str(now),
                    })
                    pipe.expire(key, 300)
                await pipe.execute()

            try:
                await redis_cb.call(_write_all)
            except Exception:
                for mid in missing:
                    pool = pools.get(mid)
                    if pool is None:
                        prices.setdefault(mid, (0.5, 0.5))
                        continue
                    total = pool.yes_shares + pool.no_shares
                    prices[mid] = (
                        (float(pool.yes_shares / total), float(pool.no_shares / total))
                        if total > 0 else (0.5, 0.5)
                    )

        for mid in market_ids:
            prices.setdefault(str(mid), (0.5, 0.5))
        return prices

    @staticmethod
    async def get_market_prices_from_db(market_id: str) -> tuple[float, float]:
        from app.database import async_session
        async with async_session() as db:
            pool_result = await db.execute(
                select(LiquidityPool).where(LiquidityPool.market_id == market_id)
            )
            pool = pool_result.scalar_one_or_none()
            if pool:
                total = pool.yes_shares + pool.no_shares
                return (
                    float(pool.yes_shares / total) if total > 0 else 0.5,
                    float(pool.no_shares / total) if total > 0 else 0.5,
                )
        return 0.5, 0.5

    @staticmethod
    async def get_cached_market_prices(market_id: str):
        try:
            r = await get_redis()
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
            yes_price = float(data["yes_price"])
            no_price = float(data["no_price"])
            # 0 prices = uninitialized market, fall through to DB
            if yes_price == 0 or no_price == 0:
                return None
            return yes_price, no_price
        except Exception:
            return None

    @staticmethod
    async def get_market_prices(market_id: str) -> tuple[float, float]:
        cached = await MarketService.get_cached_market_prices(market_id)
        if cached:
            return cached

        lock_key = f"lock:market:{market_id}"
        r = await get_redis()

        try:
            # redis-py has no setnx(ex=...); use SET with NX + EX for the stampede lock.
            acquired = await redis_cb.call(lambda: r.set(lock_key, "1", nx=True, ex=30))
            if acquired:
                try:
                    prices = await MarketService.get_market_prices_from_db(market_id)
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
                    return prices
                finally:
                    # Always release lock even if cache write fails or breaker open (H6 fix)
                    try:
                        await r.delete(lock_key)
                    except Exception:
                        pass
            else:
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    cached = await MarketService.get_cached_market_prices(market_id)
                    if cached:
                        return cached
                return await MarketService.get_market_prices_from_db(market_id)
        except Exception:
            return await MarketService.get_market_prices_from_db(market_id)
