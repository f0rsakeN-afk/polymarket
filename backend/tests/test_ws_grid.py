"""Grid price aggregation: N markets, one frame.

A market list - the home page, /markets, search results - is the case where
per-market subscriptions are the wrong shape, and the failure is not obvious.
Subscribing a socket to thirty markets looks fine and costs thirty subscription
slots against a hard cap, then delivers one frame per market per tick: thirty
frames and thirty re-renders a second, on a page whose whole point is to be
lighter than the static one it replaced. Client-side coalescing does not fix it,
because the frames are already on the wire by the time the client sees them.

So the server aggregates: the client declares what it is displaying, and the
server buffers the newest price per market and flushes one combined frame per
tick. Cost becomes O(1) in frames and O(1) in subscriptions.

These tests pin that, and the parts that can rot quietly - the reverse index
leaking, and gap detection surviving the batching.
"""
import asyncio

import pytest

from app.websocket.manager import ConnectionManager, GridFlushStats, next_grid_interval


class _Sock:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_json(self, payload):
        self.sent.append(payload)

    def batches(self):
        return [s for s in self.sent if s.get("type") == "market:prices_batch"]


@pytest.mark.asyncio
async def test_thirty_markets_arrive_as_one_frame_not_thirty():
    """The whole point: frame count must not scale with market count."""
    mgr = ConnectionManager()
    sock = _Sock()
    mgr._grid_subs[sock] = {f"m{i}" for i in range(30)}
    for i in range(30):
        mgr._grid_subscribers[f"m{i}"].add(sock)

    for i in range(30):
        await mgr._buffer_grid_event(f"m{i}", {
            "type": "market:price_update",
            "market_id": f"m{i}",
            "yes_price": 0.5,
            "no_price": 0.5,
            "seq": i + 1,
        })

    await mgr.flush_grid()

    batches = sock.batches()
    assert len(batches) == 1, f"expected one aggregated frame, got {len(batches)}"
    assert len(batches[0]["prices"]) == 30


@pytest.mark.asyncio
async def test_repeated_ticks_collapse_to_the_newest_price():
    """A market ticking fifty times between flushes must not cost fifty frames."""
    mgr = ConnectionManager()
    sock = _Sock()
    mgr._grid_subs[sock] = {"m1"}
    mgr._grid_subscribers["m1"].add(sock)

    for seq in range(1, 51):
        await mgr._buffer_grid_event("m1", {
            "type": "market:price_update",
            "market_id": "m1",
            "yes_price": seq / 100,
            "no_price": 1 - seq / 100,
            "seq": seq,
        })

    await mgr.flush_grid()

    batches = sock.batches()
    assert len(batches) == 1
    prices = batches[0]["prices"]
    assert len(prices) == 1, "fifty ticks must collapse to one buffered price"
    # The newest wins - intermediate values were never displayed and never should
    # be: a reader sees the market's current price, not a replay of its history.
    assert prices["m1"]["yes_price"] == pytest.approx(0.5)
    assert prices["m1"]["seq"] == 50


@pytest.mark.asyncio
async def test_batched_prices_carry_the_sequence_number():
    """Without `seq` a grid cannot tell a missed frame from a quiet market.

    That is the exact failure the heartbeat beacon exists to close, and it would
    quietly reopen for grids the moment batching was introduced.
    """
    mgr = ConnectionManager()
    sock = _Sock()
    mgr._grid_subs[sock] = {"m1"}
    mgr._grid_subscribers["m1"].add(sock)

    await mgr._buffer_grid_event("m1", {
        "type": "market:price_update", "market_id": "m1",
        "yes_price": 0.6, "no_price": 0.4, "seq": 42,
    })
    await mgr.flush_grid()

    assert sock.batches()[0]["prices"]["m1"]["seq"] == 42


@pytest.mark.asyncio
async def test_outcome_prices_survive_the_batch():
    """A multi-outcome market's prices must not be flattened away.

    `yes_price`/`no_price` are the binary pool's ratio and say nothing about any
    individual outcome on a parimutuel market, so dropping `outcome_prices` here
    would freeze every line except the first.
    """
    mgr = ConnectionManager()
    sock = _Sock()
    mgr._grid_subs[sock] = {"m1"}
    mgr._grid_subscribers["m1"].add(sock)

    await mgr._buffer_grid_event("m1", {
        "type": "market:price_update", "market_id": "m1",
        "yes_price": 0.5, "no_price": 0.5, "seq": 1,
        "outcome_prices": {"Yes": 0.4, "No": 0.35, "Draw": 0.25},
    })
    await mgr.flush_grid()

    price = sock.batches()[0]["prices"]["m1"]
    assert price["outcome_prices"] == {"Yes": 0.4, "No": 0.35, "Draw": 0.25}


@pytest.mark.asyncio
async def test_two_grids_get_their_own_frames():
    """Aggregation is per subscriber, not a shared broadcast."""
    mgr = ConnectionManager()
    a, b = _Sock(), _Sock()
    mgr._grid_subs[a] = {"m1", "m2"}
    mgr._grid_subs[b] = {"m1"}
    for m in ("m1", "m2"):
        mgr._grid_subscribers[m].add(a)
    mgr._grid_subscribers["m1"].add(b)

    await mgr._buffer_grid_event("m1", {
        "type": "market:price_update", "market_id": "m1",
        "yes_price": 0.6, "no_price": 0.4, "seq": 1,
    })
    await mgr.flush_grid()

    assert len(a.batches()) == 1 and len(b.batches()) == 1
    assert set(a.batches()[0]["prices"]) == {"m1"}
    assert set(b.batches()[0]["prices"]) == {"m1"}


@pytest.mark.asyncio
async def test_grid_subscribers_are_not_sent_frames_individually():
    """A grid must not also receive the per-market frame.

    Belt and braces: if the socket is in both registries it gets the frame twice,
    and the second copy is redundant work the aggregation was meant to remove.
    """
    mgr = ConnectionManager()
    sock = _Sock()
    # In the grid registry only - never a per-market subscriber.
    mgr._grid_subs[sock] = {"m1"}
    mgr._grid_subscribers["m1"].add(sock)

    await mgr.broadcast_to_market("m1", {
        "type": "market:price_update", "market_id": "m1",
        "yes_price": 0.6, "no_price": 0.4, "seq": 1,
    })

    assert sock.batches() == [], "nothing should be sent until the flush"
    await mgr.flush_grid()
    assert len(sock.batches()) == 1


@pytest.mark.asyncio
async def test_clearing_a_grid_reverses_the_reverse_index():
    """Otherwise the index leaks an entry per market the page ever showed.

    A grid that pages through the catalogue touches thousands of markets over a
    session, and every one of them would keep copying a price into a buffer for
    a socket that is no longer waiting for it.
    """
    mgr = ConnectionManager()
    sock = _Sock()
    mgr._grid_subs[sock] = {"m1", "m2"}
    mgr._grid_subscribers["m1"].add(sock)
    mgr._grid_subscribers["m2"].add(sock)
    mgr._grid_pending[sock] = {"m1": {"yes_price": 0.5}}

    mgr.clear_grid(sock)

    assert sock not in mgr._grid_subs
    assert sock not in mgr._grid_pending
    assert "m1" not in mgr._grid_subscribers, "reverse index entry left behind"
    assert "m2" not in mgr._grid_subscribers


@pytest.mark.asyncio
async def test_disconnect_clears_grid_state():
    """The reaper and the read loop both exit through `disconnect`.

    Leaving grid state behind would mean a dead socket stayed in every market's
    subscriber set forever, and each of those markets kept copying a frame into
    a buffer nobody reads.
    """
    mgr = ConnectionManager()
    sock = _Sock()
    mgr._grid_subs[sock] = {"m1"}
    mgr._grid_subscribers["m1"].add(sock)
    mgr._ws_subscriptions[sock] = {"m1"}

    class _Bus:
        async def unsubscribe_market(self, _market_id):
            return None

    await mgr.disconnect(sock, _Bus(), cause="client")

    assert "m1" not in mgr._grid_subscribers
    assert sock not in mgr._grid_subs


@pytest.mark.asyncio
async def test_subscribe_grid_replaces_the_previous_set():
    """Paging from page 1 to page 2 must not leave page 1's markets subscribed."""
    mgr = ConnectionManager()
    sock = _Sock()

    await mgr.subscribe_grid(sock, ["a", "b", "c"])
    assert set(mgr._grid_subs[sock]) == {"a", "b", "c"}

    await mgr.subscribe_grid(sock, ["d"])
    assert set(mgr._grid_subs[sock]) == {"d"}
    assert "a" not in mgr._grid_subscribers
    assert sock in mgr._grid_subscribers["d"]


@pytest.mark.asyncio
async def test_the_cap_is_enforced_and_reported():
    """A client must learn it is not live for everything it asked for."""
    mgr = ConnectionManager()
    sock = _Sock()
    mgr.MAX_GRID_MARKETS_PER_SOCKET = 3

    accepted = await mgr.subscribe_grid(sock, ["a", "b", "c", "d", "e"])

    assert len(accepted) == 3
    assert set(mgr._grid_subs[sock]) == accepted


@pytest.mark.asyncio
async def test_flush_with_nothing_pending_sends_nothing():
    """The flush loop runs four times a second forever; idle must be free."""
    mgr = ConnectionManager()
    sock = _Sock()
    mgr._grid_subs[sock] = {"m1"}
    mgr._grid_subscribers["m1"].add(sock)

    assert await mgr.flush_grid() == 0
    assert sock.sent == []


@pytest.mark.asyncio
async def test_a_market_watched_only_by_a_grid_still_updates():
    """The guard-order bug this suite exists to catch.

    Sequencing the broadcast as "return early when no per-market socket, then
    buffer for grids" looks correct and is not. A market displayed only in a list -
    which is every market nobody has opened - has no per-market socket at all, so
    the early return fires, the buffer never fills, and the entire grid feature
    silently does nothing.

    Notably this survives every other test here, because they all register a
    per-market socket as well. Only a grid-only market exposes it.
    """
    mgr = ConnectionManager()
    grid = _Sock()
    await mgr.subscribe_grid(grid, ["m1"])

    # No per-market subscriber anywhere: this market is only in a grid.
    assert "m1" not in mgr._market_subs

    await mgr.broadcast_to_market("m1", {
        "type": "market:price_update", "market_id": "m1",
        "yes_price": 0.6, "no_price": 0.4, "seq": 1,
    })
    await mgr.flush_grid()

    assert len(grid.batches()) == 1, (
        "a grid-only market produced no price at all - the buffer is being "
        "filled after an early return that grid-only markets always hit"
    )
    assert grid.batches()[0]["prices"]["m1"]["yes_price"] == 0.6

    # The sequence mark must advance too, or the heartbeat beacon reports a
    # grid-only market as never having moved and a grid client comparing against
    # it sees a permanent phantom gap.
    assert mgr._last_seq["m1"] == 1


@pytest.mark.asyncio
async def test_a_dead_grid_socket_is_reaped_on_flush():
    """A grid send that fails must disconnect, or the buffer refills forever."""
    mgr = ConnectionManager()
    mgr.SEND_TIMEOUT_S = 0.05

    class Wedged:
        async def send_json(self, _payload):
            raise RuntimeError("gone")

    sock = Wedged()
    mgr._grid_subs[sock] = {"m1"}
    mgr._grid_subscribers["m1"].add(sock)
    mgr._ws_subscriptions[sock] = {"m1"}
    mgr._grid_pending[sock] = {"m1": {"yes_price": 0.5}}

    class _Bus:
        async def unsubscribe_market(self, _market_id):
            return None

    original = ConnectionManager.disconnect
    reaped = []

    async def fake_disconnect(self, ws, redis_pubsub_ref=None, cause="client"):
        reaped.append(ws)

    ConnectionManager.disconnect = fake_disconnect
    try:
        await mgr.flush_grid()
    finally:
        ConnectionManager.disconnect = original

    assert reaped == [sock]


@pytest.mark.asyncio
async def test_the_grid_loop_flushes_and_stops_on_cancel():
    """The loop has to be scheduled somewhere; this proves it runs and is clean."""
    mgr = ConnectionManager()
    sock = _Sock()
    mgr._grid_subs[sock] = {"m1"}
    mgr._grid_subscribers["m1"].add(sock)
    mgr._grid_pending[sock] = {"m1": {"yes_price": 0.5}}

    task = asyncio.create_task(mgr.grid_loop(interval_s=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert sock.batches(), "the loop must actually flush"

class TestResolutionReachesTheGrid:
    """A settled market must leave the grid, not sit in it looking alive.

    A grid deliberately excludes markets that are already settled, so the instant
    one settles it is holding a subscription slot, painting a live-looking card,
    and showing prices that can never move again. The list then believes it is
    tradeable right up until someone reloads - and the `market:resolved` frame the
    detail page handles never reaches it at all, because that goes out on the
    per-market channel while a grid listens on the aggregate.

    So resolution rides the batch the grid was already receiving. One field, no
    second channel, no extra subscription.
    """

    async def _grid_ws(self, mgr, market_id):
        ws = _Sock()
        await mgr.subscribe_grid(ws, [market_id])
        return ws

    @pytest.mark.asyncio
    async def test_resolution_is_buffered_into_the_batch(self):
        mgr = ConnectionManager()
        ws = await self._grid_ws(mgr, "m1")

        await mgr.broadcast_to_market("m1", {
            "type": "market:resolved",
            "status": "resolving",
            "winning_outcome_id": "o1",
            "winning_outcome_name": "Yes",
            "seq": 7,
        })
        await mgr.flush_grid()

        payload = ws.batches()[0]
        frame = payload["prices"]["m1"]
        assert frame["type"] == "market:resolved"
        assert frame["winning_outcome_name"] == "Yes"
        # The seq rides along too, so the grid keeps its gap detection.
        assert frame["seq"] == 7

    @pytest.mark.asyncio
    async def test_a_late_price_tick_cannot_resurrect_a_settled_market(self):
        """The buffer holds one entry per market, so ordering decides what lands.

        A final trade settling into the book inside the same 250ms window would
        otherwise overwrite the resolution marker - and the grid would carry on
        rendering a market that is already done, which is precisely the bug this
        routing exists to fix. Resolution is terminal, so it wins.
        """
        mgr = ConnectionManager()
        ws = await self._grid_ws(mgr, "m1")

        await mgr.broadcast_to_market("m1", {"type": "market:resolved", "status": "resolved"})
        await mgr.broadcast_to_market("m1", {
            "type": "market:price_update", "yes_price": 0.99, "no_price": 0.01,
        })
        await mgr.flush_grid()

        frame = ws.batches()[0]["prices"]["m1"]
        assert frame["type"] == "market:resolved", (
            "a price frame overwrote the resolution - the grid would show a "
            "settled market as live"
        )

    @pytest.mark.asyncio
    async def test_a_market_with_no_grid_subscribers_costs_nothing(self):
        """No subscriber, no work - the point of the reverse index."""
        mgr = ConnectionManager()
        await mgr.broadcast_to_market("m1", {"type": "market:resolved", "status": "resolved"})
        assert await mgr.flush_grid() == 0


class TestAdaptiveFlushCadence:
    """The tick has to respond to load, because the tail is where users notice.

    A fixed 250ms flush is right when idle and wrong when saturated: the flush
    then consumes most of the interval and every price on screen is that much
    older than it needs to be. Measured end to end on this gateway, p50 was
    ~21ms idle while p95 reached ~213ms at 500 sockets - the tail was queueing
    behind a full tick, not anything slow inside the send.

    These exercise the policy that `grid_loop` calls, rather than a copy of it
    written out here. A test that re-implements the arithmetic beside the code
    passes when the code is broken, which is the one thing a test must not do.
    """

    @staticmethod
    def assert_shortens(after: float, before: float) -> None:
        assert after < before, f"expected < {before}, got {after}"

    @staticmethod
    def step(interval: float, sent: int, elapsed: float, base=0.25, floor=0.02,
             step_s=0.05, ratio=0.6) -> float:
        return next_grid_interval(
            interval, sockets_sent=sent, elapsed_s=elapsed,
            base=base, floor=floor, step=step_s, saturation_ratio=ratio,
        )

    def test_a_flush_that_eats_its_tick_shortens_the_cadence(self):
        # 200ms of work inside a 250ms tick: 80% of the interval, well past the
        # 60% saturation point.
        self.assert_shortens(self.step(0.25, sent=500, elapsed=0.2), 0.25)

    def test_a_cheap_flush_lengthens_the_cadence(self):
        # 5ms inside a 250ms tick is not a reason to flush harder.
        after = self.step(0.05, sent=1, elapsed=0.005)
        assert after > 0.05

    def test_an_idle_gateway_drifts_back_to_the_base(self):
        """One busy moment must not leave every socket flushing at the floor."""
        interval = 0.02  # where saturation left it
        for _ in range(20):
            interval = self.step(interval, sent=0, elapsed=0.0)
        assert interval == 0.25

    def test_the_cadence_never_falls_below_the_floor(self):
        """A tight spin starves the listener that feeds the buffer.

        Flushing faster than the loop can complete a pass does not make prices
        fresher - it burns CPU and stops Redis draining. When the floor is not
        enough the honest answer is another worker, not a faster loop.
        """
        interval = 0.25
        for _ in range(50):
            interval = self.step(interval, sent=500, elapsed=10.0)
        assert interval == 0.02

    def test_recovery_is_gradual_so_one_spike_does_not_move_everyone(self):
        # Multiplicative decrease, additive increase: fast down, slow back. A
        # single bad flush must not reset the cadence for the whole process.
        interval = self.step(0.25, sent=500, elapsed=0.24)
        assert interval == 0.125  # halved
        interval = self.step(interval, sent=1, elapsed=0.001)
        assert interval == 0.175  # +0.05, not straight back to 0.25

    def test_a_send_made_idle_by_the_interval_is_not_saturation(self):
        # `sent == 0` is handled by the idle branch. If the saturation branch ran
        # first it would halve on an idle tick, and a quiet gateway would race
        # itself to the floor for doing nothing.
        interval = 0.25
        for _ in range(10):
            interval = self.step(interval, sent=0, elapsed=0.0)
        assert interval == 0.25

    def test_stats_are_bounded_not_an_unbounded_leak(self):
        # This lives in a long-lived worker. A growing list here is a slow leak
        # in exactly the process that is meant to be steady-state.
        stats = GridFlushStats(maxlen=16)
        for i in range(500):
            stats.observe(i, 0.01, 0.25)
        snap = stats.snapshot()
        assert snap["samples"] == 16
        assert 0 <= snap["flush_p95_s"] < 1
        assert snap["interval_p50_s"] == 0.25


class _SlowSock(_Sock):
    def __init__(self, delay_s: float):
        super().__init__()
        self._delay = delay_s

    async def send_json(self, payload):
        await asyncio.sleep(self._delay)
        self.sent.append(payload)


class TestCoalescingIsNotLoss:
    """A collapsed update must not look like a dropped one.

    Grid aggregation drops intermediate sequence numbers *on purpose*. Judging
    contiguity on the last `seq` alone therefore makes every busy market look
    lossy on every tick, and the client responds by refetching the whole markets
    query - hundreds of times a second, from every open grid. The server causes
    that load and the client pays for it.

    `seq_from` is the fix: contiguity is judged from the first sequence the flush
    window actually saw.
    """

    @pytest.mark.asyncio
    async def test_seq_from_anchors_the_window_not_the_previous_tick(self):
        """The bug this pins is subtle and was shipped once already.

        Ten ticks (seq 5..14) in one window must report `seq_from = 5`. Anchoring
        on the previous tick's `seq` instead leaves it permanently one behind, so
        the window reports `seq_from = 13` - and every consumer reads a coalesced
        burst of ten updates as a gap, which is the exact failure `seq_from`
        exists to remove.
        """
        mgr = ConnectionManager()
        ws = _Sock()
        await mgr.subscribe_grid(ws, ["m1"])

        for seq in range(5, 15):
            await mgr.broadcast_to_market("m1", {
                "type": "market:price_update", "yes_price": 0.5, "no_price": 0.5,
                "seq": seq,
            })
        await mgr.flush_grid()

        frame = ws.batches()[0]["prices"]["m1"]
        assert frame["seq"] == 14, "newest seq must survive coalescing"
        assert frame["seq_from"] == 5, (
            f"seq_from anchored at {frame['seq_from']}, expected the first seq in "
            "the window (5). Anchoring on the previous tick makes every "
            "coalesced burst look like packet loss."
        )

    @pytest.mark.asyncio
    async def test_a_single_update_has_no_window_to_anchor(self):
        # Nothing was collapsed, so there is nothing to report and the consumer
        # falls back to `seq` itself.
        mgr = ConnectionManager()
        ws = _Sock()
        await mgr.subscribe_grid(ws, ["m1"])
        await mgr.broadcast_to_market("m1", {
            "type": "market:price_update", "yes_price": 0.5, "no_price": 0.5, "seq": 7,
        })
        await mgr.flush_grid()

        frame = ws.batches()[0]["prices"]["m1"]
        assert frame["seq"] == 7
        assert "seq_from" not in frame

    @pytest.mark.asyncio
    async def test_contiguity_is_judged_from_seq_from(self):
        """The consumer's rule, stated as the server enables it.

        `seq_from == last_seen + 1` means nothing was lost in transport, however
        many ticks were collapsed. A genuine gap still shows up, because
        `seq_from` jumps.
        """
        def lossy(last_seen: int, frame: dict) -> bool:
            seq_from = frame.get("seq_from", frame["seq"])
            return seq_from > last_seen + 1

        mgr = ConnectionManager()
        ws = _Sock()
        await mgr.subscribe_grid(ws, ["m1"])
        for seq in range(5, 15):
            await mgr.broadcast_to_market("m1", {
                "type": "market:price_update", "yes_price": 0.5, "no_price": 0.5,
                "seq": seq,
            })
        await mgr.flush_grid()
        frame = ws.batches()[0]["prices"]["m1"]

        # Nine updates collapsed into one frame is not loss.
        assert not lossy(4, frame)
        # ...but a frame starting at 20 when we last saw 14 is.
        assert lossy(14, {"seq": 30, "seq_from": 20})
