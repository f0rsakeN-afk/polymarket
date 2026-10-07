"""Tests for WebSocket endpoints."""
import time
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from conftest import token_for
from starlette.testclient import TestClient

# ── Helpers ─────────────────────────────────────────────────────────────────────

# ── WS client fixture ──────────────────────────────────────────────────────────

@pytest.fixture
def ws_client():
    """Synchronous WS client using starlette.testclient (deprecated with httpx but works)."""
    from app.app import app
    # Mock redis_pubsub at module level before the client connects
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_market = AsyncMock()
        mock_pubsub.subscribe_global_trades = AsyncMock()
        mock_pubsub.subscribe_user = AsyncMock()
        yield TestClient(app)


# ── Market WebSocket ──────────────────────────────────────────────────────────

def test_market_websocket_connect_and_ping(ws_client, test_market, test_user):
    """WS connects, accepts, and responds to ping."""
    token = token_for(test_user.id)
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_market = AsyncMock()
        mock_pubsub.unsubscribe_market = AsyncMock()
        with ws_client.websocket_connect(f"/ws/markets/{test_market.id}?token={token}") as ws:
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"


def test_market_websocket_reconnect_subscribes_different_market(ws_client, test_market, test_user):
    """Opening a WS to a different market subscribes to that market's channel."""
    new_market_id = str(uuid4())
    token = token_for(test_user.id)
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_market = AsyncMock()
        mock_pubsub.unsubscribe_market = AsyncMock()
        with ws_client.websocket_connect(f"/ws/markets/{new_market_id}?token={token}") as ws:
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"
            mock_pubsub.subscribe_market.assert_called_once_with(new_market_id)


def test_market_websocket_disconnect(ws_client, test_market, test_user):
    """WS disconnects cleanly without error."""
    token = token_for(test_user.id)
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_market = AsyncMock()
        mock_pubsub.unsubscribe_market = AsyncMock()
        with ws_client.websocket_connect(f"/ws/markets/{test_market.id}?token={token}") as _ws:
            pass  # context exits cleanly


# ── Global Trades WebSocket ────────────────────────────────────────────────────

def test_global_trades_websocket_connect_and_ping(ws_client, test_user):
    """WS connects to the authenticated global trades feed and responds to ping."""
    token = token_for(test_user.id)
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_global_trades = AsyncMock()
        mock_pubsub.unsubscribe_global_trades = AsyncMock()
        with ws_client.websocket_connect(f"/ws/trades?token={token}") as ws:
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"


def test_global_trades_websocket_is_public(ws_client):
    """The trades feed is public — like `GET /trades`, whose docstring says so.

    Gating it behind a login meant a logged-out visitor could read recent trades
    over HTTP but got a 403 on the live ones, and the client then re-opened the
    refused socket on every backoff tick.
    """
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_global_trades = AsyncMock()
        with ws_client.websocket_connect("/ws/trades") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
        mock_pubsub.subscribe_global_trades.assert_called_once()


def test_market_websocket_is_public(ws_client, test_market):
    """`/ws/markets/{id}` is public too — its REST twins need no auth either."""
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_market = AsyncMock()
        mock_pubsub.unsubscribe_market = AsyncMock()
        with ws_client.websocket_connect(f"/ws/markets/{test_market.id}") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
        mock_pubsub.subscribe_market.assert_called_once_with(str(test_market.id))


def test_market_websocket_still_rejects_an_invalid_token(ws_client, test_market):
    """Public does not mean unauthenticated: a *presented* token must be valid.

    Otherwise a revoked or logged-out session would silently continue as an
    anonymous one and revoking it would stop meaning anything on these sockets.
    """
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with ws_client.websocket_connect(f"/ws/markets/{test_market.id}?token=not-a-jwt"):
            pass
    assert exc_info.value.code == 1008


# ── User Notifications WebSocket ───────────────────────────────────────────────

def test_user_notifications_websocket_validtoken_for(ws_client, test_user):
    """WS connects with valid token matching user_id."""
    token = token_for(test_user.id)
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_user = AsyncMock()
        with ws_client.websocket_connect(
            f"/ws/notifications/{test_user.id}?token={token}"
        ) as ws:
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"


def test_user_notifications_websocket_rejects_anonymous(ws_client, test_user):
    """The personal feed stays private — no token at all means no delivery.

    This is the one surface that must not be public: it serves
    `user:{uid}:notifications` and `user:{uid}:fills`.
    """
    from starlette.websockets import WebSocketDisconnect

    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_user = AsyncMock()
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with ws_client.websocket_connect(f"/ws/notifications/{test_user.id}"):
                pass
    assert exc_info.value.code == 4001


def test_user_notifications_websocket_wrong_user_id(ws_client, test_user):
    """WS rejects token that doesn't match user_id in path — server closes with 4001."""
    token = token_for(test_user.id)
    wrong_user_id = str(uuid4())
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_user = AsyncMock()
        with pytest.raises(Exception):
            # Connection established but server immediately closes with auth error
            with ws_client.websocket_connect(
                f"/ws/notifications/{wrong_user_id}?token={token}"
            ) as _ws:
                pass  # should not reach here


def test_user_notifications_websocket_invalidtoken_for(ws_client, test_user):
    """WS rejects invalid token — server closes with 4001."""
    invalid_token = "invalid.token.here"
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_user = AsyncMock()
        with pytest.raises(Exception):
            with ws_client.websocket_connect(
                f"/ws/notifications/{test_user.id}?token={invalid_token}"
            ) as _ws:
                pass  # should not reach here


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_market_websocket_unknown_message_type(ws_client, test_market, test_user):
    """Market WS ignores unknown message types without crashing."""
    token = token_for(test_user.id)
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_market = AsyncMock()
        mock_pubsub.unsubscribe_market = AsyncMock()
        with ws_client.websocket_connect(f"/ws/markets/{test_market.id}?token={token}") as ws:
            ws.send_json({"type": "unknown_type", "data": "ignored"})
            # Should not raise — connection stays open
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"


def test_market_websocket_rapid_resubscribe(ws_client, test_market, test_user):
    """WS subscribe message switches market subscription without closing the connection."""
    new_market_id = str(uuid4())
    token = token_for(test_user.id)
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_market = AsyncMock()
        mock_pubsub.unsubscribe_market = AsyncMock()
        with ws_client.websocket_connect(f"/ws/markets/{test_market.id}?token={token}") as ws:
            ws.send_json({"type": "subscribe", "market_id": new_market_id})
            # Wait briefly for server to process the subscription switch
            time.sleep(0.05)
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"
            # Verify the new market was subscribed
            mock_pubsub.subscribe_market.assert_called_with(new_market_id)


def test_user_notifications_websocket_missingtoken_for(ws_client, test_user):
    """WS with no token in query string closes connection."""
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_user = AsyncMock()
        # Missing token entirely — connection should be closed by server
        with pytest.raises(Exception):
            with ws_client.websocket_connect(f"/ws/notifications/{test_user.id}"):
                pass


# ── Heartbeat sweep ────────────────────────────────────────────────────────────
#
# These exist because `_cleanup_dead` shipped as dead code: the docstring said
# "kept for periodic sweeps only" and nothing ever scheduled a sweep. A
# half-open socket (closed laptop, NAT timeout, killed container) therefore was
# never reaped — it kept its file descriptor and its per-IP counter slot, and
# broadcast-failure detection never saw it because a quiet market never
# broadcasts. The regression to guard is "the sweep is wired up and called".

def test_heartbeat_reaps_a_socket_whose_send_hangs():
    """A socket that can't accept a ping within SEND_TIMEOUT_S is disconnected."""
    import asyncio

    from app.websocket.manager import ConnectionManager

    mgr = ConnectionManager()
    reaped = []

    class WedgedSocket:
        """Stands in for a half-open socket: send_json never completes."""

        async def send_json(self, _event):
            await asyncio.sleep(60)  # never resolves within the timeout

    sock = WedgedSocket()  # type: ignore[arg-type]
    mgr._ws_subscriptions[sock] = {  # type: ignore[index]
        "00000000-0000-0000-0000-000000000001"
    }
    mgr._ws_ip[sock] = "10.0.0.1"  # type: ignore[index]
    mgr._market_subs["00000000-0000-0000-0000-000000000001"].add(sock)  # type: ignore[arg-type]

    # Record the disconnect instead of running the real one, so this asserts the
    # decision rather than the counter bookkeeping.
    async def fake_disconnect(ws, redis_pubsub_ref=None, cause="client"):
        reaped.append((ws, cause))

    mgr.disconnect = fake_disconnect  # type: ignore[method-assign]

    # Keep the sweep fast; the production interval is 30s.
    mgr.SEND_TIMEOUT_S = 0.05
    count = asyncio.run(mgr.heartbeat_once())

    assert count == 1, "the wedged socket should have been reaped"
    assert len(reaped) == 1
    assert reaped[0][1] == "heartbeat", "cause must be labelled so the metric is useful"


def test_heartbeat_leaves_a_healthy_socket_alone():
    """A socket that answers a ping is NOT disconnected — no false positives."""
    import asyncio

    from app.websocket.manager import ConnectionManager

    mgr = ConnectionManager()
    reaped = []

    class HealthySocket:
        async def send_json(self, _event):
            return None

    sock = HealthySocket()  # type: ignore[arg-type]
    mgr._ws_subscriptions[sock] = {  # type: ignore[index]
        "00000000-0000-0000-0000-000000000002"
    }
    mgr._market_subs["00000000-0000-0000-0000-000000000002"].add(sock)  # type: ignore[arg-type]

    async def fake_disconnect(ws, redis_pubsub_ref=None, cause="client"):
        reaped.append(ws)

    mgr.disconnect = fake_disconnect  # type: ignore[method-assign]

    count = asyncio.run(mgr.heartbeat_once())

    assert count == 0, "a responsive socket must survive the sweep"
    assert reaped == [], "no socket should be disconnected"


def test_heartbeat_loop_is_started_by_the_app_lifespan():
    """The sweep must be *scheduled*. This is the exact regression: the method
    existed and worked, and was still never called."""
    import inspect

    from app import app as app_module

    src = inspect.getsource(app_module)
    assert "heartbeat_loop()" in src, "app lifespan must start the heartbeat sweep"
    assert "heartbeat_task.cancel()" in src, "the sweep must be cancelled on shutdown"
