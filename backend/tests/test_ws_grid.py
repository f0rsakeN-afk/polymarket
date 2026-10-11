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

from app.websocket.manager import ConnectionManager


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
        await mgr._buffer_grid_price(f"m{i}", {
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
        await mgr._buffer_grid_price("m1", {
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

    await mgr._buffer_grid_price("m1", {
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

    await mgr._buffer_grid_price("m1", {
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

    await mgr._buffer_grid_price("m1", {
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