"""
Scalable WebSocket connection manager for 50k+ concurrent users.

Key design decisions for scale:
- Per-market locks: broadcasts to different markets never block each other
- Per-socket locks: concurrent subscribe/unsubscribe on same socket don't corrupt state
- Fire-and-forget send: each socket send is an independent asyncio task,
  one slow socket doesn't block others
- Async dead-socket cleanup: doesn't block the broadcast path
- Connection caps per IP and per user: prevents file-descriptor exhaustion
- Per-socket subscription registry with server-side filtering:
  a client only receives updates for markets it explicitly subscribed to
- Per-socket subscription cap: prevents memory exhaustion from malicious clients
"""

import asyncio
import json
import logging
import time
from collections import defaultdict, deque

import redis.asyncio as redis
from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.config import settings
from app.middleware.metrics import (
    WS_CONNECTIONS,
    WS_CONNECTS_TOTAL,
    WS_DISCONNECTS_TOTAL,
    WS_MESSAGES_FANNED_OUT,
    WS_PUBLISH_FAILURES,
    WS_SENDS_TOTAL,
    WS_SUBSCRIPTIONS,
)
from app.redis import get_redis, redis_cb
from app.websocket.publish_queue import Delivery, Pending, PublishDispatcher

# Bound concurrent broadcast tasks to avoid OOM at 5k msg/s (H9 fix)
_broadcast_sem = asyncio.Semaphore(200)

# Registry key for sockets that asked for the platform-wide trade feed
# (`/ws/trades`). Not a real market id - `disconnect` already skips `__`-prefixed
# keys when unsubscribing from Redis, which is why the sentinel is namespaced.
GLOBAL_TRADES_KEY = "__global_trades__"

# Exact Redis channel carrying the platform-wide trade feed.
# Matched as a whole string, never by prefix: it splits into two `:`-separated
# parts, so prefix routing ("global" matches no known prefix) dropped it.
GLOBAL_TRADES_CHANNEL = "global:trades"


class GridFlushStats:
    """Rolling view of what the grid flush is actually costing.

    A gateway that cannot report its own latency cannot be tuned, and "the tick
    is 250ms" says nothing about whether a price is 20ms old or 200ms old. The
    harness measured p95 near 213ms at 500 sockets while the configured interval
    said 250ms - close enough to look fine, and completely different as an
    experience.

    Keeps bounded samples rather than accumulating history, because this lives in
    a long-lived worker and an unbounded list is a slow leak in a process that is
    supposed to be steady-state.
    """

    __slots__ = ("_elapsed", "_sockets", "_intervals", "_maxlen")

    def __init__(self, maxlen: int = 256) -> None:
        self._maxlen = maxlen
        self._elapsed: deque[float] = deque(maxlen=maxlen)
        self._sockets: deque[int] = deque(maxlen=maxlen)
        self._intervals: deque[float] = deque(maxlen=maxlen)

    def observe(self, sockets_sent: int, elapsed_s: float, interval_s: float) -> None:
        self._elapsed.append(elapsed_s)
        self._sockets.append(sockets_sent)
        self._intervals.append(interval_s)

    @staticmethod
    def _pct(values: deque, q: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        return ordered[min(int(q * len(ordered)), len(ordered) - 1)]

    @property
    def flush_p95_s(self) -> float:
        """p95 flush duration - the work, excluding the sleep between ticks."""
        return self._pct(self._elapsed, 0.95)

    @property
    def interval_p50_s(self) -> float:
        """The cadence the controller settled on."""
        return self._pct(self._intervals, 0.50)

    @property
    def sockets_per_flush(self) -> int:
        return self._sockets[-1] if self._sockets else 0

    def snapshot(self) -> dict:
        return {
            "flush_p95_s": round(self.flush_p95_s, 4),
            "interval_p50_s": round(self.interval_p50_s, 4),
            "sockets_last_flush": self.sockets_per_flush,
            "samples": len(self._elapsed),
        }


def next_grid_interval(
    current: float,
    *,
    sockets_sent: int,
    elapsed_s: float,
    base: float,
    floor: float,
    step: float,
    saturation_ratio: float,
) -> float:
    """Choose the next grid flush interval from what the last one cost.

    Multiplicative decrease, additive increase. That shape is deliberate: it
    reacts fast when saturation is costing real latency, and recovers gradually,
    so one busy moment does not leave every socket pinned at the floor for the
    rest of the process's life.

    Extracted from `grid_loop` so the policy can be tested directly. A test that
    re-implements the arithmetic next to the code proves nothing - it passes
    when the loop is broken, which is the only thing a test is for.
    """
    if sockets_sent == 0:
        # Nothing to send. Drift back toward the base instead of staying at
        # whatever an earlier busy period pushed it to.
        return min(base, current + step)
    if elapsed_s > current * saturation_ratio:
        # The flush is eating the tick. Prices are ageing in the queue and the
        # cadence is the thing making them stale.
        return max(floor, current * 0.5)
    return min(base, current + step)


# Marker telling a client its private feed has a hole it should repair.
#
# Must stay byte-identical to `WS_RESYNC` in
# `frontend/apps/web/lib/ws-resync.ts`. It is a wire contract with no shared
# schema behind it, which is exactly the kind of thing that drifts silently -
# the server would send a frame the client does not recognise and the resync
# would simply never happen, with nothing failing anywhere. The value is pinned
# by a test for that reason.
WS_RESYNC = "__ws_resync__"


def market_events_channel(market_id: str) -> str:
    """The single Redis channel carrying every frame for one market.

    Price updates used to go to a separate `market:{id}:price` channel from
    everything else. Two channels for one logical feed is two orderings: the
    publishes are independent round-trips, so two concurrent orders could land
    as price(A), price(B), trade(A), trade(B), book(A), book(B) and every client
    would render a book that contradicted the price printed beside it, with no
    way to detect it. One channel is one order.

    The `market:{id}:price` *key* (an HSET cache read by `market_service`) is
    unaffected - it was never a channel and is still written by every price
    publish.
    """
    return f"market:{market_id}:events"


def market_seq_key(market_id: str) -> str:
    """Counter backing the per-market frame sequence number."""
    return f"market:{market_id}:seq"


# Atomic "allocate a sequence number and publish it" script.
#
# This has to be one round-trip and one atomic step, for two reasons:
#
#  1. Allocate-then-publish as two commands lets two publishers interleave -
#     A gets seq 1, B gets seq 2, B's PUBLISH lands first - and the client sees
#     seq 2 then seq 1. A gap-detecting client cannot tell that reorder from
#     real loss and would resync on every busy tick.
#  2. INCR and PUBLISH inside one script means no publisher, in *any* process
#     (every API worker and every Celery worker publishes), can slip between
#     them. An asyncio lock would not help: it is per process.
#
# `__SEQ__` is a placeholder rather than a Python format call because the
# payload is JSON that subscribers already parse; splicing the number in
# server-side keeps the frame shape identical. The token is distinctive enough
# not to collide with real content.
#
# The quotes are part of the match, and that is load-bearing: `tostring(seq)`
# yields a *string*, so replacing the bare token would produce `"seq": "7"`, and
# every consumer's `typeof seq === "number"` guard would silently reject it -
# gap detection would look wired up and never fire. Swallowing the quotes puts a
# real JSON number in the frame.
_SEQ_AND_PUBLISH_LUA = """
local seq = redis.call('INCR', KEYS[1])
local msg = string.gsub(ARGV[1], '"__SEQ__"', tostring(seq))
redis.call('PUBLISH', KEYS[2], msg)
return seq
"""


async def _bounded_broadcast(coro):
    async with _broadcast_sem:
        return await coro


logger = logging.getLogger("PredictX")

# ── Per-market locks ────────────────────────────────────────────────────────────


class MarketLockTable:
    """
    Per-market locks • avoids global lock contention.
    Lazily creates locks as markets gain subscribers.
    """

    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}

    async def _get_lock(self, market_id: str) -> asyncio.Lock:
        # setdefault is atomic for the specific key • no global lock needed.
        # Each market_id gets its own asyncio.Lock, created exactly once.
        return self._locks.setdefault(market_id, asyncio.Lock())

    async def release_if_idle(self, market_id: str) -> None:
        """Drop a market's lock once it has no subscribers left.

        The subscriber set was being deleted at zero but its lock was not, so
        `_locks` grew by one entry per market the process ever served and never
        shrank - a slow, permanent leak on a long-lived worker.
        """
        lock = self._locks.get(market_id)
        if lock is not None and not lock.locked():
            self._locks.pop(market_id, None)


_market_locks = MarketLockTable()


# ── Connection Manager ────────────────────────────────────────────────────────


class ConnectionManager:
    """
    Per-market WebSocket subscription manager.

    Scales to 50k+ connections by:
    1. Per-market locks • broadcasts to market A never block market B
    2. Per-socket locks • concurrent subscribe/unsubscribe on same socket are safe
    3. Fire-and-forget send • each socket gets its own asyncio task
    4. Connection limits • prevents file-descriptor exhaustion per IP/user
    5. Per-socket subscription cap • prevents memory exhaustion attacks
    6. Per-socket subscription registry • server-side filter so a client only
       receives updates for markets it explicitly subscribed to
    7. Async dead-socket cleanup • doesn't block active broadcasts
    """

    # These caps are PER PROCESS, not global • with N API nodes the real limit
    # is N × the number below. That is deliberate, not an oversight: each node
    # caps the sockets and memory it is actually holding, which is what
    # protects it, and it costs nothing on the connect path. A global cap
    # would need a Redis round-trip per connect *and* per disconnect, and a
    # counter that leaks when a node dies would take the user's quota with it
    # • trading a small precision gain for a new way to lock people out.
    #
    # What *is* per-process-only and worth knowing: message fan-out. It is NOT
    # affected by this, because publishers write to Redis pub/sub and every node
    # runs its own `RedisPubSub.listen()` loop that fans messages out to its own
    # local sockets. Cross-node delivery is proven end-to-end in
    # `tests/test_websocket_multinode.py`.
    MAX_CONNECTIONS_PER_IP = 50  # raised from 10 • NAT users share IPs
    MAX_CONNECTIONS_PER_USER = 5
    MAX_SUBSCRIPTIONS_PER_SOCKET = 50  # cap per connection to prevent abuse
    # Slow-client protection: a socket that can't accept a frame within this
    # budget is wedged (full TCP buffer, client not reading). Without a timeout
    # one wedged socket stalls the gather() for EVERY subscriber on that market.
    SEND_TIMEOUT_S = 2.0
    # Bound concurrent sends so a 50k-subscriber tick doesn't materialize 50k
    # tasks at once • memory spike per price update.
    SEND_CONCURRENCY = 1000
    # How often buffered grid prices are flushed into one combined frame.
    # 250ms is four updates a second: past the rate anyone can read a changing
    # percentage, and coarse enough that a list of trading markets costs a
    # handful of frames a second rather than a few hundred.
    GRID_FLUSH_INTERVAL_S = 0.25
    # Floor for the adaptive cadence. Below this the loop is spinning rather than
    # adapting, and a tight spin starves the very listener that fills the buffer.
    # Hitting this floor means the honest answer is another worker, not a faster
    # loop.
    GRID_FLUSH_MIN_INTERVAL_S = 0.02
    # How far the cadence climbs back per cheap flush.
    GRID_FLUSH_INTERVAL_STEP_S = 0.05
    # Fraction of the interval a flush may consume before the next one shortens.
    # Below this the gateway is keeping up; above it, prices are ageing in the
    # queue and the tick is the thing making them stale.
    GRID_FLUSH_SATURATION_RATIO = 0.6
    # Ceiling on markets one socket may display. Bounds the buffer a single
    # misbehaving client can make this worker hold.
    MAX_GRID_MARKETS_PER_SOCKET = 200
    # How long a socket may go without proving it is still there.
    #
    # The old heartbeat asked "did my write succeed?" and that cannot detect the
    # case it exists for. A TCP peer that has gone - laptop lid closed, NAT
    # timeout, container killed - usually leaves no RST, so the kernel keeps
    # accepting our bytes into a send buffer that nothing drains, and `send_json`
    # succeeds for minutes. Meanwhile the client was never asked to prove
    # anything: it receives `{"type":"ping"}`, and the browser hook drops any
    # frame without a `market_id`, so it never replies and the server never
    # learns. Those sockets then held their file descriptor, their per-IP slot
    # and their `MAX_CONNECTIONS_PER_USER` quota indefinitely - a user who lost
    # connectivity a few times was locked out of realtime permanently, with no
    # path back, because those counters only ever decremented on a clean close.
    #
    # So the probe is now a real round-trip: ping carries a deadline, the client
    # must answer, and `last_seen` - refreshed by the pong *or* by any inbound
    # frame - is what decides. Comfortably above the 30s sweep interval so one
    # lost sweep is never fatal, and low enough that a genuinely dead socket is
    # reclaimed within one or two ticks.
    PONG_TIMEOUT_S = 75.0

    def __init__(self):
        self._market_subs: dict[str, set[WebSocket]] = defaultdict(set)
        # Per-socket subscription registry: which markets each WS is subscribed to
        self._ws_subscriptions: dict[WebSocket, set[str]] = defaultdict(set)
        # Per-socket lock: serialises subscribe/unsubscribe/disconnect for same WS
        self._ws_locks: dict[WebSocket, asyncio.Lock] = {}
        # Last proof-of-life per socket (monotonic clock, never wall clock).
        self._ws_last_seen: dict[WebSocket, float] = {}
        # Highest `seq` this node has fanned out per market. Free to maintain -
        # every frame passes through `broadcast_to_market` on its way to a socket -
        # and it is what lets the heartbeat tell a client its *true* position
        # rather than leaving it to guess from its own arrival pattern.
        self._last_seq: dict[str, int] = {}
        # ── Grid subscriptions ────────────────────────────────────────────────
        #
        # A market *grid* - a list, search results, the home page - is the case
        # per-market subscriptions get wrong, and getting it wrong is the
        # difference between a page that scales and one that doesn't.
        #
        # Subscribing one socket to N markets looks fine and is not. It costs N
        # subscription slots against a hard per-connection cap, and it delivers
        # one frame per market per tick - so thirty visible markets means up to
        # thirty frames a second into the browser and thirty re-renders. That is
        # how a realtime page ends up feeling slower than a static one, and the
        # client cannot fix it: the frames are already on the wire.
        #
        # The production answer is server-side aggregation. The client states
        # which instruments it is displaying; the server keeps the latest value
        # per instrument per socket and flushes ONE frame per socket per tick
        # carrying all of them. Cost becomes O(1) in frames and O(1) in
        # subscriptions, whatever the catalogue looks like.
        #
        # Deliberately not a single global "every market on the platform"
        # firehose. That is one subscription, but it delivers thousands of
        # updates to a client displaying thirty - strictly worse than delivering
        # thirty. Real market-data systems filter per subscriber, and so does
        # this.
        #
        # Per-market subscriptions stay, for the detail page, where a client
        # wants every frame type for exactly one market.
        #
        # Socket -> markets it is displaying in a grid.
        self._grid_subs: dict[WebSocket, set[str]] = {}
        # Socket -> the grid channels it is holding a refcount on.
        #
        # Tracked separately because refcounts are global while interest is per
        # socket: releasing has to undo exactly what this socket took, or a
        # market two users are watching gets unsubscribed when one of them
        # navigates away. `set_grid`/`release_grid` are the only writers.
        self._grid_channels: dict[WebSocket, set[str]] = {}
        # Market -> sockets displaying it. The reverse index makes a price
        # update cost O(subscribers of that market) rather than O(all sockets).
        self._grid_subscribers: dict[str, set[WebSocket]] = defaultdict(set)
        # Socket -> latest un-flushed price per market. Written on every frame,
        # drained once per tick. This is what collapses N frames into one.
        self._grid_pending: dict[WebSocket, dict[str, dict]] = {}
        self._ip_connections: dict[str, int] = defaultdict(int)
        self._user_connections: dict[str, int] = defaultdict(int)
        self._ws_ip: dict[WebSocket, str | None] = {}
        self._ws_user: dict[WebSocket, str | None] = {}
        # Track pending cleanup tasks so they can be awaited on shutdown
        self._pending_cleanups: set[asyncio.Task[None]] = set()
        # Whether the last flush outran its own tick. Exposed so ops can see
        # backpressure and so tests can assert the controller is responding.
        self._grid_backpressure = False
        self._grid_flush_stats = GridFlushStats()

    def touch(self, websocket: WebSocket) -> None:
        """Record inbound traffic as proof the socket is alive.

        Called from the route read loop for every frame, pong or not. A client
        that is only receiving will never send anything else, so the server's
        ping is the only thing that can produce a pong - but a chatty client
        shouldn't have to answer pings on top of already proving liveness.
        """
        self._ws_last_seen[websocket] = time.monotonic()

    async def connect(
        self,
        websocket: WebSocket,
        market_id: str,
        client_ip: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        """Accept a WS connection and subscribe to initial market. Returns False if rejected."""
        if client_ip and self._ip_connections.get(client_ip, 0) >= self.MAX_CONNECTIONS_PER_IP:
            logger.warning(f"WS rejected: too many connections from IP {client_ip}")
            WS_CONNECTS_TOTAL.labels("rejected_ip").inc()
            return False
        if user_id and self._user_connections.get(user_id, 0) >= self.MAX_CONNECTIONS_PER_USER:
            logger.warning(f"WS rejected: too many connections for user {user_id}")
            WS_CONNECTS_TOTAL.labels("rejected_user").inc()
            return False

        await websocket.accept()

        # Add to market subscriber set
        lock = await _market_locks._get_lock(market_id)
        async with lock:
            self._market_subs[market_id].add(websocket)

        # Register subscription under per-socket lock
        ws_lock = self._lock_for(websocket)
        async with ws_lock:
            self._ws_subscriptions[websocket].add(market_id)

        if client_ip:
            self._ip_connections[client_ip] += 1
        if user_id:
            self._user_connections[user_id] += 1
        # Store these so disconnect() can decrement them
        self._ws_ip[websocket] = client_ip
        self._ws_user[websocket] = user_id
        self._ws_last_seen[websocket] = time.monotonic()

        WS_CONNECTS_TOTAL.labels("accepted").inc()
        WS_CONNECTIONS.inc()
        WS_SUBSCRIPTIONS.inc()
        logger.info(f"WS connected: market={market_id} ip={client_ip} user={user_id}")
        return True

    def _lock_for(self, websocket: WebSocket) -> asyncio.Lock:
        """Per-socket lock, created on demand.

        Plain dict, not a `defaultdict`: a defaultdict silently manufactures a
        lock for any socket that asks, including one that was never registered or
        has already been reaped, and those locks were never popped - so the map
        grew by one entry per socket that ever reached a subscribe call.
        """
        lock = self._ws_locks.get(websocket)
        if lock is None:
            lock = asyncio.Lock()
            self._ws_locks[websocket] = lock
        return lock

    async def subscribe_to_market(
        self, websocket: WebSocket, market_id: str, redis_pubsub_ref=None
    ):
        """
        Add a market subscription without removing existing ones.
        Idempotent • calling twice is safe.
        Returns True if subscribed, False if rejected (cap reached or already subscribed).
        """
        ws_lock = self._lock_for(websocket)

        async with ws_lock:
            subs = self._ws_subscriptions.get(websocket)
            if subs is None:
                # Socket was never registered (or already reaped). Creating the
                # row here would re-admit a dead socket to the broadcast set.
                return False
            if market_id in subs:
                return True  # already subscribed, idempotent

            if len(subs) >= self.MAX_SUBSCRIPTIONS_PER_SOCKET:
                logger.warning(
                    f"WS subscription rejected: cap reached on socket {id(websocket)}"
                )
                return False

            subs.add(market_id)
            WS_SUBSCRIPTIONS.inc()

        # Update market subscriber set (outside ws_lock to avoid deadlocking two socket locks)
        lock = await _market_locks._get_lock(market_id)
        async with lock:
            self._market_subs[market_id].add(websocket)

        # Subscribe to Redis channel for this market.
        #
        # Awaited, not `asyncio.create_task` + fire-and-forget. The unawaited
        # task had two failure modes and no way to report either: an exception
        # vanished into a task nobody held a reference to, and the socket was
        # already in `_market_subs[market_id]` when the SUBSCRIBE was still in
        # flight, so every frame published in that window was dropped on the
        # floor. Since Redis is already reachable from this worker (we are
        # serving a socket), the extra await is a local round-trip.
        if redis_pubsub_ref:
            await redis_pubsub_ref.subscribe_market(market_id)

        logger.debug(f"WS subscribed to market: {market_id}")
        return True

    async def unsubscribe_from_market(
        self, websocket: WebSocket, market_id: str, redis_pubsub_ref=None
    ):
        """Remove a market subscription. Keeps other subscriptions intact. Idempotent."""
        ws_lock = self._lock_for(websocket)

        async with ws_lock:
            subs = self._ws_subscriptions.get(websocket)
            if not subs or market_id not in subs:
                return  # already unsubscribed, idempotent
            subs.discard(market_id)
            WS_SUBSCRIPTIONS.dec()

        # Update market subscriber set (outside ws_lock)
        lock = await _market_locks._get_lock(market_id)
        async with lock:
            self._market_subs[market_id].discard(websocket)
            if not self._market_subs[market_id]:
                del self._market_subs[market_id]
                await _market_locks.release_if_idle(market_id)

        # Unsubscribe from this market's Redis channel.
        #
        # One release per socket that is leaving, matched by the one acquire in
        # `subscribe_to_market`. RedisPubSub reference-counts, so this only
        # actually drops the channel when the last local subscriber goes - which
        # is what stops one tab closing from blinding every other socket on this
        # worker that is watching the same market.
        if redis_pubsub_ref:
            await redis_pubsub_ref.unsubscribe_market(market_id)

        logger.debug(f"WS unsubscribed from market: {market_id}")

    async def disconnect(self, websocket: WebSocket, redis_pubsub_ref=None, cause: str = "client"):
        """Remove a WS connection and clean up all its subscriptions.

        `cause` only labels the metric • cleanup is identical either way, and
        running the same path from every exit point is what keeps the
        connection counters and gauges honest.
        """
        # Capture registration BEFORE popping: a socket can reach here that was
        # never counted (rejected before `accept()`, or already reaped), and
        # decrementing a gauge for it would drive the metric negative • worse
        # than having no metric at all.
        was_registered = websocket in self._ws_subscriptions or websocket in self._ws_ip
        n_subs = len(self._ws_subscriptions.get(websocket, ()))

        ws_lock = self._ws_locks.pop(websocket, None)
        self._ws_last_seen.pop(websocket, None)
        # Grid state too. Without this the reverse index keeps a dead socket in
        # every market set it was displaying, and each of those markets copies a
        # price into a buffer for a socket that will never read it.
        self.clear_grid(websocket)

        if ws_lock:
            async with ws_lock:
                market_ids = list(self._ws_subscriptions.pop(websocket, set()))
        else:
            market_ids = list(self._ws_subscriptions.pop(websocket, set()))

        # Decrement connection counters so new connections aren't incorrectly
        # rejected, and *delete* the entry at zero rather than leaving it there.
        # Zeroed-but-retained keys meant two things, both bad:
        #   - the dict grew by one entry per distinct client IP the node ever
        #     saw, for the life of the process • an unbounded leak;
        #   - a socket that died without a clean disconnect (killed worker,
        #     dropped TCP, abrupt close) left its count permanently elevated,
        #     so that user slowly locked themselves out of websockets at 5 with
        #     no way back.
        client_ip = self._ws_ip.pop(websocket, None)
        user_id = self._ws_user.pop(websocket, None)
        if client_ip:
            remaining = self._ip_connections.get(client_ip, 1) - 1
            if remaining > 0:
                self._ip_connections[client_ip] = remaining
            else:
                self._ip_connections.pop(client_ip, None)
        if user_id:
            remaining = self._user_connections.get(user_id, 1) - 1
            if remaining > 0:
                self._user_connections[user_id] = remaining
            else:
                self._user_connections.pop(user_id, None)

        # Clean up each market's subscriber set
        for market_id in market_ids:
            lock = await _market_locks._get_lock(market_id)
            async with lock:
                self._market_subs[market_id].discard(websocket)
                if not self._market_subs[market_id]:
                    del self._market_subs[market_id]
                    await _market_locks.release_if_idle(market_id)

        # Gauges are decremented only for sockets this worker actually counted.
        # A socket can reach here that never was • rejected before `accept()`,
        # or already reaped by the heartbeat • and decrementing for it would
        # drive the metric negative, which is worse than having no metric.
        if was_registered:
            WS_CONNECTIONS.dec()
            WS_SUBSCRIPTIONS.dec(n_subs)
            WS_DISCONNECTS_TOTAL.labels(cause).inc()

        # Release this node's Redis interest in each market, once per socket that held
        # it. Reference-counted on the far side, so a market still watched by
        # another socket on this worker keeps flowing.
        #
        # `__global_trades__` and the notification registry are NOT handled here:
        # they are subscribed by their own routes, not by market id, and their
        # endpoints release them explicitly on disconnect.
        if redis_pubsub_ref:
            for market_id in market_ids:
                if market_id.startswith("__"):
                    continue
                try:
                    await redis_pubsub_ref.unsubscribe_market(market_id)
                except Exception:
                    logger.warning(
                        "WS redis unsubscribe failed market=%s", market_id, exc_info=True
                    )
            # The grid's channels too. `clear_grid` above dropped the local
            # index, but the Redis refcounts this socket was holding for those
            # markets have to come back as well - otherwise every market ever
            # shown in a grid stays SUBSCRIBEd on this node for the life of the
            # process, and this node keeps receiving and discarding frames for
            # markets nobody is watching.
            try:
                await self.release_grid(websocket, redis_pubsub_ref)
            except Exception:
                logger.warning("WS grid unsubscribe failed", exc_info=True)

        # Drop the sequence high-water mark with the last subscriber, so it does
        # not outlive the market's presence on this node.
        for market_id in market_ids:
            if market_id.startswith("__"):
                continue
            if not self._market_subs.get(market_id):
                self._last_seq.pop(market_id, None)

        logger.debug(f"WS disconnected: {len(market_ids)} subscriptions cleaned up")

    def seq_snapshot(self, websocket: WebSocket) -> dict[str, int]:
        """This socket's markets and the highest seq fanned out for each.

        The basis of exact gap detection. A client can only notice missing frames
        when a *later* frame arrives, so on a market that trades once and then
        goes quiet, frames lost in between are invisible forever - the tab shows
        stale state and reports itself connected. This hands the client the
        server's position instead of asking it to infer one.

        Only markets this node has actually fanned out appear, so a socket that
        just subscribed is told nothing rather than something misleading.
        """
        subs = self._ws_subscriptions.get(websocket) or ()
        return {
            m: self._last_seq[m]
            for m in subs
            if not m.startswith("__") and m in self._last_seq
        }

    async def subscribe_grid(self, websocket: WebSocket, market_ids: list[str]) -> set[str]:
        """Declare which markets a socket is displaying, replacing any previous set.

        Returns the ids actually accepted, so a client that asked for more than
        the cap can fall back rather than silently believing it is live for all
        of them.

        Local bookkeeping only. This does not touch Redis, so it is NOT sufficient
        on its own - see `set_grid`.
        """
        accepted = {m for m in market_ids if isinstance(m, str) and m}
        if len(accepted) > self.MAX_GRID_MARKETS_PER_SOCKET:
            accepted = set(sorted(accepted)[: self.MAX_GRID_MARKETS_PER_SOCKET])
            logger.warning(
                "WS grid capped at %d markets for socket %s",
                self.MAX_GRID_MARKETS_PER_SOCKET, id(websocket),
            )

        self.clear_grid(websocket)
        if not accepted:
            return accepted

        self._grid_subs[websocket] = accepted
        for market_id in accepted:
            self._grid_subscribers[market_id].add(websocket)
        return accepted

    async def set_grid(
        self, websocket: WebSocket, market_ids: list[str], pubsub: "RedisPubSub"
    ) -> set[str]:
        """Declare a socket's visible markets and subscribe to them.

        `subscribe_grid` on its own is not enough, and that gap was invisible for
        a long time because both halves are individually plausible.

        It updates the *local* reverse index - which market fans out to which
        socket - but publishing to `market:{id}:events` only reaches a socket if
        this node holds a Redis SUBSCRIBE on that channel. The per-market path
        acquires one in `connect()`. The grid path acquired none, so a socket that
        had declared a grid was indexed for delivery and yet subscribed to
        nothing: every price went to Redis and none of it came back.

        Only pages that *also* opened a market detail socket worked, because that
        socket had acquired the channels for its own one market - and even then
        only for that market. So `/markets` and the home grid were permanently
        static, in every environment, with no error anywhere: no failed request,
        no dropped frame, just prices that never moved.

        Nothing caught it because the tests sat on either side of the break. The
        grid tests called `broadcast_to_market` directly, bypassing Redis
        entirely; the socket tests used a fake transport that never needed a
        channel. Only a harness that drives the whole path - publish, Redis,
        listener, fan-out, buffer, flush - can see that the two halves were never
        connected.

        The delta matters as much as the acquire. Re-declaring on scroll must not
        re-subscribe to markets the socket already wanted, and must release the
        ones it no longer does, or a long browsing session leaks channels and
        pins this node to markets nobody is watching.
        """
        previous = set(self._grid_subs.get(websocket, set()))
        accepted = await self.subscribe_grid(websocket, market_ids)

        stale = previous - accepted
        fresh = accepted - previous
        if stale:
            await pubsub.unsubscribe_markets(stale)
        if fresh:
            await pubsub.subscribe_markets(fresh)

        self._grid_channels[websocket] = set(accepted)
        return accepted

    async def release_grid(self, websocket: WebSocket, pubsub: "RedisPubSub") -> None:
        """Drop a socket's grid and give back the channels it was holding."""
        held = self._grid_channels.pop(websocket, set())
        self.clear_grid(websocket)
        if held:
            await pubsub.unsubscribe_markets(held)

    def clear_grid(self, websocket: WebSocket) -> None:
        """Drop a socket's grid set and its buffered prices.

        The reverse index has to be reversed too. A grid that pages through the
        catalogue would otherwise leave an entry behind for every market it ever
        showed, and every price update on those markets would keep copying a
        frame into a buffer nobody will ever send.
        """
        previous = self._grid_subs.pop(websocket, None)
        self._grid_pending.pop(websocket, None)
        if not previous:
            return
        for market_id in previous:
            subs = self._grid_subscribers.get(market_id)
            if subs is None:
                continue
            subs.discard(websocket)
            if not subs:
                del self._grid_subscribers[market_id]

    async def _buffer_grid_event(self, market_id: str, event: dict) -> None:
        """Record the newest event for every grid showing this market.

        No I/O and no await on the hot path - that is what makes the aggregation
        affordable. A market ticking fifty times between flushes costs fifty dict
        writes and exactly one frame on the wire.

        Resolution is buffered here too, not just prices. A grid excludes markets
        that are already settled, so the moment one settles it is holding a
        subscription slot, painting a live-looking card, and showing prices that
        can never move again. Riding along on the batch it was already receiving
        costs one field, and the grid gets to drop the market on the next flush
        instead of waiting for a reload.
        """
        subs = self._grid_subscribers.get(market_id)
        if not subs:
            return
        kind = event.get("type")
        if kind == "market:resolved":
            payload = {
                "type": "market:resolved",
                "market_id": market_id,
                "status": event.get("status"),
                "winning_outcome_id": event.get("winning_outcome_id"),
                "winning_outcome_name": event.get("winning_outcome_name"),
            }
        else:
            payload = {
                "type": "market:price_update",
                "market_id": market_id,
                "yes_price": event.get("yes_price"),
                "no_price": event.get("no_price"),
                "volume": event.get("volume"),
            }
            outcome_prices = event.get("outcome_prices")
            if outcome_prices:
                payload["outcome_prices"] = outcome_prices
        seq = event.get("seq")
        if isinstance(seq, int):
            # Carried so a grid keeps the same gap detection the detail page has.
            # Without it a grid cannot tell a missed frame from a quiet market -
            # the exact failure the heartbeat beacon exists to close.
            payload["seq"] = seq
        for ws in subs:
            pending = self._grid_pending.setdefault(ws, {})
            # Resolution is terminal, so it must not be lost to a late price tick.
            #
            # The buffer holds one entry per market, so a `market:price_update`
            # landing after the resolution - a final trade settling into the book
            # in the same 250ms window - would overwrite the marker and the grid
            # would go on showing a live-looking market for a market that is
            # already settled. Which is exactly the bug this was added to fix, so
            # the terminal state wins.
            existing = pending.get(market_id)
            if existing is not None and existing.get("type") == "market:resolved":
                continue
            if existing is not None and "seq_from" not in payload and isinstance(
                existing.get("seq"), int
            ):
                # Carry the *first* sequence this flush window saw for this
                # market, so the grid can tell coalescing apart from loss.
                #
                # Coalescing is the whole point of the aggregation: a market that
                # ticks five times between flushes must produce ONE frame, which
                # means the intermediate `seq`s are deliberately absent. But the
                # grid's gap detector cannot tell a deliberately-collapsed update
                # from a dropped one, and a collapsed one looks exactly like
                # `seq 4 -> seq 9`. So every busy market was declaring itself
                # lossy every tick and firing a full REST resync - hundreds of
                # times a second, each one refetching the entire markets query.
                #
                # `seq_from` is the difference: contiguity is judged between the
                # last seq the grid actually received and the first seq this
                # window carries. Collapsed updates make it contiguous; genuine
                # transport loss makes it a gap.
                #
                # The *existing* `seq_from` is what gets carried forward, not the
                # existing `seq`. Using `seq` would re-anchor the window on every
                # tick and leave `seq_from` permanently one behind, so a window
                # spanning seqs 5..9 would report `seq_from = 8` and every
                # consumer would read a coalesced burst as a gap - the exact
                # failure this field exists to remove.
                prior_from = existing.get("seq_from")
                payload["seq_from"] = (
                    prior_from if isinstance(prior_from, int) else existing["seq"]
                )
            pending[market_id] = payload

    async def flush_grid(self) -> int:
        """Drain every grid buffer into one frame per socket. Returns sockets hit."""
        if not self._grid_pending:
            return 0

        pending = self._grid_pending
        self._grid_pending = {}
        dead: list[WebSocket] = []

        async def send(ws: WebSocket, prices: dict[str, dict]) -> None:
            try:
                await asyncio.wait_for(
                    ws.send_json({"type": "market:prices_batch", "prices": prices}),
                    timeout=self.SEND_TIMEOUT_S,
                )
                WS_SENDS_TOTAL.labels("ok").inc()
                WS_MESSAGES_FANNED_OUT.labels("market").inc(len(prices))
            except Exception:
                WS_SENDS_TOTAL.labels("failed").inc()
                dead.append(ws)

        await asyncio.gather(
            *(send(ws, prices) for ws, prices in pending.items()),
            return_exceptions=True,
        )
        if dead:
            await self._disconnect_many(dead)
        return len(pending)

    async def grid_loop(self, interval_s: float | None = None) -> None:
        """Flush grid buffers for the life of the process, adapting the cadence.

        One timer for the whole worker, not one per socket: per-socket timers make
        the scheduler cost proportional to connected clients, which is precisely
        the thing a realtime gateway must not have.

        The cadence adapts to how long the flush actually took. A fixed tick is
        right when idle - flushing a nearly-empty buffer more often buys nothing
        but scheduler wakeups - and wrong when saturated, because the flush then
        takes most of the interval and every price the client sees is that much
        older than it needs to be. Measured on this gateway, end to end, p50 was
        ~21ms idle but p95 reached ~213ms at 500 sockets x 100 markets: the tail
        was queueing behind a full tick, not anything slow in the send itself.

        So the interval tracks the work: a flush that consumed a large share of
        the time it was allowed shortens the next one, and a cheap flush lengthens
        it back toward the base. It is multiplicative decrease / additive
        increase because that reacts fast to saturation - the case where being
        slow is expensive - while recovering gradually, so a single busy moment
        does not leave every socket flushing at the floor forever.

        The floor exists because flushing faster than the event loop can actually
        complete a pass just burns CPU and starves the listener that feeds it. If
        the floor is not enough, the honest answer is more workers, not a tighter
        loop.
        """
        base = interval_s if interval_s is not None else self.GRID_FLUSH_INTERVAL_S
        floor = self.GRID_FLUSH_MIN_INTERVAL_S
        interval = base
        while True:
            try:
                await asyncio.sleep(interval)
                started = time.monotonic()
                sent = await self.flush_grid()
                elapsed = time.monotonic() - started

                interval = next_grid_interval(
                    interval,
                    sockets_sent=sent,
                    elapsed_s=elapsed,
                    base=base,
                    floor=floor,
                    step=self.GRID_FLUSH_INTERVAL_STEP_S,
                    saturation_ratio=self.GRID_FLUSH_SATURATION_RATIO,
                )
                self._grid_backpressure = (
                    sent > 0
                    and elapsed > interval / self.GRID_FLUSH_SATURATION_RATIO
                )
                self._grid_flush_stats.observe(sent, elapsed, interval)
            except asyncio.CancelledError:
                logger.info("WS grid flush loop cancelled")
                raise
            except Exception as e:  # never let the loop kill itself
                logger.error(f"WS grid flush failed: {e}")

    async def broadcast_to_market(self, market_id: str, event: dict):
        """
        Broadcast to sockets subscribed to this market.

        Slow-client safe: each send races a timeout under a bounded semaphore,
        so one wedged socket delays neither the tick nor other subscribers.
        Sockets that time out or fail are disconnected inline (async).
        """
        lock = await _market_locks._get_lock(market_id)
        async with lock:
            raw_sockets = list(self._market_subs.get(market_id, set()))

        # Record the high-water mark and buffer for grids, whether or not any
        # socket is watching this market individually.
        #
        # Both used to sit *after* the `if not sockets: return` guard, which
        # meant a market watched only by a grid - the entire case grids exist to
        # serve - updated nothing at all: no sequence mark, so no beacon, and no
        # buffered price, so no batch. The guard below now covers only the
        # per-market send path.
        seq = event.get("seq")
        if isinstance(seq, int) and seq > self._last_seq.get(market_id, 0):
            self._last_seq[market_id] = seq

        # Grid subscribers are NOT sent this frame individually. It goes into
        # their buffer and reaches them as one combined frame per tick. The
        # reverse index makes this cost O(grids showing this market) rather than
        # O(sockets), which is the whole point of the design.
        #
        # Both `market:price_update` and `market:resolved` ride this path: a grid
        # that is not told a market settled keeps its subscription slot and keeps
        # rendering it as tradeable, which is the one thing the grid exists to
        # stop being wrong about.
        if self._grid_subscribers.get(market_id) and event.get("type") in (
            "market:price_update",
            "market:resolved",
        ):
            await self._buffer_grid_event(market_id, event)

        # Filter: only send to connections that actually subscribed to this market
        def is_subscribed(ws: WebSocket) -> bool:
            subs = self._ws_subscriptions.get(ws)
            return subs is not None and market_id in subs

        sockets = [ws for ws in raw_sockets if is_subscribed(ws)]
        if not sockets:
            return

        WS_MESSAGES_FANNED_OUT.labels("market").inc(len(sockets))
        dead = await self._bounded_send(sockets, event)
        if dead:
            task = asyncio.create_task(self._disconnect_many(dead))
            self._pending_cleanups.add(task)
            task.add_done_callback(self._pending_cleanups.discard)

    async def _bounded_send(self, sockets: list[WebSocket], event: dict) -> list[WebSocket]:
        """Send to all sockets with per-send timeout + bounded concurrency.
        Returns the sockets that failed or timed out."""
        sem = asyncio.Semaphore(self.SEND_CONCURRENCY)
        dead: list[WebSocket] = []

        async def safe_send(ws: WebSocket):
            try:
                async with sem:
                    await asyncio.wait_for(ws.send_json(event), timeout=self.SEND_TIMEOUT_S)
                WS_SENDS_TOTAL.labels("ok").inc()
            except TimeoutError:
                # Distinguish a wedged client (full TCP buffer) from a dead one.
                # Both are reaped, but they mean different things operationally.
                WS_SENDS_TOTAL.labels("timeout").inc()
                dead.append(ws)
            except Exception:
                WS_SENDS_TOTAL.labels("failed").inc()
                dead.append(ws)

        await asyncio.gather(*(safe_send(ws) for ws in sockets), return_exceptions=True)
        return dead

    async def _disconnect_many(self, sockets: list[WebSocket], cause: str = "send_failed"):
        # `redis_pubsub` is passed through on purpose. A socket reaped by the
        # heartbeat is, by definition, one whose client vanished without a close
        # frame, so its read loop is gone and nothing else will ever run the
        # release half of `disconnect`. Omitting it here left the reference count
        # permanently elevated for that market, and the node kept receiving and
        # fanning out a channel no local socket wanted - forever.
        for ws in sockets:
            try:
                await self.disconnect(ws, redis_pubsub_ref=redis_pubsub, cause=cause)
            except Exception:
                pass

    async def _ping_many(self, sockets: list[WebSocket]) -> list[WebSocket]:
        """Ping sockets concurrently under a bounded semaphore; return the dead.

        Concurrent and bounded on purpose. The obvious sequential loop is a
        scalability bug: at `SEND_TIMEOUT_S = 2.0`, fifty wedged sockets take
        100s • three times the 30s sweep interval, so sweeps pile up. Fifty
        thousand healthy sockets would take minutes. `_bounded_send` already
        had this right for frames; the sweep now does the same for pings.

        The probe does double duty. It carries each socket's per-market sequence
        high-water mark, which is what lets a client detect frames it missed
        *without* waiting for a later frame to arrive - the one case pure
        client-side gap detection cannot cover, because a market that trades once
        and then goes quiet never produces the frame that would reveal the hole.
        """
        if not sockets:
            return []

        sem = asyncio.Semaphore(self.SEND_CONCURRENCY)
        dead: list[WebSocket] = []

        async def ping(ws: WebSocket) -> None:
            try:
                payload: dict = {"type": "ping", "ts": time.time()}
                snapshot = self.seq_snapshot(ws)
                if snapshot:
                    payload["seq"] = snapshot
                async with sem:
                    await asyncio.wait_for(ws.send_json(payload), timeout=self.SEND_TIMEOUT_S)
                WS_SENDS_TOTAL.labels("ok").inc()
            except TimeoutError:
                WS_SENDS_TOTAL.labels("timeout").inc()
                dead.append(ws)
            except Exception:
                WS_SENDS_TOTAL.labels("failed").inc()
                dead.append(ws)

        await asyncio.gather(*(ping(ws) for ws in sockets), return_exceptions=True)
        return dead

    def _stale(self, websocket: WebSocket, now: float) -> bool:
        """True when this socket has not proved liveness inside the window.

        The half-open case: our writes still succeed, so `_ping_many` cannot see
        it, but no `pong` (and no inbound frame of any kind) has come back for
        longer than a socket may reasonably be silent. Reaping here is what
        returns the file descriptor, the per-IP slot and the user's connection
        quota to the pool instead of leaking them for the life of the process.
        """
        last = self._ws_last_seen.get(websocket)
        if last is None:
            return True  # registered but never touched: treat as dead, not immortal
        return (now - last) > self.PONG_TIMEOUT_S

    async def _cleanup_dead(self, sockets: list[WebSocket]):
        """Probe sockets and disconnect the unresponsive ones.

        Driven by `heartbeat_loop`, not by broadcasts: a socket on a *quiet*
        market never receives a broadcast, so broadcast-failure detection alone
        never reaps it. This was dead code until the sweep was wired up.

        Two independent verdicts, because they catch different failures:
        a failed/timed-out ping catches a fully broken socket, and the pong
        deadline catches a half-open one whose writes still "succeed".
        """
        live = [ws for ws in sockets if ws in self._ws_subscriptions]
        now = time.monotonic()
        dead = [ws for ws in live if self._stale(ws, now)]

        # Ping only what has not already failed the deadline. Sending a probe at
        # a socket we are about to reap just burns a send slot on it.
        survivors = [ws for ws in live if ws not in set(dead)]
        dead.extend(await self._ping_many(survivors))

        if dead:
            # `_disconnect_many` labels the metric, so the cause stays accurate.
            await self._disconnect_many(dead, cause="heartbeat")
        return dead

    def all_sockets(self) -> list[WebSocket]:
        """Every *market* socket this worker currently holds (no locks • a
        concurrent unsubscribe may be missed for one pass; the next sweep
        catches it). Notification sockets are a separate registry and are swept
        by `heartbeat_once`, not here."""
        out: list[WebSocket] = []
        for socks in self._market_subs.values():
            out.extend(socks)
        return out

    async def heartbeat_once(self) -> int:
        """One ping sweep over every local socket, market *and* notification.

        Returns how many were reaped. Both registries have to be swept: the
        notification sockets live in `UserConnectionManager`, so a sweep that
        only walked `_market_subs` would leave every logged-in user's socket
        unreaped • precisely the long-lived ones most likely to be half-open.
        """
        reaped = 0
        market_dead = await self._cleanup_dead(self.all_sockets())
        reaped += len(market_dead)
        reaped += await user_manager.heartbeat_once()
        if reaped:
            logger.warning(f"WS heartbeat reaped {reaped} unresponsive socket(s)")
        return reaped

    async def heartbeat_loop(self, interval_s: float = 30.0) -> None:
        """Periodically probe every socket so a half-open one cannot leak.

        Why this has to exist: a TCP connection can die without a FIN reaching
        us (laptop lid closed, NAT timeout, killed container). The socket then
        looks open forever, keeps its file descriptor, its per-IP counter slot,
        and • worse • looks healthy to every future send, because `send_json`
        only fails once the kernel buffer finally overflows. Broadcast-failure
        detection catches that, but only for markets that actually trade.

        Cancelled on shutdown; `CancelledError` is not swallowed so the task
        ends cleanly.
        """
        while True:
            try:
                await asyncio.sleep(interval_s)
                await self.heartbeat_once()
            except asyncio.CancelledError:
                logger.info("WS heartbeat loop cancelled")
                raise
            except Exception as e:  # never let the sweep kill itself
                logger.error(f"WS heartbeat sweep failed: {e}")

    async def broadcast_global(self, event: dict):
        """Push a platform-wide frame to the sockets that asked for it.

        Scoped to `GLOBAL_TRADES_KEY` subscribers rather than "every socket this
        node holds". Fanning a global trade out to market sockets leaks other
        markets' trades into every open market page, and charges each of those
        sockets a send for a frame it will discard.

        Same lock/snapshot shape as `broadcast_to_market`: the registry is read
        under the market lock, then the sends happen outside it, so a slow
        subscriber can never stall the listener loop.
        """
        lock = await _market_locks._get_lock(GLOBAL_TRADES_KEY)
        async with lock:
            raw_sockets = list(self._market_subs.get(GLOBAL_TRADES_KEY, set()))

        # Mirror `broadcast_to_market`'s server-side filter: only deliver to a
        # socket that is genuinely still subscribed. A socket mid-teardown can
        # linger in the market set after its subscription row is gone.
        sockets = [
            ws
            for ws in raw_sockets
            if GLOBAL_TRADES_KEY in (self._ws_subscriptions.get(ws) or set())
        ]
        if not sockets:
            return

        WS_MESSAGES_FANNED_OUT.labels("global").inc(len(sockets))
        dead = await self._bounded_send(sockets, event)
        if dead:
            # Tracked for shutdown like every other broadcast path - these
            # sockets belong to the notification-style registry and are the ones
            # most likely to be long-idle.
            task = asyncio.create_task(self._disconnect_many(dead))
            self._pending_cleanups.add(task)
            task.add_done_callback(self._pending_cleanups.discard)

    def subscriber_count(self, market_id: str) -> int:
        return len(self._market_subs.get(market_id, set()))

    def total_connections(self) -> int:
        return len(self._ws_subscriptions)


manager = ConnectionManager()


# ── User Connection Manager ─────────────────────────────────────────────────────


class UserConnectionManager:
    """Per-user notification WS connections. Per-user locks, fire-and-forget sends."""

    SEND_TIMEOUT_S = 2.0
    # Bound concurrent heartbeat pings for the same reason as the market
    # manager's sweep: unbounded concurrency on a large fan-out would
    # materialise one task per socket per tick.
    SEND_CONCURRENCY = 1000
    # Same contract as the market manager: a socket must prove liveness inside
    # this window or be reaped. See `ConnectionManager.PONG_TIMEOUT_S` for why
    # "the write succeeded" is not proof.
    PONG_TIMEOUT_S = 75.0

    def __init__(self):
        self._user_socks: dict[str, set[WebSocket]] = defaultdict(set)
        self._ws_to_user: dict[WebSocket, str] = {}
        self._user_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._ws_last_seen: dict[WebSocket, float] = {}
        # Track pending cleanup tasks so they can be awaited on shutdown
        self._pending_cleanups: set[asyncio.Task[None]] = set()

    async def connect(self, websocket: WebSocket, user_id: str) -> bool:
        """Accept and register the socket. Returns whether it is really live.

        The return value is not decoration: it matches `ConnectionManager.connect`,
        and the route needs it because **Starlette's `accept()` fails silently**.
        It only sends when the socket is in CONNECTING state - if the handshake
        has already gone out, it is a no-op that raises nothing. So a socket that
        is not actually connected can be registered as though it were, with the
        connection gauge incremented and a Redis subscription taken out for a
        client that is already gone. Nothing logs, because nothing failed.

        That is the shape of the crash this was hardened against: the backend
        logged an unhandled `Expected ASGI message 'websocket.send' ...
        but got 'websocket.accept'` from inside this call, meaning uvicorn had
        already completed a handshake on that connection. Reproduced against
        ~1200 connect/disconnect lifecycles without a repeat, so the trigger is
        rare and not yet identified - but the silence here is not the reason it
        was invisible. A connect that reports whether it worked is debuggable;
        one that returns nothing and assumes success is not.
        """
        if websocket.client_state is not WebSocketState.CONNECTING:
            # Already accepted or closed. Say so rather than pretending.
            logger.warning(
                f"User WS connect for user={user_id} skipped: socket is "
                f"{websocket.client_state.value}, not CONNECTING"
            )
            return False

        await websocket.accept()
        async with self._user_locks[user_id]:
            self._user_socks[user_id].add(websocket)
            self._ws_to_user[websocket] = user_id
        self._ws_last_seen[websocket] = time.monotonic()
        # Counted here too, otherwise `ws_connections` silently excludes every
        # notification socket and the capacity gauge under-reports real load.
        WS_CONNECTIONS.inc()
        logger.info(f"User WS connected: user={user_id}")
        return True

    def touch(self, websocket: WebSocket) -> None:
        self._ws_last_seen[websocket] = time.monotonic()

    async def disconnect(self, websocket: WebSocket, user_id: str, cause: str = "client"):
        # Registered check first: this socket may already have been reaped.
        was_registered = websocket in self._ws_to_user
        async with self._user_locks[user_id]:
            self._user_socks[user_id].discard(websocket)
            self._ws_to_user.pop(websocket, None)
            self._ws_last_seen.pop(websocket, None)
            if not self._user_socks[user_id]:
                del self._user_socks[user_id]
        if was_registered:
            WS_CONNECTIONS.dec()
            WS_DISCONNECTS_TOTAL.labels(cause).inc()
        logger.debug(f"User WS disconnected: user={user_id}")

    async def broadcast_to_user(self, user_id: str, event: dict):
        async with self._user_locks[user_id]:
            sockets = list(self._user_socks.get(user_id, set()))

        if not sockets:
            return

        # Unbounded `asyncio.gather` over a fan-out is the same hazard the
        # market manager avoids with `_bounded_send`: one task per socket per
        # tick. These sockets are per-user so the fan-out is naturally small,
        # but the bound costs nothing and keeps the two paths symmetrical.
        sem = asyncio.Semaphore(self.SEND_CONCURRENCY)
        dead: list[WebSocket] = []

        async def safe_send(ws: WebSocket):
            try:
                async with sem:
                    await asyncio.wait_for(ws.send_json(event), timeout=self.SEND_TIMEOUT_S)
                WS_SENDS_TOTAL.labels("ok").inc()
            except TimeoutError:
                WS_SENDS_TOTAL.labels("timeout").inc()
                dead.append(ws)
            except Exception:
                WS_SENDS_TOTAL.labels("failed").inc()
                dead.append(ws)

        WS_MESSAGES_FANNED_OUT.labels("user").inc(len(sockets))
        await asyncio.gather(*(safe_send(ws) for ws in sockets), return_exceptions=True)
        for ws in dead:
            try:
                await self.disconnect(ws, user_id, cause="send_failed")
            except Exception:
                pass

    def all_sockets(self) -> list[WebSocket]:
        """Every notification socket this worker holds."""
        return list(self._ws_to_user.keys())

    async def _ping_many(self, sockets: list[WebSocket]) -> list[WebSocket]:
        """Bounded-concurrency ping sweep • see ConnectionManager._ping_many.

        Sequential here would be just as wrong as it was there: these are the
        long-lived per-user sockets, so a page left open overnight is exactly
        the half-open case, and N wedged sockets would serialise to N × 2s.
        """
        if not sockets:
            return []
        sem = asyncio.Semaphore(self.SEND_CONCURRENCY)
        dead: list[WebSocket] = []

        async def ping(ws: WebSocket) -> None:
            try:
                async with sem:
                    await asyncio.wait_for(
                        ws.send_json({"type": "ping", "ts": time.time()}),
                        timeout=self.SEND_TIMEOUT_S,
                    )
                WS_SENDS_TOTAL.labels("ok").inc()
            except TimeoutError:
                WS_SENDS_TOTAL.labels("timeout").inc()
                dead.append(ws)
            except Exception:
                WS_SENDS_TOTAL.labels("failed").inc()
                dead.append(ws)

        await asyncio.gather(*(ping(ws) for ws in sockets), return_exceptions=True)
        return dead

    async def heartbeat_once(self) -> int:
        """Reap unresponsive notification sockets.

        Called from the single heartbeat loop so there is exactly one timer, not
        one per manager. Same two verdicts as the market manager: a failed ping,
        or silence past the pong deadline (which is what actually catches a
        half-open socket whose writes still succeed).
        """
        live = [ws for ws in self.all_sockets() if ws in self._ws_to_user]
        now = time.monotonic()
        dead = [
            ws
            for ws in live
            if (self._ws_last_seen.get(ws) is None)
            or (now - self._ws_last_seen[ws]) > self.PONG_TIMEOUT_S
        ]
        survivors = [ws for ws in live if ws not in set(dead)]
        dead.extend(await self._ping_many(survivors))
        for ws in dead:
            # Read the owner *before* disconnecting. `disconnect` pops
            # `_ws_to_user[ws]`, so looking it up afterwards returns the default
            # and releases `user::fills`/`user::notifications` - channels that
            # were never acquired - instead of the real owner's. The count for
            # the actual user then stayed elevated forever and their channels
            # were never unsubscribed, which is precisely the leak the release
            # exists to prevent. Reaped sockets are the ones nobody notices, so
            # it would have failed invisibly and permanently.
            user_id = self._ws_to_user.get(ws)
            if user_id is None:
                continue
            try:
                await self.disconnect(ws, user_id, cause="heartbeat")
                # The read loop that would normally release this user's channels
                # is gone with the socket, so the release happens here instead.
                await redis_pubsub.unsubscribe_user(user_id)
            except Exception:
                logger.warning(
                    "reaping notification socket failed user=%s", user_id, exc_info=True
                )
        return len(dead)

    async def _cleanup_dead_user(self, user_id: str, sockets: list[WebSocket]):
        await self._ping_many([ws for ws in sockets if ws in self._ws_to_user])


user_manager = UserConnectionManager()


# ── Redis Pub/Sub ─────────────────────────────────────────────────────────────


class RedisPubSub:
    def __init__(self):
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._listener_task: asyncio.Task | None = None
        self._connected = False
        # Channel -> how many LOCAL sockets want it.
        #
        # This replaces a plain `set`, which was the single worst bug in the
        # realtime path. A set records only *whether* this worker listens to a
        # channel, so the first socket to leave released the channel for
        # everyone: two sockets on the same worker subscribed to market X, one
        # disconnected, `unsubscribe_market(X)` dropped `market:X:*` process-wide,
        # and the survivor sat in `_market_subs[X]` - still "connected", still
        # counted, still subscribed - receiving nothing for the rest of its
        # life. The frontend makes the collision routine rather than exotic:
        # `trending-carousel-item` and `market-detail` share one tab-wide socket,
        # so navigating off a detail page silently killed that market's live
        # price for the carousel item still on screen.
        #
        # A reference count makes release idempotent per subscriber, so only the
        # last one out actually unsubscribes from Redis.
        self._refs: dict[str, int] = {}

        # Bounded publish queues drained by a fixed writer pool.
        #
        # Every `publish_*` below routes through this rather than talking to Redis
        # directly. `max_connections` is a hard cliff - past it redis-py raises
        # `MaxConnectionsError` instead of waiting - and every publisher used to
        # catch that and log a warning, so a burst meant trades committed to
        # Postgres that clients were never told about, followed by every client
        # detecting the gap and refetching at once. See `publish_queue` for the
        # full reasoning and the two delivery classes.
        self._dispatcher = PublishDispatcher(
            send=self._dispatch,
            writers=settings.publish_writers,
            ephemeral_max=settings.publish_queue_ephemeral,
            critical_max=settings.publish_queue_critical,
            resync=self._send_owed_resync,
        )
        # What the live pubsub client is *actually* subscribed to. Distinct from
        # `_refs` (what we want) so a reconnect can replay intent without
        # guessing, and so a subscribe that arrives while the client is down is
        # still remembered.
        self._subscribed: set[str] = set()
        # Serialises `_sync_channels`: many sockets connect concurrently on a
        # cold node and would otherwise each diff against a stale snapshot.
        self._sync_lock = asyncio.Lock()
        # Loop exit condition for `listen()`. Without it the task has to be killed
        # by cancellation alone, and a restart would be indistinguishable from a
        # completed run.
        self._closed = False

    async def connect(self):
        # Not merely "already connected": the writers may have died with their
        # event loop, and a dispatcher with no live writers accepts frames that
        # nobody ever sends. `start()` is cheap and idempotent, so always run it.
        if self._connected and self._pubsub is not None:
            await self._dispatcher.start()
            return
        self._redis = await get_redis()
        self._pubsub = self._redis.pubsub()
        self._connected = True
        self._closed = False
        # Writers start with the connection: a publisher that can enqueue into a
        # queue nobody is draining would convert a Redis cliff into an unbounded
        # memory leak, which is a worse failure with a longer fuse.
        await self._dispatcher.start()

    # ── Subscription registry ────────────────────────────────────────────────

    def _wanted(self) -> set[str]:
        return {ch for ch, n in self._refs.items() if n > 0}

    async def _sync_channels(self) -> None:
        """Reconcile the live pubsub client with what local sockets want.

        Deliberately separate from `_refs`. `_refs` is the intent and survives a
        dropped connection; `_subscribed` is only what the live client holds.
        The old code recorded intent *only* on a successful subscribe, so a
        `subscribe_market` that landed while `_pubsub` was None (a Redis blip
        mid-reconnect) returned silently and was never recorded anywhere - the
        socket joined `_market_subs` and was then never delivered a single frame
        again, because the replay on reconnect had no idea it existed. Recording
        intent first makes that window unrepresentable.
        """
        async with self._sync_lock:
            if self._pubsub is None:
                return  # `_refs` holds the intent; `_reconnect` will replay it
            want = self._wanted()
            for ch in want - self._subscribed:
                try:
                    await self._pubsub.subscribe(ch)
                except Exception:
                    logger.warning("Redis subscribe failed for %s", ch, exc_info=True)
                    continue
                self._subscribed.add(ch)
            for ch in self._subscribed - want:
                try:
                    await self._pubsub.unsubscribe(ch)
                except Exception:
                    logger.warning("Redis unsubscribe failed for %s", ch, exc_info=True)
                    continue
                self._subscribed.discard(ch)

    async def _acquire(self, *channels: str) -> None:
        for ch in channels:
            self._refs[ch] = self._refs.get(ch, 0) + 1
        await self._sync_channels()

    async def _release(self, *channels: str) -> None:
        for ch in channels:
            remaining = self._refs.get(ch, 0) - 1
            if remaining > 0:
                self._refs[ch] = remaining
            else:
                self._refs.pop(ch, None)
        await self._sync_channels()

    async def subscribe_market(self, market_id: str):
        await self._acquire(market_events_channel(market_id))

    async def subscribe_markets(self, market_ids) -> None:
        """Acquire many markets' channels in one reconcile.

        A grid declares its whole visible set at once, so the singular
        `subscribe_market` in a loop is the wrong shape: each `_acquire` runs a
        full `_sync_channels`, which walks every channel this node holds. Two
        hundred markets would mean two hundred passes over the entire set to add
        two hundred channels - quadratic in the one operation most likely to be
        large. Batching makes it one pass, and the delta means re-declaring a
        scrolled grid costs only the markets that actually changed.
        """
        channels = [market_events_channel(m) for m in market_ids]
        if channels:
            await self._acquire(*channels)

    async def unsubscribe_markets(self, market_ids) -> None:
        """Release many markets' channels in one reconcile (see `subscribe_markets`)."""
        channels = [market_events_channel(m) for m in market_ids]
        if channels:
            await self._release(*channels)

    async def unsubscribe_market(self, market_id: str):
        """Release this node's interest in a market.

        Called once per *socket* that leaves the market, not once per channel.
        The count reaching zero - not this call happening - is what unsubscribes
        from Redis.
        """
        await self._release(market_events_channel(market_id))

    async def subscribe_user(self, user_id: str):
        await self._acquire(
            f"user:{user_id}:fills",
            f"user:{user_id}:notifications",
        )

    async def unsubscribe_user(self, user_id: str):
        """Release this node's interest in a user's private channels.

        This did not exist. Every notification socket connection added two
        channels to `_subscribed` and nothing ever removed them, so a worker
        accumulated `2 x (logins on this node)` channels for the life of the
        process - one Redis subscription each, all of them polled by `listen()`
        on every tick whether or not the user was still connected.
        """
        await self._release(
            f"user:{user_id}:fills",
            f"user:{user_id}:notifications",
        )

    async def subscribe_global_trades(self):
        await self._acquire(GLOBAL_TRADES_CHANNEL)

    async def unsubscribe_global_trades(self):
        await self._release(GLOBAL_TRADES_CHANNEL)

    # ── Publish queue ───────────────────────────────────────────────────────

    async def _dispatch(self, pending) -> None:
        """Execute one queued frame against Redis, through the breaker.

        The circuit breaker and the `WS_PUBLISH_FAILURES` counter live here rather
        than at the call sites so that queueing a frame and failing to write it
        are distinguishable: the queue depth says work is waiting, the failure
        counter says the write did not happen, and neither implies the other.
        """
        try:
            await redis_cb.call(pending.op)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            WS_PUBLISH_FAILURES.labels(pending.label or pending.frame).inc()
            logger.warning(
                "queued publish failed frame=%s: %s", pending.frame, e,
            )

    async def _send_owed_resync(self, user_id: str) -> None:
        """Tell a client its private feed has a hole it should repair.

        Sent on the same private channel the lost frame would have used, so a
        client that is connected receives it. A client that is not connected is
        not owed anything: on reconnect it refetches state anyway, and every
        frame dropped for it is already durable in Postgres.
        """
        async def _op():
            await self._redis.publish(
                f"user:{user_id}:notifications",
                json.dumps({"type": WS_RESYNC}),
            )

        await self._dispatch(
            Pending(op=_op, delivery=Delivery.CRITICAL, frame="resync_marker")
        )

    def enqueue_publish(
        self,
        op,
        *,
        frame: str,
        label: str | None = None,
        owe_resync_to: str | None = None,
    ) -> bool:
        """Offer a frame to the queue. See `app/websocket/publish_queue.py`.

        `frame` and `label` are deliberately separate. `frame` is the event type
        and decides the *delivery class* - `orderbook:update` must not vanish, so
        it has to be identified by what it is, not by which method sent it.
        `label` is the metric series and stays the call site, because that is what
        an operator asks ("is the global trade feed failing?") rather than the
        event type, and because `WS_PUBLISH_FAILURES` already documents that label
        set. Collapsing the two would change an existing metric's meaning
        silently, which breaks every alert written against it.
        """
        if not self._redis:
            return False
        return self._dispatcher.enqueue(
            op, frame=frame, label=label or frame, owe_resync_to=owe_resync_to
        )

    # ── Publishing ────────────────────────────────────────────────────────
    #
    # Every market frame is stamped with a per-market monotonic `seq` by an
    # atomic INCR+PUBLISH, so a client can prove it received every frame and
    # repair itself from REST the moment it cannot. Without that, any dropped
    # frame - a Redis blip, a reconnect window, a send that timed out - left the
    # UI permanently and silently stale, and on a quiet market nothing would ever
    # correct it.
    #
    # Failures are logged and counted, never swallowed. `except RedisError: pass`
    # made a Redis outage delete trades, price frames AND the `dirty:markets`
    # marker that drives the limit-order executor, with nothing in logs and
    # nothing to alert on: the platform looked alive while no data moved.

    def _seq(self, market_id: str, payload: dict) -> str:
        """JSON payload with the sequence placeholder spliced in."""
        return json.dumps({**payload, "seq": "__SEQ__"})

    async def publish_price_update(
        self,
        market_id: str,
        yes_price: float,
        no_price: float,
        volume: float,
        outcome_prices: dict[str, float] | None = None,
    ):
        """Broadcast a price frame.

        `outcome_prices` maps outcome name -> price. It is required for markets
        with 3+ outcomes, where the single binary book cannot express a price per
        outcome and the front end has nothing to draw a per-outcome line from
        without it. Omitted for binary markets, where yes/no already say
        everything; the front end's `outcome_prices` branch is simply skipped.

        Keys are the outcome names exactly as the API reports them ("Yes", not
        "yes") so the consumer can match them against the outcome list.

        Published on the market's *events* channel, not a separate price channel:
        one channel is one order, so a client can never see a book frame that
        contradicts the price rendered next to it. The `market:{id}:price` HSET
        below is a cache read by `market_service`, unrelated to pub/sub.
        """
        if not self._redis:
            return

        msg = {
            "type": "market:price_update",
            "market_id": market_id,
            "yes_price": yes_price,
            "no_price": no_price,
            "volume": volume,
        }
        if outcome_prices:
            msg["outcome_prices"] = outcome_prices

        async def _op():
            pipe = self._redis.pipeline()
            pipe.hset(f"market:{market_id}:price", mapping={
                "yes_price": str(yes_price),
                "no_price": str(no_price),
                "volume": str(volume),
                "updated_at": str(time.time()),
            })
            pipe.expire(f"market:{market_id}:price", 300)
            pipe.eval(
                _SEQ_AND_PUBLISH_LUA,
                2,
                market_seq_key(market_id),
                market_events_channel(market_id),
                self._seq(market_id, msg),
            )
            # Mark the market dirty so the limit-order executor only scans
            # markets whose price actually moved (instead of a full-table
            # FOR UPDATE sweep every minute). No extra round-trip: same pipeline.
            pipe.sadd("dirty:markets", market_id)
            await pipe.execute()

        # Ephemeral by design: only the newest price matters, so overflowing
        # this queue drops the oldest and keeps the latest - the same coalescing
        # the grid does anyway, reached without a Redis round-trip per discard.
        self.enqueue_publish(_op, frame="price_update", label="price_update")

    async def publish_order_fill(self, user_id: str, order_data: dict):
        """Push a private fill frame to the user's own sockets."""
        if not self._redis:
            return

        async def _op():
            await self._redis.publish(
                f"user:{user_id}:fills",
                json.dumps({**order_data, "type": "order:fill"}),
            )

        # Private channel, so overflow owes this user a resync rather than a
        # silently missing "you were filled".
        self.enqueue_publish(_op, frame="order:fill", label="order_fill",
                             owe_resync_to=user_id)

    async def publish_notification(self, user_id: str, data: dict):
        if not self._redis:
            return

        async def _op():
            await self._redis.publish(
                f"user:{user_id}:notifications",
                json.dumps({**data, "type": "notification"}),
            )

        self.enqueue_publish(_op, frame="notification", label="notification",
                             owe_resync_to=user_id)

    async def publish_user_event(self, user_id: str, data: dict) -> None:
        """Publish a private event frame *preserving* its declared `type`.

        `publish_notification` unconditionally stamps `type: "notification"`,
        which silently destroyed any other event type sent down the same private
        channel. `workers/tasks.py` has been calling it with
        `{"type": "position:update"}` and the type was overwritten before it
        left the process - so `position:update` has never once reached a client,
        and the three frontend components that handle it were dead code. The
        broker had no idea; the frame looked like an ordinary notification.

        Same channel (it is the user's private stream), different contract: the
        caller's `type` is the caller's.
        """
        if not self._redis:
            return
        frame = {"type": "notification", **data}

        async def _op():
            await self._redis.publish(
                f"user:{user_id}:notifications", json.dumps(frame)
            )

        # `position:update` travels this path, so the frame name is the caller's
        # declared type - that is what makes the queue classify it as critical.
        self.enqueue_publish(_op, frame=frame.get("type") or "user_event",
                             label="user_event", owe_resync_to=user_id)

    async def publish_market_event(self, market_id: str, event_type: str, data: dict | None = None):
        """Push any market-scoped frame (`trade:new`, `orderbook:update`, ...).

        Carries the same per-market `seq` as price frames, because subscribers
        receive both on one socket and need one shared ordering to detect gaps
        across the pair.
        """
        if not self._redis:
            return

        async def _op():
            await self._redis.eval(
                _SEQ_AND_PUBLISH_LUA,
                2,
                market_seq_key(market_id),
                market_events_channel(market_id),
                self._seq(market_id, {"type": event_type, "market_id": market_id, **(data or {})}),
            )

        # The event type drives the delivery class: `orderbook:update` and
        # `trade:new` must not vanish, `market:price_update` may. Market-scoped
        # frames have no private channel, so overflow relies on the `seq` gap to
        # drive the client's refetch - which is automatic.
        self.enqueue_publish(_op, frame=event_type, label="market_event")

    async def publish_global_trade(self, trade_data: dict):
        """Push to the platform-wide trade feed.

        Not sequenced: `global:trades` is a firehose for the activity feed, and
        the client already reconciles it against `GET /trades` by trade id. A
        gap there is self-healing; a gap in a market's book is not.
        """
        if not self._redis:
            return

        async def _op():
            await self._redis.publish(
                GLOBAL_TRADES_CHANNEL, json.dumps({"type": "trade:new", **trade_data})
            )

        self.enqueue_publish(_op, frame="trade:new", label="global_trade")

    async def listen(self):
        """Consume every channel this process is subscribed to, until shutdown.

        Drives `get_message()` in a loop rather than iterating `listen()`.

        This is the single most important thing in the whole pub/sub path.
        redis-py's `listen()` is literally `while self.subscribed:`, and
        `subscribed` is `bool(self.channels or ...)`. The app starts this listener
        at startup, when *nothing* is subscribed yet - subscriptions only happen
        later, when the first WebSocket connects. So the generator's loop
        condition was false on entry, it returned immediately, and the task
        completed. Later `subscribe_market()` calls still registered the channels
        (which is why `PUBSUB CHANNELS` shows them while nothing is delivered):
        Redis accepted the SUBSCRIBE, but there was no consumer left to read the
        messages. Every price frame, trade and orderbook push was published into
        a channel nobody was listening to, and live updates were dead in every
        environment - including tests, which passed only because they subscribed
        *before* starting the listener, the opposite order to production.

        `get_message()` has no such precondition: it blocks for `timeout` and
        returns None on timeout, so the loop survives having zero subscriptions
        and picks up later ones with no restart.

        A dropped Redis connection is also recovered from in-loop. Previously any
        exception ended the task for good, and nothing ever restarted it -
        `start_listener()` is only called during lifespan startup - so one blip
        meant permanent silence for the rest of the process's life.
        """
        backoff = 0.5
        while not self._closed:
            if self._pubsub is None:
                if not await self._reconnect():
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 10.0)
                    continue
                backoff = 0.5

            if not self._pubsub.subscribed:
                # Idle, not dead. `parse_response` raises "pubsub connection not
                # set" until at least one SUBSCRIBE has run, and subscriptions
                # only arrive later, when the first WebSocket connects. This is
                # the state the app starts in, so the loop must simply wait here
                # and pick up as soon as `subscribe_market` sets the first
                # channel. Polling is on a short interval rather than blocking,
                # because there is no connection to block on yet.
                await asyncio.sleep(0.05)
                continue

            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                # Connection lost. Drop the dead client so the next iteration
                # rebuilds it and re-subscribes everything we were tracking.
                logger.warning("Redis pubsub connection lost • reconnecting", exc_info=True)
                await self._drop_pubsub()
                continue

            if message is None:
                continue  # idle tick

            if message["type"] != "message":
                continue

            try:
                data = json.loads(message["data"])
                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()

                if channel == GLOBAL_TRADES_CHANNEL:
                    # Matched on the whole channel string BEFORE the prefix split
                    # below. `global:trades` splits into two parts, so it always
                    # entered the `len(parts) >= 2` branch, matched neither
                    # "market" nor "user", and fell out of the loop silently -
                    # making the entire global trade feed dead code, and
                    # `broadcast_global` unreachable.
                    asyncio.create_task(
                        _bounded_broadcast(manager.broadcast_global(data))
                    )
                else:
                    parts = channel.split(":")
                    if len(parts) >= 2:
                        prefix, target = parts[0], parts[1]
                        if prefix == "market":
                            asyncio.create_task(
                                _bounded_broadcast(
                                    manager.broadcast_to_market(target, data)
                                )
                            )
                        elif prefix == "user":
                            asyncio.create_task(
                                _bounded_broadcast(
                                    user_manager.broadcast_to_user(target, data)
                                )
                            )
                        else:
                            logger.debug("Ignoring unroutable Redis channel %s", channel)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from Redis: {str(message['data'])[:100]}")
            except Exception:
                logger.exception("Error broadcasting Redis message")

    async def _drop_pubsub(self) -> None:
        """Discard a broken pubsub client, keeping the tracked channel list."""
        self._pubsub = None
        # `_refs` deliberately survives: it is the record of what we want to be
        # listening to, and `_reconnect` replays it against the new client.
        # `_subscribed` must NOT - the client it described is gone, and leaving
        # it populated would make `_sync_channels` believe a fresh client was
        # already subscribed and skip the subscribe entirely.
        self._subscribed.clear()
        try:
            self._connected = False
        except Exception:
            pass

    async def _reconnect(self) -> bool:
        """Rebuild the pubsub client and replay every tracked subscription.

        Returns False when Redis is still unreachable, so the caller can back off
        rather than spinning on a failing connect.

        Takes `_sync_lock`, which it did not before. `_sync_channels` holds that
        lock while it issues SUBSCRIBE/UNSUBSCRIBE, and this method was issuing
        its own SUBSCRIBE on the same freshly-built pubsub client without it. A
        socket connecting in the window between `connect()` and the replay could
        interleave two subscribe calls on one redis-py PubSub, leaving
        `_subscribed` describing a set of channels the client does not actually
        hold - and `_sync_channels` then believes there is nothing to fix, so the
        mismatch is permanent for the process.
        """
        try:
            await self.connect()
        except Exception:
            logger.warning("Redis pubsub reconnect failed", exc_info=True)
            return False

        if not self._pubsub:
            return False

        # Replay from `_refs` (intent), never from `_subscribed` (what the dead
        # client happened to hold). `_refs` is the superset and survives the
        # connection loss, so a subscribe that arrived while the client was down
        # is restored here instead of being lost for the process's lifetime.
        async with self._sync_lock:
            wanted = sorted(self._wanted())
            self._subscribed.clear()
            if not wanted:
                return True
            try:
                await self._pubsub.subscribe(*wanted)
            except Exception:
                logger.warning("Redis pubsub re-subscribe failed", exc_info=True)
                return False

            self._subscribed = set(wanted)

        logger.info("Redis pubsub resubscribed to %d channel(s)", len(wanted))
        return True

    async def start_listener(self):
        # `listen()` is restartable: it returns normally on close(), and any
        # earlier exit (including the pre-fix one where redis-py's `listen()`
        # returned instantly because nothing was subscribed yet) leaves the task
        # done. Re-creating it here makes the call idempotent and recoverable
        # rather than start-once-and-never-again.
        if self._listener_task is None or self._listener_task.done():
            self._closed = False
            self._listener_task = asyncio.create_task(self.listen())

    async def close(self):
        # Set before cancelling so an in-flight `get_message` returns promptly and
        # the loop exits on its own condition rather than only via CancelledError.
        self._closed = True
        # Reset the connection flags as well as stopping the tasks.
        #
        # Leaving `_connected` true after a close means the next `connect()`
        # early-returns on a `_pubsub` that has already been closed underneath
        # it - so the caller believes it has a working Redis connection and every
        # subscribe and publish fails against a corpse, with nothing to say why.
        # Restarting is the whole contract of `connect()`.
        self._connected = False
        # Writers stop before the Redis connection closes, so a queued frame is
        # not handed to a client that is going away.
        await self._dispatcher.stop()
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if self._pubsub:
            try:
                await self._pubsub.unsubscribe()
                await self._pubsub.close()
            except Exception:
                pass
        if self._redis:
            try:
                await self._redis.aclose()
            except Exception:
                pass
        self._connected = False
        self._subscribed.clear()
        self._refs.clear()


redis_pubsub = RedisPubSub()
