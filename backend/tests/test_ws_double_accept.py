"""No socket may be accepted twice.

## The failure this came from

The backend logged, outside any handler:

    RuntimeError: Expected ASGI message 'websocket.send' or 'websocket.close',
    but got 'websocket.accept'

from `UserConnectionManager.connect`. Reading Starlette, the mechanism is clear
and it is not a mystery:

`WebSocket.accept()` has **no guard**. It conditionally waits for the connect
message and then sends `websocket.accept` *unconditionally*:

    async def accept(self, subprotocol=None, headers=None):
        if self.client_state == WebSocketState.CONNECTING:
            await self.receive()
        await self.send({"type": "websocket.accept", ...})

Hand it a socket that has already been accepted, or closed, and the server
answers with exactly the message above. The connection dies with no close frame,
nothing is logged at route level, and the client sees an abrupt drop it cannot
explain.

Starlette's own `send()` would normally catch this on a single object, because it
tracks `application_state`. The production crash came from *uvicorn*, meaning the
socket object was no longer in `CONNECTING` while the transport had already
completed a handshake - so the defence has to live at the call site, which is
where it now does.

The market path (`ConnectionManager.connect`) had no check at all, and it is the
busier of the two.

These tests pin the guard rather than the symptom, because the symptom needs a
race to reproduce and the guard is a property of the code.
"""

import asyncio

import pytest
from starlette.websockets import WebSocket, WebSocketState

from app.websocket.manager import ConnectionManager, UserConnectionManager

SCOPE = {"type": "websocket", "path": "/ws/markets/x", "headers": []}


async def _make_connected(ws: WebSocket) -> None:
    """Consume the connect message, exactly as `accept()` would have.

    This is the state that matters: the handshake has been read, so Starlette
    will not wait again, but nothing has been accepted yet.
    """
    await ws.receive()
    assert ws.client_state is WebSocketState.CONNECTED

_SENT: list[str] = []


async def _record(message):
    _SENT.append(message["type"])


def _receiver():
    """One `websocket.connect`, then silence.

    The first message matters: Starlette's `accept()` calls `receive()` when the
    socket is still CONNECTING, and that is what moves `client_state`. A receiver
    that sleeps immediately would hang the test rather than model anything.
    """
    state = {"sent_connect": False}

    async def receive():
        if not state["sent_connect"]:
            state["sent_connect"] = True
            return {"type": "websocket.connect"}
        await asyncio.sleep(3600)
        return {"type": "websocket.disconnect", "code": 1006}

    return receive




@pytest.mark.asyncio
async def test_starlette_really_does_not_guard_accept():
    """The premise, asserted rather than assumed.

    If a future Starlette adds a guard, this test tells us the defence below is
    belt-and-braces instead of load-bearing - which is worth knowing. If it ever
    fails because Starlette started *raising* here instead, the guards in the
    managers become unnecessary and this is where that would show up.
    """
    sent: list[str] = []

    async def send(message):
        sent.append(message["type"])

    ws = WebSocket(SCOPE, _receiver(), send)
    await ws.accept()
    with pytest.raises(RuntimeError, match="websocket.accept"):
        await ws.accept()




@pytest.mark.asyncio
async def test_market_connect_refuses_an_already_connected_socket():
    manager = ConnectionManager()
    ws = WebSocket(SCOPE, _receiver(), _record)
    await _make_connected(ws)

    accepted = await manager.connect(ws, "market-x")

    assert accepted is False
    # Nothing may have been sent: the whole point is that no second accept goes
    # out, and a fake `send` that silently accepted everything would pass this
    # test while proving nothing.
    assert _SENT == []


@pytest.mark.asyncio
async def test_user_connect_refuses_an_already_connected_socket():
    manager = UserConnectionManager()
    ws = WebSocket(SCOPE, _receiver(), _record)
    await _make_connected(ws)

    accepted = await manager.connect(ws, "user-x")

    assert accepted is False
    assert _SENT == []


@pytest.fixture(autouse=True)
def _clear_sent():
    _SENT.clear()
    yield
    _SENT.clear()


@pytest.mark.asyncio
async def test_a_connecting_socket_is_still_accepted():
    """The guard must not reject a perfectly good socket.

    A guard that refuses everything would pass every test above while breaking
    the product, so the normal path is asserted too.
    """
    manager = UserConnectionManager()
    ws = WebSocket(SCOPE, _receiver(), _record)

    assert await manager.connect(ws, "user-ok") is True
    assert _SENT == ["websocket.accept"]
    assert ws in manager._ws_to_user