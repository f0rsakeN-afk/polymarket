"""Liveness for the Celery worker pool, recorded in Redis.

## Why this exists

Some of the realtime product depends on background workers, and nothing noticed
when they stopped. Immediate fill notifications are published by the API process
itself (`_notify_fill_participants`), so those keep working. But:

* `check_markets_ready_to_resolve` closes and settles markets - workers down means
  markets pass their close time and simply stay open. No winner is ever
  announced, positions stay live, and escrow stays locked.
* `expire_stale_orders` publishes expiry frames, so resting orders stay "open"
  forever and their funds stay locked.
* `check_price_alerts` never fires a user's price alert.

Every socket stays connected, every page reports live, and nothing arrives. The
same silent-failure shape as a hundred other things in this codebase, and the
worst version of it, because the consequence is money held against a market that
should have settled.

`/health/ready` deliberately does **not** gate on this. Readiness answers "can
this process serve traffic", and it can - perfectly well - with no workers alive.
Wiring worker liveness into readiness would mean a busy or briefly unreachable
worker pool flapping the API out of rotation, taking down a service that is
working. That trades a silent failure for an outage. See `app/services/ops_signals.py`.

## How liveness is recorded

A Redis sorted set of worker ids scored by last-heartbeat timestamp.

A sorted set rather than one key per worker: counting live keys means `SCAN` over
the whole keyspace, and this is scraped continuously. Trimming by score and
counting with `ZCARD` is O(log n) and exact.

Members carry no TTL of their own - a sorted set entry only goes away when
trimmed - so a worker killed with `SIGKILL` ages out on its own after
`WORKER_TTL_S`. Deregistration is a courtesy, not a mechanism, because the
failure we care about is a worker vanishing without running any cleanup.

## A thread, deliberately

The heartbeat runs on a daemon thread with the synchronous Redis client rather
than as an asyncio task. Celery's prefork pool runs tasks in child processes with
no asyncio event loop of their own, so an asyncio heartbeat would need the worker
to be configured for the asyncio pool - coupling liveness to a deployment
decision, and silently reporting zero live workers for anyone who chose prefork.

A thread works under every pool configuration, which matters for a signal whose
entire job is to be true when something else is wrong.
"""

import logging
import os
import socket
import threading
import time

from app.redis import get_redis_sync

logger = logging.getLogger("PredictX")

WORKERS_KEY = "predictx:workers"

# A worker must miss this many beats before it counts as gone. Generous on
# purpose: a long settlement is not a dead worker, and a page that fires whenever
# a big task holds the slot teaches people to ignore pages.
HEARTBEAT_INTERVAL_S = 15.0
WORKER_TTL_S = 90.0


def worker_id() -> str:
    """Stable-per-process identity: host and pid, so two workers on one host differ."""
    return f"{socket.gethostname()}:{os.getpid()}"


def beat() -> bool:
    """Record one heartbeat. Returns whether it landed."""
    try:
        redis = get_redis_sync()
        redis.zadd(WORKERS_KEY, {worker_id(): time.time()})
        return True
    except Exception as exc:
        logger.warning(f"Celery worker heartbeat failed: {exc}")
        return False


def live_worker_count() -> int:
    """How many workers have checked in recently. Never raises."""
    try:
        redis = get_redis_sync()
        cutoff = time.time() - WORKER_TTL_S
        redis.zremrangebyscore(WORKERS_KEY, "-inf", cutoff)
        return int(redis.zcard(WORKERS_KEY))
    except Exception as exc:
        # Redis being unreachable must not turn a status read into a 500. The
        # gauge keeps its last value and the Redis alert fires on its own.
        logger.debug(f"worker liveness unavailable: {exc}")
        return 0


def _loop() -> None:
    while True:
        beat()
        time.sleep(HEARTBEAT_INTERVAL_S)


def start_heartbeat() -> threading.Thread | None:
    """Begin beating in this process. Safe to call more than once."""
    existing = getattr(start_heartbeat, "_thread", None)
    if existing is not None and existing.is_alive():
        return existing

    # Beat immediately so a worker that starts and is immediately killed still
    # registers, rather than only appearing once it survives an interval.
    beat()
    thread = threading.Thread(target=_loop, name="celery-heartbeat", daemon=True)
    thread.start()
    start_heartbeat._thread = thread  # type: ignore[attr-defined]
    logger.info(f"Celery worker heartbeat started ({worker_id()})")
    return thread


def register_signals() -> None:
    """Attach Celery's lifecycle hooks to the heartbeat.

    `worker_process_init` rather than `worker_ready`: with the prefork pool the
    ready signal fires once in the parent, while the processes that actually run
    tasks are the children. Starting from the parent's ready signal would give
    exactly one heartbeat - from a process that runs no tasks - and report a
    pool of one no matter how many workers were actually working.
    """
    from celery.signals import worker_process_init, worker_shutdown

    @worker_process_init.connect
    def _on_process_init(**_kwargs) -> None:
        start_heartbeat()

    @worker_shutdown.connect
    def _on_shutdown(**_kwargs) -> None:
        try:
            get_redis_sync().zrem(WORKERS_KEY, worker_id())
            logger.info(f"Celery worker heartbeat released ({worker_id()})")
        except Exception:
            # Not an error worth raising on the way down: the entry ages out on
            # its own after WORKER_TTL_S regardless.
            pass