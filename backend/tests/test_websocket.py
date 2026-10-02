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


def test_global_trades_websocket_rejects_anonymous(ws_client):
    """Every WS surface requires auth — an anonymous handshake is closed 1008."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with ws_client.websocket_connect("/ws/trades") as ws:
            ws.send_json({"type": "ping"})
            ws.receive_json()
    assert exc_info.value.code == 1008
    assert "Authentication required" in (exc_info.value.reason or "")


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
