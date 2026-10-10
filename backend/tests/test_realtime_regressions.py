"""Realtime regressions: the bugs that made feeds go silently dead.

Every test here corresponds to a failure that looked like "the WebSocket is
flaky" from the outside while the socket itself was healthy - connected,
subscribed, counted, and delivering nothing. That is what makes these worth
pinning: none of them fail loudly in normal use, they just quietly serve stale
or missing data.
"""

import asyncio
import json

import pytest

from app.websocket.manager import (
    ConnectionManager,
    RedisPubSub,
    market_events_channel,
    market_seq_key,
    user_manager,
)

# ── Reference counting ────────────────────────────────────────────────────────


class _FakePubSub:
    """Records the channel set the client is subscribed to."""

    def __init__(self):
        self.channels: set[str] = set()
        self.subscribe_calls = 0
        self.unsubscribe_calls = 0

    async def subscribe(self, *channels):
        self.subscribe_calls += 1
        self.channels.update(channels)

    async def unsubscribe(self, *channels):
        self.unsubscribe_calls += 1
        for ch in channels:
            self.channels.discard(ch)

    @property
    def subscribed(self) -> bool:
        return bool(self.channels)


def _bus_with_pubsub() -> tuple[RedisPubSub, _FakePubSub]:
    bus = RedisPubSub()
    fake = _FakePubSub()
    bus._pubsub = fake  # type: ignore[assignment]
    bus._connected = True
    return bus, fake


@pytest.mark.asyncio
async def test_one_socket_leaving_does_not_unsubscribe_the_others():
    """THE bug: two sockets, one market, one leaves -> the other goes blind.

    The registry was a `set`, so the first release dropped the channel for the
    whole worker. The survivor stayed in `_market_subs`, stayed counted, stayed
    "connected" - and received nothing for the rest of its life. Nothing in the
    logs said a word.

    This is not a corner case: the frontend shares one tab-wide socket between
    the market detail page and the trending carousel, so both can be watching
    the same market at once, and navigating off one silently killed the other.
    """
    bus, fake = _bus_with_pubsub()
    market = "market-1"
    channel = market_events_channel(market)

    # Two local sockets subscribe.
    await bus.subscribe_market(market)
    await bus.subscribe_market(market)
    assert channel in fake.channels

    # One of them goes away.
    await bus.unsubscribe_market(market)

    assert channel in fake.channels, (
        "the second subscriber still wants this market, but the channel was "
        "dropped process-wide - it is now connected to nothing"
    )
    assert bus._refs[channel] == 1

    # Only the last one leaving releases it.
    await bus.unsubscribe_market(market)
    assert channel not in fake.channels
    assert channel not in bus._refs


@pytest.mark.asyncio
async def test_subscribe_is_remembered_while_redis_is_down():
    """A Redis blip must not lose a subscription for the life of the process.

    `subscribe_market` used to bail out when there was no pubsub client and
    record nothing. The socket was already in `_market_subs`, so it looked
    subscribed - and the replay on reconnect had no idea it existed, so it never
    came back.
    """
    bus = RedisPubSub()
    bus._pubsub = None  # simulating the window inside `listen()`'s reconnect

    await bus.subscribe_market("market-1")

    assert market_events_channel("market-1") in bus._refs, (
        "intent must be recorded even when the client is down, or the reconnect "
        "replay has nothing to restore"
    )


@pytest.mark.asyncio
async def test_reconnect_replays_intent_not_stale_state():
    """After a dropped connection, the replay set is what sockets want now."""
    bus, fake = _bus_with_pubsub()
    market = "market-1"

    await bus.subscribe_market(market)
    # Market A is released while the connection is down.
    await bus._release(market_events_channel("market-A"))
    await bus._release(market_events_channel("market-A"))

    await bus._drop_pubsub()
    bus._pubsub = fake  # type: ignore[assignment]

    assert await bus._reconnect() is True
    assert market_events_channel(market) in fake.channels
    assert market_events_channel("market-A") not in fake.channels


@pytest.mark.asyncio
async def test_notification_channels_are_released_on_disconnect():
    """Every login used to leak two Redis subscriptions per worker, forever.

    `unsubscribe_user` did not exist, so a worker's channel list grew by two per
    notification connection for the life of the process and `listen()` polled
    all of them on every tick.
    """
    bus, fake = _bus_with_pubsub()
    await bus.subscribe_user("user-1")
    assert "user:user-1:fills" in fake.channels
    assert "user:user-1:notifications" in fake.channels

    await bus.unsubscribe_user("user-1")
    assert "user:user-1:fills" not in fake.channels
    assert "user:user-1:notifications" not in fake.channels


# ── Sequencing ────────────────────────────────────────────────────────────────


class _RecordingRedis:
    """Captures the Lua-mediated publish, direct or inside a pipeline.

    `publish_market_event` issues a bare `EVAL` (one command, one round-trip);
    `publish_price_update` batches the same `EVAL` with its cache HSET and the
    `dirty:markets` marker. Both paths have to be observable.
    """

    def __init__(self):
        self.published: list[str] = []
        self.eval_calls: list[tuple] = []

    def pipeline(self):
        return _RecordingPipeline(self)

    async def eval(self, script, numkeys, *keys_and_args):
        self.eval_calls.append((numkeys, keys_and_args))
        self.published.append(keys_and_args[-1])
        return 1


class _RecordingPipeline:
    def __init__(self, owner):
        self._owner = owner

    def hset(self, *a, **k):
        return self

    def expire(self, *a, **k):
        return self

    def sadd(self, *a, **k):
        return self

    def eval(self, script, numkeys, *keys_and_args):
        self._owner.eval_calls.append((numkeys, keys_and_args))
        self._owner.published.append(keys_and_args[-1])
        return self

    async def execute(self):
        return None


@pytest.mark.asyncio
async def test_every_market_frame_is_sequenced():
    """Frames carry a `seq` so a client can prove it missed nothing.

    Without it there is no way to tell a delivered frame from a lost one, so a
    dropped frame left the UI permanently stale with nothing to notice - and on
    a market that then went quiet, nothing would ever correct it.
    """
    bus = RedisPubSub()
    fake = _RecordingRedis()
    bus._redis = fake  # type: ignore[assignment]

    from unittest.mock import patch

    async def _call(op):
        return await op()

    with patch("app.websocket.manager.redis_cb.call", new=_call):
        await bus.publish_market_event("m1", "trade:new", {"id": "t1"})

    # The fake applies the same substitution the Lua script does - quotes
    # included - so this asserts the real on-wire shape.
    payload = json.loads(fake.published[0].replace('"__SEQ__"', "7"))
    assert payload["seq"] == 7, (
        "seq must be a JSON number, not a string - a stringified seq is "
        "silently rejected by the client's numeric gap check"
    )
    assert isinstance(payload["seq"], int)
    # seq key and channel are handed to the script in that order.
    assert fake.eval_calls[0][1][0] == market_seq_key("m1")
    assert fake.eval_calls[0][1][1] == market_events_channel("m1")


@pytest.mark.asyncio
async def test_price_and_events_share_one_channel_and_one_sequence_space():
    """One channel per market means one order for everything on that market.

    They used to be two channels published in separate round-trips, so two
    concurrent orders could interleave price(A), price(B), trade(A), book(A),
    and a client would render a book that contradicted the price beside it with
    no way to detect it.
    """
    bus = RedisPubSub()
    fake = _RecordingRedis()
    bus._redis = fake  # type: ignore[assignment]

    from unittest.mock import patch

    async def _call(op):
        return await op()

    with patch("app.websocket.manager.redis_cb.call", new=_call):
        await bus.publish_price_update("m1", 0.6, 0.4, 10.0)
        await bus.publish_market_event("m1", "trade:new", {"id": "t1"})

    channels = [call[1][1] for call in fake.eval_calls]
    seq_keys = [call[1][0] for call in fake.eval_calls]
    assert channels == [market_events_channel("m1")] * 2
    assert seq_keys == [market_seq_key("m1")] * 2


@pytest.mark.asyncio
async def test_a_failing_publish_is_logged_and_counted_not_swallowed():
    """`except RedisError: pass` made a Redis outage delete live data silently.

    It also skipped the `dirty:markets` marker that drives the limit-order
    executor, so resting orders quietly stopped being serviced - all with
    nothing in the logs and nothing to alert on.
    """
    bus = RedisPubSub()
    bus._redis = object()  # will blow up inside the circuit breaker

    from unittest.mock import patch

    async def _boom(op):
        raise RuntimeError("redis is down")

    with patch("app.websocket.manager.redis_cb.call", new=_boom):
        # Must not raise: the trade already committed and a failed publish
        # cannot un-commit it. But it must not be silent either.
        await bus.publish_price_update("m1", 0.6, 0.4, 10.0)
        await bus.publish_global_trade({"id": "t1"})

    from app.middleware.metrics import WS_PUBLISH_FAILURES

    assert WS_PUBLISH_FAILURES.labels("price_update")._value.get() >= 1
    assert WS_PUBLISH_FAILURES.labels("global_trade")._value.get() >= 1


# ── Private frames keep their type ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_user_event_preserves_its_type():
    """`position:update` never once reached a client.

    `publish_notification` stamps `type: "notification"` over whatever the
    caller passed, so the worker that publishes `position:update` had its type
    overwritten before the frame left the process - and three components were
    handling an event that could not exist.
    """
    bus = RedisPubSub()
    sent: list[str] = []

    class _P:
        def pipeline(self):
            raise AssertionError("not used")

    class _R:
        async def publish(self, channel, payload):
            sent.append(payload)

    bus._redis = _R()  # type: ignore[assignment]

    from unittest.mock import patch

    async def _call(op):
        return await op()

    with patch("app.websocket.manager.redis_cb.call", new=_call):
        await bus.publish_user_event("u1", {"type": "position:update", "shares": 5})

    frame = json.loads(sent[0])
    assert frame["type"] == "position:update"
    assert frame["shares"] == 5

    # And the notification publisher still stamps its own type, so the
    # notification bell keeps working.
    sent.clear()
    with patch("app.websocket.manager.redis_cb.call", new=_call):
        await bus.publish_notification("u1", {"type": "whatever", "title": "hi"})
    assert json.loads(sent[0])["type"] == "notification"


# ── Liveness ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_half_open_socket_is_reaped_even_though_writes_succeed():
    """The heartbeat's original question - "did my write land?" - cannot work.

    A TCP peer that has gone - laptop lid, NAT timeout, killed container -
    usually leaves no RST, so the kernel keeps accepting bytes into a buffer
    nothing drains and `send_json` succeeds for minutes. Those sockets then
    held their file descriptor, per-IP slot and per-user connection quota
    indefinitely, and because the counts only decrement on a clean close, a user
    who lost connectivity a few times was locked out of realtime permanently.

    Only an unanswered probe can see it.
    """
    mgr = ConnectionManager()
    reaped = []

    class HalfOpen:
        """Accepts every write - just like a socket whose peer has vanished."""

        async def send_json(self, _event):
            return None

    sock = HalfOpen()
    mgr._ws_subscriptions[sock] = {"m1"}  # type: ignore[index]
    mgr._market_subs["m1"].add(sock)  # type: ignore[arg-type]

    async def fake_disconnect(ws, redis_pubsub_ref=None, cause="client"):
        reaped.append((ws, cause))

    mgr.disconnect = fake_disconnect  # type: ignore[method-assign]

    # Fresh lease: it has just answered, so the *first* sweep must let it live.
    mgr._ws_last_seen[sock] = asyncio.get_running_loop().time()  # type: ignore[index]
    assert await mgr.heartbeat_once() == 0
    assert reaped == []

    # Now go quiet for longer than the pong deadline while writes still succeed.
    mgr._ws_last_seen[sock] = (  # type: ignore[index]
        asyncio.get_running_loop().time() - ConnectionManager.PONG_TIMEOUT_S - 1
    )
    assert await mgr.heartbeat_once() == 1
    assert reaped and reaped[0][1] == "heartbeat"


@pytest.mark.asyncio
async def test_heartbeat_still_reaps_a_socket_whose_ping_wedges():
    """The deadline is not the only signal - a broken write is still fatal."""
    mgr = ConnectionManager()

    class Wedged:
        async def send_json(self, _event):
            await asyncio.sleep(60)

    sock = Wedged()
    mgr._ws_subscriptions[sock] = {"m1"}  # type: ignore[index]
    mgr._market_subs["m1"].add(sock)  # type: ignore[arg-type]
    mgr._ws_last_seen[sock] = asyncio.get_running_loop().time()  # type: ignore[index]
    mgr.SEND_TIMEOUT_S = 0.05

    reaped = []

    async def fake_disconnect(ws, redis_pubsub_ref=None, cause="client"):
        reaped.append(ws)

    mgr.disconnect = fake_disconnect  # type: ignore[method-assign]

    assert await mgr.heartbeat_once() == 1
    assert reaped == [sock]


@pytest.mark.asyncio
async def test_touch_renews_the_lease():
    """Inbound traffic is proof of life, so a busy client is never reaped."""
    mgr = ConnectionManager()

    class Sock:
        async def send_json(self, _event):
            return None

    sock = Sock()
    mgr._ws_subscriptions[sock] = {"m1"}  # type: ignore[index]
    mgr._market_subs["m1"].add(sock)  # type: ignore[arg-type]
    stale = asyncio.get_running_loop().time() - ConnectionManager.PONG_TIMEOUT_S - 1
    mgr._ws_last_seen[sock] = stale  # type: ignore[index]

    mgr.touch(sock)
    assert not mgr._stale(sock, asyncio.get_running_loop().time())


@pytest.mark.asyncio
async def test_notification_sockets_are_swept_by_the_same_contract():
    """The user socket is the long-lived one, so it is the likeliest to wedge."""

    class HalfOpen:
        async def send_json(self, _event):
            return None

    ws = HalfOpen()
    user_manager._user_socks["u1"] = {ws}  # type: ignore[arg-type]
    user_manager._ws_to_user[ws] = "u1"  # type: ignore[index]
    user_manager._ws_last_seen[ws] = (  # type: ignore[index]
        asyncio.get_running_loop().time() - user_manager.PONG_TIMEOUT_S - 1
    )

    reaped = []

    async def fake_disconnect(sock, user_id, cause="client"):
        reaped.append(sock)

    original = user_manager.disconnect
    user_manager.disconnect = fake_disconnect  # type: ignore[method-assign]
    try:
        assert await user_manager.heartbeat_once() == 1
        assert reaped == [ws]
    finally:
        user_manager.disconnect = original  # type: ignore[method-assign]
        user_manager._user_socks.clear()
        user_manager._ws_to_user.clear()
        user_manager._ws_last_seen.clear()


# ── Reaper releases Redis interest ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_reaper_releases_the_socket_redis_interest():
    """A socket reaped by the heartbeat has no read loop left to do it.

    `disconnect` is what releases a socket's channels, and on the reaper path
    it was called without the pubsub handle - so the reference count for that
    market stayed elevated forever and the node went on receiving and fanning
    out a channel no local socket wanted.
    """
    mgr = ConnectionManager()
    calls: list[str] = []

    class Sock:
        pass

    sock = Sock()
    mgr._ws_subscriptions[sock] = {"m1"}  # type: ignore[index]
    mgr._market_subs["m1"].add(sock)  # type: ignore[arg-type]

    from app.websocket import manager as mgr_mod

    original = mgr_mod.RedisPubSub.unsubscribe_market

    async def spy(self, market_id):
        calls.append(market_id)

    mgr_mod.RedisPubSub.unsubscribe_market = spy  # type: ignore[method-assign]
    try:
        await mgr._disconnect_many([sock])
    finally:
        mgr_mod.RedisPubSub.unsubscribe_market = original  # type: ignore[method-assign]

    assert calls == ["m1"]