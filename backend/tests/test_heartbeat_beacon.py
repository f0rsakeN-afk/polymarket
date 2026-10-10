"""Heartbeat beacons: the server tells the client where the stream actually is.

Pure client-side gap detection has a hole, and it is the same shape as the bug
this whole effort started from. A gap is only observable when a *later* frame
arrives to reveal it. So on a market that trades once and then goes quiet -
resolved, closed, or simply calm - frames lost in between are invisible forever:
the page renders pre-loss state, the indicator says "connected", and nothing ever
corrects it.

A time-based "it's been quiet, refetch anyway" heuristic would close the
symptom, but it fires on every genuinely healthy quiet market too, and it still
cannot tell "quiet" from "lost". The server already sees every frame it fans
out, so it can just say where it got to. That is exact, costs one small map on
a frame that is already being sent, and never guesses.

These tests pin the parts that can silently rot: the mark advancing, the beacon
reaching the socket, and the mark not outliving the market's presence.
"""

import asyncio

import pytest

from app.websocket.manager import ConnectionManager, user_manager


class _Sock:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_broadcast_records_the_sequence_high_water_mark():
    """The mark is what the beacon reports, so it must track real frames."""
    mgr = ConnectionManager()
    sock = _Sock()
    mgr._ws_subscriptions[sock] = {"m1"}  # type: ignore[index]
    mgr._market_subs["m1"].add(sock)  # type: ignore[arg-type]

    await mgr.broadcast_to_market("m1", {"type": "trade:new", "market_id": "m1", "seq": 7})
    assert mgr._last_seq["m1"] == 7

    # Monotonic: an out-of-order or replayed frame must not move it backwards,
    # or the beacon would tell a caught-up client it is behind.
    await mgr.broadcast_to_market("m1", {"type": "trade:new", "market_id": "m1", "seq": 3})
    assert mgr._last_seq["m1"] == 7


@pytest.mark.asyncio
async def test_frames_without_a_sequence_do_not_move_the_mark():
    """Unsequenced frames must not be mistaken for position."""
    mgr = ConnectionManager()
    sock = _Sock()
    mgr._ws_subscriptions[sock] = {"m1"}  # type: ignore[index]
    mgr._market_subs["m1"].add(sock)  # type: ignore[arg-type]

    await mgr.broadcast_to_market("m1", {"type": "comment:new", "market_id": "m1"})
    assert "m1" not in mgr._last_seq


@pytest.mark.asyncio
async def test_the_heartbeat_carries_the_snapshot_to_each_socket():
    """The client cannot detect a quiet-market loss any other way."""
    mgr = ConnectionManager()
    mgr.SEND_TIMEOUT_S = 1.0

    watched = _Sock()
    quiet = _Sock()
    mgr._ws_subscriptions[watched] = {"m1"}  # type: ignore[index]
    mgr._market_subs["m1"].add(watched)  # type: ignore[arg-type]
    mgr._ws_subscriptions[quiet] = {"m2"}  # type: ignore[index]
    mgr._market_subs["m2"].add(quiet)  # type: ignore[arg-type]

    # Only m1 has produced a frame. m2 has subscribers but no traffic yet.
    await mgr.broadcast_to_market("m1", {"type": "trade:new", "market_id": "m1", "seq": 42})
    mgr._ws_last_seen[watched] = asyncio.get_running_loop().time()  # type: ignore[index]
    mgr._ws_last_seen[quiet] = asyncio.get_running_loop().time()  # type: ignore[index]

    await mgr._ping_many([watched, quiet])

    watched_ping = next(p for p in watched.sent if p["type"] == "ping")
    quiet_ping = next(p for p in quiet.sent if p["type"] == "ping")

    assert watched_ping["seq"] == {"m1": 42}
    # Nothing has been fanned out for m2, so saying nothing is the honest
    # answer. Inventing a number here would tell the client it is behind when
    # it is merely early - a false alarm on every fresh subscription.
    assert "seq" not in quiet_ping


@pytest.mark.asyncio
async def test_the_beacon_omits_the_global_trades_sentinel():
    """`__global_trades__` is not a market and has no sequence."""
    mgr = ConnectionManager()
    sock = _Sock()
    mgr._ws_subscriptions[sock] = {"__global_trades__"}  # type: ignore[index]
    mgr._last_seq["__global_trades__"] = 99
    assert mgr.seq_snapshot(sock) == {}


@pytest.mark.asyncio
async def test_the_mark_does_not_outlive_the_last_subscriber():
    """Otherwise `_last_seq` grows by one entry per market the node ever served,
    for the life of the process - the same leak the market locks had."""
    mgr = ConnectionManager()
    sock = _Sock()
    mgr._ws_subscriptions[sock] = {"m1"}  # type: ignore[index]
    mgr._market_subs["m1"].add(sock)  # type: ignore[arg-type]
    mgr._last_seq["m1"] = 5

    class _Bus:
        async def unsubscribe_market(self, _market_id):
            return None

    await mgr.disconnect(sock, _Bus(), cause="client")

    assert "m1" not in mgr._last_seq
    assert "m1" not in mgr._market_subs


@pytest.mark.asyncio
async def test_the_reaper_releases_the_owners_channels_not_a_fallback():
    """A regression in the reaper itself, and one that failed invisibly.

    `disconnect` pops `_ws_to_user[ws]`, so reading the owner *after* calling it
    returns the fallback. The release then targeted `user::fills` /
    `user::notifications` - channels nobody acquired - while the real owner's
    count stayed elevated forever. The leak this release exists to prevent was
    therefore still present for every reaped notification socket, and since a
    reaped socket is precisely the one nobody notices, nothing reported it.
    """
    from app.websocket import manager as mgr_mod

    released: list[str] = []
    original = mgr_mod.RedisPubSub.unsubscribe_user

    async def spy(self, user_id):
        released.append(user_id)

    mgr_mod.RedisPubSub.unsubscribe_user = spy  # type: ignore[method-assign]

    class _HalfOpen:
        """Accepts every write - like a socket whose peer has vanished."""

        async def send_json(self, _payload):
            return None

    ws = _HalfOpen()
    user_manager._user_socks["owner-1"] = {ws}  # type: ignore[arg-type]
    user_manager._ws_to_user[ws] = "owner-1"  # type: ignore[index]
    user_manager._ws_last_seen[ws] = (  # type: ignore[index]
        asyncio.get_running_loop().time() - user_manager.PONG_TIMEOUT_S - 1
    )

    try:
        assert await user_manager.heartbeat_once() == 1
        assert released == ["owner-1"], (
            f"expected the owner's channels to be released, got {released}"
        )
    finally:
        mgr_mod.RedisPubSub.unsubscribe_user = original  # type: ignore[method-assign]
        user_manager._user_socks.clear()
        user_manager._ws_to_user.clear()
        user_manager._ws_last_seen.clear()