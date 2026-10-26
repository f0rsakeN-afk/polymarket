"""Publish one price frame for a market, exactly as the order path does.

Used to prove the grid is genuinely live: a browser holds the markets page open,
this moves a price in Redis, and the page is asked whether the number on screen
followed. Anything short of that - a live badge, a connected socket - is
consistent with a page that renders perfectly and never changes.
"""
import asyncio
import json
import sys

from app.websocket.manager import (
    _SEQ_AND_PUBLISH_LUA,
    RedisPubSub,
    market_events_channel,
    market_seq_key,
)


async def main(market_id: str, yes_price: float) -> None:
    ps = RedisPubSub()
    await ps.connect()
    payload = json.dumps({
        "type": "market:price_update",
        "market_id": market_id,
        "yes_price": yes_price,
        "no_price": round(1 - yes_price, 4),
    })
    await ps._redis.eval(
        _SEQ_AND_PUBLISH_LUA, 2,
        market_seq_key(market_id),
        market_events_channel(market_id),
        payload,
    )
    await ps.close()
    print(f"published {market_id} yes={yes_price}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], float(sys.argv[2])))