"""End-to-end order execution on a parimutuel (multi-outcome) market.

End-to-end proof against a real database that an order on a three-way market
moves the OUTCOME'S OWN pool - not a shared binary reserve.

The failure this replaces was subtle: with one binary book, every outcome that
was not literally "yes" was priced off the NO reserve, so an order in "Away"
moved reserves belonging to "Draw". The assertions below check pool membership,
not just that something changed.

The `market` (binary) fixture is exercised alongside `multi_outcome_market` so
the two paths are covered together: a binary market must keep filling from its
single pool, unchanged by the per-outcome schema.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.liquidity import LiquidityPool
from app.models.market import Outcome
from app.models.position import Position
from app.schemas.order import OrderRequest
from app.services.market_service import MarketService
from app.services.order_service import OrderService

# Outcome lookup is by `name.lower()`, so requests must use lower-case names.
HOME, DRAW, AWAY = "home", "draw", "away"


async def _pools(db, market):
    return list(
        (
            await db.execute(
                select(LiquidityPool).where(LiquidityPool.market_id == market.id)
            )
        ).scalars().all()
    )


async def _shares(db, market):
    """Shares per outcome id. Async because it reads the DB."""
    return {str(p.outcome_id): p.yes_shares for p in await _pools(db, market)}


async def _outcomes(db, market):
    """Outcome rows for a market. Async: the relationship is lazy."""
    return list(
        (
            await db.execute(
                select(Outcome).where(Outcome.market_id == market.id)
                .order_by(Outcome.outcome_index)
            )
        ).scalars().all()
    )


async def _prices(db, market):
    return MarketService.outcome_prices(
        await MarketService.load_outcome_pools(db, market.id)
    )


def _request(market, outcome: str, **kw) -> OrderRequest:
    return OrderRequest(
        market_id=str(market.id),
        outcome=outcome,
        side=kw.pop("side", "buy"),
        order_type=kw.pop("order_type", "limit"),
        amount=Decimal(str(kw.pop("amount", "100"))),
        price=Decimal(str(kw.pop("price", "0.90"))),
        **kw,
    )


class TestParimutuelOrderUsesItsOwnPool:
    async def test_buying_an_outcome_moves_only_that_outcome_reserve(
        self, db_session, multi_outcome_market, test_user
    ):
        market = multi_outcome_market
        before = await _shares(db_session, market)
        assert len(before) >= 3, "fixture must seed a pool per outcome"

        result = await OrderService.execute_order(
            db_session, test_user, _request(market, AWAY)
        )
        assert result.status == "filled"

        after = await _shares(db_session, market)
        moved = [oid for oid in before if before[oid] != after[oid]]
        assert len(moved) == 1, f"exactly one pool may move, moved={len(moved)}"

        outcomes = await _outcomes(db_session, market)
        away_id = next(str(o.id) for o in outcomes if o.name.lower() == AWAY)
        assert moved == [away_id]
        assert after[away_id] > before[away_id]

    async def test_buying_one_outcome_lowers_the_others(
        self, db_session, multi_outcome_market, test_user
    ):
        market = multi_outcome_market
        before = await _prices(db_session, market)

        await OrderService.execute_order(db_session, test_user, _request(market, HOME))

        after = await _prices(db_session, market)
        outs = await _outcomes(db_session, market)
        away_id = next(str(o.id) for o in outs if o.name.lower() == AWAY)
        home_id = next(str(o.id) for o in outs if o.name.lower() == HOME)

        assert after[home_id] > before[home_id], "the traded outcome should rise"
        assert after[away_id] < before[away_id], "an unt traded outcome should fall"
        assert sum(after.values()) == pytest.approx(1.0, abs=1e-9)

    async def test_position_is_recorded_for_the_traded_outcome(
        self, db_session, multi_outcome_market, test_user
    ):
        market = multi_outcome_market
        await OrderService.execute_order(db_session, test_user, _request(market, DRAW))

        positions = (
            await db_session.execute(
                select(Position).where(
                    Position.user_id == test_user.id,
                    Position.market_id == market.id,
                )
            )
        ).scalars().all()

        assert len(positions) == 1
        draw_id = next(str(o.id) for o in await _outcomes(db_session, market) if o.name.lower() == DRAW)
        assert str(positions[0].outcome_id) == draw_id
        assert positions[0].shares_held > 0

    async def test_every_outcome_trades_independently(
        self, db_session, multi_outcome_market, test_user
    ):
        """No outcome is special-cased - the original defect in one test.

        The engine used to privilege the literal string "yes". This market has
        no such outcome, and all three must trade against their own pool.
        """
        market = multi_outcome_market
        for name in (HOME, DRAW, AWAY):
            result = await OrderService.execute_order(
                db_session, test_user, _request(market, name, amount="50")
            )
            assert result.status == "filled", f"{name} did not fill"

        prices = await _prices(db_session, market)
        assert sum(prices.values()) == pytest.approx(1.0, abs=1e-9)
        assert len(prices) == 3
        # Each outcome is individually addressable and none collapsed to zero.
        assert all(p > 0 for p in prices.values())


class TestQuoteOnParimutuel:
    async def test_quote_returns_a_real_price_for_the_outcome(
        self, db_session, multi_outcome_market, test_user
    ):
        """It used to raise AMM_NOT_AVAILABLE - the workaround, now removed."""
        market = multi_outcome_market
        quote = await OrderService.compute_quote(
            db_session,
            user_id=str(test_user.id),
            market_id=str(market.id),
            outcome_name=AWAY,
            side="buy",
            amount=Decimal(100),
        )

        assert 0 < float(quote["price_before"]) < 1


class TestBinaryMarketsUnchanged:
    async def test_binary_order_fills_from_the_single_pool(
        self, db_session, test_market, test_user
    ):
        pool_before = await _shares(db_session, test_market)
        assert len(pool_before) == 1, "a binary market keeps exactly one pool"

        result = await OrderService.execute_order(
            db_session, test_user, _request(test_market, "yes")
        )
        assert result.status == "filled"

        pool_after = await _shares(db_session, test_market)
        assert pool_after != pool_before

    async def test_binary_quote_still_works(
        self, db_session, test_market, test_user
    ):
        quote = await OrderService.compute_quote(
            db_session,
            user_id=str(test_user.id),
            market_id=str(test_market.id),
            outcome_name="yes",
            side="buy",
            amount=Decimal(100),
        )
        assert 0 < float(quote["price_before"]) < 1

    async def test_binary_yes_and_no_stay_complementary(
        self, db_session, test_market
    ):
        prices = MarketService.compute_prices(
            await MarketService.load_binary_pool(db_session, test_market.id)
        )
        assert prices[0] + prices[1] == pytest.approx(1.0, abs=1e-9)