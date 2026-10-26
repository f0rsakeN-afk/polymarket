"""The sequencer, verified against a real Redis rather than a fake.

Every other test in the realtime suite substitutes its own publish logic, so
none of them actually execute `_SEQ_AND_PUBLISH_LUA`. That left the single most
load-bearing new piece of code - the thing every gap-detection guarantee rests on
- unverified until it ran against a real server.

Two properties matter and only one of them is obvious:

  1. `seq` must land in the frame as a JSON **number**. `tostring()` in Lua
     yields a string, so a naive `string.gsub(ARGV[1], '__SEQ__', ...)` produces
     `"seq": "7"`. Every client's `typeof seq === "number"` guard then rejects it
     and gap detection silently never fires - it looks wired up and does nothing.
  2. Allocation and publish must be **atomic**, or concurrent orders interleave.
     The naive alternative - `INCR`, then `PUBLISH` - is exactly the shape that
     lets publisher B (holding seq 2) deliver before publisher A (holding seq 1),
     which a gap-detecting client cannot distinguish from real packet loss.

Skipped when Redis is unreachable so the suite still runs in isolation.
"""

import asyncio
import json
from collections import defaultdict

import pytest

from app.websocket.manager import _SEQ_AND_PUBLISH_LUA

pytestmark = pytest.mark.asyncio


async def collect(pubsub, expected: int, timeout_s: float = 5.0):
    """Read exactly `expected` real frames.

    Deliberately does not stop at the first `None`: `get_message` spends one call
    per buffered subscribe-ack and returns `None` for it, so a drain that breaks
    on `None` reads acknowledgements and nothing else. The production listener
    spins on `None`, which is why this quirk only bites a test harness - and why
    it is worth spelling out rather than rediscovering later.
    """
    out = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while len(out) < expected and loop.time() < deadline:
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        if msg and msg["type"] == "message":
            out.append((msg["channel"], msg["data"]))
    return out


@pytest.fixture
async def real_redis():
    """A Redis client on the test database, or skip.

    A *dedicated* client, not the application's shared pool. This test drives
    200 concurrent commands, which the app's production pool size is not meant to
    absorb - hitting `MaxConnectionsError` here would say nothing about the
    sequencer, only about the test borrowing a pool it should not.
    """
    import redis.asyncio as aioredis

    from app.config import settings

    try:
        client = aioredis.Redis.from_url(
            settings.redis_url, decode_responses=True, max_connections=400
        )
        await client.ping()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Redis unavailable: {exc}")

    yield client
    try:
        await client.flushdb()
        await client.aclose()
    except Exception:
        pass


async def test_seq_is_spliced_in_as_a_json_number(real_redis):
    """A stringified `seq` is silently ignored by every client."""
    ps = real_redis.pubsub()
    await ps.subscribe("seqtest:type")
    await asyncio.sleep(0.2)

    await real_redis.eval(
        _SEQ_AND_PUBLISH_LUA,
        2,
        "seqtest:key",
        "seqtest:type",
        json.dumps({"type": "trade:new", "seq": "__SEQ__"}),
    )
    frames = await collect(ps, 1)

    assert frames, "nothing was published"
    payload = json.loads(frames[0][1])
    assert payload["seq"] == 1
    assert isinstance(payload["seq"], int), (
        "seq must be a JSON number. A quoted string passes a naive test and "
        "then fails every client's numeric check, disabling gap detection."
    )
    await ps.unsubscribe("seqtest:type")
    await ps.aclose()


async def test_sequence_is_monotonic_per_channel_under_concurrency(real_redis):
    """200 interleaved publishes must arrive in strict order, per market.

    This is the property the Lua exists for. Allocation and publish in separate
    round-trips let a publisher holding a higher seq deliver first, and a client
    reading seq 4 then seq 2 sees a reordering it cannot tell from loss - so it
    resyncs on every busy tick, or worse, trusts a book that contradicts the
    price rendered beside it.
    """
    channels = [f"seqtest:mon{i}" for i in range(4)]
    per_channel = 50
    ps = real_redis.pubsub()
    await ps.subscribe(*channels)
    await asyncio.sleep(0.3)

    await asyncio.gather(
        *[
            real_redis.eval(
                _SEQ_AND_PUBLISH_LUA,
                2,
                f"seqtest:counter:{ch}",
                ch,
                json.dumps({"seq": "__SEQ__"}),
            )
            for ch in channels
            for _ in range(per_channel)
        ]
    )

    frames = await collect(ps, len(channels) * per_channel, timeout_s=10.0)
    assert len(frames) == len(channels) * per_channel, (
        f"expected {len(channels) * per_channel} frames, got {len(frames)}"
    )

    by_channel = defaultdict(list)
    for channel, raw in frames:
        by_channel[channel].append(json.loads(raw)["seq"])

    for ch in channels:
        seqs = by_channel[ch]
        assert len(seqs) == per_channel
        assert len(set(seqs)) == per_channel, f"{ch}: duplicate sequence numbers"
        assert all(seqs[i] < seqs[i + 1] for i in range(len(seqs) - 1)), (
            f"{ch}: frames arrived out of order - allocate+publish is not atomic"
        )

    await ps.unsubscribe(*channels)
    await ps.aclose()


async def test_the_naive_alternative_really_does_reorder(real_redis):
    """Why the Lua exists - demonstrated, so nobody 'simplifies' it back.

    Orchestrated rather than raced. Letting 60 coroutines fight it out and
    asserting a reorder *happened* is a coin flip that passes on a fast machine
    and flakes on a loaded CI box. Here the interleaving is forced: A allocates,
    B allocates and publishes, then A publishes. That is precisely the window a
    two-command implementation leaves open, and it reorders every time.
    """
    ps = real_redis.pubsub()
    await ps.subscribe("seqtest:naive")
    await asyncio.sleep(0.3)
    await real_redis.delete("seqtest:naive-counter")

    # A allocates its number...
    seq_a = await real_redis.incr("seqtest:naive-counter")
    # ...B allocates and publishes while A is still holding its number...
    seq_b = await real_redis.incr("seqtest:naive-counter")
    await real_redis.publish("seqtest:naive", json.dumps({"seq": seq_b}))
    # ...and only now does A publish.
    await real_redis.publish("seqtest:naive", json.dumps({"seq": seq_a}))

    frames = await collect(ps, 2, timeout_s=5.0)
    seqs = [json.loads(raw)["seq"] for _, raw in frames]

    assert len(seqs) == 2
    assert seq_a == 1 and seq_b == 2, "both allocations should have succeeded"
    assert seqs == [2, 1], (
        "the two-command version delivered seq 2 before seq 1. This is exactly "
        "the reordering a gap-detecting client cannot distinguish from packet "
        "loss - so it would resync on every busy tick. The Lua script exists to "
        "close exactly this window."
    )

    await ps.unsubscribe("seqtest:naive")
    await ps.aclose()


async def test_the_sequenced_publish_cannot_reorder_that_window(real_redis):
    """Same forced interleaving, same two publishers, one command.

    The counterpart to the test above: proves the fix does not merely make
    reordering *less likely* but makes it structurally impossible, because no
    publisher can observe a number without also publishing it.
    """
    ps = real_redis.pubsub()
    channel = "seqtest:atomic"
    await ps.subscribe(channel)
    await asyncio.sleep(0.3)
    await real_redis.delete("seqtest:atomic-counter")

    async def publish(_):
        # One command: no coroutine can interleave between allocate and publish.
        await real_redis.eval(
            _SEQ_AND_PUBLISH_LUA,
            2,
            "seqtest:atomic-counter",
            channel,
            json.dumps({"seq": "__SEQ__"}),
        )

    await asyncio.gather(*[publish(i) for i in range(60)])
    frames = await collect(ps, 60, timeout_s=10.0)
    seqs = [json.loads(raw)["seq"] for _, raw in frames]

    assert len(seqs) == 60
    assert all(seqs[i] < seqs[i + 1] for i in range(len(seqs) - 1))

    await ps.unsubscribe(channel)
    await ps.aclose()