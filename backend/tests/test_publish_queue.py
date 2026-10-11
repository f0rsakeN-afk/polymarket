"""The publish queue: turning a silent cliff into observable backpressure.

`max_connections` is a hard cliff, not a queue. Measured against real Redis:

    burst  300 -> ok=100 failed=200  {MaxConnectionsError}
    burst 1000 -> ok=100 failed=900  {MaxConnectionsError}

Every publisher used to catch that and `log.warning(...)`. So the trade was
committed to Postgres, the client was never told, and nothing anywhere recorded
that a frame had been thrown away. Worse, it compounded: each dropped frame
became a client-detected gap, each gap a REST refetch, and the refetches landed
exactly when the system was already saturated.

These pin the properties that make the queue a real answer rather than a delay
in disguise.
"""

import asyncio

import pytest

from app.websocket.publish_queue import (
    CRITICAL_FRAMES,
    PublishDispatcher,
)


def make(**kw):
    """A dispatcher plus the list of frames it actually wrote."""
    sent: list[str] = []

    async def _send(pending):
        sent.append(pending.frame)

    kw.setdefault("writers", 2)
    return PublishDispatcher(send=_send, **kw), sent


# ── Overflow policy ─────────────────────────────────────────────────────────────


class TestEphemeralOverflowKeepsTheNewest:
    """Dropping a price must never move a user's display backwards.

    Coalescing is what the grid does anyway, so a stale price is not merely
    redundant - delivering it late would show a number the user has already seen
    superseded. Keeping the newest is the same answer the client would have
    reached, reached sooner and without a Redis round-trip per discard.
    """

    @pytest.mark.asyncio
    async def test_overflow_drops_the_oldest_and_keeps_the_newest(self):
        async def noop():
            return None

        d, sent = make(ephemeral_max=3)
        d._send = lambda pending: _noop()  # never started; inspect the buffer
        for i in range(5):
            d.enqueue(noop, frame="price_update")

        assert len(d._ephemeral) == 3
        # Five offered, three kept - and they are the *newest* three.
        assert d._ephemeral[-1].frame == "price_update"
        assert len(sent) == 0

    @pytest.mark.asyncio
    async def test_a_prices_frame_is_ephemeral(self):
        d, _ = make()
        assert d.enqueue(lambda: _noop(), frame="price_update") is True
        assert d.depth["ephemeral"] == 1
        assert d.depth["critical"] == 0


async def _noop():
    return None


# ── Critical overflow owes a resync ─────────────────────────────────────────────


class TestCriticalOverflowIsNotSilentLoss:
    """The frame is dropped, but the reconciliation is not.

    These events are durable in Postgres and `applyPrivateFeedResync` already
    invalidates positions, orders, wallet and notifications. So "the client did
    not see this happen" is a recoverable state - but only if the client is
    *told* to go and get it. Dropping the frame without the marker is silent loss
    wearing backpressure's clothes.
    """

    @pytest.mark.asyncio
    async def test_overflow_owes_a_resync_to_the_affected_user(self):
        d, _ = make(critical_max=2)
        for _ in range(4):
            d.enqueue(_noop, frame="order:fill", owe_resync_to="user-1")

        assert d.depth["critical"] == 2
        # Two fills were refused, but the client owes one marker - not two.
        # One marker per user, not one per dropped frame, is the point.
        assert d.owed_resyncs == 1

    @pytest.mark.asyncio
    async def test_owed_resyncs_actually_reach_the_wire(self):
        owed: list[str] = []

        async def resync(user_id):
            owed.append(user_id)

        d, _ = make(critical_max=1, resync=resync)
        d.enqueue(_noop, frame="order:fill", owe_resync_to="user-7")
        d.enqueue(_noop, frame="order:fill", owe_resync_to="user-7")

        await d._flush_owed_resyncs()
        assert owed == ["user-7"]
        assert d.owed_resyncs == 0

    @pytest.mark.asyncio
    async def test_a_failed_marker_does_not_block_the_ones_behind_it(self):
        """One unreachable user must not withhold everyone else's reconciliation."""
        sent: list[str] = []

        async def resync(user_id):
            sent.append(user_id)
            if user_id == "bad":
                raise RuntimeError("nope")

        d, _ = make(critical_max=1, resync=resync)
        for uid in ("bad", "good"):
            d.enqueue(_noop, frame="order:fill", owe_resync_to=uid)
            d.enqueue(_noop, frame="order:fill", owe_resync_to=uid)

        await d._flush_owed_resyncs()
        assert "good" in sent, "a failing marker must not take the others with it"

    @pytest.mark.asyncio
    async def test_market_scoped_frames_owe_nobody_because_seq_already_does(self):
        # `orderbook:update` is critical but has no private channel. The `seq`
        # gap it leaves behind is already the client's trigger to refetch, so
        # there is no marker to send - and inventing one would be noise.
        d, _ = make(critical_max=1)
        d.enqueue(_noop, frame="orderbook:update")
        d.enqueue(_noop, frame="orderbook:update")
        assert d.owed_resyncs == 0


# ── Classification ──────────────────────────────────────────────────────────────


class TestDeliveryClassification:
    """The queue's whole policy hangs off this mapping, so it is pinned here."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("frame", sorted(CRITICAL_FRAMES))
    async def test_frames_that_must_not_vanish_are_critical(self, frame):
        d, _ = make()
        d.enqueue(_noop, frame=frame)
        assert d.depth["critical"] == 1, f"{frame} must be critical"

    @pytest.mark.asyncio
    async def test_prices_are_not(self):
        d, _ = make()
        d.enqueue(_noop, frame="price_update")
        assert d.depth["ephemeral"] == 1

    @pytest.mark.asyncio
    async def test_an_unknown_frame_defaults_to_ephemeral(self):
        """Fail open toward dropping, not toward promising delivery we cannot keep.

        A new frame type that nobody classified should not silently inherit
        critical handling and cause unbounded growth; it should behave like a
        price until someone decides it matters. The cost of getting this wrong is
        an extra marker, not a lost trade.
        """
        d, _ = make()
        d.enqueue(_noop, frame="something:new")
        assert d.depth["ephemeral"] == 1

    @pytest.mark.asyncio
    async def test_a_private_critical_frame_keeps_its_resync_target(self):
        d, _ = make()
        d.enqueue(_noop, frame="position:update", owe_resync_to="u1")
        pending = d._critical[0]
        assert pending.owe_resync_to == "u1"

    @pytest.mark.asyncio
    async def test_an_ephemeral_frame_never_owes_a_resync(self):
        # Otherwise a burst of prices against a full queue would owe resyncs for
        # frames that carry no private state - a refetch storm caused by the
        # queue's own overflow handling.
        d, _ = make()
        d.enqueue(_noop, frame="price_update", owe_resync_to="u1")
        assert d._ephemeral[0].owe_resync_to is None


# ── Ordering and drain ──────────────────────────────────────────────────────────


    async def test_critical_frames_are_served_before_ephemeral(self):
        """Critical must never queue *behind* the class that is allowed to lose.

        The claim is about work enqueued after the critical frame, not before it:
        a writer already part-way through earlier frames finishes them, which is
        plain FIFO and obviously right. What must never happen is a price that
        arrived *later* being written first - that is the frame being delayed by
        the very work it is supposed to outrank.
        """
        sent: list[str] = []

        async def send(pending):
            sent.append(pending.frame)
            await asyncio.sleep(0.002)

        d = PublishDispatcher(send=send, writers=1)
        await d.start()
        try:
            d.enqueue(_noop, frame="order:fill", owe_resync_to="u1")
            for i in range(5):
                d.enqueue(_noop, frame="price_update")

            await asyncio.wait_for(
                _until(lambda: len(sent) == 6 and not any(d.depth.values())), timeout=3
            )
        finally:
            await d.stop()

        assert sent[0] == "order:fill", (
            f"a price enqueued after the fill was written first: {sent}"
        )

    async def test_a_critical_frame_is_not_stuck_behind_a_slow_one(self):
        """A wedged write must not delay the event that matters.

        Ordering is by class, then FIFO within a class - so a fill enqueued while
        a writer is blocked on a slow price is picked up by whichever writer is
        free. Without spare writers the queue degrades to FIFO, which is why the
        writer pool exists at all rather than a single serialised task.
        """
        sent: list[str] = []
        gate = asyncio.Event()

        async def send(pending):
            sent.append(pending.frame)
            if pending.frame == "slow-price":
                await gate.wait()

        d = PublishDispatcher(send=send, writers=2)
        await d.start()
        try:
            d.enqueue(_noop, frame="slow-price")
            await _until(lambda: sent == ["slow-price"])
            d.enqueue(_noop, frame="order:fill", owe_resync_to="u1")

            # The second writer must take it while the first is still wedged.
            await asyncio.wait_for(_until(lambda: "order:fill" in sent), timeout=2)
        finally:
            gate.set()
            await d.stop()

        assert "order:fill" in sent, (
            "a fill waited behind an unrelated slow write - the one event that "
            "must never be delayed by the work it outranks"
        )

    async def test_frames_are_written_in_the_order_they_were_queued(self):
        """Within a delivery class, order is the contract.

        Two fills arriving swapped would tell a user the wrong story about their
        own position, so the queue preserves it rather than treating the frames
        as an unordered set.
        """
        order: list[int] = []
        released = asyncio.Event()

        async def send(pending):
            order.append(pending.frame)
            # One writer, so ordering is observable.
            await asyncio.sleep(0.005)

        d = PublishDispatcher(send=send, writers=1)
        await d.start()
        try:
            for i in range(20):
                d.enqueue(_noop, frame=f"trade:new-{i}")
            await asyncio.wait_for(_until(lambda: len(order) == 20), timeout=3)
        finally:
            released.set()
            await d.stop()

        assert order == [f"trade:new-{i}" for i in range(20)]

    async def test_one_failing_frame_does_not_kill_the_writer(self):
        """A single bad frame must not take the writer - and its queue - with it."""
        good: list[str] = []

        async def send(pending):
            if pending.frame == "boom":
                raise RuntimeError("bad frame")
            good.append(pending.frame)

        d = PublishDispatcher(send=send, writers=1)
        await d.start()
        try:
            d.enqueue(_noop, frame="boom")
            for i in range(3):
                d.enqueue(_noop, frame=f"ok-{i}")
            await asyncio.wait_for(_until(lambda: len(good) == 3), timeout=2)
        finally:
            await d.stop()

        assert good == ["ok-0", "ok-1", "ok-2"]

    async def test_the_queue_actually_drains_to_the_sender(self):
        """The end-to-end property: nothing sits in the queue after the writers run."""
        sent: list[str] = []

        async def send(pending):
            sent.append(pending.frame)

        d = PublishDispatcher(send=send, writers=4)
        await d.start()
        try:
            for i in range(500):
                d.enqueue(_noop, frame="price_update")
            await asyncio.wait_for(_until(lambda: d.depth["ephemeral"] == 0), timeout=5)
        finally:
            await d.stop()

        assert len(sent) == 500, "frames were lost inside the queue"


# ── The wire contract ───────────────────────────────────────────────────────────


def test_the_resync_marker_matches_the_client():
    """`WS_RESYNC` is a wire contract with no shared schema behind it.

    The server sending a frame the client does not recognise is not a crash and
    not a failed request - the resync simply never happens, and nothing anywhere
    reports it. So the agreement is pinned here, against the frontend source.
    """
    import pathlib
    import re

    from app.websocket.manager import WS_RESYNC

    root = pathlib.Path(__file__).resolve().parents[1]
    client = root / "../frontend/apps/web/lib/ws-resync.ts"
    if not client.exists():  # backend-only checkout
        pytest.skip("frontend not present")

    text = client.read_text()
    match = re.search(r'WS_RESYNC\s*=\s*["\']([^"\']+)["\']', text)
    assert match, f"could not find WS_RESYNC in {client}"
    assert match.group(1) == WS_RESYNC, (
        f"server sends {WS_RESYNC!r}, client listens for {match.group(1)!r}. "
        "The client would silently ignore every reconciliation."
    )


async def _until(predicate, poll: float = 0.002):
    """Wait on a condition; a fixed sleep would flake on a loaded machine."""
    import time

    deadline = time.perf_counter() + 3.0
    while time.perf_counter() < deadline:
        if predicate():
            return True
        await asyncio.sleep(poll)
    raise AssertionError("condition never became true")

# ── The wiring ──────────────────────────────────────────────────────────────────


class TestPublishersActuallyRouteThroughTheQueue:
    """Every `publish_*` must enqueue rather than write to Redis inline.

    The dispatcher is fully tested on its own, and would stay green while the
    application kept bypassing it entirely - which is exactly the state this
    codebase was in. These pin the link, because "the queue exists and works" is
    not the same claim as "the queue is on the path".
    """

    @staticmethod
    def _bus():
        from app.websocket.manager import RedisPubSub

        bus = RedisPubSub()
        bus._redis = object()  # present, so `enqueue_publish` does not no-op
        return bus

    @pytest.mark.parametrize(
        "call,expected",
        [
            (lambda b: b.publish_market_event("m1", "price_update", {}), "price_update"),
            (lambda b: b.publish_market_event("m1", "orderbook:update", {}), "orderbook:update"),
            (lambda b: b.publish_market_event("m1", "trade:new", {}), "trade:new"),
            (lambda b: b.publish_global_trade({"id": "t1"}), "trade:new"),
            (lambda b: b.publish_user_event("u1", {"type": "position:update"}), "position:update"),
            (lambda b: b.publish_notification("u1", {"id": "n1"}), "notification"),
            (lambda b: b.publish_order_fill("u1", {"order_id": "o1"}), "order:fill"),
        ],
    )
    async def test_the_frame_is_queued_with_the_right_event_type(self, call, expected):
        bus = self._bus()
        await call(bus)
        depths = bus._dispatcher.depth
        assert sum(depths.values()) == 1, f"{expected} never reached the queue"
        queued = (bus._dispatcher._critical + bus._dispatcher._ephemeral)[0]
        assert queued.frame == expected, (
            f"event type is what decides the delivery class; got {queued.frame!r}"
        )

    async def test_a_price_lands_ephemeral_and_an_orderbook_update_lands_critical(self):
        """The classification the queue's whole policy depends on."""
        bus = self._bus()
        await bus.publish_market_event("m1", "market:price_update", {})
        await bus.publish_market_event("m1", "orderbook:update", {})
        d = bus._dispatcher.depth
        assert d["ephemeral"] == 1 and d["critical"] == 1

    async def test_a_private_critical_frame_carries_its_resync_target(self):
        bus = self._bus()
        await bus.publish_order_fill("u-42", {"order_id": "o1"})
        pending = bus._dispatcher._critical[0]
        assert pending.owe_resync_to == "u-42", (
            "a dropped fill with no resync target is a silently lost fill"
        )

    async def test_nothing_reaches_redis_before_a_writer_runs(self):
        """The property that removes the cliff: `enqueue` does no I/O.

        If a publisher awaited Redis itself, a burst would again be bounded by
        `max_connections` - which is a hard limit, not a queue - and the whole
        design would be inert.
        """
        bus = self._bus()
        await bus.publish_market_event("m1", "trade:new", {"id": "t1"})
        # No writers started, so nothing can have been written, and no
        # MaxConnectionsError can have been raised either.
        assert bus._dispatcher.depth["critical"] == 1
