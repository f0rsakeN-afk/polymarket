"""Harnesses must speak the app's language, and be able to.

## The failure this comes from

Two separate problems, both of the same shape - a harness that looks like it is
proving something while it is not.

**1. Phase 5 and 7 of `load_realtime` were dead and nothing said so.** Adding the
double-accept guard made `ConnectionManager.connect` read `websocket.client_state`.
`_NullSock` - the harness's stand-in for a socket - had no such attribute, so both
phases raised `AttributeError` the moment they ran. Nothing runs this harness in
CI, and a phase that crashes looks exactly like a phase nobody needed. They had
been dead since the guard landed.

**2. Channel names were re-spelled per harness.** `scale_out.py` proves a frame
reaches another process's socket *by publishing to the exact channel that process
subscribes to*. Written out inline, the two spellings can drift, and then the
proof passes while demonstrating nothing - the frames it sent were the frames
nobody was listening for. That is the same silent-failure shape as (1), and it is
the third time the harnesses have failed this way.

The fixes are structural: `_NullSock` now models the socket state machine, and
every channel name has one definition in a dependency-free module the harnesses
import. These tests pin both, because both were invisible until someone ran the
thing by hand.
"""

import re
from pathlib import Path

import pytest

HARNESS_DIR = Path(__file__).resolve().parents[1] / "harness"


def _source(name: str) -> str:
    return (HARNESS_DIR / name).read_text()


# ── The socket double models what the managers read ───────────────────────────


@pytest.mark.asyncio
async def test_the_harness_socket_double_satisfies_connect():
    """The double must survive `connect()`, which reads `client_state`.

    This is the whole guard. Modelling only what the code happened to touch last
    time the double was written breaks the moment the code starts caring about
    something new - and it breaks as an `AttributeError` deep inside the manager,
    which reads like the manager being wrong rather than the double being stale.
    """
    from app.websocket.manager import ConnectionManager
    from harness.load_realtime import _NullSock

    ws = _NullSock()
    assert await ConnectionManager().connect(ws, "market-1") is True, (
        "the harness socket double no longer satisfies ConnectionManager.connect - "
        "load_realtime phases 5 and 7 will raise AttributeError"
    )


@pytest.mark.asyncio
async def test_the_harness_socket_double_is_refused_once_accepted():
    """The other half: the double has to be *rejectable*, or it tests nothing.

    A double that always succeeds would pass the burst phase while proving the
    guard does not fire.
    """
    from starlette.websockets import WebSocketState

    from app.websocket.manager import ConnectionManager
    from harness.load_realtime import _NullSock

    ws = _NullSock()
    manager = ConnectionManager()
    assert await manager.connect(ws, "market-1") is True

    ws.client_state = WebSocketState.CONNECTED
    assert await manager.connect(ws, "market-1") is False, (
        "the double cannot be put into a state the manager refuses, so a test "
        "using it would never exercise the double-accept guard"
    )


def test_the_harness_socket_double_exposes_what_send_json_needs():
    from harness.load_realtime import _NullSock

    ws = _NullSock()
    assert isinstance(ws.frames, list)
    # `send_json` is the only other thing every manager path calls.
    assert callable(ws.accept) and callable(ws.send_json)


# ── Channel names have exactly one definition ─────────────────────────────────


@pytest.mark.parametrize(
    "harness",
    ["load_realtime.py", "scale_out.py", "push_frame.py", "push_price.py", "bench_publish_queue.py"],
)
def test_no_harness_re_spells_a_channel_name(harness: str):
    """No harness may write a channel or key format out by hand.

    `f"market:{...}:events"` in a harness is a second definition of a wire
    contract. If it drifts from the app's, the harness publishes to a channel
    nobody subscribes to and reports success - a proof of delivery that delivers
    nothing.
    """
    offenders = re.findall(r'f"(?:market|user|global):\{', _source(harness))
    assert not offenders, (
        f"{harness} re-spells a channel name inline ({offenders}). Import it from "
        "app.websocket.channels instead."
    )


def test_the_channel_module_has_no_imports():
    """What makes it safe for a standalone harness to import.

    `scale_out.py` drives two real uvicorn subprocesses and deliberately does not
    import the application. A channel module that pulled in settings and Redis
    clients would force that choice.
    """
    import ast

    tree = ast.parse((HARNESS_DIR.parent / "app" / "websocket" / "channels.py").read_text())
    imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert not imports, (
        "app/websocket/channels.py must have no imports so harnesses can name "
        f"channels without pulling in the app; found {len(imports)}"
    )


def test_manager_still_re_exports_the_channel_names():
    """Existing imports must keep working, and must resolve to the one definition."""
    import app.websocket.channels as channels
    import app.websocket.manager as manager

    for name in (
        "GLOBAL_TRADES_CHANNEL",
        "WS_RESYNC",
        "market_events_channel",
        "market_seq_key",
        "user_fills_channel",
        "user_notifications_channel",
    ):
        assert getattr(manager, name) is getattr(channels, name), (
            f"{name} is defined twice - manager.py must re-export, not redefine"
        )


def test_no_inline_channel_formats_remain_in_the_manager():
    """Ten inline f-strings became two helper calls. This stops them creeping back."""
    source = (HARNESS_DIR.parent / "app" / "websocket" / "manager.py").read_text()
    offenders = re.findall(r'f"(?:market|user):\{[^}]*\}:(?:events|fills|notifications|seq)"', source)
    assert not offenders, (
        f"manager.py re-spells channel names inline: {offenders}. Use the helpers "
        "in app.websocket.channels."
    )


# ── The load phase measures something real ────────────────────────────────────


def test_the_burst_phase_does_not_enqueue_no_ops():
    """A load harness that measures a writer doing nothing reports a number
    nobody can act on.

    The old phase handed the queue a closure returning `None` and then printed
    the result as throughput. Worse, it divided the delivered count by the
    *enqueue* time only - the entire drain was excluded from the denominator - so
    the figure was inflated twice over: no real work, then divided by the wrong
    interval. It reported 176,424 frames/sec against a real end-to-end 5,496.
    """
    source = _source("load_realtime.py")
    assert "_make_noop" not in source, (
        "load_realtime.py still builds no-op publishes - the reported frames/sec "
        "would not be throughput"
    )
    assert "market_publish_op" in source, (
        "the burst phase must enqueue the app's own publish op, not a stand-in"
    )


def test_the_burst_phase_times_the_drain_not_just_the_enqueue():
    """The denominator must cover the work being reported.

    Captured before `wait_for`, a rate is `delivered / enqueue_time` - which
    excludes the entire drain and inflates the figure by however long the drain
    took. That is not a detail of this harness; it is the difference between a
    number and a decoration.
    """
    import inspect

    from harness import load_realtime

    lines = inspect.getsource(load_realtime.phase_publish_burst).split("\n")
    drain_line = max(
        (i for i, line in enumerate(lines) if "wait_for(" in line),
        default=-1,
    )
    assert drain_line > 0, "the phase must wait for the burst to drain"

    divisions = [
        i for i, line in enumerate(lines) if re.search(r"max\(\w*elapsed", line)
    ]
    assert divisions, "the phase must report a rate at all"
    for i in divisions:
        assert i > drain_line, (
            "frames/sec is divided by a timer read before the drain completed - "
            "that measures how fast frames were queued and labels it throughput"
        )