"""The Redis listener must survive starting with zero subscriptions.

This is the bug that made every live update dead in production, and it is
invisible to a test that subscribes before starting the listener.

redis-py's `PubSub.listen()` is literally:

    async def listen(self):
        while self.subscribed:            # bool(self.channels or ...)
            ...

The app starts this listener during lifespan startup, when *nothing* is
subscribed yet - subscriptions only arrive later, when the first WebSocket
connects. So the loop condition was false on entry, the generator returned
immediately, and the listener task completed. Later `subscribe_market()` calls
still registered the channels, which is why `PUBSUB CHANNELS` listed them while
nothing was ever delivered: Redis accepted the SUBSCRIBE, but there was no
consumer left to read the messages. Every price frame, trade and orderbook push
was published into a channel nobody was listening to.

`test_live_updates_e2e.py` passed throughout because it subscribes *before*
calling `start_listener()` - the opposite order to production. These tests use
the production order.

Real Redis, because the failure depends on redis-py's own loop condition.
"""
import asyncio
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.websocket.manager import GLOBAL_TRADES_KEY, ConnectionManager, RedisPubSub


class FakeSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def accept(self):
        return None

    async def send_json(self, payload):
        self.sent.append(payload)


async def _await(sock: FakeSocket, tries: int = 60) -> bool:
    for _ in range(tries):
        await asyncio.sleep(0.02)
        if sock.sent:
            return True
    return False


@pytest.mark.asyncio
async def test_listener_survives_starting_with_no_subscriptions():
    """Production order: the listener starts first, subscriptions come later."""
    bus = RedisPubSub()
    await bus.connect()
    await bus.start_listener()
    try:
        # Nothing is subscribed yet - exactly the lifespan-startup state.
        await asyncio.sleep(0.3)

        assert bus._listener_task is not None
        assert not bus._listener_task.done(), (
            "the listener completed immediately because redis-py's listen() is "
            "`while self.subscribed:` and nothing was subscribed yet. Every frame "
            "published afterwards has no consumer."
        )
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_a_channel_subscribed_after_the_listener_started_still_delivers():
    """The bug's actual consequence, not just its symptom."""
    from app.websocket.manager import manager as global_manager

    node = ConnectionManager()
    bus = RedisPubSub()
    await bus.connect()
    await bus.start_listener()          # <- BEFORE any subscription
    await asyncio.sleep(0.2)

    market_id = str(uuid4())
    sock = FakeSocket()
    await node.connect(sock, market_id, client_ip="10.9.9.1")

    with patch.object(global_manager, "broadcast_to_market", node.broadcast_to_market):
        # Subscribed after the listener is already running.
        await bus.subscribe_market(market_id)
        await asyncio.sleep(0.2)
        await bus.publish_price_update(market_id, 0.71, 0.29, 10.0)
        delivered = await _await(sock)

        assert delivered, (
            "a channel subscribed AFTER the listener started received nothing • "
            "this is the production ordering, and it is why live updates never "
            "arrived in the running app"
        )
        assert sock.sent[0]["yes_price"] == 0.71

    await bus.close()


@pytest.mark.asyncio
async def test_the_listener_task_is_still_running_after_a_delivery():
    """Guards against a fix that only works for the first message."""
    bus = RedisPubSub()
    await bus.connect()
    await bus.start_listener()
    await asyncio.sleep(0.2)

    for i in range(5):
        await bus.publish_price_update(str(uuid4()), 0.5 + i / 100, 0.5 - i / 100, 1.0)
        await asyncio.sleep(0.1)
        assert not bus._listener_task.done(), f"listener died after frame {i}"

    await bus.close()


@pytest.mark.asyncio
async def test_start_listener_is_idempotent_and_restartable():
    """`start_listener` must not leave a completed task behind."""
    bus = RedisPubSub()
    await bus.connect()

    await bus.start_listener()
    first = bus._listener_task
    await asyncio.sleep(0.1)

    # Calling again while healthy must not spawn a second consumer, which would
    # double-deliver every frame.
    await bus.start_listener()
    assert bus._listener_task is first, "start_listener spawned a duplicate listener"

    # After a clean close it must be startable again.
    await bus.close()
    await bus.start_listener()
    await asyncio.sleep(0.1)
    assert bus._listener_task is not None and not bus._listener_task.done(), (
        "listener could not be restarted after close()"
    )
    await bus.close()


@pytest.mark.asyncio
async def test_a_global_trade_subscribed_after_startup_still_delivers():
    """Same ordering hazard for the global feed."""
    from app.websocket.manager import manager as global_manager

    node = ConnectionManager()
    bus = RedisPubSub()
    await bus.connect()
    await bus.start_listener()
    await asyncio.sleep(0.2)

    sock = FakeSocket()
    await node.connect(sock, GLOBAL_TRADES_KEY, client_ip="10.9.9.2")

    with patch.object(global_manager, "broadcast_global", node.broadcast_global):
        await bus.subscribe_global_trades()
        await asyncio.sleep(0.2)
        await bus.publish_global_trade({"market_id": str(uuid4()), "outcome": "Yes"})
        delivered = await _await(sock)

        assert delivered, "global feed subscribed after startup received nothing"

    await bus.close()