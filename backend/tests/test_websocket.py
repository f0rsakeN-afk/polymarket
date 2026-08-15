"""Tests for WebSocket endpoints."""
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from starlette.testclient import TestClient

from app.deps import create_access_token


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _token(user_id: str) -> str:
    t, _ = create_access_token(str(user_id))
    return t


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

def test_market_websocket_connect_and_ping(ws_client, test_market):
    """WS connects, accepts, and responds to ping."""
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_market = AsyncMock()
        with ws_client.websocket_connect(f"/ws/markets/{test_market.id}") as ws:
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"


def test_market_websocket_reconnect_subscribes_different_market(ws_client, test_market):
    """Opening a WS to a different market subscribes to that market's channel."""
    new_market_id = str(uuid4())
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_market = AsyncMock()
        with ws_client.websocket_connect(f"/ws/markets/{new_market_id}") as ws:
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"
            mock_pubsub.subscribe_market.assert_called_once_with(new_market_id)


def test_market_websocket_disconnect(ws_client, test_market):
    """WS disconnects cleanly without error."""
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_market = AsyncMock()
        with ws_client.websocket_connect(f"/ws/markets/{test_market.id}") as ws:
            pass  # context exits cleanly


# ── Global Trades WebSocket ────────────────────────────────────────────────────

def test_global_trades_websocket_connect_and_ping(ws_client):
    """WS connects to global trades feed and responds to ping."""
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_global_trades = AsyncMock()
        with ws_client.websocket_connect("/ws/trades") as ws:
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"


# ── User Notifications WebSocket ───────────────────────────────────────────────

def test_user_notifications_websocket_valid_token(ws_client, test_user):
    """WS connects with valid token matching user_id."""
    token = _token(test_user.id)
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
    token = _token(test_user.id)
    wrong_user_id = str(uuid4())
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_user = AsyncMock()
        with pytest.raises(Exception):
            # Connection established but server immediately closes with auth error
            with ws_client.websocket_connect(
                f"/ws/notifications/{wrong_user_id}?token={token}"
            ) as ws:
                pass  # should not reach here


def test_user_notifications_websocket_invalid_token(ws_client, test_user):
    """WS rejects invalid token — server closes with 4001."""
    invalid_token = "invalid.token.here"
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_user = AsyncMock()
        with pytest.raises(Exception):
            with ws_client.websocket_connect(
                f"/ws/notifications/{test_user.id}?token={invalid_token}"
            ) as ws:
                pass  # should not reach here


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_market_websocket_unknown_message_type(ws_client, test_market):
    """Market WS ignores unknown message types without crashing."""
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_market = AsyncMock()
        with ws_client.websocket_connect(f"/ws/markets/{test_market.id}") as ws:
            ws.send_json({"type": "unknown_type", "data": "ignored"})
            # Should not raise — connection stays open
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"


def test_market_websocket_rapid_resubscribe(ws_client, test_market):
    """WS subscribe message switches market subscription without closing the connection."""
    new_market_id = str(uuid4())
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_market = AsyncMock()
        with ws_client.websocket_connect(f"/ws/markets/{test_market.id}") as ws:
            ws.send_json({"type": "subscribe", "market_id": new_market_id})
            ws.send_json({"type": "subscribe", "market_id": new_market_id})  # same market again — no-op
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"


def test_user_notifications_websocket_missing_token(ws_client, test_user):
    """WS with no token in query string closes connection."""
    with patch("app.websocket.routes.redis_pubsub") as mock_pubsub:
        mock_pubsub.subscribe_user = AsyncMock()
        # Missing token entirely — connection should be closed by server
        with pytest.raises(Exception):
            with ws_client.websocket_connect(f"/ws/notifications/{test_user.id}"):
                pass
