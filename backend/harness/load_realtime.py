"""Load harness for the realtime gateway, against a real Redis.

Not a test. It measures, so that claims about scalability rest on numbers instead
of on reasoning about the code:

    REDIS_PASSWORD=devpass .venv/bin/python -m harness.load_realtime

**It measures the whole path**, not a slice of it. Frames are published through
`publish_market_event`, consumed by a real `RedisPubSub.listen()` task, fanned
out by the real `ConnectionManager`, buffered by the real grid aggregator, and
delivered to sockets. That matters because the interesting costs are exactly the
ones hiding between the stages: publish→consume is Redis round-trip latency,
consume→fan-out is scheduling, fan-out→socket is buffering. Measuring only
`broadcast_to_market` would have reported the cheapest part of the system and
called it good.

Sockets are simulated transports. That is deliberate: `send_json` does no I/O, so
the harness isolates gateway decision cost from kernel throughput, and it can
model a slow consumer deliberately rather than hoping one shows up.

Five properties, each a distinct way the gateway could be wrong:

1. **Fan-out cost must not grow with connection count.** Publishing to one market
   costs O(subscribers of that market). A slope here means something iterates
   every socket regardless of whether that socket wants the frame - the classic
   way a realtime gateway collapses on its way to being popular.
2. **A tick must stay one frame per grid, not one per market.** This is a browser
   budget, not a server one: the server looks fine and the client melts.
3. **Latency distribution, including the tail.** A mean hides the 2-second tail,
   and the tail is what a user notices.
4. **No head-of-line blocking.** One wedged socket must not delay everyone.
5. **`seq` must be gapless under concurrency.** Gaps read as packet loss and
   trigger a full REST resync on every client - so false gaps are a self-inflicted
   load problem, not just a correctness one.
"""

import asyncio
import statistics
import time
from dataclasses import dataclass

from app.websocket.manager import RedisPubSub, market_events_channel
from app.websocket.manager import manager as global_manager


class LoadSocket:
    """A socket that accepts frames as fast as the gateway offers them."""

    def __init__(self, sid: str = ""):
        self.sid = sid
        self.frames: list[dict] = []
        self.closed = False
        self.delay_s = 0.0

    async def accept(self) -> None:
        """Present so the same stub works for `connect()` as well as grid declare."""

    async def send_json(self, payload: dict) -> None:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        # Stamp at delivery so latency can be attributed to the frame that
        # actually carried it, rather than to whenever the harness looks.
        self.frames.append({**payload, "_at": time.perf_counter()})

    def arrivals(self, market_id: str) -> list[tuple[float, float]]:
        """`(published_at, arrived_at)` for every grid frame carrying this market.

        Arrival must be stamped *here*, at delivery. Reading the clock later -
        after the run finishes - measures when the harness got round to looking,
        not when the data landed, and reports the whole run's duration as if it
        were latency. That is the difference between "86ms" and "3 seconds", and
        it is invisible unless the two are kept separate.
        """
        out = []
        for frame in self.batches():
            payload = frame.get("prices", {}).get(market_id)
            stamp = (payload or {}).get("yes_price")
            if isinstance(stamp, (int, float)):
                out.append((stamp, frame.get("_at", time.perf_counter())))
        return out

    def batches(self) -> list[dict]:
        return [f for f in self.frames if f.get("type") == "market:prices_batch"]

    def reset(self) -> None:
        self.frames.clear()


@dataclass
class Phase:
    name: str
    detail: str = ""
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    max: float = 0.0
    mean: float = 0.0
    units: str = ""

    def render(self) -> str:
        return (
            f"  {self.name:<32} mean {self.mean:>8.2f}{self.units} | "
            f"p50 {self.p50:>8.2f}  p95 {self.p95:>8.2f}  "
            f"p99 {self.p99:>8.2f}  max {self.max:>9.2f}{self.units}"
            + (f"   {self.detail}" if self.detail else "")
        )


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(int(q * len(ordered)), len(ordered) - 1)]


def summarise(name: str, samples: list[float], units: str = "", detail: str = "") -> Phase:
    if not samples:
        return Phase(name, detail or "no samples", units=units)
    return Phase(
        name=name, detail=detail, units=units,
        p50=pct(samples, 0.50), p95=pct(samples, 0.95), p99=pct(samples, 0.99),
        max=max(samples), mean=statistics.fmean(samples),
    )


def is_subscribed(pubsub: RedisPubSub, market_id: str) -> bool:
    """Has this node actually reached SUBSCRIBE for `market_id`'s channel yet?

    Two things make this easy to get wrong, and both fail silently:

      - Declaring a grid is not subscribing. `set_grid` updates the local index
        and then talks to Redis, and that round-trip is asynchronous - so a
        harness that publishes the instant it has declared measures its own race
        instead of the gateway.
      - `_subscribed` holds *channel names* (`market:{id}:events`), not market
        ids. Comparing against a raw id is always False, which reads as "the
        gateway never subscribed" when the gateway is perfectly fine.
    """
    return market_events_channel(market_id) in getattr(pubsub, "_subscribed", set())


async def start_grid_loop() -> asyncio.Task:
    """Run the real flush loop for the life of the harness.

    `broadcast_to_market` only *buffers*; the grid reaches a socket via a timer
    somewhere else entirely. Without that timer running, every socket correctly
    receives nothing and the harness reports a failure that is really the harness
    forgetting to start the server - which is exactly what happened the first
    time this was written.

    The loop belongs in the measurement rather than being stubbed out, because
    its cadence *is* the user-visible latency. Measuring `broadcast_to_market`
    alone would report the cheapest stage of the pipeline and call it the system.
    """
    return asyncio.create_task(global_manager.grid_loop())


def reset_global() -> None:
    """Start a phase from a clean slate.

    Also resets the Redis circuit breaker. It is process-wide state with a
    multi-second recovery timeout, so one phase tripping it silently poisons
    every phase after it - the harness then reports five failures where there is
    one, and the real signal is buried.
    """
    from app.redis import redis_cb

    redis_cb._state = "closed"
    redis_cb._failures = 0
    global_manager._grid_subs.clear()
    global_manager._grid_channels.clear()
    global_manager._grid_subscribers.clear()
    global_manager._grid_pending.clear()
    global_manager._market_subs.clear()
    global_manager._ws_subscriptions.clear()
    global_manager._last_seq.clear()


def require(ok: bool, message: str) -> None:
    """Fail loudly on a missed precondition.

    A `wait_for` whose result is discarded turns "the harness never subscribed"
    into "the gateway delivered nothing", which reads as a product failure and
    sends you hunting in the wrong file entirely.
    """
    if not ok:
        raise AssertionError(f"harness precondition failed: {message}")


async def wait_for(predicate, timeout_s: float = 5.0, poll_s: float = 0.002) -> bool:
    """Wait on a condition instead of sleeping a guessed amount.

    A fixed sleep here would either waste time or flake, and a load harness that
    flakes is worse than none - it gets ignored. Polling for the condition makes
    every phase measure the same thing regardless of machine speed.
    """
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        if predicate():
            return True
        await asyncio.sleep(poll_s)
    return False


# ── [1] Fan-out cost vs. total connection count ─────────────────────────────────


async def phase_fanout_scaling(pubsub: RedisPubSub, markets: list[str]) -> None:
    print("\n[1] Fan-out cost vs. connected sockets  (20 markets, all markets hot)")
    print("    Per-publish time should stay flat. Cost is O(subscribers of the")
    print("    market being published to), not O(sockets on the gateway.")

    for n_sockets in (10, 100, 500, 1000):
        reset_global()
        sockets = [LoadSocket(f"g-{i}") for i in range(n_sockets)]
        for ws in sockets:
            await global_manager.set_grid(ws, markets[:20], pubsub)
        await wait_for(lambda: all(is_subscribed(pubsub, m) for m in markets[:20]))

        # Warm up: SUBSCRIBE acks and set-up must not be counted as steady-state.
        for m in markets[:20]:
            await pubsub.publish_market_event(m, "market:price_update",
                                             {"yes_price": 0.5, "no_price": 0.5})
        await wait_for(lambda: all(s.batches() for s in sockets))
        for s in sockets:
            s.reset()

        samples = []
        for i in range(150):
            market = markets[i % 20]
            t0 = time.perf_counter()
            await pubsub.publish_market_event(market, "market:price_update", {
                "yes_price": 0.40 + (i % 10) / 100,
                "no_price": 0.60 - (i % 10) / 100,
            })
            samples.append((time.perf_counter() - t0) * 1000)
            await asyncio.sleep(0.005)

        await wait_for(lambda: all(s.batches() for s in sockets), timeout_s=10.0)
        per_socket_frames = len(sockets[0].frames) if sockets else 0
        print("\n" + summarise(f"{n_sockets:>5} sockets x 20 mkts", samples, " ms",
                               f"{per_socket_frames} frames delivered/socket",
                               ).render())


# ── [2] Frame amplification ─────────────────────────────────────────────────────


async def phase_frame_amplification(pubsub: RedisPubSub, markets: list[str]) -> None:
    print("\n[2] Grid frame amplification")
    print("    A grid showing K markets gets ONE frame per tick carrying K prices.")
    print("    Frames-per-tick-per-market must stay 1/K - otherwise the server is")
    print("    fine and the browser is the one paying.")

    for n_markets in (10, 50, 200):
        reset_global()
        ws = LoadSocket("grid")
        await global_manager.set_grid(ws, markets[:n_markets], pubsub)
        await wait_for(lambda: all(is_subscribed(pubsub, m) for m in markets[:n_markets]))

        # A tick where every market moves at once, as a busy market produces.
        for m in markets[:n_markets]:
            await pubsub.publish_market_event(m, "market:price_update",
                                             {"yes_price": 0.51, "no_price": 0.49})
        # Coverage, not "exactly one frame".
        #
        # Publishing N markets takes real time, and the flush timer can fire
        # midway through the publish loop and emit a partial batch. That is
        # correct behaviour - the flush is a timer, not a barrier - and a
        # harness asserting a single frame would really be asserting that
        # publishing finished inside one tick, which is a property of the
        # machine rather than of the gateway.
        #
        # The property worth pinning is that every market arrives, and that they
        # arrive in a *few* frames rather than one per market. One per market is
        # the failure mode that leaves the server healthy and melts the browser.
        def covered() -> set[str]:
            out: set[str] = set()
            for f in ws.batches():
                out |= set(f["prices"].keys())
            return out

        await wait_for(lambda: len(covered()) == n_markets, timeout_s=20.0)

        n_prices = len(covered())
        sizes = sorted(len(f["prices"]) for f in ws.batches())
        n_frames = len(sizes)
        ok = n_prices == n_markets and n_frames <= 4
        ratio = n_frames / n_markets if n_markets else 0
        print(f"\n  {n_markets:>4} markets on one grid -> {n_prices} price(s) in "
              f"{n_frames} frame(s)   [{'PASS' if ok else 'FAIL'}]  "
              f"amplification {ratio:.3f}  sizes {sizes}")


# ── [3] Latency distribution ────────────────────────────────────────────────────


async def phase_flush_latency(pubsub: RedisPubSub, markets: list[str]) -> None:
    print("\n[3] Publish -> socket latency  (the number a user feels)")
    print("    End-to-end: publish_market_event, Redis, listener, fan-out, the")
    print("    grid buffer, and the flush timer. Idle vs. saturated.")

    for label, n_markets, n_sockets in (
        ("idle   5 mkts /  50 sockets", 5, 50),
        ("busy  20 mkts / 200 sockets", 20, 200),
        ("hot  100 mkts / 500 sockets", 100, 500),
    ):
        reset_global()
        sockets = [LoadSocket(f"g-{i}") for i in range(n_sockets)]
        for ws in sockets:
            await global_manager.set_grid(ws, markets[:n_markets], pubsub)
        await wait_for(lambda: all(is_subscribed(pubsub, m) for m in markets[:n_markets]))

        # Mark the probe market so latency is measured on one traceable stream
        # rather than smeared across the whole grid.
        probe = markets[0]
        stop = asyncio.Event()

        async def publisher() -> None:
            while not stop.is_set():
                # The stamp rides in the payload, so each arriving frame reports
                # the publish time that actually produced it - not the most recent
                # one, which coalescing guarantees is a different publish.
                await pubsub.publish_market_event(probe, "market:price_update", {
                    "yes_price": time.perf_counter(),
                    "no_price": 0.5,
                })
                await asyncio.sleep(0.02)

        task = asyncio.create_task(publisher())
        await asyncio.sleep(3.0)
        stop.set()
        await task
        await asyncio.sleep(0.6)

        arrivals = [
            (arrived - published) * 1000 for published, arrived in sockets[0].arrivals(probe)
        ]

        print("\n" + summarise(label, arrivals, " ms",
                               f"{len(arrivals)} frames delivered", ).render())


# ── [4] Head-of-line blocking ───────────────────────────────────────────────────


async def phase_slow_consumer(pubsub: RedisPubSub, markets: list[str]) -> None:
    print("\n[4] Head-of-line blocking under slow consumers")
    print("    A few wedged sockets must not delay the flush for everyone else.")

    reset_global()
    healthy = [LoadSocket(f"ok-{i}") for i in range(90)]
    slow = [LoadSocket(f"slow-{i}") for i in range(10)]
    for ws in slow:
        ws.delay_s = 0.05  # 50ms/frame: pathological, but not an infinite hang
    for ws in healthy + slow:
        await global_manager.set_grid(ws, markets[:10], pubsub)
    await wait_for(lambda: all(is_subscribed(pubsub, m) for m in markets[:10]))

    for m in markets[:10]:
        await pubsub.publish_market_event(m, "market:price_update",
                                         {"yes_price": 0.5, "no_price": 0.5})

    t0 = time.perf_counter()
    ok = await wait_for(lambda: all(s.batches() for s in healthy), timeout_s=5.0)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Serialised would be 10 x 50ms = 500ms of pure waiting on the slow ones.
    verdict = "PASS" if ok and elapsed_ms < 200 else "FAIL"
    print("\n  90 healthy + 10 slow(50ms) sockets, one tick")
    print(f"    healthy all fed     {ok!s:>10}   [{verdict}]")
    print(f"    elapsed             {elapsed_ms:>8.1f} ms   (serialised ~500ms)")


# ── [5] seq atomicity under concurrency ─────────────────────────────────────────


async def phase_seq_atomicity(pubsub: RedisPubSub, markets: list[str]) -> None:
    print("\n[5] seq atomicity under concurrent publishers")
    print("    Per-market channel, where coalescing does not apply, so every")
    print("    published sequence must arrive exactly once and in order.")

    reset_global()
    burst_markets = [f"seqburst{i}" for i in range(30)]
    sockets = [_NullSock() for _ in burst_markets]
    for ws, mid in zip(sockets, burst_markets):
        await global_manager.connect(ws, mid)
        # `connect()` registers the socket locally; the Redis SUBSCRIBE is the
        # route's job, so the harness has to do it too or it measures a gateway
        # that is subscribed to nothing.
        await pubsub.subscribe_market(mid)
    require(await wait_for(lambda: all(is_subscribed(pubsub, m) for m in burst_markets)),
           "per-market phases never subscribed - every publish goes nowhere")

    # Sized to the Redis connection pool (`redis_max_connections = 100`).
    #
    # Beyond that, publishes are dropped rather than queued: `publish_market_event`
    # catches the pool error and logs, so the frame is silently lost. That is a
    # real capacity limit and worth knowing, but it is not a *sequencing* limit -
    # and testing it here would just measure the pool. The seq guarantee only
    # needs enough concurrency that a split INCR/PUBLISH would reorder, and 60
    # racing publishers is far more than enough for that.
    #
    # What makes the loss safe is the same `seq` beacon: the client sees the gap
    # and repairs from REST. Degradation, not corruption.
    total = 60
    burst = [burst_markets[i % len(burst_markets)] for i in range(total)]

    await asyncio.gather(*(
        pubsub.publish_market_event(mid, "market:price_update",
                                    {"yes_price": 0.5, "no_price": 0.5})
        for mid in burst
    ))
    await asyncio.sleep(1.5)

    # `seq` is per-market: each market has its own counter starting at 1. Pooling
    # them and sorting gives 1,1,2,2,3,3..., so every repeat looks like a gap and
    # a perfectly ordered stream reads as broken. Contiguity is only meaningful
    # within one market's own sequence.
    delivered = 0
    gaps: list[tuple[str, int, int]] = []
    for mid, ws in zip(burst_markets, sockets):
        own = sorted(f["seq"] for f in ws.frames if isinstance(f.get("seq"), int))
        delivered += len(own)
        for a, b in zip(own, own[1:]):
            if b != a + 1:
                gaps.append((mid, a, b))
    ok = delivered == total and not gaps
    print(f"\n  {total} concurrent publishes across {len(burst_markets)} markets"
          f" -> {delivered} frames")
    print(f"    gaps / reordering    {len(gaps):>10}   "
          f"[{'PASS - gapless' if ok else f'FAIL {gaps[:3]}'}]"
          + ("" if delivered == total else f"   ({delivered}/{total} arrived)"))


class _NullSock:
    """Collects per-market frames; `connect` only needs `accept` + `send_json`."""

    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def accept(self) -> None:
        """`connect()` calls this; a real socket would begin its read loop here."""

    async def send_json(self, payload: dict) -> None:
        self.frames.append(payload)


async def phase_coalescing_not_loss(pubsub: RedisPubSub, markets: list[str]) -> None:
    """A collapsed update must not look like a lost one.

    Grid aggregation drops intermediate sequence numbers *on purpose*. Judging
    contiguity on the last `seq` alone therefore makes every busy market look
    lossy on every tick, and the client responds by refetching the whole markets
    query - hundreds of times a second, from every open grid. That is a load
    problem the server causes and the client pays for.

    `seq_from` is the fix: contiguity is judged from the first sequence the
    flush window actually saw.
    """
    print("\n[6] Coalescing must not be mistaken for loss")
    print("    A market ticking many times per flush must stay contiguous.")

    market = markets[0]
    reset_global()
    ws = LoadSocket("grid")
    await global_manager.set_grid(ws, [market], pubsub)
    require(await wait_for(lambda: is_subscribed(pubsub, market)),
           "grid never subscribed - nothing to baseline against")

    # Establish the baseline the client would hold. `seq` is monotonic for the
    # life of the market, not reset per harness run, so asserting `seq_from == 1`
    # would be asserting something that stopped being true on the first publish.
    # Establish the baseline the client would already be holding. Something has to
    # publish for there to be a frame to read - waiting on a quiet market waits
    # forever, which is correct behaviour and useless as a measurement.
    await pubsub.publish_market_event(market, "market:price_update",
                                      {"yes_price": 0.5, "no_price": 0.5})
    baseline: int | None = None
    for _ in range(40):
        await asyncio.sleep(0.02)
        if ws.batches():
            baseline = ws.batches()[-1]["prices"][market].get("seq")
            break
    if baseline is None:
        print("\n  no baseline frame arrived - FAIL")
        return
    ws.reset()
    await asyncio.sleep(0.4)  # let the buffer drain so the burst starts clean

    # Ten ticks inside one flush window - the coalescing case.
    for i in range(10):
        await pubsub.publish_market_event(market, "market:price_update", {
            "yes_price": 0.5 + i / 100, "no_price": 0.5 - i / 100,
        })

    got = False
    for _ in range(200):
        await asyncio.sleep(0.02)
        if ws.batches():
            got = True
            break
    if not got:
        print("\n  no grid frame arrived - FAIL")
        return
    payload = ws.batches()[0]["prices"][market]
    seq, seq_from = payload.get("seq"), payload.get("seq_from")

    # One frame, and it accounts for the whole window.
    collapsed = len(ws.batches()) == 1
    contiguous = isinstance(seq_from, int) and seq_from == baseline + 1
    ok = collapsed and contiguous
    print(f"\n  baseline seq {baseline}; 10 ticks in one window -> "
          f"{len(ws.batches())} frame (seq {seq_from}..{seq})")
    print(f"    judged lossy?        {str(not contiguous):>10}   "
          f"[{'PASS - not loss' if ok else 'FAIL'}]")


async def main() -> None:
    from app.config import settings

    print("=" * 78)
    print("Realtime gateway load harness")
    print(f"  redis {settings.redis_url}")
    print("=" * 78)

    pubsub = RedisPubSub()
    await pubsub.connect()
    await pubsub.start_listener()
    grid_task = await start_grid_loop()
    markets = [f"loadm{i}" for i in range(200)]

    try:
        phases = (
            phase_fanout_scaling,
            phase_frame_amplification,
            phase_flush_latency,
            phase_slow_consumer,
            phase_seq_atomicity,
            phase_coalescing_not_loss,
        )
        for phase in phases:
            # Each phase is isolated: a harness that aborts on the first exception
            # reports one problem per run and has to be re-run after every fix.
            try:
                await phase(pubsub, markets)
            except Exception as exc:  # noqa: BLE001
                print(f"\n  [ERROR] {phase.__name__}: {type(exc).__name__}: {exc}")
    finally:
        grid_task.cancel()
        await asyncio.gather(grid_task, return_exceptions=True)
        await pubsub.close()

    print("\n" + "=" * 78)

if __name__ == "__main__":
    asyncio.run(main())