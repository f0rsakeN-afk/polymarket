"""Every route that calls a manager's `connect()` must honour its return value.

## The failure this came from

`UserConnectionManager.connect()` returns a bool, and its own docstring says "the
route needs it" - but `/ws/notifications/{user_id}` discarded it, while
`/ws/markets/{id}` and `/ws/trades` both checked it.

So when the guard added for the double-accept crash refused a socket, this route
carried straight on: it took a Redis subscription for a connection that did not
exist, then entered the read loop, whose first `receive_text()` raises

    RuntimeError: WebSocket is not connected. Need to call "accept" first.

That landed in the route's `except Exception` and logged a full traceback for a
rejection that was entirely routine - so the guard's own failure mode produced
exactly the class of noise the guard was added to stop, on the one surface where
it was not wired up.

The market and trades routes are asserted here too. They were already correct, and
a test covering only the path that was broken leaves the other two free to
regress the same way.
"""

from unittest.mock import AsyncMock, patch

import pytest
from conftest import token_for
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.app import app


@pytest.fixture
def pubsub():
    """Mock Redis pubsub, and hand it back so the assertions can inspect it.

    The unsubscribe halves matter as much as the subscribe halves: every endpoint
    releases its channels on disconnect, and a bare MagicMock is not awaitable, so
    an unstubbed release fails with a TypeError that looks nothing like the
    routing problem it is reporting.
    """
    with patch("app.websocket.routes.redis_pubsub") as mock:
        mock.subscribe_market = AsyncMock()
        mock.unsubscribe_market = AsyncMock()
        mock.subscribe_global_trades = AsyncMock()
        mock.unsubscribe_global_trades = AsyncMock()
        mock.subscribe_user = AsyncMock()
        mock.unsubscribe_user = AsyncMock()
        yield mock


@pytest.fixture
def ws_client(pubsub):
    return TestClient(app)


@pytest.fixture
def refused_connect():
    """Make the manager refuse, as the double-accept guard does."""
    started = []

    def _refuse(target: str):
        patcher = patch(target)
        m = patcher.start()
        started.append(patcher)
        m.connect = AsyncMock(return_value=False)
        return m

    yield _refuse
    for patcher in started:
        patcher.stop()


def test_a_rejected_user_socket_never_takes_a_redis_subscription(
    ws_client, test_user, pubsub, refused_connect
):
    """The specific bug: a refused connect still subscribed.

    Subscribing is not free and not harmless - `subscribe_user` is a shared
    per-user channel with a reference count, so a subscription taken for a socket
    that was never accepted has to be released by a route that is no longer
    running. That is how a user ends up with a channel nothing will ever
    unsubscribe.
    """
    refused_connect("app.websocket.routes.user_manager")
    token = token_for(test_user.id)

    # The refusal lands at the handshake, so the context manager entry itself
    # raises. `WebSocketDisconnect` is the correct outcome: the client is told,
    # rather than left waiting on an accept that never comes.
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect(f"/ws/notifications/{test_user.id}?token={token}"):
            pass

    pubsub.subscribe_user.assert_not_called()


def test_a_rejected_market_socket_never_takes_a_subscription(
    ws_client, pubsub, refused_connect
):
    """The market route already checked this - asserted so it stays that way."""
    refused_connect("app.websocket.routes.manager")

    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect("/ws/markets/abc"):
            pass

    pubsub.subscribe_market.assert_not_called()


def test_a_rejected_trades_socket_never_takes_a_subscription(
    ws_client, pubsub, refused_connect
):
    """Same again for the global trades feed."""
    refused_connect("app.websocket.routes.manager")

    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect("/ws/trades"):
            pass

    pubsub.subscribe_global_trades.assert_not_called()


def test_an_accepted_user_socket_still_subscribes_and_serves(
    ws_client, test_user, pubsub
):
    """The guard must not have broken the working path.

    A route that refused every connection would satisfy all three tests above
    while the product was completely broken, so the happy path is asserted too.
    """
    token = token_for(test_user.id)

    with ws_client.websocket_connect(
        f"/ws/notifications/{test_user.id}?token={token}"
    ) as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}

    pubsub.subscribe_user.assert_awaited_once_with(str(test_user.id))