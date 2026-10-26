"""Expiry is a change to *your* order and *your* balance, so it must reach you.

`expire_stale_orders` releases the locked remainder of a buy order - real money
moving back into available balance - and used to publish only to the market
channel. Every market page refreshed for everyone while the owner kept a
"pending" order on screen that no longer existed, holding funds they could no
longer see released.

Same omission the fill and cancel paths had, and worth pinning separately
because "the market updated but my screen did not" is the exact shape of the
original report - and this was the instance that survived the first pass.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from conftest import token_for
from sqlalchemy import select

from app.models.order import Order


class _Capture:
    def __init__(self):
        self.fills: list[tuple[str, dict]] = []
        self.user_events: list[tuple[str, dict]] = []
        self.market_events: list[tuple[str, str, dict]] = []

    async def publish_order_fill(self, user_id, data):
        self.fills.append((str(user_id), data))

    async def publish_user_event(self, user_id, data):
        self.user_events.append((str(user_id), data))

    async def publish_market_event(self, market_id, event_type, data=None):
        self.market_events.append((str(market_id), event_type, data or {}))


async def _run_task(task):
    """Invoke a Celery task body the way a worker would, minus the broker.

    Every task here is a `@shared_task` whose body runs a nested coroutine
    through `celery_run()`, which needs a thread with no running loop. Calling it
    inline from an async test deadlocks on the event loop.
    """
    return await asyncio.to_thread(task.run)


async def _rest_expiring_orders(client, db_session, market, token, count=1):
    """Place `count` resting buy orders and backdate them past expiry."""
    client.cookies.set("access_token", token)
    ids = []
    for _ in range(count):
        resp = await client.post("/api/v1/orders/", json={
            "market_id": str(market.id),
            "outcome": "yes",
            "side": "buy",
            "order_type": "limit",
            "amount": 10.0,
            "price": 0.05,  # far below the pool, so it rests rather than fills
        })
        assert resp.status_code == 200, resp.text
        ids.append(resp.json()["data"]["order_id"])

    rows = await db_session.execute(
        select(Order).where(Order.id.in_([uuid.UUID(i) for i in ids]))
    )
    for order in rows.scalars().all():
        order.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.commit()
    return ids


@pytest.mark.asyncio
async def test_expiry_publishes_to_the_owner_not_just_the_market(
    client, test_user, test_market, db_session
):
    """The book changed for everyone; the owner's order and balance changed for them."""
    from app.workers.tasks import expire_stale_orders

    order_ids = await _rest_expiring_orders(
        client, db_session, test_market, token_for(test_user.id)
    )

    capture = _Capture()
    with patch("app.workers.tasks.redis_pubsub", capture):
        await _run_task(expire_stale_orders)

    assert capture.market_events, (
        "the market must still hear about it - a level left the book"
    )
    assert any(t == "order:expired" for _, t, _ in capture.market_events)

    owner_fills = [d for uid, d in capture.fills if uid == str(test_user.id)]
    assert owner_fills, (
        "the owner's order expired and their locked funds were released, but "
        "nothing was published to them - their orders page keeps showing a "
        "pending order that no longer exists"
    )
    assert owner_fills[0]["status"] == "expired"
    assert order_ids[0] in owner_fills[0]["order_ids"]

    owner_events = [d for uid, d in capture.user_events if uid == str(test_user.id)]
    assert owner_events, (
        "the owner's order/position caches need invalidating too, or the list "
        "keeps rendering the expired row"
    )
    assert owner_events[0]["status"] == "expired"


@pytest.mark.asyncio
async def test_several_expiring_orders_produce_one_message(
    client, test_user, test_market, db_session
):
    """One user with three dead orders gets one message naming all three.

    The sweeper drains in batches and a busy user can easily have several orders
    expire together. Three identical toasts and three bell entries is noise; one
    message saying how many is the useful thing.
    """
    from app.workers.tasks import expire_stale_orders

    order_ids = await _rest_expiring_orders(
        client, db_session, test_market, token_for(test_user.id), count=3
    )

    capture = _Capture()
    with patch("app.workers.tasks.redis_pubsub", capture):
        await _run_task(expire_stale_orders)

    owner_fills = [d for uid, d in capture.fills if uid == str(test_user.id)]
    assert len(owner_fills) == 1, (
        f"expected one aggregated message, got {len(owner_fills)}"
    )
    assert set(owner_fills[0]["order_ids"]) == set(order_ids), (
        "all three order ids should be named in the single message"
    )


@pytest.mark.asyncio
async def test_expiry_releases_the_locked_funds(client, test_user, test_market, db_session):
    """Sanity on the underlying behaviour: expiry is money, not just a status."""
    from app.models.wallet import Wallet

    await _rest_expiring_orders(client, db_session, test_market, token_for(test_user.id))

    wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == test_user.id)
    )).scalar_one()
    locked_before = wallet.locked_balance

    from app.workers.tasks import expire_stale_orders
    capture = _Capture()
    with patch("app.workers.tasks.redis_pubsub", capture):
        await _run_task(expire_stale_orders)

    await db_session.refresh(wallet)
    assert wallet.locked_balance < locked_before, (
        "the unspent remainder must come back to the available balance - which "
        "is exactly why the owner has to be told"
    )