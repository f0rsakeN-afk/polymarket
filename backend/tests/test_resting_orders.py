"""A resting limit order must actually exist.

`OrderService.execute_order` has one commit, at the end of the fill path. The
"AMM price is worse than my limit, leave it resting" branch returned an
`OrderResult` from *inside* the function — before that commit — so on the way
out `get_db` closed the session and rolled the whole thing back.

The visible effects, in order of how much they hurt:

1. **Resting limit orders do not exist.** The row is discarded. Every limit
   order that doesn't cross the spread immediately is gone, so the whole
   resting-order feature — and the 350-line sweeper that services it — has
   never had anything to service in production.
2. **The client is told it worked.** A 200 with `status: "pending"` and
   `order_id: ""`, so the UI shows "order resting" for an order the platform
   never stored, and any follow-up cancel/poll by that id has nothing to find.
3. **The locked funds vanish too.** `wallet.locked_balance += remaining_usdc`
   was rolled back with it, so the balance is self-consistent — nothing is
   stolen — but nothing is reserved either.

These tests assert against a *second* session, because the endpoint's session
can see its own uncommitted writes and would happily hide the bug.
"""
from decimal import Decimal

import pytest
from conftest import token_for
from sqlalchemy import func, select

from app.models.order import Order
from app.models.wallet import Wallet

D = Decimal


async def _committed_orders_for(db, market_id: str) -> int:
    """Count order rows that survive a rollback.

    The endpoint's session is the test session, so it can read its own
    uncommitted writes — which is exactly how this bug stayed invisible. A
    rollback is the discriminator: committed data survives it, uncommitted
    data is discarded. So "row still there after rollback" means "committed".
    """
    await db.rollback()
    result = await db.execute(
        select(func.count(Order.id)).where(Order.market_id == market_id)
    )
    return result.scalar_one()


@pytest.mark.asyncio
async def test_a_resting_limit_order_is_persisted(client, test_user, test_market, db_session):
    """The regression, stated directly: place a limit buy priced below the
    market and it must be a real row afterwards."""
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "limit",
        "amount": 10.0,
        "price": 0.45,          # pool is 50/50 → price 0.50, so this rests
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] in ("pending", "partial")

    # 1. The client gets a usable id. An empty one cannot be cancelled,
    #    polled, or shown in the order history.
    assert data["order_id"], (
        "resting order returned an empty order_id — the client has nothing to "
        "track, cancel or poll"
    )

    # 2. The row survives the request. This is the actual bug: it used to be
    #    rolled back because the branch returned before the single commit.
    committed = await _committed_orders_for(db_session, str(test_market.id))
    assert committed == 1, (
        f"expected the resting order to be committed, found {committed} rows "
        "visible from a separate session — it was rolled back"
    )

    order = (
        await client.get(f"/api/v1/orders/{data['order_id']}")
    )
    assert order.status_code == 200
    assert order.json()["data"]["status"] in ("pending", "partial")


@pytest.mark.asyncio
async def test_a_resting_order_holds_its_funds_locked(client, test_user, test_market, db_session):
    """Locked balance is what stops the same money being spent twice while the
    order waits. If it is not locked, a resting order is a promise the wallet
    cannot keep."""
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "limit",
        "amount": 10.0,
        "price": 0.45,
    })
    assert resp.status_code == 200, resp.text

    assert await _committed_orders_for(db_session, str(test_market.id)) == 1
    wallet = (
        await db_session.execute(
            select(Wallet)
            .where(Wallet.user_id == test_user.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert wallet.locked_balance == D("10"), (
        "a resting buy must keep its budget locked in a committed row, "
        "or it can be spent twice"
    )


@pytest.mark.asyncio
async def test_a_resting_order_reports_real_prices_not_zeros(
    client, test_user, test_market, db_session
):
    """The resting response hardcoded `yes_price_after = 0` and
    `no_price_after = 0`. A client rendering those shows a 0/0 market, and
    anything computing off them (slippage, chart) is working from fiction —
    even though no trade happened, so the prices are simply unchanged."""
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "limit",
        "amount": 10.0,
        "price": 0.45,
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    pool = (
        await client.get(f"/api/v1/markets/{test_market.slug}")
    ).json()["data"]
    yes = Decimal(str(pool["yes_price"]))
    no = Decimal(str(pool["no_price"]))

    assert D(data["yes_price_after"]) == yes
    assert D(data["no_price_after"]) == no
    # Unchanged by definition: no leg executed.
    assert D(data["price_after"]) == D(data["price_before"])


@pytest.mark.asyncio
async def test_a_resting_order_can_then_be_cancelled(
    client, test_user, test_market, db_session
):
    """The end-to-end user story: place a limit order that rests, then cancel
    it, and get the locked money back. Needs the order to exist first."""
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "limit",
        "amount": 10.0,
        "price": 0.45,
    })
    order_id = resp.json()["data"]["order_id"]

    cancel = await client.delete(f"/api/v1/orders/{order_id}")
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["data"]["status"] == "cancelled"

    assert await _committed_orders_for(db_session, str(test_market.id)) == 1
    wallet = (
        await db_session.execute(
            select(Wallet)
            .where(Wallet.user_id == test_user.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert wallet.locked_balance == D("0"), "cancel must release the locked funds"

    order = (
        await db_session.execute(
            select(Order).where(Order.id == order_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert order.status == "cancelled"


@pytest.mark.asyncio
async def test_a_market_order_that_fills_is_unaffected(client, test_user, test_market, db_session):
    """Guard against over-correcting: the immediate-fill path always
    committed, and must still return its real id."""
    client.cookies.set("access_token", token_for(test_user.id))

    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": 10.0,
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "filled"
    assert data["order_id"]
    assert await _committed_orders_for(db_session, str(test_market.id)) == 1


@pytest.mark.asyncio
async def test_a_sell_limit_order_below_the_market_also_rests(
    client, test_user, test_market, db_session
):
    """The sell side of the same branch — it shares the code path, so it needs
    the same guarantee."""
    client.cookies.set("access_token", token_for(test_user.id))

    # Buy first — you cannot sell shares you don't hold.
    buy = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "market",
        "amount": 10.0,
    })
    assert buy.status_code == 200, buy.text

    resp = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "sell",
        "order_type": "limit",
        "amount": 5.0,
        "price": 0.70,          # market is 0.50, so a sell at 0.70 rests
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] in ("pending", "partial")
    assert data["order_id"]

    # Two rows: the market buy that created the position, plus the resting sell.
    assert await _committed_orders_for(db_session, str(test_market.id)) == 2