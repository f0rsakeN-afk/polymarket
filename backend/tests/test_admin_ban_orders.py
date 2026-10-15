"""A ban must not strand the funds it prevents the user from releasing.

## The failure

`PATCH /admin/users/{id}/ban` deactivated the account and revoked every session,
and left open orders exactly where they were. Only BUY orders lock USDC, and a
resting BUY order keeps `remaining_amount` reserved in `wallet.locked_balance`
until it fills or is cancelled.

So a banned user ends up with money reserved against a market they are locked out
of, and are unreachable to release it - their sessions are revoked, so they
cannot even see the order. Account deletion already refuses for precisely this
state (`AccountDeletionBlockedError`); a ban was quietly creating it.

## Why cancelled rather than refused

The obvious alternative is to refuse the ban with a 409, matching deletion. That
is wrong here. A ban is frequently urgent - fraud, abuse, a stolen account being
used right now - and a resting order is a reason to act *faster*, not a reason to
make an admin wait for a support ticket.

So the orders are cancelled and the funds are **released, not confiscated**:
`balance` is untouched, `locked_balance` comes back down, and unban leaves the
user with their money available.

## Why each order goes through `cancel_order`

Because removing a resting order makes every *other* client's orderbook stale,
and that push has to happen per order, exactly as it does for a user-initiated
cancel. A second implementation of "release the funds" would eventually drift -
publishing a fill without releasing, or releasing without publishing - and that
divergence surfaces as a wallet that does not add up.
"""

from decimal import Decimal

import pytest
from conftest import token_for
from httpx import AsyncClient
from sqlalchemy import select

from app.models.audit import AdminAuditEvent
from app.models.order import Order
from app.models.wallet import Transaction, Wallet


async def _resting_buy(db_session, user, market, *, amount="10", price="0.40", status="pending"):
    """A resting BUY order, which is what actually locks funds.

    SELL orders reserve shares rather than USDC, so a test that only ever creates
    sells would pass while the real stranding path stayed broken.
    """
    order = Order(
        user_id=user.id,
        market_id=market.id,
        outcome_id=market.outcomes[0].id,
        side="buy",
        order_type="limit",
        amount=Decimal(amount),
        price=Decimal(price),
        remaining_amount=Decimal(amount),
        status=status,
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order


async def _locked(db_session, user_id) -> Decimal:
    wallet = (
        await db_session.execute(select(Wallet).where(Wallet.user_id == user_id))
    ).scalar_one()
    return Decimal(str(wallet.locked_balance))


async def _as_admin(client, user):
    client.cookies.set("access_token", token_for(user.id))


@pytest.mark.asyncio
async def test_banning_cancels_resting_orders(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    order = await _resting_buy(db_session, test_user, test_market)
    await _as_admin(client, admin_user)

    resp = await client.patch(f"/api/v1/admin/users/{test_user.id}/ban")

    assert resp.status_code == 200, resp.text
    assert str(order.id) in resp.json()["data"]["cancelled_order_ids"]

    await db_session.refresh(order)
    assert order.status == "cancelled", (
        "the order is still resting after a ban - a banned user cannot cancel it, "
        "so its funds are reserved with nobody able to release them"
    )


@pytest.mark.asyncio
async def test_banning_releases_the_locked_funds(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """The balance is untouched; only the lock comes down.

    Conflating the two would be confiscation dressed as an admin action, and it
    would make `unban` a lie - the user would come back to less money than they
    left with.
    """
    await _resting_buy(db_session, test_user, test_market, amount="10")
    wallet = (
        await db_session.execute(select(Wallet).where(Wallet.user_id == test_user.id))
    ).scalar_one()
    balance_before = Decimal(str(wallet.balance))
    wallet.locked_balance = Decimal(10)
    await db_session.commit()

    await _as_admin(client, admin_user)
    resp = await client.patch(f"/api/v1/admin/users/{test_user.id}/ban")
    assert resp.status_code == 200

    await db_session.refresh(wallet)
    assert Decimal(str(wallet.locked_balance)) == Decimal(0), (
        "the ban did not release the reserved funds"
    )
    assert Decimal(str(wallet.balance)) == balance_before, (
        "the ban moved the balance as well as the lock - that is confiscation"
    )


@pytest.mark.asyncio
async def test_a_partial_order_is_also_cancelled(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """`partial` still holds `remaining_amount`, so leaving it behind strands funds
    exactly as a `pending` one does."""
    order = await _resting_buy(db_session, test_user, test_market, status="partial", amount="10")
    await _as_admin(client, admin_user)

    await client.patch(f"/api/v1/admin/users/{test_user.id}/ban")

    await db_session.refresh(order)
    assert order.status == "cancelled"


@pytest.mark.asyncio
async def test_a_filled_order_is_left_alone(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """Only live orders are cancelled. A filled order is history.

    Rewriting it would corrupt the record of a trade that actually happened.
    """
    order = await _resting_buy(db_session, test_user, test_market, status="filled")
    await _as_admin(client, admin_user)

    await client.patch(f"/api/v1/admin/users/{test_user.id}/ban")

    await db_session.refresh(order)
    assert order.status == "filled"


@pytest.mark.asyncio
async def test_banning_does_not_touch_the_ledger(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """A ban moves no money. Deposits, trades and referrals stay as they were."""
    tx = Transaction(
        user_id=test_user.id,
        wallet_id=None,
        type="deposit",
        amount=Decimal(100),
        balance_after=Decimal(1000),
    )
    wallet = (
        await db_session.execute(select(Wallet).where(Wallet.user_id == test_user.id))
    ).scalar_one()
    tx.wallet_id = wallet.id
    db_session.add(tx)
    await _resting_buy(db_session, test_user, test_market)
    await db_session.commit()
    tx_id = tx.id

    await _as_admin(client, admin_user)
    await client.patch(f"/api/v1/admin/users/{test_user.id}/ban")

    assert await db_session.get(Transaction, tx_id) is not None, (
        "a ban rewrote the ledger - cancelling a resting order releases a lock, "
        "it does not move money"
    )


@pytest.mark.asyncio
async def test_the_audit_names_the_orders_it_cancelled(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """Which orders were pulled, and the funds released, is the first question
    anyone asks after a ban - so it belongs in the trail, not in a log line."""
    order = await _resting_buy(db_session, test_user, test_market)
    await _as_admin(client, admin_user)

    await client.patch(f"/api/v1/admin/users/{test_user.id}/ban")

    rows = (
        await db_session.execute(
            select(AdminAuditEvent).where(AdminAuditEvent.action == "user_banned")
        )
    ).scalars().all()
    assert rows, "the ban was not audited"
    payload = rows[0].payload or {}
    assert str(order.id) in (payload.get("cancelled_order_ids") or []), (
        "the audit does not record which orders were cancelled, so the released "
        "funds cannot be reconciled afterwards"
    )


@pytest.mark.asyncio
async def test_banning_with_no_open_orders_still_works(
    client: AsyncClient, db_session, admin_user, test_user
):
    """The common case must not depend on the sweep having found anything."""
    await _as_admin(client, admin_user)

    resp = await client.patch(f"/api/v1/admin/users/{test_user.id}/ban")

    assert resp.status_code == 200
    assert resp.json()["data"]["cancelled_order_ids"] == []


@pytest.mark.asyncio
async def test_unban_leaves_the_funds_available(
    client: AsyncClient, db_session, admin_user, test_user, test_market
):
    """The end-to-end promise: ban then unban is a round trip, not a loss."""
    wallet = (
        await db_session.execute(select(Wallet).where(Wallet.user_id == test_user.id))
    ).scalar_one()
    balance_before = Decimal(str(wallet.balance))
    wallet.locked_balance = Decimal(10)
    await _resting_buy(db_session, test_user, test_market, amount="10")
    await db_session.commit()

    await _as_admin(client, admin_user)
    await client.patch(f"/api/v1/admin/users/{test_user.id}/ban")
    await client.patch(f"/api/v1/admin/users/{test_user.id}/unban")

    await db_session.refresh(wallet)
    assert Decimal(str(wallet.balance)) == balance_before
    assert Decimal(str(wallet.locked_balance)) == Decimal(0)