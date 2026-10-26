"""Adding liquidity must not move the price.

`add_liquidity` split every deposit 50/50 across both reserve sides. That
preserves the YES/NO ratio only on a pool that is already 50/50 - which is exactly
the state a freshly created market is in, and exactly the state a traded market is
not. So the bug was invisible in testing and present on every market anyone had
actually traded:

    pool at YES 57.10 / NO 50.00   price 0.5331
    + 50 USDC, even split          YES 82.10 / NO 75.00   price 0.5226  <- moved

An LP could shift the market by depositing, against existing holders, while their
LP tokens were minted at a flat 2x that ignored the move entirely.

Two knock-on effects made this worse than a cosmetic mispricing:

  - the deposit's own slippage guard fired on it, rejecting a legitimate deposit
    with "adverse price movement" for a move the depositor had caused;
  - LP tokens were minted at 2x regardless of the price the deposit had shifted.

Market creation already seeded proportionally (`yes_shares += amount * prob`), so
this makes deposits consistent with it.

Parimutuel pools are excluded on purpose: there `yes_shares` is the outcome's
share of the *market* total and `no_shares` is a derived cache, so there is no
independent NO side to hold in proportion. Funding one outcome of a shared-total
book legitimately raises that outcome's price.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.amm.engine import BinaryAMM
from app.models.liquidity import LiquidityPool
from app.models.market import Outcome
from app.services.liquidity_service import LiquidityService
from app.websocket.manager import redis_pubsub

D = Decimal


def _no_publish():
    return (
        patch.object(redis_pubsub, "publish_price_update", new=AsyncMock()),
        patch.object(redis_pubsub, "publish_market_event", new=AsyncMock()),
    )


def _trade(pool: LiquidityPool, outcome: str, collateral_in: D) -> None:
    amm = BinaryAMM(pool.yes_shares, pool.no_shares, pool.fee_rate or D("0.02"))
    amm.buy("yes" if outcome.lower() == "yes" else "no", collateral_in)
    pool.yes_shares = amm.yes_shares
    pool.no_shares = amm.no_shares
    pool.collateral = (pool.collateral or D(0)) + collateral_in


def _price_yes(pool: LiquidityPool) -> D:
    total = D(str(pool.yes_shares)) + D(str(pool.no_shares))
    return D(str(pool.yes_shares)) / total


async def _pool(db, market_id) -> LiquidityPool:
    return (
        await db.execute(
            select(LiquidityPool).where(
                LiquidityPool.market_id == market_id,
                LiquidityPool.outcome_id.is_(None),
            )
        )
    ).scalar_one()


@pytest.fixture
async def skewed_pool(db_session, test_market):
    """A funded pool that has traded away from 50/50."""
    pool = await _pool(db_session, test_market.id)
    pool.yes_shares = D("50")
    pool.no_shares = D("50")
    pool.collateral = D("100")
    pool.lp_token_supply = D("200")
    await db_session.commit()

    _trade(pool, "yes", D("40"))
    await db_session.commit()
    assert _price_yes(pool) > D("0.5"), "precondition: pool must be skewed"
    return pool


async def test_depositing_into_a_traded_pool_does_not_move_the_price(
    db_session, test_user, test_market, skewed_pool
):
    """The regression: a deposit must be price-neutral."""
    before = _price_yes(skewed_pool)

    p1, p2 = _no_publish()
    with p1, p2:
        await LiquidityService.add_liquidity(
            db_session, test_user, str(test_market.id), D("50")
        )

    after = _price_yes(skewed_pool)
    assert after == pytest.approx(before, abs=D("0.0000001")), (
        f"depositing moved the price from {before} to {after} • the deposit was "
        "not split in proportion to the reserves"
    )


async def test_the_deposit_is_split_in_proportion_to_reserves(
    db_session, test_user, test_market, skewed_pool
):
    """Check the arithmetic, not just the invariant.

    y' = y(1 + X/T) and n' = n(1 + X/T).
    """
    pool = await _pool(db_session, test_market.id)
    y, n, total = D(str(pool.yes_shares)), D(str(pool.no_shares)), (
        D(str(pool.yes_shares)) + D(str(pool.no_shares))
    )
    amount = D("50")

    p1, p2 = _no_publish()
    with p1, p2:
        await LiquidityService.add_liquidity(
            db_session, test_user, str(test_market.id), amount
        )

    assert D(str(pool.yes_shares)) == pytest.approx(y * (1 + amount / total), abs=D("0.000001"))
    assert D(str(pool.no_shares)) == pytest.approx(n * (1 + amount / total), abs=D("0.000001"))
    # And the escrow still rises by the full amount.
    assert D(str(pool.collateral)) == pytest.approx(D("140") + amount, abs=D("0.000001"))


async def test_an_unseeded_binary_pool_still_bootstraps_evenly(
    db_session, test_user, test_market
):
    """No reserves means no ratio to preserve, so an even split is correct."""
    pool = await _pool(db_session, test_market.id)
    pool.yes_shares = D(0)
    pool.no_shares = D(0)
    pool.collateral = D(0)
    pool.lp_token_supply = D(0)
    await db_session.commit()

    p1, p2 = _no_publish()
    with p1, p2:
        await LiquidityService.add_liquidity(
            db_session, test_user, str(test_market.id), D("50")
        )

    assert D(str(pool.yes_shares)) == D("25")
    assert D(str(pool.no_shares)) == D("25")
    assert _price_yes(pool) == D("0.5")


async def test_depositing_into_a_skewed_pool_is_not_rejected_as_adverse(
    db_session, test_user, test_market, skewed_pool
):
    """The slippage guard must not fire on the depositor's own move.

    With an even split, a large deposit into a skewed pool moved the price by more
    than the tolerance and the request was refused with "adverse price movement" -
    the depositor being blocked because of a shift they caused.
    """
    pool = await _pool(db_session, test_market.id)
    pool.yes_shares = D("80")
    pool.no_shares = D("20")
    pool.collateral = D("100")
    pool.lp_token_supply = D("200")
    await db_session.commit()

    p1, p2 = _no_publish()
    with p1, p2:
        # Default tolerance is 5%; the even split shifted this by ~11%.
        await LiquidityService.add_liquidity(
            db_session, test_user, str(test_market.id), D("100")
        )

    assert _price_yes(pool) == pytest.approx(D("0.8"), abs=D("0.0000001"))


async def test_a_pool_with_one_side_empty_stays_price_neutral(
    db_session, test_user, test_market, skewed_pool
):
    """Degenerate reserves: a proportional deposit must not invent the other side."""
    pool = await _pool(db_session, test_market.id)
    pool.yes_shares = D("0")
    pool.no_shares = D("40")
    pool.collateral = D("40")
    pool.lp_token_supply = D("80")
    await db_session.commit()

    p1, p2 = _no_publish()
    with p1, p2:
        await LiquidityService.add_liquidity(
            db_session, test_user, str(test_market.id), D("10")
        )

    # Price stays at 0 - adding liquidity must not fabricate YES depth.
    assert _price_yes(pool) == D(0)
    assert D(str(pool.no_shares)) == pytest.approx(D("50"), abs=D("0.000001"))


async def test_parimutuel_pool_behaviour_is_unchanged(
    db_session, test_user, multi_outcome_market
):
    """Explicitly pins the carve-out.

    On a parimutuel pool `no_shares` is a derived cache of `total - shares_i`, so
    there is no independent NO side to keep in proportion and the even split stays.
    This test exists so a future "fix" to that path is a deliberate change rather
    than an accident.
    """
    market_id = str(multi_outcome_market.id)
    pool = (
        await db_session.execute(
            select(LiquidityPool)
            .where(
                LiquidityPool.market_id == multi_outcome_market.id,
                LiquidityPool.outcome_id.isnot(None),
            )
            .limit(1)
        )
    ).scalar_one()
    outcome = (
        await db_session.execute(
            select(Outcome).where(Outcome.id == pool.outcome_id)
        )
    ).scalar_one()

    yes_before = D(str(pool.yes_shares))
    no_before = D(str(pool.no_shares))

    p1, p2 = _no_publish()
    with p1, p2:
        await LiquidityService.add_liquidity(
            db_session, test_user, market_id, D("30"), outcome_name=outcome.name
        )

    assert D(str(pool.yes_shares)) == yes_before + D("15")
    assert D(str(pool.no_shares)) == no_before + D("15")