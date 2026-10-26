"""Every path that changes the resting book must push it.

The orderbook push used to live only on the fill path. That looked complete until
you check what `build_orderbook` actually selects: pending limit / fill-or-kill
orders only. A fully-filled market order lands as `status="filled"` and is
filtered out, so the one path that published never changed the book - while the
two paths that *do* change it published nothing:

  - a limit order resting in the book (the early-return branch in `execute_order`,
    which returns before the notification block ever runs), and
  - a cancellation, which only invalidated the cache.

The result was a book that was never visibly wrong, just permanently behind on
every already-open client.

These tests assert the *publish call happens*, not that a message arrives - the
routing and fan-out are covered in `test_global_trade_feed.py` and
`test_websocket_multinode.py`. What matters here is that each book-changing code
path reaches the publish at all, which is exactly what was missing.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

D = Decimal


@pytest.fixture
def spy_push():
    """Patch `_push_orderbook` so tests assert the call without doing Redis work."""
    with patch(
        "app.services.order_service._push_orderbook", new=AsyncMock()
    ) as mock:
        yield mock


@pytest.mark.asyncio
async def test_a_resting_limit_order_pushes_the_book(
    client, test_user, test_market, spy_push
):
    """Placing a limit order that rests adds a level to the book.

    This is the path that returned from inside `execute_order` before the
    notification block, so it never told anyone the book had grown.
    """
    client.cookies.set("access_token", _token(test_user.id))

    resp = await client.post(
        "/api/v1/orders/",
        json={
            "market_id": str(test_market.id),
            "outcome": "yes",
            "side": "buy",
            "order_type": "limit",
            "amount": 10.0,
            "price": 0.45,  # pool is 50/50, so this rests rather than filling
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] in ("pending", "partial")

    spy_push.assert_awaited_once()
    assert spy_push.await_args.args[0] == str(test_market.id), (
        "the book push must name the market whose book changed"
    )


@pytest.mark.asyncio
async def test_a_market_order_that_fills_pushes_the_book(
    client, test_user, test_market, spy_push
):
    """A fill consumes resting maker orders, so the book changes here too."""
    client.cookies.set("access_token", _token(test_user.id))

    resp = await client.post(
        "/api/v1/orders/",
        json={
            "market_id": str(test_market.id),
            "outcome": "yes",
            "side": "buy",
            "order_type": "market",
            "amount": 10.0,
        },
    )
    assert resp.status_code == 200, resp.text
    spy_push.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelling_a_resting_order_pushes_the_book(
    client, test_user, test_market, spy_push
):
    """Cancelling removes a level, so every other client needs to hear about it.

    It used to only invalidate the cache, which fixed the next REST read and left
    every already-open orderbook - including the canceller's own - stale.
    """
    client.cookies.set("access_token", _token(test_user.id))

    placed = await client.post(
        "/api/v1/orders/",
        json={
            "market_id": str(test_market.id),
            "outcome": "yes",
            "side": "buy",
            "order_type": "limit",
            "amount": 10.0,
            "price": 0.45,
        },
    )
    order_id = placed.json()["data"]["order_id"]
    spy_push.reset_mock()

    cancel = await client.delete(f"/api/v1/orders/{order_id}")
    assert cancel.status_code == 200, cancel.text

    spy_push.assert_awaited_once_with(str(test_market.id))


@pytest.mark.asyncio
async def test_a_rejected_order_pushes_nothing(client, test_user, test_market, spy_push):
    """Guard against over-correcting: an order that never touched the book must
    not claim it did. A failed order leaves no trace in the resting book."""
    client.cookies.set("access_token", _token(test_user.id))

    resp = await client.post(
        "/api/v1/orders/",
        json={
            "market_id": str(test_market.id),
            "outcome": "yes",
            "side": "buy",
            "order_type": "market",
            "amount": 10.0,
            "max_slippage": 0.0000001,  # tighter than any real fill
        },
    )
    # Either outcome is fine; what matters is that a non-fill does not publish a
    # book change it did not make.
    if resp.status_code != 200:
        spy_push.assert_not_awaited()


@pytest.mark.asyncio
async def test_push_orderbook_uses_its_own_session():
    """`_push_orderbook` must not borrow the caller's session.

    Every caller has already committed, and borrowing the request session would
    open a second transaction on a session the caller still owns. Closing that
    transaction is worse than leaving it: SQLAlchemy expires every loaded instance
    on rollback, so a shared session would leave the caller holding detached
    objects whose attribute access then raises `MissingGreenlet` outside a greenlet
    context. Own session, own lifetime.
    """
    entered: list[str] = []

    class _SessionCtx:
        async def __aenter__(self):
            entered.append("enter")
            return object()

        async def __aexit__(self, *exc):
            entered.append("exit")
            return False

    with patch(
        "app.services.order_service.async_session",
        new=lambda: _SessionCtx(),
    ), patch(
        "app.services.order_service.build_orderbook",
        new=AsyncMock(return_value={"outcomes": {}}),
    ), patch(
        "app.services.order_service.cache_set_orderbook", new=AsyncMock()
    ), patch(
        "app.services.order_service.redis_pubsub.publish_market_event", new=AsyncMock()
    ):
        from app.services.order_service import _push_orderbook

        await _push_orderbook("mkt-1")

    assert entered == ["enter", "exit"], (
        "_push_orderbook must open and close its own session so it never leaves a "
        "transaction on a session the caller still owns"
    )


def _token(user_id) -> str:
    from conftest import token_for

    return token_for(user_id)