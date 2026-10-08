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
from collections import defaultdict

import redis.asyncio as redis
from fastapi import WebSocket

from app.middleware.metrics import (
    WS_CONNECTIONS,
    WS_CONNECTS_TOTAL,
    WS_DISCONNECTS_TOTAL,
    WS_MESSAGES_FANNED_OUT,
    WS_SENDS_TOTAL,
    WS_SUBSCRIPTIONS,
)
from app.redis import get_redis, redis_cb

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

    def __init__(self):
        self._market_subs: dict[str, set[WebSocket]] = defaultdict(set)
        # Per-socket subscription registry: which markets each WS is subscribed to
        self._ws_subscriptions: dict[WebSocket, set[str]] = defaultdict(set)
        # Per-socket lock: serialises subscribe/unsubscribe/disconnect for same WS
        self._ws_locks: dict[WebSocket, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._ip_connections: dict[str, int] = defaultdict(int)
        self._user_connections: dict[str, int] = defaultdict(int)
        self._ws_ip: dict[WebSocket, str | None] = {}
        self._ws_user: dict[WebSocket, str | None] = {}
        # Track pending cleanup tasks so they can be awaited on shutdown
        self._pending_cleanups: set[asyncio.Task[None]] = set()

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
        ws_lock = self._ws_locks[websocket]
        async with ws_lock:
            self._ws_subscriptions[websocket].add(market_id)

        if client_ip:
            self._ip_connections[client_ip] += 1
        if user_id:
            self._user_connections[user_id] += 1
        # Store these so disconnect() can decrement them
        self._ws_ip[websocket] = client_ip
        self._ws_user[websocket] = user_id

        WS_CONNECTS_TOTAL.labels("accepted").inc()
        WS_CONNECTIONS.inc()
        WS_SUBSCRIPTIONS.inc()
        logger.info(f"WS connected: market={market_id} ip={client_ip} user={user_id}")
        return True

    async def subscribe_to_market(
        self, websocket: WebSocket, market_id: str, redis_pubsub_ref=None
    ):
        """
        Add a market subscription without removing existing ones.
        Idempotent • calling twice is safe.
        Returns True if subscribed, False if rejected (cap reached or already subscribed).
        """
        ws_lock = self._ws_locks[websocket]

        async with ws_lock:
            subs = self._ws_subscriptions[websocket]

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

        # Subscribe to Redis channel for this market (fire-and-forget)
        if redis_pubsub_ref:
            asyncio.create_task(redis_pubsub_ref.subscribe_market(market_id))

        logger.debug(f"WS subscribed to market: {market_id}")
        return True

    async def unsubscribe_from_market(
        self, websocket: WebSocket, market_id: str, redis_pubsub_ref=None
    ):
        """Remove a market subscription. Keeps other subscriptions intact. Idempotent."""
        ws_lock = self._ws_locks[websocket]

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

        # Unsubscribe from Redis channel (fire-and-forget)
        if redis_pubsub_ref:
            asyncio.create_task(redis_pubsub_ref.unsubscribe_market(market_id))

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

        # Gauges are decremented only for sockets this worker actually counted.
        # A socket can reach here that never was • rejected before `accept()`,
        # or already reaped by the heartbeat • and decrementing for it would
        # drive the metric negative, which is worse than having no metric.
        if was_registered:
            WS_CONNECTIONS.dec()
            WS_SUBSCRIPTIONS.dec(n_subs)
            WS_DISCONNECTS_TOTAL.labels(cause).inc()

        # Unsubscribe from all Redis channels this socket was listening to.
        # __global_trades__ and __notifications__ prefixes are not real market IDs
        # and were subscribed via subscribe_global_trades / subscribe_user • skip them.
        if redis_pubsub_ref:
            for market_id in market_ids:
                if not market_id.startswith("__"):
                    asyncio.create_task(redis_pubsub_ref.unsubscribe_market(market_id))

        logger.debug(f"WS disconnected: {len(market_ids)} subscriptions cleaned up")

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

        if not raw_sockets:
            return

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
        for ws in sockets:
            try:
                await self.disconnect(ws, cause=cause)
            except Exception:
                pass

    async def _ping_many(self, sockets: list[WebSocket]) -> list[WebSocket]:
        """Ping sockets concurrently under a bounded semaphore; return the dead.

        Concurrent and bounded on purpose. The obvious sequential loop is a
        scalability bug: at `SEND_TIMEOUT_S = 2.0`, fifty wedged sockets take
        100s • three times the 30s sweep interval, so sweeps pile up. Fifty
        thousand healthy sockets would take minutes. `_bounded_send` already
        had this right for frames; the sweep now does the same for pings.
        """
        if not sockets:
            return []

        sem = asyncio.Semaphore(self.SEND_CONCURRENCY)
        dead: list[WebSocket] = []

        async def ping(ws: WebSocket) -> None:
            try:
                async with sem:
                    await asyncio.wait_for(
                        ws.send_json({"type": "ping"}), timeout=self.SEND_TIMEOUT_S
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

    async def _cleanup_dead(self, sockets: list[WebSocket]):
        """Probe sockets and disconnect the unresponsive ones.

        Driven by `heartbeat_loop`, not by broadcasts: a socket on a *quiet*
        market never receives a broadcast, so broadcast-failure detection alone
        never reaps it. This was dead code until the sweep was wired up.
        """
        live = [ws for ws in sockets if ws in self._ws_subscriptions]
        dead = await self._ping_many(live)
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

    def __init__(self):
        self._user_socks: dict[str, set[WebSocket]] = defaultdict(set)
        self._ws_to_user: dict[WebSocket, str] = {}
        self._user_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # Track pending cleanup tasks so they can be awaited on shutdown
        self._pending_cleanups: set[asyncio.Task[None]] = set()

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        async with self._user_locks[user_id]:
            self._user_socks[user_id].add(websocket)
            self._ws_to_user[websocket] = user_id
        # Counted here too, otherwise `ws_connections` silently excludes every
        # notification socket and the capacity gauge under-reports real load.
        WS_CONNECTIONS.inc()
        logger.info(f"User WS connected: user={user_id}")

    async def disconnect(self, websocket: WebSocket, user_id: str, cause: str = "client"):
        # Registered check first: this socket may already have been reaped.
        was_registered = websocket in self._ws_to_user
        async with self._user_locks[user_id]:
            self._user_socks[user_id].discard(websocket)
            self._ws_to_user.pop(websocket, None)
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
                        ws.send_json({"type": "ping"}), timeout=self.SEND_TIMEOUT_S
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
        """Reap unresponsive notification sockets. Called from the single
        heartbeat loop so there is exactly one timer, not one per manager."""
        live = [ws for ws in self.all_sockets() if ws in self._ws_to_user]
        dead = await self._ping_many(live)
        for ws in dead:
            try:
                await self.disconnect(ws, self._ws_to_user.get(ws, "unknown"), cause="heartbeat")
            except Exception:
                pass
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
        self._subscribed: set[str] = set()
        # Loop exit condition for `listen()`. Without it the task has to be killed
        # by cancellation alone, and a restart would be indistinguishable from a
        # completed run.
        self._closed = False

    async def connect(self):
        if self._connected and self._pubsub is not None:
            return
        self._redis = await get_redis()
        self._pubsub = self._redis.pubsub()
        self._connected = True
        self._closed = False

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
            pipe.publish(f"market:{market_id}:price", json.dumps(msg))
            # Mark the market dirty so the limit-order executor only scans
            # markets whose price actually moved (instead of a full-table
            # FOR UPDATE sweep every minute). No extra round-trip: same pipeline.
            pipe.sadd("dirty:markets", market_id)
            await pipe.execute()

        try:
            await redis_cb.call(_op)
        except redis.RedisError:
            pass

    async def publish_order_fill(self, user_id: str, order_data: dict):
        if not self._redis:
            return
        msg = json.dumps({**order_data, "type": "order:fill"})

        async def _op():
            await self._redis.publish(f"user:{user_id}:fills", msg)

        try:
            await redis_cb.call(_op)
        except redis.RedisError:
            pass

    async def publish_notification(self, user_id: str, data: dict):
        if not self._redis:
            return
        msg = json.dumps({**data, "type": "notification"})

        async def _op():
            await self._redis.publish(f"user:{user_id}:notifications", msg)

        try:
            await redis_cb.call(_op)
        except redis.RedisError:
            pass

    async def publish_market_event(self, market_id: str, event_type: str, data: dict | None = None):
        if not self._redis:
            return
        msg = json.dumps({"type": event_type, "market_id": market_id, **(data or {})})

        async def _op():
            await self._redis.publish(f"market:{market_id}:events", msg)

        try:
            await redis_cb.call(_op)
        except redis.RedisError:
            pass

    async def publish_global_trade(self, trade_data: dict):
        if not self._redis:
            return
        msg = json.dumps({"type": "trade:new", **trade_data})

        async def _op():
            await self._redis.publish("global:trades", msg)

        try:
            await redis_cb.call(_op)
        except redis.RedisError:
            pass

    async def subscribe_market(self, market_id: str):
        if not self._pubsub:
            return
        for ch in (f"market:{market_id}:price", f"market:{market_id}:events"):
            if ch not in self._subscribed:
                await self._pubsub.subscribe(ch)
                self._subscribed.add(ch)

    async def unsubscribe_market(self, market_id: str):
        """Unsubscribe from market channels and clean up tracked subscription."""
        if not self._pubsub:
            return
        for ch in (f"market:{market_id}:price", f"market:{market_id}:events"):
            if ch in self._subscribed:
                await self._pubsub.unsubscribe(ch)
                self._subscribed.discard(ch)

    async def subscribe_user(self, user_id: str):
        if not self._pubsub:
            return
        for ch in (f"user:{user_id}:fills", f"user:{user_id}:notifications"):
            if ch not in self._subscribed:
                await self._pubsub.subscribe(ch)
                self._subscribed.add(ch)

    async def subscribe_global_trades(self):
        if not self._pubsub:
            return
        if GLOBAL_TRADES_CHANNEL not in self._subscribed:
            await self._pubsub.subscribe(GLOBAL_TRADES_CHANNEL)
            self._subscribed.add(GLOBAL_TRADES_CHANNEL)

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
        # `_subscribed` deliberately survives: it is the record of what we want to
        # be listening to, and `_reconnect` replays it against the new client.
        try:
            self._connected = False
        except Exception:
            pass

    async def _reconnect(self) -> bool:
        """Rebuild the pubsub client and replay every tracked subscription.

        Returns False when Redis is still unreachable, so the caller can back off
        rather than spinning on a failing connect.
        """
        try:
            await self.connect()
        except Exception:
            logger.warning("Redis pubsub reconnect failed", exc_info=True)
            return False

        if not self._pubsub:
            return False

        wanted = sorted(self._subscribed)
        if not wanted:
            return True
        try:
            await self._pubsub.subscribe(*wanted)
        except Exception:
            logger.warning("Redis pubsub re-subscribe failed", exc_info=True)
            return False

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


redis_pubsub = RedisPubSub()
