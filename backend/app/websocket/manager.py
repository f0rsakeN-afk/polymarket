"""
Scalable WebSocket connection manager for 50k+ concurrent users.

Key design decisions for scale:
- Per-market locks: broadcasts to different markets never block each other
- Fire-and-forget send: each socket send is an independent asyncio task,
  one slow socket doesn't block others
- Async dead-socket cleanup: doesn't block the broadcast path
- Connection caps per IP and per user: prevents resource exhaustion attacks
"""

import asyncio
import json
import logging
import time
from collections import defaultdict

import redis.asyncio as redis
from fastapi import WebSocket

from app.redis import get_redis, redis_cb

logger = logging.getLogger("polymarket")

# ── Per-market locks ────────────────────────────────────────────────────────────


class MarketLockTable:
    """
    Per-market locks — avoids global lock contention.
    Lazily creates locks as markets gain subscribers.
    """

    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}
        self._global = asyncio.Lock()

    async def _get_lock(self, market_id: str) -> asyncio.Lock:
        async with self._global:
            if market_id not in self._locks:
                self._locks[market_id] = asyncio.Lock()
            return self._locks[market_id]


_market_locks = MarketLockTable()


# ── Connection Manager ────────────────────────────────────────────────────────


class ConnectionManager:
    """
    Per-market WebSocket subscription manager.

    Scales to 50k+ connections by:
    1. Per-market locks — broadcasts to market A never block market B
    2. Fire-and-forget send — each socket gets its own asyncio task
    3. Connection limits — prevents file-descriptor exhaustion per IP/user
    4. Async dead-socket cleanup — doesn't block active broadcasts
    """

    MAX_CONNECTIONS_PER_IP = 10
    MAX_CONNECTIONS_PER_USER = 5

    def __init__(self):
        self._market_subs: dict[str, set[WebSocket]] = defaultdict(set)
        self._ws_to_market: dict[WebSocket, str] = {}
        self._ip_connections: dict[str, int] = defaultdict(int)
        self._user_connections: dict[str, int] = defaultdict(int)

    async def connect(
        self,
        websocket: WebSocket,
        market_id: str,
        client_ip: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        """Accept a WS connection and subscribe to a market. Returns False if rejected."""
        if client_ip and self._ip_connections.get(client_ip, 0) >= self.MAX_CONNECTIONS_PER_IP:
            logger.warning(f"WS rejected: too many connections from IP {client_ip}")
            return False
        if user_id and self._user_connections.get(user_id, 0) >= self.MAX_CONNECTIONS_PER_USER:
            logger.warning(f"WS rejected: too many connections for user {user_id}")
            return False

        await websocket.accept()
        lock = await _market_locks._get_lock(market_id)
        async with lock:
            self._market_subs[market_id].add(websocket)
            self._ws_to_market[websocket] = market_id

        if client_ip:
            self._ip_connections[client_ip] += 1
        if user_id:
            self._user_connections[user_id] += 1

        logger.info(f"WS connected: market={market_id} ip={client_ip} user={user_id}")
        return True

    async def switch_market(self, websocket: WebSocket, new_market_id: str):
        old = self._ws_to_market.get(websocket)
        if old == new_market_id:
            return

        if old:
            lock = await _market_locks._get_lock(old)
            async with lock:
                self._market_subs[old].discard(websocket)
                if not self._market_subs[old]:
                    del self._market_subs[old]

        lock = await _market_locks._get_lock(new_market_id)
        async with lock:
            self._market_subs[new_market_id].add(websocket)
            self._ws_to_market[websocket] = new_market_id

        logger.info(f"WS switched: {old} -> {new_market_id}")

    async def disconnect(self, websocket: WebSocket, client_ip: str | None = None, user_id: str | None = None):
        market_id = self._ws_to_market.pop(websocket, None)
        if market_id:
            lock = await _market_locks._get_lock(market_id)
            async with lock:
                self._market_subs[market_id].discard(websocket)
                if not self._market_subs[market_id]:
                    del self._market_subs[market_id]

        if client_ip and self._ip_connections.get(client_ip, 0) > 0:
            self._ip_connections[client_ip] -= 1
        if user_id and self._user_connections.get(user_id, 0) > 0:
            self._user_connections[user_id] -= 1

        logger.debug(f"WS disconnected: market={market_id}")

    async def broadcast_to_market(self, market_id: str, event: dict):
        """Fire-and-forget broadcast — does not block on slow sockets."""
        lock = await _market_locks._get_lock(market_id)
        async with lock:
            sockets = list(self._market_subs.get(market_id, set()))

        if not sockets:
            return

        async def safe_send(ws: WebSocket):
            try:
                await ws.send_json(event)
            except Exception:
                pass

        # Fire-and-forget: all sends run concurrently
        await asyncio.gather(*(safe_send(ws) for ws in sockets), return_exceptions=True)
        # Cleanup dead sockets in background (non-blocking)
        asyncio.create_task(self._cleanup_dead(sockets))

    async def _cleanup_dead(self, sockets: list[WebSocket]):
        for ws in sockets:
            if ws not in self._ws_to_market:
                continue
            try:
                await ws.send_json({"type": "ping"})
            except Exception:
                await self.disconnect(ws)

    async def broadcast_global(self, event: dict):
        all_sockets: list[WebSocket] = []
        async with _market_locks._global:
            for socks in self._market_subs.values():
                all_sockets.extend(socks)

        if not all_sockets:
            return

        async def safe_send(ws: WebSocket):
            try:
                await ws.send_json(event)
            except Exception:
                pass

        await asyncio.gather(*(safe_send(ws) for ws in all_sockets), return_exceptions=True)
        asyncio.create_task(self._cleanup_dead(all_sockets))

    def subscriber_count(self, market_id: str) -> int:
        return len(self._market_subs.get(market_id, set()))

    def total_connections(self) -> int:
        return len(self._ws_to_market)


manager = ConnectionManager()


# ── User Connection Manager ─────────────────────────────────────────────────────


class UserConnectionManager:
    """Per-user notification WS connections. Per-user locks, fire-and-forget sends."""

    def __init__(self):
        self._user_socks: dict[str, set[WebSocket]] = defaultdict(set)
        self._ws_to_user: dict[WebSocket, str] = {}
        self._user_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        async with self._user_locks[user_id]:
            self._user_socks[user_id].add(websocket)
            self._ws_to_user[websocket] = user_id
        logger.info(f"User WS connected: user={user_id}")

    async def disconnect(self, websocket: WebSocket, user_id: str):
        async with self._user_locks[user_id]:
            self._user_socks[user_id].discard(websocket)
            self._ws_to_user.pop(websocket, None)
            if not self._user_socks[user_id]:
                del self._user_socks[user_id]
        logger.debug(f"User WS disconnected: user={user_id}")

    async def broadcast_to_user(self, user_id: str, event: dict):
        async with self._user_locks[user_id]:
            sockets = list(self._user_socks.get(user_id, set()))

        if not sockets:
            return

        async def safe_send(ws: WebSocket):
            try:
                await ws.send_json(event)
            except Exception:
                pass

        await asyncio.gather(*(safe_send(ws) for ws in sockets), return_exceptions=True)
        asyncio.create_task(self._cleanup_dead_user(user_id, sockets))

    async def _cleanup_dead_user(self, user_id: str, sockets: list[WebSocket]):
        for ws in sockets:
            if ws not in self._ws_to_user:
                continue
            try:
                await ws.send_json({"type": "ping"})
            except Exception:
                await self.disconnect(ws, user_id)


user_manager = UserConnectionManager()


# ── Redis Pub/Sub ───────────────────────────────────────────────────────────────


class RedisPubSub:
    def __init__(self):
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._listener_task: asyncio.Task | None = None
        self._connected = False
        self._subscribed: set[str] = set()

    async def connect(self):
        if self._connected:
            return
        self._redis = await get_redis()
        self._pubsub = self._redis.pubsub()
        self._connected = True

    async def publish_price_update(self, market_id: str, yes_price: float, no_price: float, volume: float):
        if not self._redis:
            return

        msg = {
            "type": "market:price_update",
            "market_id": market_id,
            "yes_price": yes_price,
            "no_price": no_price,
            "volume": volume,
        }

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
        if "global:trades" not in self._subscribed:
            await self._pubsub.subscribe("global:trades")
            self._subscribed.add("global:trades")

    async def listen(self):
        if not self._pubsub:
            return
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    channel = message["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode()
                    parts = channel.split(":")
                    if len(parts) >= 2:
                        prefix, target = parts[0], parts[1]
                        if prefix == "market":
                            # Fire-and-forget: don't let a slow broadcast block the listener
                            asyncio.create_task(manager.broadcast_to_market(target, data))
                        elif prefix == "user":
                            asyncio.create_task(user_manager.broadcast_to_user(target, data))
                    elif channel == "global:trades":
                        asyncio.create_task(manager.broadcast_global(data))
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from Redis: {message['data'][:100]}")
                except Exception:
                    logger.exception("Error broadcasting Redis message")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Redis pubsub listener died")

    async def start_listener(self):
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(self.listen())

    async def close(self):
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
