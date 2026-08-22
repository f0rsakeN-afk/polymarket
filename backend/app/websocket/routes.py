import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

from app.config import settings
from app.websocket.manager import manager, redis_pubsub, user_manager

logger = logging.getLogger("polymarket")
router = APIRouter(tags=["websocket"])


async def verify_ws_token(token: str) -> str | None:
    """Verify WS token and return user_id or None."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        return payload.get("sub")
    except JWTError:
        return None


@router.websocket("/ws/markets/{market_id}")
async def market_websocket(websocket: WebSocket, market_id: str, token: str = Query(...)):
    """
    Single multiplexed WebSocket connection per client.

    On connect the client is subscribed to `market_id`.
    The client may then send:
      - {type: "subscribe", market_id: "..."}  — add a market subscription
      - {type: "unsubscribe", market_id: "..."} — remove a market subscription
      - {type: "ping"}                         — server replies {type: "pong"}

    The server enforces MAX_SUBSCRIPTIONS_PER_SOCKET (50) per connection.
    """
    client_ip = websocket.client[0] if websocket.client else None
    user_id = await verify_ws_token(token)
    if not user_id:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    accepted = await manager.connect(websocket, market_id, client_ip=client_ip, user_id=user_id)
    if not accepted:
        await websocket.close(code=1008, reason="Connection limit exceeded")
        return

    # Subscribe this server instance to the Redis channel for the initial market
    await redis_pubsub.subscribe_market(market_id)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "subscribe":
                new_market_id = data.get("market_id")
                if not new_market_id:
                    continue
                ok = await manager.subscribe_to_market(
                    websocket, new_market_id, redis_pubsub
                )
                if not ok:
                    await websocket.send_json({
                        "type": "error",
                        "code": "subscription_cap_reached",
                        "message": "Maximum subscriptions per connection reached",
                    })

            elif msg_type == "unsubscribe":
                old_market_id = data.get("market_id")
                if old_market_id:
                    await manager.unsubscribe_from_market(
                        websocket, old_market_id, redis_pubsub
                    )

    except WebSocketDisconnect:
        await manager.disconnect(websocket, redis_pubsub)
        logger.info(f"WS disconnected: market={market_id}")
    except Exception:
        logger.exception(f"WS error: market={market_id}")
        await manager.disconnect(websocket, redis_pubsub)


@router.websocket("/ws/trades")
async def global_trades_websocket(websocket: WebSocket, token: str | None = Query(None)):
    """Global trades feed — streams all new trades across the platform."""
    client_ip = websocket.client[0] if websocket.client else None
    user_id = await verify_ws_token(token) if token else None
    accepted = await manager.connect(
        websocket, "__global_trades__", client_ip=client_ip, user_id=user_id
    )
    if not accepted:
        await websocket.close(code=1008, reason="Connection limit exceeded")
        return
    await redis_pubsub.subscribe_global_trades()

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await manager.disconnect(websocket, redis_pubsub)
        logger.info("Global trades WS disconnected")
    except Exception:
        logger.exception("Global trades WS error")
        await manager.disconnect(websocket, redis_pubsub)


@router.websocket("/ws/notifications/{user_id}")
async def user_notifications_websocket(websocket: WebSocket, user_id: str, token: str = Query(...)):
    """User notification channel — requires valid access token matching user_id."""
    authenticated_user_id = await verify_ws_token(token)
    if not authenticated_user_id or authenticated_user_id != user_id:
        await websocket.close(code=4001, reason="Unauthorized")
        return
    await user_manager.connect(websocket, user_id)
    await redis_pubsub.subscribe_user(user_id)

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await user_manager.disconnect(websocket, user_id)
        logger.info(f"User WS disconnected: user={user_id}")
    except Exception:
        logger.exception(f"User WS error: user={user_id}")
        await user_manager.disconnect(websocket, user_id)
