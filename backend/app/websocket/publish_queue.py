"""Bounded, rate-decoupled publishing to Redis.

## The problem

`max_connections` is a cliff, not a queue. Past it redis-py raises
`MaxConnectionsError` rather than waiting for a connection to free up. Measured
against real Redis:

    burst  300 -> ok=100 failed=200  {MaxConnectionsError}
    burst 1000 -> ok=100 failed=900  {MaxConnectionsError}

Every publisher in this codebase ended that in `except: log.warning(...)`. So
under burst the trade was committed to Postgres and the client was simply never
told. That is the worst failure shape available: no error the user sees, no
rollback, and a log line nobody was watching. Worse, it compounds - every dropped
frame becomes a client-detected gap, every gap becomes a REST refetch, and the
refetches arrive precisely when the system is already saturated.

## The fix

Decouple *rate* from *concurrency*. Callers hand a closure to `enqueue()` and
return; a small pool of writers drains to Redis sequentially.

A writer holds one connection no matter how large the burst, so the pool size
stops being a correctness cliff and becomes a throughput knob. And the queue
being explicitly bounded turns silent loss into observable backpressure, which
is the difference between a system that degrades and one that fails quietly.

## Two delivery classes, because "can this be lost?" has two answers

The queue exists to stop dropping, but some frames are legitimately droppable and
dropping them is *better* than queueing them, so a single policy would be wrong
in both directions.

**Ephemeral** - prices. Only the newest value matters; the grid coalesces
anyway, so an older price that arrives late is not merely redundant, it is
actively wrong. Overflow drops the oldest and keeps the newest, which is
precisely the coalescing the client would have done.

**Critical** - fills, orderbook updates, position updates. These must not vanish.
On overflow the frame is dropped *and the affected client is owed a resync*: the
event is dropped, but the client is told to refetch the state that event would
have told it. That is spill-and-reconcile rather than spill-and-forget, and it
is cheap - one marker per affected client, not one per dropped frame.

Crucially the reconciliation is already built: `applyPrivateFeedResync`
invalidates positions, orders, wallet and notifications. These events are
durable in Postgres, so "the client did not see this happen" and "the client
does not see that it happened" are recoverable states. The marker is what makes
the difference.

## Why this never blocks a request

`enqueue()` is synchronous and never awaits. That matters more than it looks:
`place_order` holds `SELECT ... FOR UPDATE` on Market, Pool and Wallet for the
whole of execution, so anything that waits here would extend lock hold time under
exactly the load that caused the problem, converting a throughput ceiling into
lock contention and deadlock pressure.

Publishing also already happens after `await db.commit()` on the order path, so
DB state is durable before a frame is offered - which is what makes deferring the
write to a writer task safe rather than a window onto uncommitted truth.
"""

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from app.middleware.metrics import (
    WS_PUBLISH_DROPPED,
    WS_PUBLISH_QUEUE_DEPTH,
    WS_PUBLISH_QUEUED,
    WS_PUBLISH_SPILL_OWED,
)

logger = logging.getLogger(__name__)

# Frames that must never be silently lost.
CRITICAL_FRAMES = frozenset(
    {
        "trade:new",
        "orderbook:update",
        "order:fill",
        "position:update",
        "order:update",
        "trade:settlement",
    }
)


class Delivery(StrEnum):
    EPHEMERAL = "ephemeral"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Pending:
    """One publish waiting for a writer."""

    op: Callable[[], Awaitable]
    delivery: Delivery
    #: Event type - what the frame *is*, and what decides its delivery class.
    frame: str
    #: Metric series - the call site. See `RedisPubSub.enqueue_publish`.
    label: str = ""
    #: Private channel to owe a resync to, if this frame overflows. `None` for
    #: market-scoped frames, where the `seq` gap already drives reconciliation.
    owe_resync_to: str | None = None


class PublishDispatcher:
    """Bounded queues plus a fixed pool of writers."""

    def __init__(
        self,
        *,
        send: Callable[[Pending], Awaitable],
        writers: int = 4,
        ephemeral_max: int = 20_000,
        critical_max: int = 10_000,
        resync: Callable[[str], Awaitable] | None = None,
    ) -> None:
        self._send = send
        self._writers = max(1, writers)
        self._resync = resync
        self._ephemeral: deque[Pending] = deque()
        self._critical: deque[Pending] = deque()
        self._ephemeral_max = ephemeral_max
        self._critical_max = critical_max
        self._tasks: list[asyncio.Task] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake = asyncio.Event()
        self._owed_resyncs: set[str] = set()

    # ── Introspection, for tests and /metrics ────────────────────────────────

    @property
    def depth(self) -> dict[str, int]:
        return {
            Delivery.EPHEMERAL.value: len(self._ephemeral),
            Delivery.CRITICAL.value: len(self._critical),
        }

    @property
    def owed_resyncs(self) -> int:
        return len(self._owed_resyncs)

    # ── The hot path ────────────────────────────────────────────────────────

    def enqueue(
        self,
        op: Callable[[], Awaitable],
        *,
        frame: str,
        label: str | None = None,
        owe_resync_to: str | None = None,
    ) -> bool:
        """Offer a publish. Returns False if it was dropped for overflow.

        Synchronous by design - see the module docstring. The caller gets no
        back-pressure signal it is expected to act on, because the one caller that
        *could* act is holding database locks.
        """
        delivery = Delivery.CRITICAL if frame in CRITICAL_FRAMES else Delivery.EPHEMERAL
        WS_PUBLISH_QUEUED.labels(delivery.value).inc()
        pending = Pending(
            op=op,
            delivery=delivery,
            frame=frame,
            label=label or frame,
            owe_resync_to=owe_resync_to if delivery is Delivery.CRITICAL else None,
        )

        if delivery is Delivery.CRITICAL:
            if len(self._critical) >= self._critical_max:
                self._spill(pending)
                return False
            self._critical.append(pending)
        else:
            if len(self._ephemeral) >= self._ephemeral_max:
                # Drop the oldest, keep the newest.
                #
                # Coalescing is what the grid does anyway, so an older price that
                # arrived late is not redundant - it is stale, and delivering it
                # would move a user's display *backwards* to a price they have
                # already seen superseded. Keeping the newest is the same answer
                # the client would have reached, reached sooner and without
                # spending a Redis round-trip per discarded frame.
                self._ephemeral.popleft()
                WS_PUBLISH_DROPPED.labels(Delivery.EPHEMERAL.value, "overflow_coalesced").inc()
            self._ephemeral.append(pending)

        WS_PUBLISH_QUEUE_DEPTH.labels(delivery.value).set(
            len(self._critical if delivery is Delivery.CRITICAL else self._ephemeral)
        )
        self._wake.set()
        return True

    def _spill(self, pending: Pending) -> None:
        """Overflow on a frame that must not be lost.

        The event is dropped but the reconciliation is not: the client is marked
        as owing a resync and told once the queue has drained. Without that this
        would be silent loss dressed up as backpressure - the frame is gone and
        nobody downstream knows to go and get it.

        Frames with no private channel (market-scoped ones) have nowhere to send
        a marker, and do not need one: the `seq` gap they leave behind is already
        the client's trigger to refetch from REST. So the debt is only real for
        private frames, and the counter reflects exactly that.
        """
        WS_PUBLISH_DROPPED.labels(Delivery.CRITICAL.value, "overflow_spilled").inc()
        if pending.owe_resync_to:
            WS_PUBLISH_SPILL_OWED.labels(pending.label or pending.frame).inc()
            self._owed_resyncs.add(pending.owe_resync_to)
            self._wake.set()
        else:
            # Market-scoped: the seq gap already drives reconciliation. Logged
            # because it is the one case with no automatic repair.
            logger.warning(
                "critical frame dropped, no client marker possible frame=%s",
                pending.frame,
            )

    # ── Writers ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        # Restart if any writer is gone, not merely if the list is empty.
        #
        # `if self._tasks` looks like a guard and is not one: the list can be full
        # of tasks that have already finished - because the writer died, or
        # because the event loop they were bound to is gone. Then every publish
        # would enqueue into a queue nobody is draining, which turns a transient
        # writer failure into a slow, silent memory leak with no error anywhere.
        # `start_listener` already guards this way for the same reason.
        # A task on a *closed* loop reports `done() is False` forever - it was
        # never cancelled, it was orphaned. Comparing the loop is the only way to
        # tell "still running" from "belongs to a world that no longer exists",
        # and `done()` alone gets that wrong in exactly the case where it costs
        # the most: a silent queue nobody is draining.
        loop = asyncio.get_running_loop()
        if (
            self._tasks
            and self._loop is loop
            and not any(t.done() for t in self._tasks)
        ):
            return
        if self._tasks and self._loop is not loop:
            logger.warning(
                "publish writers belong to a closed event loop; restarting"
            )
        self._loop = loop
        self._tasks = [t for t in self._tasks if not t.done()]
        self._tasks = [
            asyncio.create_task(self._writer(i), name=f"publish-writer-{i}")
            for i in range(self._writers)
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []

    def _next(self) -> Pending | None:
        # Critical first: it is the class that must not be delayed by the one
        # that is allowed to be dropped, so it never queues behind it.
        if self._critical:
            return self._critical.popleft()
        if self._ephemeral:
            return self._ephemeral.popleft()
        return None

    async def _writer(self, idx: int) -> None:
        while True:
            pending = self._next()
            if pending is None:
                # Nothing to do. Reconcile before idling, so an owed resync is
                # not left sitting until the next frame happens to arrive.
                await self._flush_owed_resyncs()
                self._wake.clear()
                # A lost wakeup here would park this writer while work waits, so
                # the clear-then-check order matters: re-check after clearing.
                if self._next() is None:
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(self._wake.wait(), timeout=1.0)
                continue

            try:
                await self._send(pending)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # one bad frame must not kill the writer
                logger.warning("publish writer %d frame=%s failed: %s", idx, pending.frame, exc)
            finally:
                self._update_depth()

    def _update_depth(self) -> None:
        WS_PUBLISH_QUEUE_DEPTH.labels(Delivery.EPHEMERAL.value).set(len(self._ephemeral))
        WS_PUBLISH_QUEUE_DEPTH.labels(Delivery.CRITICAL.value).set(len(self._critical))

    async def _flush_owed_resyncs(self) -> None:
        if not self._owed_resyncs or self._resync is None:
            return
        # Swap first: a marker that fails must not block the ones behind it.
        owed, self._owed_resyncs = self._owed_resyncs, set()
        for user_id in owed:
            try:
                await self._resync(user_id)
            except Exception as exc:
                logger.warning("owed resync failed user=%s: %s", user_id, exc)