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

Hand it a socket that has already been accepted, or closed, and `send()` refuses
it: at `application_state == CONNECTED` the only legal messages are
`websocket.send` and `websocket.close`, so the second `accept` raises the error
above. The connection dies with no close frame, and the client sees an abrupt
drop it cannot explain.

## Two corrections to what this file previously claimed

Both claims below were wrong, and both pointed the investigation away from the
answer. They are recorded because the wrong story is more dangerous than no
story: it reads like a finding.

1. **"The production crash came from uvicorn."** It does not. The exact error
   reproduces on a bare in-process `WebSocket` with a stub `send` - no server, no
   transport, no asyncio task involved. `test_the_error_needs_no_server` asserts
   that, so the claim cannot come back.
2. **"`accept()` fails silently."** It does not. It sends `websocket.accept`
   unconditionally and `send()` *raises*. The failure was never silent; it was
   just unlabelled.

## What is actually known about the trigger

The app has exactly two `accept()` call sites and three route callers, each
calling `connect()` once per socket - so today's code cannot reach this state on
its own. Either the trigger came from a path that has since changed, or two
coroutines reached one socket concurrently. Which is why the skip counter is split
by state: if it fires again, the state tells you which of those it was.
"""

import asyncio

import pytest
from starlette.websockets import WebSocket, WebSocketState

from app.middleware.metrics import WS_CONNECTS_TOTAL
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


@pytest.mark.asyncio
async def test_the_error_needs_no_server():
    """The production error reproduces with no uvicorn, no transport, no server.

    This pins the correction to the original explanation, which claimed the crash
    "came from uvicorn" because the transport had completed a handshake behind
    Starlette's back. It did not - `send()` refuses the message on a plain
    in-process object. Without this, that story looks plausible again and sends
    the next person looking at the gateway.
    """
    sent: list[str] = []

    async def send(message):
        sent.append(message["type"])

    ws = WebSocket(SCOPE, _receiver(), send)
    await ws.accept()

    with pytest.raises(RuntimeError) as exc:
        await ws.accept()

    assert str(exc.value) == (
        "Expected ASGI message \"websocket.send\" or \"websocket.close\", "
        "but got 'websocket.accept'"
    ), "the error text changed - re-check the explanation in this file's docstring"
    # One accept went out, the second never did.
    assert sent == ["websocket.accept"]


@pytest.mark.asyncio
async def test_the_skip_counter_distinguishes_the_two_states():
    """`skipped_connected` and `skipped_disconnected` are different bugs.

    A single combined counter - which is what shipped first - cannot tell an
    operator whether something is accepting twice or whether we accepted a socket
    that had already gone. An alert built on the combined counter cannot answer
    the only question it exists to answer.
    """
    from app.middleware.metrics import WS_CONNECTS_TOTAL

    manager = ConnectionManager()
    ws = WebSocket(SCOPE, _receiver(), _record)
    await _make_connected(ws)

    before_connected = WS_CONNECTS_TOTAL.labels("skipped_connected")._value.get()
    before_disconnected = WS_CONNECTS_TOTAL.labels("skipped_disconnected")._value.get()

    assert await manager.connect(ws, "market-x") is False

    assert WS_CONNECTS_TOTAL.labels("skipped_connected")._value.get() == before_connected + 1
    assert (
        WS_CONNECTS_TOTAL.labels("skipped_disconnected")._value.get() == before_disconnected
    ), "an already-accepted socket must not be counted as a closed one"


@pytest.mark.asyncio
async def test_a_closed_socket_is_counted_separately_from_an_accepted_one():
    ws = WebSocket(SCOPE, _receiver(), _record)
    await _make_connected(ws)
    ws.application_state = WebSocketState.DISCONNECTED
    ws.client_state = WebSocketState.DISCONNECTED

    manager = ConnectionManager()
    before = WS_CONNECTS_TOTAL.labels("skipped_disconnected")._value.get()

    assert await manager.connect(ws, "market-x") is False

    assert WS_CONNECTS_TOTAL.labels("skipped_disconnected")._value.get() == before + 1


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