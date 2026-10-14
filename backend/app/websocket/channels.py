"""Redis channel and key names - a wire contract, in one leaf module.

## Why this exists as its own file

These strings are a contract between four parties: the backend, the load
harnesses, the E2E probes, and - for `WS_RESYNC` - the frontend. When the format
was written out inline at each site, the harnesses had to re-spell it. That is
the arrangement that produces a harness which passes while proving nothing: the
app changes `user:{id}:fills` to include a shard, the harness is still publishing
to the old name, and the proof-of-delivery check reports success because the
frames it sent were the frames nobody was listening for.

Three harnesses in a row failed silently by speaking a language the app does not
speak. This is the structural fix rather than another patch of symptoms.

## Why it has no imports

`scale_out.py` drives two real uvicorn subprocesses and deliberately does not
import the application - but it still needs to name channels. A leaf module with
no dependencies means it can `from app.websocket.channels import ...` without
pulling in settings, Redis clients and the manager's module-level state.

`manager.py` re-exports everything here, so existing
`from app.websocket.manager import market_events_channel` keeps working and there
is still exactly one definition of each name.
"""

# Marker telling a client its private feed has a hole it should repair.
#
# Must stay byte-identical to `WS_RESYNC` in
# `frontend/apps/web/lib/ws-resync.ts`. It is a wire contract with no shared
# schema behind it, which is exactly the kind of thing that drifts silently -
# the server would send a frame the client does not recognise and the resync
# would simply never happen, with nothing failing anywhere. The value is pinned
# by a test for that reason.
WS_RESYNC = "__ws_resync__"

GLOBAL_TRADES_CHANNEL = "global:trades"


def market_events_channel(market_id: str) -> str:
    """The single Redis channel carrying every frame for one market.

    Price updates used to go to a separate `market:{id}:price` channel from
    everything else. Two channels for one logical feed is two orderings: the
    publishes are independent round-trips, so two concurrent orders could land
    as price(A), price(B), trade(A), trade(B), book(A), book(B) and every client
    would render a book that contradicted the price printed beside it, with no
    way to detect it. One channel is one order.

    The `market:{id}:price` *key* (an HSET cache read by `market_service`) is
    unaffected - it was never a channel and is still written by every price
    publish.
    """
    return f"market:{market_id}:events"


def market_seq_key(market_id: str) -> str:
    """Counter backing the per-market frame sequence number."""
    return f"market:{market_id}:seq"


def user_fills_channel(user_id: str) -> str:
    """Private channel carrying one user's fills."""
    return f"user:{user_id}:fills"


def user_notifications_channel(user_id: str) -> str:
    """Private channel carrying one user's notifications."""
    return f"user:{user_id}:notifications"