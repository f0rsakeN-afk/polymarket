"""The publish queue, drained against real Redis rather than a stub.

Every other test in this area drives the queue with fake senders, which is right
for testing the *policy* - what coalescing drops, what spills, what is owed a
resync - and useless for testing the *machine*. A queue can implement every rule
correctly and still fall over at depth, because the thing it is buffering against
is a Redis round trip it has never actually made.

`load_realtime`'s burst phase has the same blind spot, and worse: it enqueues
`_make_noop` operations, so it measures the queue's internal bookkeeping and
reports a healthy drain while nothing is ever published anywhere.

So these run the writers against real Redis at the configured depths. Speed is
deliberately not asserted - that belongs to `harness/bench_publish_queue.py` and
would be flaky here - but *correctness at depth* is a property of the code and
can be pinned.
"""

import asyncio
import time

import pytest

from app.config import settings
from app.redis import get_redis
from app.websocket.publish_queue import PublishDispatcher

CHANNEL = "test:publish_queue:real_redis"


async def _drain(redis, *, writers: int, frames: int, frame: str, owed: str | None = None):
    """Push `frames` real publishes through the queue. Returns the dispatcher."""
    written: asyncio.Queue = asyncio.Queue()

    async def send(_pending) -> None:
        await redis.publish(CHANNEL, b'{"type":"probe"}')
        written.put_nowait(1)

    dispatcher = PublishDispatcher(
        send=send,
        writers=writers,
        ephemeral_max=settings.publish_queue_ephemeral,
        critical_max=settings.publish_queue_critical,
    )
    await dispatcher.start()
    try:
        for i in range(frames):
            dispatcher.enqueue(
                lambda: asyncio.sleep(0),
                frame=frame,
                owe_resync_to=owed,
            )
        deadline = time.monotonic() + 90
        while written.qsize() < frames and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert written.qsize() == frames, (
            f"only {written.qsize()}/{frames} publishes reached Redis - the drain "
            f"stalled or dropped frames at {writers} writers"
        )
    finally:
        await dispatcher.stop()
    return dispatcher


@pytest.mark.asyncio
async def test_a_full_ephemeral_queue_drains_without_loss():
    """A burst exactly filling the queue must come out whole.

    At capacity and not over it, coalescing must not fire: drop-oldest is
    correct behaviour *past* the bound, and using it at exactly the bound would
    mean the queue silently discards a frame every time it fills - which is the
    difference between a buffer and a lossy channel that only looks lossless.
    """
    redis = await get_redis()
    await redis.ping()

    frames = settings.publish_queue_ephemeral
    dispatcher = await _drain(redis, writers=settings.publish_writers, frames=frames, frame="price_update")

    assert dispatcher.depth["ephemeral"] == 0
    assert dispatcher.depth["critical"] == 0
    # Nothing was owed a resync: an ephemeral burst that drained cleanly is not
    # a reconciliation event.
    assert dispatcher.owed_resyncs == 0


@pytest.mark.asyncio
async def test_a_full_critical_queue_drains_without_owing_a_resync():
    """The critical queue is the one that costs something when it overflows.

    Spilling marks every affected user as owing a resync, which becomes real
    reconciliation traffic against the API. So a burst that fits must drain with
    no spill - otherwise the queue manufactures work for itself every time it
    fills, and the resync alert fires for a burst that was actually delivered.
    """
    redis = await get_redis()
    await redis.ping()

    frames = settings.publish_queue_critical
    dispatcher = await _drain(
        redis,
        writers=settings.publish_writers,
        frames=frames,
        frame="order:fill",
        owed="user-bench",
    )

    assert dispatcher.depth["critical"] == 0
    assert dispatcher.owed_resyncs == 0, (
        "a critical burst that fit in the queue still owed a resync - the "
        "overflow check is firing at capacity rather than past it"
    )


@pytest.mark.asyncio
async def test_overflow_past_the_bound_coalesces_prices_rather_than_losing_them():
    """One past the bound, and the newest price is the one that survives.

    This is the documented policy, and it is the right one: an older price
    arriving late is stale, and delivering it would move a user's display
    *backwards* to a value they have already seen superseded. Coalescing keeps the
    newest, which is the same answer the client would have reached on its own.
    """
    redis = await get_redis()
    await redis.ping()

    max_depth = settings.publish_queue_ephemeral
    written: asyncio.Queue = asyncio.Queue()

    async def send(_pending) -> None:
        await redis.publish(CHANNEL, b'{"type":"probe"}')
        written.put_nowait(1)

    dispatcher = PublishDispatcher(
        send=send,
        writers=settings.publish_writers,
        ephemeral_max=max_depth,
        critical_max=settings.publish_queue_critical,
    )
    await dispatcher.start()
    try:
        for i in range(max_depth + 500):
            dispatcher.enqueue(lambda: asyncio.sleep(0), frame="price_update")

        deadline = time.monotonic() + 90
        # Exactly `max_depth` frames can come out: 500 were coalesced away.
        while written.qsize() < max_depth and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
    finally:
        await dispatcher.stop()

    assert written.qsize() == max_depth, (
        f"{written.qsize()} published for a {max_depth}-frame queue - overflow "
        "should coalesce, not block and not grow"
    )
    assert dispatcher.owed_resyncs == 0, (
        "coalescing a price must never owe a resync - nothing was lost, only "
        "superseded, and a resync here would be pure cost"
    )