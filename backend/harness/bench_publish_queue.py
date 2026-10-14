"""Measure what the publish queue can actually drain, against real Redis.

## Why this exists

`settings.publish_writers = 8` with 20,000 / 10,000 queue depths was chosen by
arithmetic, not measurement. The supporting comment cites ~0.6ms per publish -
but that number comes from `load_realtime`'s fan-out phase, which measures
**in-process socket fan-out**. It says nothing about the thing the writers
actually do, which is a round trip to Redis.

This bench was written because `load_realtime`'s burst phase enqueued `_make_noop`
operations: it measured the queue's internal plumbing and never touched Redis at
all, so the writer pool had never been observed doing its job against the system
it publishes to.

That has since been fixed - `load_realtime` phase 7 now enqueues the app's own
`market_publish_op` and counts frames on a subscribed socket. What this bench adds
on top is the **depth sweep**, which is what sets `publish_queue_critical` and
`publish_queue_ephemeral`: where the queue starts coalescing ephemeral frames, and
where it starts refusing to drop critical ones.

Queue depth is only meaningful relative to drain rate. A 20,000-frame queue is a
generous buffer or a trivial one depending entirely on how fast writers retire
frames, so the two have to be read together. This harness measures the rate, then
reports the burst window each configuration actually buys.

## What it answers

1. Does throughput scale with writers, or does Redis saturate first? The answer
   decides whether more writers help at all - if Redis is the wall, raising the
   pool just moves the queue's backlog around.
2. At the measured rate, how long does a full queue take to drain? That is the
   real size of the buffer, in seconds, which is the only unit an operator can
   reason about.
3. Does the configured pool drain a full 20,000-frame queue faster than the queue
   is likely to fill? If not, the depth is a delay, not a safety margin.

Run:  python -m harness.bench_publish_queue
"""

import asyncio
import json
import statistics
import time

from app.config import settings
from app.redis import get_redis
from app.websocket.publish_queue import PublishDispatcher

# A scratch channel nothing subscribes to, so the measurement is publish
# throughput and not fan-out.
CHANNEL = "bench:publish_queue:sink"

PAYLOAD = json.dumps({"type": "market:price_update", "payload": {"p": 0.5}, "pad": "x" * 256})

# Repeated runs per configuration. A single run on a shared machine is noise.
REPEATS = 3


def _bench_client(configured_writers: int, redis) -> tuple[PublishDispatcher, asyncio.Queue]:
    """A dispatcher whose writers perform real Redis publishes."""
    published: asyncio.Queue = asyncio.Queue()

    async def send(pending) -> None:
        await redis.publish(CHANNEL, PAYLOAD)
        published.put_nowait(1)

    return (
        PublishDispatcher(
            send=send,
            writers=configured_writers,
            ephemeral_max=20_000,
            critical_max=10_000,
        ),
        published,
    )


async def _measure(redis, writers: int, frames: int) -> tuple[float, float]:
    """One run: enqueue `frames` publishes, return (seconds, frames/second).

    Real Redis round trips throughout, timed from the first enqueue to the last
    write completing.

    The `offer` loop yields often on purpose. An earlier version enqueued all
    20,000 frames in a tight loop, which starves the writer tasks - they cannot
    run until the loop yields - so the result measured how long it took to *build
    the queue*, not how fast it drained. It produced a non-monotonic curve (2
    writers appearing slower than 1) that was really just scheduling noise.
    """
    dispatcher, published = _bench_client(writers, redis)
    await dispatcher.start()

    # Prime the pool so connection setup is not counted as throughput.
    await redis.publish(CHANNEL, PAYLOAD)
    await asyncio.sleep(0.2)
    while not published.empty():
        published.get_nowait()

    async def offer() -> None:
        # Yield regularly so the writers actually get to run while we fill the
        # queue; otherwise this measures queue construction, not drain.
        for i in range(frames):
            dispatcher.enqueue(lambda: asyncio.sleep(0), frame="market:price_update")
            if i % 250 == 0:
                await asyncio.sleep(0)

    t0 = time.perf_counter()
    await offer()
    deadline = t0 + 120
    while published.qsize() < frames and time.perf_counter() < deadline:
        await asyncio.sleep(0.01)
    elapsed = time.perf_counter() - t0

    await dispatcher.stop()
    return elapsed, frames / elapsed


async def main() -> None:
    redis = await get_redis()
    await redis.ping()

    frames = 20_000
    print("=" * 74)
    print("Publish-queue drain throughput, against real Redis")
    print(f"payload {len(PAYLOAD)}B · {frames:,} frames per run")
    print(f"configured: {settings.publish_writers} writers, "
          f"{settings.publish_queue_ephemeral:,} ephemeral / "
          f"{settings.publish_queue_critical:,} critical")
    print("=" * 74)

    # A discarded warm-up first: the first run pays for lazy imports, pool
    # growth and allocator warm-up, and none of that is steady-state behaviour.
    await _measure(redis, 4, 2_000)

    results: dict[int, tuple[float, float]] = {}
    for writers in (1, 2, 4, 8, 16, 32):
        runs = [await _measure(redis, writers, frames) for _ in range(REPEATS)]
        rates = [r for _, r in runs]
        # Best-of, not mean: the best run is the one least disturbed by whatever
        # else the machine was doing. A mean would fold scheduler noise into the
        # number and make the pool look noisier than it is.
        best = max(rates)
        median = statistics.median(rates)
        results[writers] = (frames / best, best)
        spread = f" (median {median:,.0f})" if REPEATS > 1 else ""
        print(f"  {writers:3d} writers  {best:>10,.0f} frames/s{spread}")

    print("\nScaling:")
    base = results[1][1]
    for writers in sorted(results):
        print(f"  {writers:3d} writers  {results[writers][1] / base:>5.2f}x vs 1 writer")

    best_writers = max(results, key=lambda w: results[w][1])
    best_rate = results[best_writers][1]
    configured_rate = results.get(settings.publish_writers, (0, 0))[1]

    print("\nWhat the configured depths actually buy, in seconds of buffer:")
    for depth, name in (
        (settings.publish_queue_ephemeral, "ephemeral"),
        (settings.publish_queue_critical, "critical"),
    ):
        print(f"  {name:<10} {depth:>7,} frames  ->  "
              f"{depth / best_rate:>6.2f}s at the best measured rate, "
              f"{depth / configured_rate:>6.2f}s at the configured one")

    print("\nVerdict:")
    if configured_rate >= best_rate * 0.95:
        print(f"  the configured pool ({settings.publish_writers} writers) is within 5% of the")
        print(f"  best measured rate ({best_writers} writers). More writers would not help;")
        print("  Redis is the ceiling.")
    else:
        print(f"  the configured pool ({settings.publish_writers} writers) reaches "
              f"{configured_rate:,.0f}/s,")
        print(f"  but {best_writers} writers reach {best_rate:,.0f}/s "
              f"({best_rate / configured_rate:.2f}x).")

    # Diminishing returns: if doubling the largest pool bought under 15% more,
    # the writers have stopped being the constraint.
    biggest = max(results)
    half = biggest // 2
    if half in results and results[biggest][1] / results[half][1] < 1.15:
        print(f"  doubling {half} -> {biggest} writers bought under 15% more, so the pool")
        print("  has saturated: Redis, not the number of writers, is the limit.")


if __name__ == "__main__":
    asyncio.run(main())