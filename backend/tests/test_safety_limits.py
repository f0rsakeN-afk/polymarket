"""Circuit breakers and event-driven triggers around the trading engine.

Three protections that only become visible when something is about to go
wrong, plus the trigger that keeps resting limit orders from going stale:

* an LP exit must never take escrow that open positions still need • at
  resolution only ONE side is paid $1 per share, so the floor is the larger
  side's unsettled shares plus protocol fees still owed;
* split and merge mint and burn real shares, so the AMM reserves have to move
  with them (they used not to, which locked split-created shares out of the
  AMM sell path);
* a fill wakes the limit-order sweeper instead of leaving an order whose
  price just got crossed waiting for the next 30s beat tick.
"""
from decimal import Decimal
from unittest.mock import patch

import pytest
from conftest import token_for
from httpx import AsyncClient
from sqlalchemy import select

from app.models.liquidity import LiquidityPool, LPShare
from app.models.market import Outcome
from app.models.position import Position

D = Decimal


async def _get_pool(db, market_id) -> LiquidityPool:
    return (
        await db.execute(
            select(LiquidityPool)
            .where(LiquidityPool.market_id == market_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _balance(db, user_id) -> Decimal:
    from app.models.wallet import Wallet

    wallet = (
        await db.execute(
            select(Wallet)
            .where(Wallet.user_id == user_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return wallet.balance


# ── Split / merge keep AMM reserves in step ───────────────────────────────────

@pytest.mark.asyncio
async def test_split_and_merge_move_amm_reserves_with_the_shares(
    client: AsyncClient, test_user, test_market, db_session
):
    """A split mints `amount_after_fee` shares of EACH side, a merge burns
    `amount` of each • the AMM reserves have to follow, or the shares the
    split just handed out cannot be sold back (``amm.sell`` refuses to pay
    out more than the reserve holds). Both sides always move by the same
    amount, so the price ratio is untouched."""
    client.cookies.set("access_token", token_for(test_user.id))

    before = await _get_pool(db_session, test_market.id)
    yes0, no0 = before.yes_shares, before.no_shares

    resp = await client.post("/api/v1/split-merge/split", json={
        "market_id": str(test_market.id), "amount": 20.0,
    })
    assert resp.status_code == 200, resp.text

    pool = await _get_pool(db_session, test_market.id)
    minted = D("20") * (D("1") - D("0.02"))   # 2% split fee
    assert pool.yes_shares == yes0 + minted
    assert pool.no_shares == no0 + minted
    # Equal growth on both sides ⇒ the quoted price is exactly where it was.
    price_before = yes0 / (yes0 + no0)
    price_after = pool.yes_shares / (pool.yes_shares + pool.no_shares)
    assert price_after == price_before

    resp = await client.post("/api/v1/split-merge/merge", json={
        "market_id": str(test_market.id), "amount": 10.0,
    })
    assert resp.status_code == 200, resp.text

    pool = await _get_pool(db_session, test_market.id)
    assert pool.yes_shares == yes0 + minted - D("10")
    assert pool.no_shares == no0 + minted - D("10")


# ── LP exit escrow floor ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lp_exit_cannot_take_escrow_away_from_open_positions(
    client: AsyncClient, test_user, test_market, db_session
):
    """Withdrawals are refused once the remaining escrow would no longer cover
    the worst case at settlement (the larger side's unsettled shares • only
    one side is ever paid • plus protocol fees still owed). Without the floor
    an LP could empty the pool while traders still hold shares, and
    settlement would have to short-change them."""
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.post(f"/api/v1/markets/{test_market.id}/liquidity", json={"amount": 50.0})
    assert resp.status_code == 200, resp.text

    # The user is now an LP *and* a trader holding far more open claims than
    # their slice of the escrow would leave behind.
    yes_outcome = (
        await db_session.execute(
            select(Outcome).where(Outcome.market_id == test_market.id, Outcome.name.ilike("yes"))
        )
    ).scalar_one()
    db_session.add(Position(
        user_id=test_user.id,
        market_id=test_market.id,
        outcome_id=yes_outcome.id,
        shares_held=D("120"),
        average_price=D("0.5"),
    ))
    await db_session.commit()

    pool = await _get_pool(db_session, test_market.id)
    lp = (
        await db_session.execute(
            select(LPShare).where(LPShare.pool_id == pool.id, LPShare.user_id == test_user.id)
        )
    ).scalar_one()

    fraction = lp.lp_tokens / pool.lp_token_supply
    payout = pool.collateral * fraction
    withdrawable = pool.collateral - D("120") - pool.protocol_fees
    # Preconditions • otherwise the assertions below prove nothing.
    assert payout > withdrawable, "full slice must exceed the floor for this test"
    assert withdrawable > 0, "partial withdrawal must still be possible"

    # Scalars, not the row: `_get_pool` hands back the identity-mapped
    # instance, so a later successful withdrawal mutates it in place.
    collateral_then = pool.collateral
    supply_then = pool.lp_token_supply

    w0 = await _balance(db_session, test_user.id)
    resp = await client.request(
        "DELETE", f"/api/v1/markets/{test_market.id}/liquidity",
        json={"lp_tokens": str(lp.lp_tokens)},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "ESCROW_FLOOR"

    # Nothing moved: no escrow left, no wallet credit, no burned LP tokens.
    after = await _get_pool(db_session, test_market.id)
    assert after.collateral == collateral_then
    assert after.lp_token_supply == supply_then
    assert await _balance(db_session, test_user.id) == w0

    # A slice that fits the floor still goes through.
    half = lp.lp_tokens / 2
    if pool.collateral * (half / pool.lp_token_supply) <= withdrawable:
        resp = await client.request(
            "DELETE", f"/api/v1/markets/{test_market.id}/liquidity",
            json={"lp_tokens": str(half)},
        )
        assert resp.status_code == 200, resp.text
        assert (await _get_pool(db_session, test_market.id)).collateral < collateral_then


@pytest.mark.asyncio
async def test_lp_exit_still_works_when_no_positions_are_open(
    client: AsyncClient, test_user, test_market, db_session
):
    """The floor must not stand in the ordinary case: with no open claims the
    whole pro-rata slice is withdrawable."""
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.post(f"/api/v1/markets/{test_market.id}/liquidity", json={"amount": 50.0})
    assert resp.status_code == 200, resp.text

    pool = await _get_pool(db_session, test_market.id)
    lp = (
        await db_session.execute(
            select(LPShare).where(LPShare.pool_id == pool.id, LPShare.user_id == test_user.id)
        )
    ).scalar_one()

    resp = await client.request(
        "DELETE", f"/api/v1/markets/{test_market.id}/liquidity",
        json={"lp_tokens": str(lp.lp_tokens)},
    )
    assert resp.status_code == 200, resp.text


# ── Fills wake the limit-order sweeper ────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_fill_enqueues_the_limit_order_sweep_immediately(
    client: AsyncClient, test_user, test_market, db_session
):
    """`celery beat` only runs the limit-order sweep every 30s. A fill moves
    the price, so an order sitting on the other side of it may already be
    fillable • waiting up to half a minute is a filled order the trader did
    not get. The sweep is therefore enqueued right after the fill (throttled
    to one per second by a Redis NX key)."""
    from app.redis import get_redis

    client.cookies.set("access_token", token_for(test_user.id))

    r = await get_redis()
    await r.delete("limit_check:enqueued")   # ignore the throttle for this assertion

    with patch("app.workers.tasks.check_limit_order_execution.delay") as sweep:
        resp = await client.post("/api/v1/orders/", json={
            "market_id": str(test_market.id),
            "outcome": "yes",
            "side": "buy",
            "order_type": "market",
            "amount": 10.0,
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "filled"
        sweep.assert_called_once()
