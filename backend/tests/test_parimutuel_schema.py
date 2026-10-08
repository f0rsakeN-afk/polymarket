"""Schema-level guarantees for per-outcome liquidity pools.

The service-layer maths is unit-tested in test_parimutuel_pricing.py. What
cannot be unit-tested is the database constraint that makes it safe: if a
binary market can grow a second pool, every `scalar_one_or_none()` pool lookup
raises MultipleResultsFound at runtime and binary trading - the overwhelming
majority of markets - breaks.

These talk to a real database, which is the only place the constraints exist.
The `multi_outcome_market` fixture already seeds one pool per outcome and NO
binary pool, which is the shape these assert.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.liquidity import LiquidityPool
from app.models.market import Outcome
from app.services.market_service import MarketService

pytestmark = pytest.mark.asyncio


async def _outcomes(db, market):
    return list(
        (
            await db.execute(
                select(Outcome)
                .where(Outcome.market_id == market.id)
                .order_by(Outcome.outcome_index)
            )
        ).scalars().all()
    )


async def _pools(db, market):
    return list(
        (
            await db.execute(
                select(LiquidityPool).where(LiquidityPool.market_id == market.id)
            )
        ).scalars().all()
    )


class TestBinaryMarketsAreUnaffected:
    async def test_binary_market_keeps_exactly_one_pool(self, db_session, test_market):
        pool = await MarketService.load_binary_pool(db_session, test_market.id)
        assert pool is not None
        assert pool.outcome_id is None

        # The market_id-only lookup the rest of the codebase still uses must stay
        # single-valued, or it raises MultipleResultsFound.
        assert len(await _pools(db_session, test_market)) == 1

    async def test_database_rejects_a_second_binary_pool(self, db_session, test_market):
        """The partial unique index, exercised rather than assumed."""
        db_session.add(
            LiquidityPool(
                market_id=test_market.id,
                outcome_id=None,
                yes_shares="1",
                no_shares="1",
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_a_binary_market_is_not_parimutuel(self, test_market):
        assert not MarketService.is_parimutuel(list(test_market.outcomes))


class TestParimutuelPools:
    async def test_fixture_seeds_one_pool_per_outcome_and_no_binary_pool(
        self, db_session, multi_outcome_market
    ):
        outcomes = await _outcomes(db_session, multi_outcome_market)
        pools = await _pools(db_session, multi_outcome_market)

        assert len(outcomes) >= 3
        assert len(pools) == len(outcomes)
        assert {p.outcome_id for p in pools} == {o.id for o in outcomes}
        # No leftover binary pool: on a three-way market it has no meaning and a
        # market_id-only lookup would pick it up.
        assert all(p.outcome_id is not None for p in pools)

    async def test_database_rejects_two_pools_for_the_same_outcome(
        self, db_session, multi_outcome_market
    ):
        outcomes = await _outcomes(db_session, multi_outcome_market)
        db_session.add(
            LiquidityPool(
                market_id=multi_outcome_market.id,
                outcome_id=outcomes[0].id,
                yes_shares="10",
                no_shares="0",
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_outcome_prices_from_real_pools_sum_to_one(
        self, db_session, multi_outcome_market
    ):
        """End-to-end: real rows produce a normalised price set."""
        pools = await MarketService.load_outcome_pools(db_session, multi_outcome_market.id)
        outcomes = await _outcomes(db_session, multi_outcome_market)

        assert len(pools) == len(outcomes)
        prices = MarketService.outcome_prices(pools)

        total = sum(prices.values())
        assert total == pytest.approx(1.0, abs=1e-9)
        for outcome in outcomes:
            assert str(outcome.id) in prices

    async def test_pools_load_in_outcome_order(self, db_session, multi_outcome_market):
        """Determinism: the first pool must be the lowest outcome_index.

        The chart's primary line is built from the first outcome, so a
        nondeterministic order would make it change between requests.
        """
        pools = await MarketService.load_outcome_pools(db_session, multi_outcome_market.id)
        outcomes = await _outcomes(db_session, multi_outcome_market)

        assert [p.outcome_id for p in pools] == [o.id for o in outcomes]

    async def test_binary_pool_lookup_ignores_outcome_rows(
        self, db_session, multi_outcome_market
    ):
        """load_binary_pool must not pick up a per-outcome row."""
        assert await MarketService.load_binary_pool(db_session, multi_outcome_market.id) is None

    async def test_deleting_an_outcome_removes_its_pool(
        self, db_session, multi_outcome_market
    ):
        """CASCADE, so a removed outcome cannot leave an orphan pool behind."""
        outcomes = await _outcomes(db_session, multi_outcome_market)
        target = outcomes[0]
        assert any(p.outcome_id == target.id for p in await _pools(db_session, multi_outcome_market))

        await db_session.delete(target)
        await db_session.commit()

        remaining = await _pools(db_session, multi_outcome_market)
        assert all(p.outcome_id != target.id for p in remaining)

    async def test_buying_one_outcome_lowers_the_others(
        self, db_session, multi_outcome_market
    ):
        """The behaviour a parimutuel market exists for.

        Mutate one outcome's pool the way a fill does, then re-price: the traded
        outcome must rise and every other must fall.
        """
        pools = await MarketService.load_outcome_pools(db_session, multi_outcome_market.id)
        before = MarketService.outcome_prices(pools)
        target_id = pools[0].outcome_id

        pools[0].yes_shares = pools[0].yes_shares + 100
        await db_session.commit()

        fresh = await MarketService.load_outcome_pools(db_session, multi_outcome_market.id)
        after = MarketService.outcome_prices(fresh)

        assert after[str(target_id)] > before[str(target_id)]
        for pool_row in fresh[1:]:
            assert after[str(pool_row.outcome_id)] < before[str(pool_row.outcome_id)]

        assert sum(after.values()) == pytest.approx(1.0, abs=1e-9)