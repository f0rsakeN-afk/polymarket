"""Operational signals about work the system owes.

Two things the application can state plainly, both of which used to be invisible:

1. **Markets past their close time that are not resolved.** `closed` means no new
   orders and awaiting resolution; `resolving` means resolution has been proposed
   and is in its dispute window. Both are legitimate transient states - and both
   are exactly what a dead worker pool produces, forever. Counted, and aged.

   This is deliberately the *consequence* rather than the cause. A worker count
   tells an operator that infrastructure may be down; "14 markets are past close
   and unsettled, the oldest for six hours" tells them what it is costing and is
   the number worth waking up for.

2. **How many workers are alive.** See `app/workers/heartbeat.py` for why this is
   kept out of readiness.

Neither of these gates anything. They exist to be read.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import _get_engine
from app.middleware.metrics import (
    CELERY_WORKERS_ALIVE,
    MARKETS_UNRESOLVED,
    MARKETS_UNRESOLVED_OLDEST_AGE,
)
from app.models.market import STATUS_CLOSED, STATUS_RESOLVING, Market
from app.workers.heartbeat import live_worker_count  # sync Redis client by design

logger = logging.getLogger("PredictX")

REFRESH_INTERVAL_S = 30.0

# Statuses that mean "past close, outcome not yet final".
_UNRESOLVED = (STATUS_CLOSED, STATUS_RESOLVING)


async def unresolved_backlog(session: AsyncSession) -> tuple[int, float]:
    """(count, age in seconds of the oldest) for markets awaiting resolution.

    The age is what turns a count into something actionable: a backlog of two is
    normal, a backlog of two where the oldest is six hours old means the worker
    pool is not doing its job. A count alone cannot tell those apart.
    """
    count = await session.scalar(
        select(func.count())
        .select_from(Market)
        .where(Market.status.in_(_UNRESOLVED))
    )
    oldest = await session.scalar(
        select(func.min(Market.closes_at)).where(Market.status.in_(_UNRESOLVED))
    )
    age = 0.0
    if oldest is not None:
        now = datetime.now(UTC)
        # `closes_at` is stored naive in some rows and aware in others; treat a
        # naive value as UTC rather than raising, because a monitoring read must
        # never be the thing that breaks.
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        age = max(0.0, (now - oldest).total_seconds())
    return int(count or 0), age


async def refresh_once() -> tuple[int, float, int]:
    """Recompute and publish the gauges. Returns (workers, count, age)."""
    # Synchronous on purpose: the worker pool is recorded through the sync
    # client (see app/workers/heartbeat.py), and doing the read the same way keeps
    # it one code path rather than two that could disagree.
    workers = await asyncio.to_thread(live_worker_count)
    count = 0
    age = 0.0
    try:
        async with _get_engine().connect() as conn:
            count, age = await unresolved_backlog(conn)
            await conn.commit()
    except Exception as exc:
        # A database blip must not stop the worker gauge being refreshed, and
        # must not take the loop down with it.
        logger.warning(f"unresolved-market backlog unavailable: {exc}")

    CELERY_WORKERS_ALIVE.set(workers)
    MARKETS_UNRESOLVED.set(count)
    MARKETS_UNRESOLVED_OLDEST_AGE.set(age)

    if count and age > 900:
        logger.warning(
            f"{count} market(s) past close and unresolved, oldest "
            f"{age / 60:.0f} minutes - the resolution worker is not keeping up"
        )
    return workers, count, age


async def backlog_snapshot() -> tuple[int, int, float]:
    """(workers, unresolved count, oldest age) for the health payload.

    A read that does not touch the gauges, so curling /health/ready cannot
    itself move a metric - a monitoring read should be free to have side effects
    elsewhere, but not here, where a scrape would look like an operational change.
    """
    workers = await asyncio.to_thread(live_worker_count)
    count, age = 0, 0.0
    try:
        async with _get_engine().connect() as conn:
            count, age = await unresolved_backlog(conn)
    except Exception as exc:
        logger.debug(f"backlog snapshot unavailable: {exc}")
    return workers, count, age


async def ops_loop() -> None:
    """Refresh on an interval until cancelled."""
    while True:
        try:
            await refresh_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"ops signal refresh failed: {exc}")
        await asyncio.sleep(REFRESH_INTERVAL_S)