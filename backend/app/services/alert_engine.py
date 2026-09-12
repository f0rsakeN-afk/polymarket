"""
Alert trigger index — Redis ZSET + Lua for exactly-once firing at scale.

Problem with the naive approach: on every trade, load ALL untriggered alerts
for the market into Python, evaluate, write back. That is O(alerts) DB rows per
trade plus a race — two workers handling concurrent trades both see the same
untriggered alert and both notify the user.

Design here:
- Each untriggered alert is indexed in a Redis sorted set keyed by
  (market, tracked side, condition), scored by trigger_price:
      alerts:{market_id}:{yes|no}:{above|below}  ->  {alert_id: trigger_price}
- `outcome=None` ("either") alerts track the YES price (same as the old
  Python path: price = yes_price if outcome in ("yes", None)).
- On each price update, a Lua script atomically finds AND removes ("claims")
  the due alert IDs per set. Atomic claim = exactly one worker wins, even with
  N workers firing concurrently. Claimed IDs are then flipped in Postgres with
  a guarded UPDATE ... WHERE triggered=false, and only flipped rows notify.
- The ZSET is a pure index: Postgres remains the source of truth. Deletes and
  triggers remove members; a cold/missing index falls back to a DB scan and
  self-repairs via reindex.

Lua claim script (per set):
    ARGV[1] = current price, ARGV[2] = "above" | "below"
    above -> due = score <= price  (matches Python: price >= trigger)
    below -> due = score >= price  (matches Python: price <= trigger)
"""

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.redis import get_redis, redis_cb

logger = logging.getLogger("polymarket")

DIRTY_MARKETS_KEY = "dirty:markets"


def _tracked_side(outcome: str | None) -> str:
    """Which price series this alert follows. None tracks YES (legacy behavior)."""
    return "no" if outcome == "no" else "yes"


def _zset_key(market_id: str, outcome: str | None, condition: str) -> str:
    return f"alerts:{market_id}:{_tracked_side(outcome)}:{condition}"


# Atomically fetch + remove due alert IDs so concurrent workers can't
# double-claim. Returns list of alert-id strings (possibly empty).
CLAIM_SCRIPT = """
local members
if ARGV[2] == 'above' then
    members = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
else
    members = redis.call('ZRANGEBYSCORE', KEYS[1], ARGV[1], '+inf')
end
if #members > 0 then
    redis.call('ZREM', KEYS[1], unpack(members))
end
return members
"""


async def index_alert(market_id: str, alert_id: str, outcome: str | None, condition: str, trigger_price: float) -> None:
    """Add an alert to the trigger index (write-through on create)."""
    r = await get_redis()
    key = _zset_key(str(market_id), outcome, condition)

    async def _op():
        await r.zadd(key, {str(alert_id): float(trigger_price)})
        await r.expire(key, 86400 * 7)  # self-cleaning; reindexed on use anyway

    try:
        await redis_cb.call(_op)
    except Exception as e:
        logger.warning(f"Alert index write failed (non-fatal): {e}")


async def deindex_alert(market_id: str, alert_id: str, outcome: str | None, condition: str) -> None:
    """Remove an alert from the index (delete / manual trigger paths)."""
    r = await get_redis()
    key = _zset_key(str(market_id), outcome, condition)

    async def _op():
        await r.zrem(key, str(alert_id))

    try:
        await redis_cb.call(_op)
    except Exception as e:
        logger.warning(f"Alert deindex failed (non-fatal): {e}")


async def claim_due_alerts(market_id: str, yes_price: float, no_price: float) -> list[str]:
    """Atomically claim due alert IDs across the 4 index sets. Empty list if none."""
    r = await get_redis()
    specs = (
        (_zset_key(market_id, "yes", "above"), yes_price, "above"),
        (_zset_key(market_id, "yes", "below"), yes_price, "below"),
        (_zset_key(market_id, "no", "above"), no_price, "above"),
        (_zset_key(market_id, "no", "below"), no_price, "below"),
    )
    claimed: list[str] = []
    for key, price, direction in specs:
        try:
            members = await redis_cb.call(lambda: r.eval(CLAIM_SCRIPT, 1, key, price, direction))
        except Exception as e:
            logger.warning(f"Alert claim failed for {key} (non-fatal): {e}")
            continue
        for m in members or []:
            claimed.append(m.decode() if isinstance(m, bytes) else m)
    return claimed


async def reindex_market_alerts(db: AsyncSession, market_id: str) -> int:
    """Rebuild the index for a market from Postgres (cold-start repair)."""
    result = await db.execute(
        select(Alert).where(Alert.market_id == market_id, Alert.triggered.is_(False))
    )
    alerts = result.scalars().all()
    if not alerts:
        return 0
    r = await get_redis()

    async def _op():
        pipe = r.pipeline()
        for a in alerts:
            pipe.zadd(
                _zset_key(str(market_id), a.outcome, a.condition),
                {str(a.id): float(a.trigger_price)},
            )
        for side in ("yes", "no"):
            for cond in ("above", "below"):
                pipe.expire(_zset_key(str(market_id), side, cond), 86400 * 7)
        await pipe.execute()

    try:
        await redis_cb.call(_op)
    except Exception as e:
        logger.warning(f"Alert reindex failed (non-fatal): {e}")
        return 0
    return len(alerts)


async def mark_triggered(db: AsyncSession, alert_ids: list[str]):
    """Flip claimed alerts to triggered, returning only rows this worker won.

    The `triggered=false` guard makes this idempotent even if two workers ever
    claim overlapping IDs (e.g. index rebuilt mid-claim).
    """
    if not alert_ids:
        return []
    result = await db.execute(
        update(Alert)
        .where(Alert.id.in_(alert_ids), Alert.triggered.is_(False))
        .values(triggered=True)
        .returning(Alert)
    )
    return result.scalars().all()


async def pop_dirty_markets() -> list[str] | None:
    """Drain the dirty-market set. None = Redis unavailable, caller falls back
    to a full scan. Empty list = nothing moved, safe to skip work entirely."""
    r = await get_redis()
    try:
        members = await redis_cb.call(lambda: r.spop(DIRTY_MARKETS_KEY, 10000))
    except Exception as e:
        logger.warning(f"Dirty-market pop failed, falling back to full scan: {e}")
        return None
    if not members:
        return []
    if isinstance(members, (str, bytes)):
        members = [members]
    return [m.decode() if isinstance(m, bytes) else m for m in members]
