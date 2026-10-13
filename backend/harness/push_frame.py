"""Publish one frame the way the application does, so a browser can be asked
whether it actually reacted.

Every other test in this repo can pass while the UI renders a perfectly composed
page that never changes. Nothing here proves the browser is *connected to
anything*, because nothing asks. This is the tool that lets a test ask.

Each subcommand mirrors a real publisher in `app/websocket/manager.py`:

    price    publish_market_event(market_id, "market:price_update", ...)
    trade    publish_market_event(market_id, "trade:new", ...)
    book     publish_market_event(market_id, "orderbook:update", ...)
    global   publish_global_trade(...)   -> the `global:trades` firehose
    resolved publish_market_event(market_id, "market:resolved", ...)

The market-scoped ones go through the Lua sequencer, because that is what
allocates `seq` atomically with the publish. Getting that wrong would mean
testing a path the application never takes.
"""

import asyncio
import json
import sys

from app.websocket.manager import (
    _SEQ_AND_PUBLISH_LUA,
    GLOBAL_TRADES_CHANNEL,
    RedisPubSub,
    market_events_channel,
    market_seq_key,
)


async def _publish_market(ps: RedisPubSub, market_id: str, event: dict) -> None:
    await ps._redis.eval(
        _SEQ_AND_PUBLISH_LUA,
        2,
        market_seq_key(market_id),
        market_events_channel(market_id),
        json.dumps(event),
    )


async def main(kind: str, market_id: str, value: float | None = None) -> None:
    ps = RedisPubSub()
    await ps.connect()
    try:
        if kind == "price":
            yes = value if value is not None else 0.77
            await _publish_market(ps, market_id, {
                "type": "market:price_update",
                "market_id": market_id,
                "yes_price": yes,
                "no_price": round(1 - yes, 4),
            })
        elif kind == "trade":
            marker = int(value) if value is not None else int(__import__("time").time() * 1000) % 10_000
            await _publish_market(ps, market_id, {
                "type": "trade:new",
                "market_id": market_id,
                "market_slug": market_id,
                "side": "buy",
                "outcome": "Yes",
                "price": 0.61,
                "amount": 12.5,
                "id": f"probe-{marker}",
            })
        elif kind == "book":
            # Shape matters, and guessing it wastes a whole debugging cycle.
            # `_push_orderbook` publishes `build_orderbook`'s dict directly, which
            # is keyed by outcome: `{ "yes": { bids, asks } }`. The detail page
            # looks for exactly that `outcomes` wrapper and ignores anything else -
            # correctly. A frame with flat `bids`/`asks` is not a malformed book,
            # it is a different message entirely.
            await _publish_market(ps, market_id, {
                "type": "orderbook:update",
                "market_id": market_id,
                "outcomes": {
                    "yes": {
                        "bids": [{"price": 0.58, "size": 500}],
                        "asks": [{"price": 0.63, "size": 400}],
                    }
                },
            })
        elif kind == "global":
            marker = int(value) if value is not None else int(__import__("time").time() * 1000) % 10_000
            await ps._redis.publish(GLOBAL_TRADES_CHANNEL, json.dumps({
                "type": "trade:new",
                "id": f"gprobe-{marker}",
                "market_id": market_id,
                "market_slug": market_id,
                "side": "buy",
                "outcome": "Yes",
                "price": 0.64,
                "amount": 9.0,
            }))
        elif kind == "resolved":
            await _publish_market(ps, market_id, {
                "type": "market:resolved",
                "market_id": market_id,
                "status": "resolved",
                "winning_outcome_name": "Yes",
                "winning_outcome_id": "yes",
            })
        elif kind in ("fill", "position", "notification"):
            # Private frames go to the user's own channels - a different path from
            # everything above: no Lua sequencer (there is no shared ordering to
            # maintain for a stream only one person reads), and two channels
            # rather than one, because fills and notifications are different
            # contracts.
            #
            # This is the highest-consequence path in the product. A user who is
            # not told they were filled has no way of knowing to go and look.
            channel = (
                f"user:{market_id}:fills"
                if kind in ("fill", "position")
                else f"user:{market_id}:notifications"
            )
            if kind == "fill":
                payload = {
                    "type": "order:fill",
                    "order_id": "probe-order",
                    "order_ids": ["probe-order"],
                    "market_id": "probe-market",
                    "market_slug": "probe-market",
                    "status": "filled",
                    "side": "buy",
                    "shares": 25.0,
                    "price": 0.61,
                    "avg_price": 0.61,
                }
            elif kind == "position":
                payload = {
                    "type": "position:update",
                    "market_id": "probe-market",
                    "outcome": "Yes",
                    "shares": 137.5,
                    "avg_price": 0.42,
                    "realized_pnl": 3.5,
                }
            else:
                # Mirror the real frame from `notification_service.create`, which
                # carries the notification twice: flat for the portfolio toast,
                # nested for the notification bell.
                #
                # A flat-only probe looks like it works - it publishes, the socket
                # receives it, nothing errors - and then proves nothing, because
                # each consumer reads one shape or the other and silently ignores
                # what it did not expect. That is how this path stayed untested:
                # the harness spoke a shape the application never sent.
                nid = f"probe-{int(__import__('time').time())}"
                notification = {
                    "id": nid,
                    "type": "system",
                    "title": "Probe notification",
                    "body": "Private feed probe",
                    "data": {},
                    "read_at": None,
                    "created_at": None,
                }
                payload = {
                    **notification,
                    # Stamped last, exactly as `publish_notification` does: the
                    # outer type is the transport, the inner one is the
                    # notification's kind.
                    "type": "notification",
                    "notification": notification,
                }
            await ps._redis.publish(channel, json.dumps(payload))
        else:
            raise SystemExit(f"unknown kind: {kind}")
        print(f"published {kind} for {market_id}")
    finally:
        await ps.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("usage: push_frame <kind> <market_id> [value]")
    val = float(sys.argv[3]) if len(sys.argv) > 3 else None
    asyncio.run(main(sys.argv[1], sys.argv[2], val))