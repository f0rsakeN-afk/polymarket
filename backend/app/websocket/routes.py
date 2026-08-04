import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websocket.manager import manager, redis_pubsub, user_manager

logger = logging.getLogger("polymarket")
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/markets/{market_id}")
async def market_websocket(websocket: WebSocket, market_id: str):
    await manager.connect(websocket, market_id)
    # Also subscribe this server to the Redis channel for this market
    await redis_pubsub.subscribe_market(market_id)

    try:
        while True:
            data = await websocket.receive_json()
            # Client messages: ping/pong, subscribe/unsubscribe
            msg_type = data.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "subscribe":
                new_market_id = data.get("market_id")
                if new_market_id:
                    await manager.disconnect(websocket)
                    await manager.connect(websocket, new_market_id)
                    await redis_pubsub.subscribe_market(new_market_id)
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
        logger.info(f"WS disconnected: market={market_id}")
    except Exception:
        logger.exception(f"WS error: market={market_id}")
        await manager.disconnect(websocket)


@router.websocket("/ws/trades")
async def global_trades_websocket(websocket: WebSocket):
    await manager.connect(websocket, "__global__")
    await redis_pubsub.subscribe_global_trades()

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
        logger.info("Global trades WS disconnected")
    except Exception:
        logger.exception("Global trades WS error")
        await manager.disconnect(websocket)


@router.websocket("/ws/notifications/{user_id}")
async def user_notifications_websocket(websocket: WebSocket, user_id: str):
    await user_manager.connect(websocket, user_id)
    # Subscribe to user's notification channels
    await redis_pubsub.subscribe_user(user_id)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await user_manager.disconnect(websocket, user_id)
        logger.info(f"User WS disconnected: user={user_id}")
    except Exception:
        logger.exception(f"User WS error: user={user_id}")
        await user_manager.disconnect(websocket, user_id)
