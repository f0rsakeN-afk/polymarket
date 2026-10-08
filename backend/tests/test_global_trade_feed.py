"""The platform-wide trade feed must actually deliver.

Two independent defects made `/trades` permanently dead, and neither surfaced as
an error - the feed just stayed empty while everything else looked healthy.

1. `RedisPubSub.listen` routed channels by splitting on `:` and matching the first
   segment. `"global:trades"` splits into two segments, so it always entered the
   `len(parts) >= 2` branch, matched neither `market` nor `user`, and fell out of
   the loop. The `elif channel == "global:trades"` clause meant to handle it was
   unreachable, which made `broadcast_global` dead code.
2. `broadcast_global` fanned out to every socket on the node, so even once wired
   up it would have leaked other markets' trades into every open market page.

Real Redis pub/sub, mirroring `test_websocket_multinode.py` - the bug was in
channel routing, so the test has to exercise real channel names to catch it.
"""
import asyncio
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.websocket.manager import (
    GLOBAL_TRADES_CHANNEL,
    GLOBAL_TRADES_KEY,
    ConnectionManager,
    RedisPubSub,
)

# Sanity-check the constant the whole file routes on. A silent rename here would
# make every routing test pass while the real `/ws/trades` socket sat under a
# different key and received nothing.
assert GLOBAL_TRADES_CHANNEL == "global:trades"
assert GLOBAL_TRADES_KEY.startswith("__")


class FakeSocket:
    """Minimal WebSocket stand-in that records what it was sent."""

    def __init__(self):
        self.accepted = False
        self.sent: list[dict] = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent.append(payload)


async def _settle(predicate, bus: RedisPubSub, tries: int = 50):
    """Poll until `predicate` holds; pub/sub delivery is asynchronous."""
    for _ in range(tries):
        await asyncio.sleep(0.02)
        if predicate():
            return True
    return False


@pytest.mark.asyncio
async def test_a_global_trade_reaches_a_global_trades_socket():
    """The regression: a `global:trades` publish must reach its subscriber."""
    from app.websocket.manager import manager as global_manager

    node = ConnectionManager()
    bus = RedisPubSub()
    await bus.connect()

    trade_socket = FakeSocket()
    # Registered the way `/ws/trades` does it.
    await node.connect(trade_socket, GLOBAL_TRADES_KEY, client_ip="1.2.3.4")

    with patch.object(global_manager, "broadcast_global", node.broadcast_global):
        await bus.subscribe_global_trades()
        await bus.start_listener()
        try:
            await bus.publish_global_trade(
                {"market_id": str(uuid4()), "outcome": "Yes", "price": "0.62"}
            )
            await _settle(lambda: bool(trade_socket.sent), bus)

            assert trade_socket.sent, (
                "a global:trades publish reached nobody • the feed is dead. This "
                "was the unreachable `elif channel == 'global:trades'` branch: the "
                "channel splits into two parts on ':', so it never reached it"
            )
            assert trade_socket.sent[0]["type"] == "trade:new"
        finally:
            await bus.close()


@pytest.mark.asyncio
async def test_a_global_trade_does_not_leak_into_a_market_socket():
    """A market page must not receive other markets' trades.

    `broadcast_global` used to enumerate every socket in `_market_subs`, so a
    global trade reached every open market page - and the market page's handler
    only filtered on `type == 'trade:new'`, so it would have rendered another
    market's trade in its own feed.
    """
    from app.websocket.manager import manager as global_manager

    node = ConnectionManager()
    bus = RedisPubSub()
    await bus.connect()

    market_socket = FakeSocket()
    global_socket = FakeSocket()
    await node.connect(market_socket, str(uuid4()), client_ip="5.6.7.8")
    await node.connect(global_socket, GLOBAL_TRADES_KEY, client_ip="9.9.9.9")

    with patch.object(global_manager, "broadcast_global", node.broadcast_global):
        await bus.subscribe_global_trades()
        await bus.start_listener()
        try:
            await bus.publish_global_trade(
                {"market_id": str(uuid4()), "outcome": "Yes", "price": "0.40"}
            )
            await _settle(lambda: bool(global_socket.sent), bus)

            assert not market_socket.sent, (
                "a global trade leaked into a market-page socket • the market page "
                "would show another market's trade in its own feed"
            )
            assert global_socket.sent, "the global socket must still receive it"
        finally:
            await bus.close()


@pytest.mark.asyncio
async def test_market_channels_still_route_by_prefix():
    """Guards the fix against regressing the branch that already worked."""
    from app.websocket.manager import manager as global_manager

    node = ConnectionManager()
    bus = RedisPubSub()
    await bus.connect()

    market_id = str(uuid4())
    market_socket = FakeSocket()
    await node.connect(market_socket, market_id, client_ip="1.1.1.1")

    with patch.object(global_manager, "broadcast_to_market", node.broadcast_to_market):
        await bus.subscribe_market(market_id)
        await bus.start_listener()
        try:
            await bus.publish_price_update(market_id, 0.62, 0.38, 10.0)
            await _settle(lambda: bool(market_socket.sent), bus)

            assert market_socket.sent, "market price routing regressed"
            assert market_socket.sent[0]["type"] == "market:price_update"
        finally:
            await bus.close()


@pytest.mark.asyncio
async def test_broadcast_global_with_no_subscribers_is_a_no_op():
    """No subscriber must not raise - the sweeper publishes on quiet markets."""
    node = ConnectionManager()
    await node.broadcast_global({"type": "trade:new"})