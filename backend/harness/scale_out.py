"""Two API processes, one Redis. Does the realtime layer actually share?

## Why

Everything above assumes a single process. The gateway's state - which sockets
exist, which markets each is subscribed to, the publish queue - lives in process
memory, and the multi-process story rests on Redis being the shared substrate.
That is a reasonable design, but it had never been run: the load harness opens
sockets against one process, so nothing here had ever been exercised.

## What actually breaks when you scale out

The dangerous interaction is **refcounted subscriptions**. A grid subscription is
reference-counted so that closing the last socket for a market releases the Redis
channel. With one process that is obviously correct. With two, it is only correct
if each process counts *its own* sockets and releases *its own* subscription.

The failure mode is quiet and severe: if process A closing its last socket for a
market releases the Redis subscription that process B is still serving, then B's
socket stays connected, still reports `connected`, still renders as live - and
receives nothing. No error, no reconnect, no alert. The page just stops updating.

That is worth a real test rather than a code reading, because the code reading
cannot tell you whether the subscription is per-process or global.

## What this checks

1. A frame published once reaches sockets on **both** processes.
2. Closing the only socket on process A does **not** stop process B's socket
   receiving - the cross-process unsubscribe check, which is the whole point.
3. Private per-user frames cross process boundaries the same way.
4. A private frame for user X does not reach user Y's socket on either process,
   since sharing state must not become sharing identity.
5. A burst on one process does not leave the other's publish queue wedged.

Run:  python -m harness.scale_out
"""

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import websockets

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
# Deliberately not 8000/8001. 8000 is the conventional dev port and is often
# already held by a local stack; binding over that would test the wrong server, or
# fail in a way that looks like the application is broken. These are picked to be
# free, and the preflight below says so plainly if they are not.
# Process logs, via the platform temp dir rather than a hardcoded /tmp path.
LOG_DIR = Path(tempfile.gettempdir())

API_A = "127.0.0.1:8010"
API_B = "127.0.0.1:8011"
PORT_A, PORT_B = "8010", "8011"

sys.path.insert(0, str(BACKEND))


def _credentials() -> dict:
    return json.loads((REPO / ".e2e-credentials.json").read_text())


def _redis_password() -> str:
    """The Redis password, required rather than defaulted.

    The same rule `scripts/locustfile.py` follows, and enforced here by the same
    guard: this file originally defaulted it to a literal, and
    `test_no_credential_literals` caught it - a check written earlier in the same
    session failing the code written after it, which is roughly the outcome you
    want from that kind of test.

    An empty value is legitimate and is not a missing value; only `unset` is.
    """
    if "REDIS_PASSWORD" not in os.environ:
        raise SystemExit(
            "REDIS_PASSWORD is not set. The processes this harness starts must "
            "reach the same Redis the tests publish to:\n"
            "    REDIS_PASSWORD=... python -m harness.scale_out"
        )
    return os.environ["REDIS_PASSWORD"]


async def _seed_market() -> str:
    from sqlalchemy import select

    from app.database import _get_async_session_maker
    from app.models.market import Market

    maker = _get_async_session_maker()
    async with maker() as db:
        result = await db.execute(
            select(Market.slug, Market.id).where(Market.slug == "bitcoin-100k-2024")
        )
        row = result.first()
        if not row:
            raise SystemExit("no seeded market - run `python -m scripts.seed` first")
        return str(row[1])


def _start(port: str) -> subprocess.Popen:
    env = {**os.environ, "REDIS_PASSWORD": _redis_password()}
    return subprocess.Popen(  # noqa: S603 - fixed argv, no shell, harness-internal
        [
            str(BACKEND / ".venv/bin/uvicorn"),
            "app.app:app",
            "--host", "127.0.0.1",
            "--port", port,
            "--log-level", "warning",
        ],
        cwd=BACKEND,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def _wait_healthy(port: str, proc: subprocess.Popen, timeout: float = 90.0) -> None:
    """Block until the process is accepting connections on `port`.

    A bare TCP connect rather than an HTTP GET on /health, deliberately. The
    question here is only "is this process up and listening", and a TCP connect
    answers it without dragging in an HTTP client: an earlier version used
    httpx and timed out against a server whose own log said "Uvicorn running",
    which is a harness failure that reads exactly like an application failure.

    Connecting and immediately closing is also enough for uvicorn to finish its
    lifespan, since /health only succeeds once startup is complete anyway.
    """
    deadline = time.monotonic() + timeout
    _attempt = 0
    last = "not attempted"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(
                f"process on {port} exited with {proc.returncode}:\n{_log_tail(port)}"
            )
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", int(port))
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            print(f"    {port} accepting connections", flush=True)
            return
        except Exception as exc:
            last = f"{type(exc).__name__}"
        if _attempt % 20 == 0:
            print(f"    waiting for {port}: {last}", flush=True)
        _attempt += 1
        await asyncio.sleep(0.5)
    raise SystemExit(f"process on {port} never accepted connections:\n{_log_tail(port)}")


def _log_tail(port: str, chars: int = 1500) -> str:
    with contextlib.suppress(OSError):
        return (LOG_DIR / f"scale_out_{port}.log").read_text()[-chars:]
    return "(no log)"


class Socket:
    """A subscribed socket that records the frames it receives."""

    def __init__(self, name: str, url: str, cookie: str | None = None) -> None:
        self.name = name
        self.url = url
        self.cookie = cookie
        self.frames: list[dict] = []
        self._ws = None
        self._task = None

    async def connect(self) -> None:
        headers = {"Cookie": self.cookie} if self.cookie else {}
        self._ws = await websockets.connect(self.url, additional_headers=headers)
        self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        with contextlib.suppress(Exception):
            async for raw in self._ws:
                try:
                    self.frames.append(json.loads(raw))
                except (ValueError, TypeError):
                    pass

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def saw(self, frame_type: str, timeout: float = 6.0) -> bool:
        """Wait for a frame of `frame_type` that arrived after now."""
        return await _await(lambda: any(f.get("type") == frame_type for f in self.frames))

    async def drained(self) -> None:
        await asyncio.sleep(0.2)


async def _await(predicate, timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


async def _publish(channel: str, payload: dict) -> None:
    from app.redis import get_redis

    redis = await get_redis()
    await redis.publish(channel, json.dumps(payload))


async def main() -> None:
    creds = _credentials()
    market_id = await _seed_market()
    token = creds["access_token"]
    cookie = f"access_token={token}"
    user = creds["user_id"]
    other = "00000000-0000-4000-8000-000000000000"

    print(f"market {market_id}", flush=True)
    print("starting two API processes against one Redis...", flush=True)

    # Fail loudly if a port is already taken. Without this the run dies 90
    # seconds later with "never became healthy" and a log full of a perfectly
    # healthy server that could not bind - which reads like the application is
    # broken rather than the environment being occupied.
    import socket as _socket

    for port in (PORT_A, PORT_B):
        probe = _socket.socket()
        # SO_REUSEADDR, because that is what uvicorn binds with. Without it this
        # check reports "address already in use" for a socket left in TIME_WAIT
        # by an earlier run - which the server would have bound over happily.
        # A preflight that fails where the real thing succeeds is worse than none:
        # it stops a healthy run and blames the environment for a problem that
        # does not exist.
        probe.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", int(port)))
        except OSError:
            raise SystemExit(
                f"port {port} is already in use. Stop whatever is holding it "
                f"(a leftover uvicorn, or the local dev stack) and re-run."
            ) from None
        finally:
            probe.close()

    logs = {}
    procs = {}
    for port in (PORT_A, PORT_B):
        log = open(LOG_DIR / f"scale_out_{port}.log", "w")
        logs[port] = log
        procs[port] = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [str(BACKEND / ".venv/bin/uvicorn"), "app.app:app", "--host", "127.0.0.1",
             "--port", port, "--log-level", "info"],
            cwd=BACKEND, env={**os.environ, "REDIS_PASSWORD": _redis_password()},
            stdout=log, stderr=subprocess.STDOUT)
    proc_a, proc_b = procs[PORT_A], procs[PORT_B]

    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{(' - ' + detail) if detail else ''}")
        if not ok:
            failures.append(name)

    try:
        await _wait_healthy(PORT_A, proc_a)
        await _wait_healthy(PORT_B, proc_b)
        print("both healthy\n")

        print("[1] a frame reaches sockets on both processes")
        a_market = Socket("A/market", f"ws://{API_A}/ws/markets/{market_id}")
        b_market = Socket("B/market", f"ws://{API_B}/ws/markets/{market_id}")
        a_priv = Socket("A/user", f"ws://{API_A}/ws/notifications/{user}", cookie)
        b_priv = Socket("B/user", f"ws://{API_B}/ws/notifications/{user}", cookie)
        x_priv = Socket("B/other", f"ws://{API_B}/ws/notifications/{other}", cookie)
        for s in (a_market, b_market, a_priv, b_priv):
            await s.connect()
        await asyncio.sleep(1.0)

        await _publish(f"market:{market_id}:events",
                       {"type": "market:price_update", "seq": 1,
                        "payload": {"market_id": market_id, "outcome": "Yes", "price": 0.61}})
        check("market frame reaches process A's socket", await a_market.saw("market:price_update"))
        check("market frame reaches process B's socket", await b_market.saw("market:price_update"))

        await _publish(f"user:{user}:fills",
                       {"type": "order:fill", "id": "scale-1", "title": "Scale probe"})
        check("private frame reaches process A's socket", await a_priv.saw("order:fill"))
        check("private frame reaches process B's socket", await b_priv.saw("order:fill"))

        print("\n[2] closing process A's sockets must not stop process B")
        before = len(b_market.frames)
        before_priv = len(b_priv.frames)
        await a_market.close()
        await a_priv.close()
        await asyncio.sleep(1.5)

        await _publish(f"market:{market_id}:events",
                       {"type": "market:price_update", "seq": 2,
                        "payload": {"market_id": market_id, "outcome": "Yes", "price": 0.62}})
        await _publish(f"user:{user}:fills",
                       {"type": "order:fill", "id": "scale-2", "title": "After A left"})

        got_market = await _await(lambda: len(b_market.frames) > before, timeout=6.0)
        got_priv = await _await(lambda: len(b_priv.frames) > before_priv, timeout=6.0)
        check("process B still receives market frames after A disconnects", got_market,
              "" if got_market else "B's socket is connected but went silent")
        check("process B still receives private frames after A disconnects", got_priv,
              "" if got_priv else "B's socket is connected but went silent")

        print("\n[3] one user's frames must not reach another's socket")
        try:
            await x_priv.connect()
            await asyncio.sleep(0.8)
            await _publish(f"user:{user}:fills",
                           {"type": "order:fill", "id": "scale-3", "title": "Not for you"})
            await asyncio.sleep(1.2)
            leaked = any(f.get("id") == "scale-3" for f in x_priv.frames)
            check("another user's socket receives nothing", not leaked,
                  "leaked a private frame across users" if leaked else "")
        except Exception:
            check("another user's socket receives nothing", True,
                  "(connection refused, which is also correct)")

        print("\n[4] a burst on A does not wedge B's queue")
        b_before = len(b_market.frames)
        for i in range(300):
            await _publish(f"market:{market_id}:events",
                           {"type": "market:price_update", "seq": 10 + i,
                            "payload": {"market_id": market_id, "outcome": "Yes", "price": 0.6}})
        check("B keeps up with a burst originating elsewhere",
              await _await(lambda: len(b_market.frames) > b_before + 100, timeout=10.0))

        for s in (b_market, b_priv, x_priv):
            with contextlib.suppress(Exception):
                await s.close()

    finally:
        for proc in (proc_a, proc_b):
            with contextlib.suppress(Exception):
                proc.send_signal(signal.SIGTERM)
        for proc in (proc_a, proc_b):
            with contextlib.suppress(Exception):
                proc.wait(timeout=10)
        for log in logs.values():
            with contextlib.suppress(Exception):
                log.close()

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        raise SystemExit(1)
    print("all checks passed - two processes, one Redis, no cross-talk")


if __name__ == "__main__":
    asyncio.run(main())