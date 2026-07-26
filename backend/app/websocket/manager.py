import json
import logging
import time
from typing import Dict, Set
import asyncio

import redis.asyncio as redis
from fastapi import WebSocket

from app.config import settings
from app.redis import get_redis, redis_cb

logger = logging.getLogger("polymarket")

# Global lock for all connection manager operations — prevents disconnect/broadcast races
_manager_lock = asyncio.Lock()


class ConnectionManager:
    def __init__(self):
        self._market_subs: Dict[str, Set[WebSocket]] = {}
        self._ws_to_market: Dict[WebSocket, str] = {}
        self._lock = _manager_lock

    async def connect(self, websocket: WebSocket, market_id: str):
        await websocket.accept()
        async with self._lock:
            if market_id not in self._market_subs:
                self._market_subs[market_id] = set()
            self._market_subs[market_id].add(websocket)
            self._ws_to_market[websocket] = market_id
        logger.info(f"WS connected: market={market_id}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            market_id = self._ws_to_market.pop(websocket, None)
            if market_id and market_id in self._market_subs:
                self._market_subs[market_id].discard(websocket)
                if not self._market_subs[market_id]:
                    del self._market_subs[market_id]

    async def broadcast_to_market(self, market_id: str, event: dict):
        async with self._lock:
            sockets = list(self._market_subs.get(market_id, set()))

        if not sockets:
            return

        dead = []
        for ws in sockets:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    market_id_for_ws = self._ws_to_market.get(ws)
                    self._ws_to_market.pop(ws, None)
                    if market_id_for_ws and market_id_for_ws in self._market_subs:
                        self._market_subs[market_id_for_ws].discard(ws)

    async def broadcast_global(self, event: dict):
        async with self._lock:
            all_sockets = [ws for sockets in self._market_subs.values() for ws in sockets]

        dead = []
        for ws in all_sockets:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    market_id = self._ws_to_market.pop(ws, None)
                    if market_id and market_id in self._market_subs:
                        self._market_subs[market_id].discard(ws)


# Global manager instance
manager = ConnectionManager()


class RedisPubSub:
    def __init__(self):
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._listener_task: asyncio.Task | None = None
        self._connected = False
        self._subscribed: Set[str] = set()

    async def connect(self):
        if self._connected:
            return  # prevent duplicate connections
        self._redis = get_redis()
        self._pubsub = self._redis.pubsub()
        self._connected = True

    async def publish_price_update(self, market_id: str, yes_price: float, no_price: float, volume: float, outcome_prices: dict[str, float] | None = None):
        if not self._redis:
            return

        key = f"market:{market_id}:price"
        pubsub_channel = f"market:{market_id}:price"

        msg_payload: dict = {
            "type": "market:price_update",
            "market_id": market_id,
            "yes_price": yes_price,
            "no_price": no_price,
            "volume": volume,
        }
        if outcome_prices:
            msg_payload["outcome_prices"] = outcome_prices

        async def _op():
            pipe = self._redis.pipeline()
            pipe.hset(key, mapping={
                "yes_price": str(yes_price),
                "no_price": str(no_price),
                "volume": str(volume),
                "updated_at": time.time(),
            })
            pipe.expire(key, 300)
            pipe.publish(pubsub_channel, json.dumps(msg_payload))
            await pipe.execute()

        try:
            await redis_cb.call(_op)
        except redis.RedisError:
            pass

    async def publish_order_fill(self, user_id: str, order_data: dict):
        if not self._redis:
            return
        async def _op():
            msg = json.dumps({**order_data, "type": "order:fill"})
            await self._redis.publish(f"user:{user_id}:fills", msg)
        try:
            await redis_cb.call(_op)
        except redis.RedisError:
            pass

    async def publish_market_event(self, market_id: str, event_type: str, data: dict | None = None):
        if not self._redis:
            return
        async def _op():
            msg = json.dumps({"type": event_type, "market_id": market_id, **(data or {})})
            await self._redis.publish(f"market:{market_id}:events", msg)
        try:
            await redis_cb.call(_op)
        except redis.RedisError:
            pass

    async def subscribe_market(self, market_id: str):
        if not self._pubsub:
            return
        channels = [
            f"market:{market_id}:price",
            f"market:{market_id}:events",
        ]
        for ch in channels:
            if ch not in self._subscribed:
                await self._pubsub.subscribe(ch)
                self._subscribed.add(ch)

    async def listen(self):
        """Listen for Redis messages and broadcast to local WebSocket clients."""
        if not self._pubsub:
            return
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    channel = message["channel"].decode() if isinstance(message["channel"], bytes) else message["channel"]
                    parts = channel.split(":")
                    if len(parts) >= 2:
                        market_id = parts[1]
                        await manager.broadcast_to_market(market_id, data)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from Redis channel {channel}: {message['data'][:100]}")
                except Exception:
                    logger.exception("Error broadcasting Redis message")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Redis pubsub listener died — restart will be attempted on next publish/connect")

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


# Global instance
redis_pubsub = RedisPubSub()
