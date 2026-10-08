import asyncio
import logging
import time
from contextlib import asynccontextmanager
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.amm.engine import BinaryAMM
from app.models.liquidity import LiquidityPool
from app.redis import get_redis, redis_cb

logger = logging.getLogger("PredictX")


class MarketService:

    @staticmethod
    @asynccontextmanager
    async def _session(db: AsyncSession | None = None):
        """Reuse the caller's session when one is provided.

        Passing the request-scoped ``get_db``/``get_db_replica`` session avoids
        opening a nested connection inside an already-open request session
        (doubled connection usage per request). Callers without a request
        context (WebSocket fan-out, background jobs) fall back to the shared
        pooled session factory in ``app.database``.
        """
        if db is not None:
            yield db
        else:
            from app.database import async_session
            async with async_session() as own_session:
                yield own_session


    @staticmethod
    def compute_prices(pool: LiquidityPool | None) -> tuple[Decimal, Decimal]:
        if pool is None:
            return Decimal("0.5"), Decimal("0.5")
        total = pool.yes_shares + pool.no_shares
        if total == 0:
            return Decimal("0.5"), Decimal("0.5")
        # Use Decimal division to preserve precision instead of float()
        yes_price = pool.yes_shares / total
        no_price = pool.no_shares / total
        return (yes_price, no_price)

    @staticmethod
    def pool_price(pool: LiquidityPool) -> Decimal:
        total = pool.yes_shares + pool.no_shares
        if total == 0:
            return Decimal("0.5")
        return pool.yes_shares / total

    # ── Parimutuel (multi-outcome) pricing ──────────────────────────────────
    #
    # A market with 3+ mutually exclusive outcomes is parimutuel, not binary.
    # Each outcome owns a pool row whose `yes_shares` is that outcome's share
    # count; the price is its share of the market total, so the outcome prices
    # sum to 1 and buying one raises its price while lowering the others.
    #
    # BinaryAMM is reused unchanged: constructed per outcome with
    # yes_shares=shares_i and no_shares=total-shares_i, its reserve is the
    # outcome's own and its total is the market total - the same constant-product
    # curve it always was, now with a correct reserve.

    @staticmethod
    def is_parimutuel(outcomes) -> bool:
        """True when the market has no real YES/NO pair.

        Decided by name, matching the frontend and the detail endpoint: counting
        outcomes would call a two-way named market (Trump vs Biden) binary and
        invent a NO side that does not exist.
        """
        names = [o.name.lower() for o in outcomes]
        return not ("yes" in names and "no" in names)

    @staticmethod
    def outcome_prices(pools: list[LiquidityPool]) -> dict[str, Decimal]:
        """Price per outcome from its pool: shares_i / SUM(shares)."""
        total = sum((p.yes_shares or Decimal(0)) for p in pools)
        if total == 0:
            # Nothing funded: an even split is the only non-fabricated answer.
            n = len(pools) or 1
            return {str(p.outcome_id): Decimal(1) / Decimal(n) for p in pools}
        return {str(p.outcome_id): (p.yes_shares or Decimal(0)) / total for p in pools}

    @staticmethod
    def build_outcome_amm(
        pools: list[LiquidityPool], outcome_id
    ) -> tuple["BinaryAMM", Decimal]:
        """BinaryAMM for one outcome, plus the market total.

        The reserve is the outcome's own shares; the opposite side is the
        complement (total - shares_i), which is what makes the constant-product
        maths behave like a parimutuel book rather than a second binary market.
        """
        total = sum((p.yes_shares or Decimal(0)) for p in pools)
        target = next(
            (p for p in pools if str(p.outcome_id) == str(outcome_id)), None
        )
        own = (target.yes_shares if target else Decimal(0)) or Decimal(0)
        fee_rate = target.fee_rate if target else Decimal("0.02")
        amm = BinaryAMM(
            yes_shares=own,
            no_shares=max(total - own, Decimal(0)),
            fee_rate=fee_rate,
        )
        return amm, total

    @staticmethod
    async def load_outcome_pools(
        db: AsyncSession, market_id
    ) -> list[LiquidityPool]:
        """Every per-outcome pool for a market, ordered by outcome for determinism."""
        from app.models.market import Outcome

        result = await db.execute(
            select(LiquidityPool)
            .join(Outcome, Outcome.id == LiquidityPool.outcome_id)
            .where(LiquidityPool.market_id == market_id)
            .order_by(Outcome.outcome_index)
        )
        return list(result.scalars().all())

    @staticmethod
    async def load_binary_pool(
        db: AsyncSession, market_id
    ) -> LiquidityPool | None:
        """The single NULL-outcome pool, for a binary market.

        Scoped explicitly on outcome_id IS NULL. A market_id-only lookup used to
        be safe because market_id was UNIQUE; with per-outcome rows it would
        match several and raise MultipleResultsFound.
        """
        result = await db.execute(
            select(LiquidityPool).where(
                LiquidityPool.market_id == market_id,
                LiquidityPool.outcome_id.is_(None),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def load_all_pools(
        db: AsyncSession, market_id
    ) -> list[LiquidityPool]:
        """Every pool row for a market, whatever its kind.

        For read paths that must aggregate across a market rather than price one
        outcome - total liquidity, a user's LP stake, the pool count. Returns a
        list on purpose: calling scalar_one_or_none() here would raise
        MultipleResultsFound on a parimutuel market, and picking one row would
        report a fraction of the market as if it were the whole thing.
        """
        result = await db.execute(
            select(LiquidityPool).where(LiquidityPool.market_id == market_id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def load_pools_for_outcomes(
        db: AsyncSession, market_id, outcome_ids
    ) -> dict[str, LiquidityPool]:
        """Pool rows keyed by outcome id, for a batch of outcomes.

        Prices a position against the pool of the outcome it was actually taken
        in. Keying on market_id alone would let a position in "Draw" be priced
        off whichever pool happened to be last in the result set.
        """
        if not outcome_ids:
            return {}
        result = await db.execute(
            select(LiquidityPool).where(
                LiquidityPool.market_id == market_id,
                LiquidityPool.outcome_id.in_(outcome_ids),
            )
        )
        return {str(row.outcome_id): row for row in result.scalars().all()}

    @staticmethod
    async def get_market_prices_batch(
        market_ids: list[str],
        db: AsyncSession | None = None,
    ) -> dict[str, tuple[float, float]]:
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
            # Reuse the caller's session when provided (no nested connection).
            async with MarketService._session(db) as session:
                pool_result = await session.execute(
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
    async def get_market_prices_from_db(
        market_id: str,
        db: AsyncSession | None = None,
    ) -> tuple[float, float]:
        async with MarketService._session(db) as session:
            pool = await MarketService.load_binary_pool(session, market_id)
            if pool is None:
                # Parimutuel market: no binary pool exists. The (yes, no) pair
                # callers expect is generalised to the leading outcome versus
                # everything else - the same information compressed to two
                # numbers, and it still sums to 1.
                prices = MarketService.outcome_prices(
                    await MarketService.load_outcome_pools(session, market_id)
                )
                if prices:
                    lead = max(prices.values())
                    return float(lead), float(Decimal(1) - lead)
            elif pool is not None:
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
    async def get_market_prices(
        market_id: str,
        db: AsyncSession | None = None,
    ) -> tuple[float, float]:
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
                    prices = await MarketService.get_market_prices_from_db(market_id, db=db)
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
                return await MarketService.get_market_prices_from_db(market_id, db=db)
        except Exception:
            return await MarketService.get_market_prices_from_db(market_id, db=db)
