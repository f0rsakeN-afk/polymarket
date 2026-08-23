import logging
import os

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

from app.config import settings
from app.services.rate_limit_service import RateLimitService
from app.websocket.manager import manager, redis_pubsub, user_manager

logger = logging.getLogger("polymarket")
router = APIRouter(tags=["websocket"])

MAX_WS_PAYLOAD_SIZE = 64 * 1024  # 64 KB per incoming frame — prevents memory exhaustion

# Reuse the same trusted-proxy logic as HTTP middleware
_TRUSTED_PROXY_IPS = [
    ip.strip()
    for ip in os.environ.get("TRUSTED_PROXY_IPS", "").split(",")
    if ip.strip()
]


def _get_real_client_ip(websocket: WebSocket) -> str:
    direct_ip = websocket.client[0] if websocket.client else None
    if direct_ip in _TRUSTED_PROXY_IPS:
        import warnings
        forwarded = websocket.headers.get("x-forwarded-for")
        if forwarded:
            return RateLimitService._normalize_ip(forwarded.split(",")[0].strip())
    return RateLimitService._normalize_ip(direct_ip or "unknown")


async def verify_ws_token(token: str | None) -> str | None:
    """Verify WS token and return user_id or None. Token may be None (optional auth)."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        return payload.get("sub")
    except JWTError:
        return None


def _get_token_from_request(websocket: WebSocket) -> str | None:
    """
    Extract auth token from cookie first (secure), then query param (fallback).
    Cookies are sent with WebSocket handshake in modern browsers.
    """
    # HttpOnly cookie set by set_auth_cookies
    cookie_token = websocket.cookies.get("access_token")
    if cookie_token:
        return cookie_token
    # Fallback: query param (for convenience / legacy compatibility)
    return websocket.query_params.get("token")


@router.websocket("/ws/markets/{market_id}")
async def market_websocket(websocket: WebSocket, market_id: str):
    """
    Single multiplexed WebSocket connection per client.

    Auth: access_token cookie (preferred) or ?token= query param (fallback).
    On connect the client is subscribed to `market_id`.
    The client may then send:
      - {type: "subscribe", market_id: "..."}  — add a market subscription
      - {type: "unsubscribe", market_id: "..."} — remove a market subscription
      - {type: "ping"}                         — server replies {type: "pong"}

    The server enforces MAX_SUBSCRIPTIONS_PER_SOCKET (50) per connection.
    """
    client_ip = _get_real_client_ip(websocket)
    token = _get_token_from_request(websocket)
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
            # Size-check before parsing to prevent memory exhaustion
            raw = await websocket.receive_text()
            if len(raw) > MAX_WS_PAYLOAD_SIZE:
                await websocket.close(code=1009, reason="Payload too large")
                break
            import json
            data = json.loads(raw)
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
async def global_trades_websocket(websocket: WebSocket):
    """Global trades feed — streams all new trades across the platform."""
    client_ip = _get_real_client_ip(websocket)
    token = _get_token_from_request(websocket)
    user_id = await verify_ws_token(token)
    accepted = await manager.connect(
        websocket, "__global_trades__", client_ip=client_ip, user_id=user_id
    )
    if not accepted:
        await websocket.close(code=1008, reason="Connection limit exceeded")
        return
    await redis_pubsub.subscribe_global_trades()

    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw) > MAX_WS_PAYLOAD_SIZE:
                await websocket.close(code=1009, reason="Payload too large")
                break
            import json
            data = json.loads(raw)
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await manager.disconnect(websocket, redis_pubsub)
        logger.info("Global trades WS disconnected")
    except Exception:
        logger.exception("Global trades WS error")
        await manager.disconnect(websocket, redis_pubsub)


@router.websocket("/ws/notifications/{user_id}")
async def user_notifications_websocket(websocket: WebSocket, user_id: str):
    """User notification channel — requires valid access token matching user_id."""
    token = _get_token_from_request(websocket)
    authenticated_user_id = await verify_ws_token(token)
    if not authenticated_user_id or authenticated_user_id != user_id:
        await websocket.close(code=4001, reason="Unauthorized")
        return
    await user_manager.connect(websocket, user_id)
    await redis_pubsub.subscribe_user(user_id)

    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw) > MAX_WS_PAYLOAD_SIZE:
                await websocket.close(code=1009, reason="Payload too large")
                break
            import json
            data = json.loads(raw)
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await user_manager.disconnect(websocket, user_id)
        logger.info(f"User WS disconnected: user={user_id}")
    except Exception:
        logger.exception(f"User WS error: user={user_id}")
        await user_manager.disconnect(websocket, user_id)
