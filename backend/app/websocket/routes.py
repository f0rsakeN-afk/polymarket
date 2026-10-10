import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.rate_limit_service import RateLimitService
from app.websocket.manager import GLOBAL_TRADES_KEY, manager, redis_pubsub, user_manager

logger = logging.getLogger("PredictX")
router = APIRouter(tags=["websocket"])

MAX_WS_PAYLOAD_SIZE = 64 * 1024  # 64 KB per incoming frame • prevents memory exhaustion

# Reuse the same trusted-proxy logic as HTTP middleware
_TRUSTED_PROXY_IPS = [
    ip.strip()
    for ip in os.environ.get("TRUSTED_PROXY_IPS", "").split(",")
    if ip.strip()
]


def _get_real_client_ip(websocket: WebSocket) -> str:
    direct_ip = websocket.client[0] if websocket.client else None
    if direct_ip in _TRUSTED_PROXY_IPS:
        forwarded = websocket.headers.get("x-forwarded-for")
        if forwarded:
            return RateLimitService._normalize_ip(forwarded.split(",")[0].strip())
    return RateLimitService._normalize_ip(direct_ip or "unknown")


async def authenticate_ws_token(token: str | None) -> tuple[str | None, bool]:
    """Resolve an *optional* access token. Returns `(user_id, token_presented)`.

    The market feeds are public • `GET /markets/{slug}/orderbook`, `GET /trades`
    and `GET /markets/{slug}/trades` all serve the same data with no auth at all •
    so requiring a token to watch prices gated public information behind a login.
    Requiring one was collateral from hardening the *validation* of tokens that are
    presented, not a considered product decision.

    Absent-token and invalid-token are therefore different answers, and callers
    must treat them differently:

    - `(None, False)` • no token. Anonymous; fine for a public feed.
    - `(user_id, True)` • valid. Full chain checked, exactly as HTTP does.
    - `(None, True)` • a token *was* presented and it failed. **Reject.** A logged-out
      or revoked session must not quietly continue as an anonymous one, or revoking
      a session would stop meaning anything on these sockets.

    Validation is `deps.authenticate_token()`, the same chain HTTP uses: signature,
    `type == "access"`, jti blacklist, `user.is_active`, `sid` session binding. Any
    failure • including a database error • is reported as invalid, so auth fails
    closed rather than open.
    """
    if not token:
        return None, False

    from app.database import async_session
    from app.deps import authenticate_token

    try:
        async with async_session() as db:
            user = await authenticate_token(db, token)
        return str(user.id), True
    except Exception:
        # Covers JWTError, UnauthorizedError, ForbiddenError and DB failures.
        # A logger.debug (not exception) keeps forged-token probes out of the
        # traceback noise while still leaving a trace.
        logger.debug("WS token rejected")
        return None, True


def _get_token_from_request(websocket: WebSocket) -> str | None:
    """
    Extract auth token from cookie first (secure), then query param (fallback).

    Cookies are sent with the WebSocket handshake by every modern browser and
    are scoped to the host rather than the port, so the cookie path works for
    the web app on any origin pair the API already serves. The `?token=`
    fallback is disabled by default (`WS_ALLOW_QUERY_TOKEN=false`): a JWT in a
    URL lands in proxy access logs, browser history and Referer headers.
    """
    # HttpOnly cookie set by set_auth_cookies
    cookie_token = websocket.cookies.get("access_token")
    if cookie_token:
        return cookie_token
    from app.config import settings

    if not settings.ws_allow_query_token:
        # Not a warning: this is the default for every browser client, and a
        # probe with ?token= should leave only a debug trace.
        logger.debug("WS query-param token rejected (WS_ALLOW_QUERY_TOKEN is false)")
        return None
    return websocket.query_params.get("token")


@router.websocket("/ws/markets/{market_id}")
async def market_websocket(websocket: WebSocket, market_id: str):
    """
    Single multiplexed WebSocket connection per client.

    Auth: **optional**. A valid `access_token` cookie (or `?token=` when
    `WS_ALLOW_QUERY_TOKEN=true`) is validated in full and used for the
    per-user connection cap; without one the connection is anonymous.
    This is deliberate • the REST equivalents of everything pushed here
    (`/markets/{slug}/orderbook`, `/markets/{slug}/trades`) are public, and the
    only frames on this channel are public market events. Private frames
    (`notification`, `order:fill`) ride per-user Redis channels and are served
    by `/ws/notifications/{user_id}` alone.

    A token that *is* presented must still be valid • see
    `authenticate_ws_token`.

    On connect the client is subscribed to `market_id`.
    The client may then send:
      - {type: "subscribe", market_id: "..."}  • add a market subscription
      - {type: "unsubscribe", market_id: "..."} • remove a market subscription
      - {type: "ping"}                         • server replies {type: "pong"}

    The server enforces MAX_SUBSCRIPTIONS_PER_SOCKET (50) per connection, and
    MAX_CONNECTIONS_PER_IP (50) per IP whether or not the caller is signed in •
    which is what bounds an anonymous socket.
    """
    client_ip = _get_real_client_ip(websocket)
    token = _get_token_from_request(websocket)
    user_id, token_presented = await authenticate_ws_token(token)
    if token_presented and not user_id:
        await websocket.close(code=1008, reason="Invalid or expired token")
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
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # A malformed frame is the client's problem, not a reason to
                # tear down a socket that may be perfectly healthy. It used to
                # raise out of the loop and land in the generic `except`, which
                # disconnected the client and dropped every market it was
                # watching because of one bad byte.
                logger.debug("WS: dropped unparseable frame market=%s", market_id)
                continue
            if not isinstance(data, dict):
                logger.debug("WS: dropped non-object frame market=%s", market_id)
                continue

            # Any inbound traffic is proof of life. The heartbeat reaps on
            # silence past `PONG_TIMEOUT_S`, so this - not whether our next
            # write succeeds - is what keeps a healthy socket's lease renewed.
            manager.touch(websocket)

            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "pong":
                # Answer to a server heartbeat probe. Handled in the read loop
                # rather than ignored: without it the server has no way to tell a
                # half-open socket (laptop closed, NAT timeout - writes still
                # succeed, peer long gone) from a live one, and those sockets
                # leaked their per-user connection quota until the user was
                # permanently locked out of realtime.
                pass

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
        await manager.disconnect(websocket, redis_pubsub, cause="client")
        logger.info(f"WS disconnected: market={market_id}")
    except Exception:
        logger.exception(f"WS error: market={market_id}")
        await manager.disconnect(websocket, redis_pubsub, cause="error")


@router.websocket("/ws/trades")
async def global_trades_websocket(websocket: WebSocket):
    """Global trades feed • streams all new trades across the platform.

    Public, like `GET /trades` whose docstring calls itself a *"Public global
    feed"*. Auth is optional; a token that is presented must be valid.
    """
    client_ip = _get_real_client_ip(websocket)
    token = _get_token_from_request(websocket)
    user_id, token_presented = await authenticate_ws_token(token)
    if token_presented and not user_id:
        await websocket.close(code=1008, reason="Invalid or expired token")
        return

    accepted = await manager.connect(
        websocket, GLOBAL_TRADES_KEY, client_ip=client_ip, user_id=user_id
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
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("Global trades WS: dropped unparseable frame")
                continue
            manager.touch(websocket)
            if isinstance(data, dict) and data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await manager.disconnect(websocket, redis_pubsub, cause="client")
        # The global feed is subscribed by this route rather than by market id,
        # so `disconnect` skips it (it lives under the `__global_trades__`
        # sentinel key). Released here, and reference-counted like any other
        # channel, so the node stops being polled for a feed nobody is watching.
        await redis_pubsub.unsubscribe_global_trades()
        logger.info("Global trades WS disconnected")
    except Exception:
        logger.exception("Global trades WS error")
        await manager.disconnect(websocket, redis_pubsub, cause="error")
        try:
            await redis_pubsub.unsubscribe_global_trades()
        except Exception:
            pass


@router.websocket("/ws/notifications/{user_id}")
async def user_notifications_websocket(websocket: WebSocket, user_id: str):
    """User notification channel • **auth required**, token's uid must match.

    This is the only private surface: it serves `user:{uid}:notifications` and
    `user:{uid}:fills`, so an anonymous or mismatched caller is refused outright.
    """
    token = _get_token_from_request(websocket)
    authenticated_user_id, _presented = await authenticate_ws_token(token)
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
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("User WS: dropped unparseable frame")
                continue
            # Same liveness contract as the market socket: this is a long-lived
            # connection held open by users who left the tab open overnight, so
            # it is the most likely to be silently half-open.
            user_manager.touch(websocket)
            if isinstance(data, dict) and data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await user_manager.disconnect(websocket, user_id, cause="client")
        # Release the two private Redis channels. This never happened, so each
        # login permanently added two channels per worker for the life of the
        # process, all of them polled by `listen()` on every tick.
        await redis_pubsub.unsubscribe_user(user_id)
        logger.info(f"User WS disconnected: user={user_id}")
    except Exception:
        logger.exception(f"User WS error: user={user_id}")
        await user_manager.disconnect(websocket, user_id, cause="error")
        try:
            await redis_pubsub.unsubscribe_user(user_id)
        except Exception:
            pass
