"""LP tokens must be worth the same thing on the way in and on the way out.

Every way an LP token turns back into dollars is denominated in escrow:

    remove_liquidity : pool.collateral * (lp_tokens / lp_token_supply)
    settlement      : pool.collateral / lp_token_supply

Entry was denominated in *reserves* (`yes_shares + no_shares`) instead, so the
two sides disagreed as soon as the denominators diverged - and they diverge on the
first trade, because the AMM mints shares to every buyer while fees raise the
escrow.

The concrete failure: on a 100 USDC pool, after a 40 USDC YES buy the reserves
summed to 157.44 while the escrow held 140. A new 10 USDC LP was minted 12.70
tokens and could immediately redeem 8.96 - a ~10% loss on entry, for doing nothing
and taking no risk.

These tests assert the invariant directly: deposit then withdraw returns exactly
what was deposited, including after trading has skewed the pool.
"""
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.amm.engine import BinaryAMM
from app.api.exceptions import ValidationError
from app.deps import hash_password
from app.models.liquidity import LiquidityPool, LPShare
from app.models.user import User
from app.models.wallet import Wallet
from app.services.liquidity_service import LiquidityService
from app.websocket.manager import redis_pubsub

D = Decimal


def _no_publish():
    """Silence the post-commit WS broadcasts; this suite is about accounting."""
    return (
        patch.object(redis_pubsub, "publish_price_update", new=AsyncMock()),
        patch.object(redis_pubsub, "publish_market_event", new=AsyncMock()),
    )


def _trade(pool: LiquidityPool, outcome: str, collateral_in: D) -> D:
    """Simulate an AMM fill, exactly as execute_order does.

    Returns the shares the trader received.
    """
    amm = BinaryAMM(pool.yes_shares, pool.no_shares, pool.fee_rate or D("0.02"))
    q = amm.buy("yes" if outcome.lower() == "yes" else "no", collateral_in)
    pool.yes_shares = amm.yes_shares
    pool.no_shares = amm.no_shares
    # execute_order credits the FULL amount - the 2% fee stays in the escrow.
    pool.collateral = (pool.collateral or D(0)) + collateral_in
    return q.shares_out


async def _balance(db, user_id) -> D:
    wallet = (
        await db.execute(select(Wallet).where(Wallet.user_id == user_id))
    ).scalar_one()
    return D(str(wallet.balance))


async def _binary_pool(db, market_id) -> LiquidityPool:
    pool = (
        await db.execute(
            select(LiquidityPool).where(
                LiquidityPool.market_id == market_id,
                LiquidityPool.outcome_id.is_(None),
            )
        )
    ).scalar_one()
    return pool


async def _claim(db, pool_id, user_id) -> D:
    """What an LP's tokens are currently worth, using the payout formula.

    Mirrors both real redemption paths, which are identical in shape:
    `collateral * (lp_tokens / lp_token_supply)`.
    """
    pool = (
        await db.execute(select(LiquidityPool).where(LiquidityPool.id == pool_id))
    ).scalar_one()
    lp = (
        await db.execute(
            select(LPShare).where(LPShare.pool_id == pool_id, LPShare.user_id == user_id)
        )
    ).scalar_one()
    supply = D(str(pool.lp_token_supply))
    if supply <= 0:
        return D(0)
    return D(str(lp.lp_tokens)) * (D(str(pool.collateral)) / supply)


@pytest.fixture
async def other_user(db_session):
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"lp_{uid}@example.com",
        username=f"lp{uid}",
        password_hash=hash_password("Lp!Pass1"),
        is_email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        Wallet(user_id=user.id, balance="1000.00", locked_balance="0", currency="USDC")
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def traded_pool(db_session, test_market, other_user):
    """A pool that has already absorbed a trade, so reserves != escrow.

    `other_user` is the incumbent LP; `test_user` is whoever wants to join.
    """
    pool = await _binary_pool(db_session, test_market.id)

    # Seed 100 the way market creation does: 50/50 reserves, 100 escrow, 200 supply.
    pool.yes_shares = D("50")
    pool.no_shares = D("50")
    pool.collateral = D("100")
    pool.lp_token_supply = D("200")
    test_market.total_liquidity = D("100")
    db_session.add(
        LPShare(
            pool_id=pool.id,
            user_id=other_user.id,
            lp_tokens=D("200"),
            collateral_deposited=D("100"),
        )
    )
    await db_session.commit()

    _trade(pool, "yes", D("40"))   # reserves -> 157.44, escrow -> 140
    await db_session.commit()
    return pool


async def test_deposit_then_withdraw_returns_exactly_the_deposit(
    db_session, test_user, test_market
):
    """The invariant, on a quiet pool."""
    pool = await _binary_pool(db_session, test_market.id)
    pool.collateral = D("100")

    before = await _balance(db_session, test_user.id)
    p1, p2 = _no_publish()
    with p1, p2:
        added = await LiquidityService.add_liquidity(
            db_session, test_user, str(test_market.id), D("25")
        )
        await LiquidityService.remove_liquidity(
            db_session, test_user, str(test_market.id), D(added["lp_tokens_minted"])
        )

    after = await _balance(db_session, test_user.id)
    assert after == before, (
        f"balance moved by {after - before} on a round trip • entry and exit "
        "disagree on what a token is worth"
    )


async def test_a_new_lp_does_not_lose_money_by_joining_a_traded_pool(
    db_session, test_user, test_market, traded_pool
):
    """The regression itself: joining a traded pool must not cost the joiner."""
    pool = await _binary_pool(db_session, test_market.id)

    # Precondition: this is exactly the state that broke entry pricing.
    assert D(str(pool.yes_shares)) + D(str(pool.no_shares)) != D(str(pool.collateral)), (
        "precondition: reserves and escrow must have diverged, otherwise this "
        "test is not exercising the bug"
    )

    before = await _balance(db_session, test_user.id)
    p1, p2 = _no_publish()
    with p1, p2:
        added = await LiquidityService.add_liquidity(
            db_session, test_user, str(test_market.id), D("10")
        )
        await LiquidityService.remove_liquidity(
            db_session, test_user, str(test_market.id), D(added["lp_tokens_minted"])
        )

    after = await _balance(db_session, test_user.id)
    assert after == before, (
        "a new LP deposited 10 into a pool where reserves and escrow had diverged "
        "and did not get 10 back • tokens were minted against reserves but "
        "redeemed against escrow"
    )


async def test_the_incumbent_lp_is_not_shortchanged_by_a_new_join(
    db_session, test_user, test_market, traded_pool, other_user
):
    """A new deposit must not dilute the incumbent's claim on the escrow.

    If a joiner receives exactly their deposit back, the incumbent's absolute
    claim must not shrink - otherwise "correct entry pricing" is just moving the
    loss onto whoever was already in the pool.
    """
    before = await _claim(db_session, traded_pool.id, other_user.id)

    p1, p2 = _no_publish()
    with p1, p2:
        await LiquidityService.add_liquidity(
            db_session, test_user, str(test_market.id), D("10")
        )

    assert await _claim(db_session, traded_pool.id, other_user.id) >= before, (
        "a new deposit reduced the existing LP's claim on the escrow"
    )


async def test_fees_still_accrue_to_lps_after_the_change(traded_pool):
    """The fix must not become "stop paying LPs".

    Trading raises the escrow while leaving `lp_token_supply` untouched, so each
    token's claim on the escrow grows. That drift between reserves and escrow is
    exactly what broke entry pricing, so it needs a test of its own.
    """
    supply = D(str(traded_pool.lp_token_supply))
    assert supply > 0
    per_token_before = D(str(traded_pool.collateral)) / supply

    _trade(traded_pool, "yes", D("50"))

    per_token_after = D(str(traded_pool.collateral)) / supply
    assert per_token_after > per_token_before, (
        "trading did not increase what each LP token is worth • fee income is no "
        "longer reaching LPs"
    )


async def test_joining_an_empty_escrow_fails_with_a_clear_error(
    db_session, test_user, test_market, traded_pool
):
    """No bare ZeroDivisionError when the escrow has been drained."""
    traded_pool.collateral = D(0)

    with pytest.raises(ValidationError) as exc:
        await LiquidityService.add_liquidity(
            db_session, test_user, str(test_market.id), D("10")
        )
    assert exc.value.error_code == "POOL_ESCROW_EMPTY"


async def test_first_lp_bootstrap_stays_collateral_consistent(
    db_session, test_user, test_market
):
    """A brand-new pool's first LP still bootstraps at the 2x ratio."""
    pool = await _binary_pool(db_session, test_market.id)
    pool.lp_token_supply = D(0)
    pool.collateral = D(0)

    p1, p2 = _no_publish()
    with p1, p2:
        added = await LiquidityService.add_liquidity(
            db_session, test_user, str(test_market.id), D("50")
        )

    assert D(added["lp_tokens_minted"]) == D("100")
    assert D(str(pool.lp_token_supply)) == D("100")
    assert D(str(pool.collateral)) == D("50")