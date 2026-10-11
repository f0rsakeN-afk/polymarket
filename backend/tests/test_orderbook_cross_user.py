"""Does one user's trade move the book on *everyone else's* screen?

The question this file answers is the one the whole realtime layer exists for:
user A places an order, and user B - who is looking at the same market and did
nothing at all - sees the book change immediately.

The mechanism has three links, and any one of them can be missing while the
product still looks fine in a single-user demo:

  1. The write path rebuilds the book and publishes it to the market's channel.
  2. The fan-out delivers to every socket subscribed to that market, on every
     API node - not just the one that handled the order.
  3. The client applies it to the cache the orderbook component actually reads.

A break in (1) means the book is stale for everyone but the actor; a break in
(2) means it only updates for users who happen to be on the node that processed
the order; a break in (3) means the frame arrives and is discarded.

`_push_orderbook` is the single chokepoint for (1), which is why every
book-changing path funnels through it.
"""
from unittest.mock import patch

import pytest
from conftest import token_for

from app.models.order import Order


class _BookCapture:
    """Records every orderbook the server publishes, with its market."""

    def __init__(self):
        self.events: list[tuple[str, str, dict]] = []
        self.market_events: list[tuple[str, str, dict]] = []

    async def publish_market_event(self, market_id, event_type, data=None):
        self.market_events.append((str(market_id), event_type, data or {}))

    async def publish_price_update(self, *a, **k):
        pass

    async def publish_global_trade(self, *a, **k):
        pass

    async def publish_order_fill(self, *a, **k):
        pass

    async def publish_user_event(self, *a, **k):
        pass

    async def publish_notification(self, *a, **k):
        pass

    def orderbooks(self, market_id: str) -> list[dict]:
        return [d for m, t, d in self.market_events
                if m == str(market_id) and t == "orderbook:update"]


@pytest.mark.asyncio
async def test_a_resting_order_reaches_other_users_through_the_market_channel(
    client, test_user, test_market, db_session
):
    """The core property: one user's order, published to everyone watching.

    Not "the actor sees their own order" - that always works, because the actor's
    own client can reconcile optimistically. This asserts the *market channel*
    carried the frame, which is the only path user B's socket can receive it on.
    """
    client.cookies.set("access_token", token_for(test_user.id))
    capture = _BookCapture()
    with patch("app.services.order_service.redis_pubsub", capture):
        resp = await client.post("/api/v1/orders/", json={
            "market_id": str(test_market.id),
            "outcome": "yes",
            "side": "buy",
            "order_type": "limit",
            "amount": 20.0,
            "price": 0.30,  # below the 50/50 pool, so it rests
        })
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] in ("pending", "partial")

    books = capture.orderbooks(str(test_market.id))
    assert books, (
        "a resting order was placed and no orderbook:update was published - the "
        "book on every other user's screen still shows the pre-order levels"
    )


@pytest.mark.asyncio
async def test_the_published_book_contains_the_new_level(
    client, test_user, test_market, db_session
):
    """Publishing an empty or stale book is as broken as publishing nothing.

    The frame has to carry the level that was just added, or every client
    repaints itself back to the same state it already had - which looks exactly
    like the frame never arriving.
    """
    client.cookies.set("access_token", token_for(test_user.id))
    capture = _BookCapture()
    with patch("app.services.order_service.redis_pubsub", capture):
        resp = await client.post("/api/v1/orders/", json={
            "market_id": str(test_market.id),
            "outcome": "yes",
            "side": "buy",
            "order_type": "limit",
            "amount": 25.0,
            "price": 0.30,
        })
    assert resp.status_code == 200, resp.text

    books = capture.orderbooks(str(test_market.id))
    assert books, "nothing published"

    latest = books[-1]
    # `build_orderbook` keys by lower-cased outcome name.
    yes = latest.get("yes") or (latest.get("outcomes") or {}).get("yes")
    assert yes is not None, f"no yes-outcome book in the payload: {latest.keys()}"
    bids = yes.get("bids") or []
    assert any(
        abs(float(b.get("price")) - 0.30) < 1e-9 for b in bids
    ), f"the 0.30 bid is missing from the published book: {bids}"


@pytest.mark.asyncio
async def test_a_cancel_is_published_so_the_level_disappears_everywhere(
    client, test_user, test_market, db_session
):
    """The removal half.

    Placing an order is the case everyone tests. Cancelling is the one that
    silently rots: if only the add is published, a level stays on every screen
    after it no longer exists, and the book shows liquidity that cannot be
    traded - the worst kind of wrong, because it looks entirely plausible.
    """
    client.cookies.set("access_token", token_for(test_user.id))
    rest = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "limit",
        "amount": 15.0,
        "price": 0.28,
    })
    assert rest.status_code == 200, rest.text
    order_id = rest.json()["data"]["order_id"]

    capture = _BookCapture()
    with patch("app.services.order_service.redis_pubsub", capture):
        cancel = await client.delete(f"/api/v1/orders/{order_id}")
    assert cancel.status_code == 200, cancel.text

    books = capture.orderbooks(str(test_market.id))
    assert books, (
        "an order was cancelled and no orderbook:update was published - the "
        "cancelled level stays visible on every other user's screen"
    )

    latest = books[-1]
    yes = latest.get("yes") or (latest.get("outcomes") or {}).get("yes")
    bids = yes.get("bids") or []
    assert not any(
        abs(float(b.get("price")) - 0.28) < 1e-9 for b in bids
    ), f"the cancelled 0.28 bid is still in the published book: {bids}"


@pytest.mark.asyncio
async def test_expiry_publishes_the_book_so_the_level_disappears_everywhere(
    client, test_user, test_market, db_session
):
    """Expiry removes a resting order, and used to say nothing.

    `expire_stale_orders` marks the order expired, releases the locked funds and
    invalidates the REST cache - but published no orderbook frame. Every open
    page kept showing the expired level as tradable until a manual reload, which
    is precisely the "the book lies to you" failure the rest of this layer
    exists to remove.
    """
    from datetime import UTC, datetime, timedelta

    client.cookies.set("access_token", token_for(test_user.id))
    rest = await client.post("/api/v1/orders/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "side": "buy",
        "order_type": "limit",
        "amount": 12.0,
        "price": 0.26,
    })
    assert rest.status_code == 200, rest.text

    # `.scalar_one()` matters: `execute` returns a Result, and setting an
    # attribute on it silently does nothing - so the order was never backdated,
    # the sweeper found nothing to expire, and the assertion below failed for a
    # reason that had nothing to do with the bug it was written for.
    order = (
        await db_session.execute(select_one_order(rest.json()["data"]["order_id"]))
    ).scalar_one()
    order.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.commit()

    capture = _BookCapture()
    # `_push_orderbook` is defined in `order_service` and resolves
    # `redis_pubsub` from *that* module's globals, so patching the tasks module
    # alone leaves the book push going to the real bus. Both, or the assertion
    # fails for a reason unrelated to the bug.
    with patch("app.workers.tasks.redis_pubsub", capture), \
         patch("app.services.order_service.redis_pubsub", capture):
        import asyncio

        from app.workers.tasks import expire_stale_orders
        await asyncio.to_thread(expire_stale_orders.run)

    books = capture.orderbooks(str(test_market.id))
    assert books, (
        "an order expired - removing a tradable level - and no orderbook:update "
        "was published. Every open page keeps showing an expired order as live "
        "liquidity until someone reloads."
    )

    latest = books[-1]
    yes = latest.get("yes") or (latest.get("outcomes") or {}).get("yes")
    bids = yes.get("bids") or []
    assert not any(
        abs(float(b.get("price")) - 0.26) < 1e-9 for b in bids
    ), f"the expired 0.26 bid is still published as live liquidity: {bids}"


def select_one_order(order_id: str):
    """A SELECT for one order, as a statement object for `db_session.execute`."""
    import uuid

    from sqlalchemy import select

    return select(Order).where(Order.id == uuid.UUID(order_id))


@pytest.mark.asyncio
async def test_the_frame_is_on_the_market_channel_any_other_client_listens_to(
    client, test_user, test_market, db_session
):
    """Link (2): the channel name must match what `/ws/markets/{id}` subscribes.

    A publish to a channel nobody is subscribed to is indistinguishable from no
    publish at all - Redis accepts the PUBLISH, no error is raised, and the
    frame is simply dropped. Asserting the channel explicitly is what catches a
    rename that leaves both sides compiling.
    """
    from app.websocket.manager import market_events_channel

    client.cookies.set("access_token", token_for(test_user.id))
    capture = _BookCapture()
    with patch("app.services.order_service.redis_pubsub", capture):
        await client.post("/api/v1/orders/", json={
            "market_id": str(test_market.id),
            "outcome": "yes",
            "side": "buy",
            "order_type": "limit",
            "amount": 18.0,
            "price": 0.24,
        })

    published = capture.market_events
    assert published, "nothing was published at all"

    # `publish_market_event` derives the channel from the market id; assert the
    # derived name is the one the socket endpoint subscribes to.
    assert market_events_channel(str(test_market.id)) == f"market:{test_market.id}:events"
    assert any(t == "orderbook:update" for _, t, _ in published)