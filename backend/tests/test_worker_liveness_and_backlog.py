"""Worker liveness and the debt it creates, measured rather than assumed.

A Celery pool that stops leaves markets past their close time unresolved
indefinitely: no winner announced, positions live, escrow locked. Every socket
stays connected and every page reports live, so nothing about the UI says
anything is wrong. That is the same silent-failure shape this codebase keeps
producing, and it is the worst version of it because the money is involved.

These pin the two things that turn it into a visible condition: a worker count
that is correct, and a backlog that is counted and aged.
"""

import time
import uuid

import pytest

from app.workers.heartbeat import (
    WORKER_TTL_S,
    WORKERS_KEY,
    beat,
    live_worker_count,
    start_heartbeat,
    worker_id,
)


@pytest.fixture(autouse=True)
async def _clean_workers():
    from app.redis import get_redis_sync

    redis = get_redis_sync()
    redis.delete(WORKERS_KEY)
    yield
    redis.delete(WORKERS_KEY)


@pytest.mark.asyncio
async def test_a_worker_that_beat_is_counted():
    assert live_worker_count() == 0

    assert beat() is True

    assert live_worker_count() == 1


@pytest.mark.asyncio
async def test_a_second_worker_is_counted_separately():
    """Two workers must read as two, or the gauge cannot detect half a pool.

    A count that collapses workers together would show a healthy pool when one of
    two has died - the exact case the signal exists for.
    """
    from app.redis import get_redis_sync

    beat()
    redis = get_redis_sync()
    redis.zadd(WORKERS_KEY, {"someotherhost:999": time.time()})

    assert live_worker_count() == 2


@pytest.mark.asyncio
async def test_a_silent_worker_ages_out_without_any_cleanup():
    """The failure that matters is a worker vanishing, so expiry must be passive.

    Deregistration is a courtesy. A worker killed with SIGKILL runs no shutdown
    hook, so if membership depended on deregistering, a dead worker would count as
    alive forever and the gauge would be worse than nothing - it would look
    healthy precisely when everything is not.
    """
    from app.redis import get_redis_sync

    beat()
    assert live_worker_count() == 1

    # Backdate the entry rather than sleeping the TTL out.
    get_redis_sync().zadd(WORKERS_KEY, {worker_id(): time.time() - WORKER_TTL_S - 1})

    assert live_worker_count() == 0, (
        "a worker that stopped beating is still counted as alive - which makes "
        "the gauge worse than no gauge, because it looks healthy while the pool "
        "is down"
    )


@pytest.mark.asyncio
async def test_recent_beats_are_not_swept_away():
    """Trimming must only remove what has actually gone quiet.

    A trim that swept healthy workers would report zero during a busy period -
    the moment the pool is working hardest.
    """
    from app.redis import get_redis_sync

    beat()
    get_redis_sync().zadd(WORKERS_KEY, {"busyworker:1": time.time() - 1})

    assert live_worker_count() == 2


@pytest.mark.asyncio
async def test_liveness_never_raises_when_redis_is_unreachable(monkeypatch):
    """A status read must not become a 500.

    Redis being down is itself an alertable condition; if reading the gauge also
    failed the endpoint, the failure would take out the one place that was about
    to explain it.
    """
    def _explode():
        raise RuntimeError("redis unreachable")

    monkeypatch.setattr("app.workers.heartbeat.get_redis_sync", _explode)

    assert live_worker_count() == 0


@pytest.mark.asyncio
async def test_heartbeat_starts_once_however_many_times_it_is_asked():
    """Two threads beating would double-count the worker.

    The hook is connected once but a worker can be started by several signals
    under some pool configurations, and a second thread would make one process
    look like two.
    """
    first = start_heartbeat()
    second = start_heartbeat()

    assert first is not None
    assert second is first, "a second heartbeat thread was started for one process"


# ── The debt: markets past close and unresolved ───────────────────────────────


def _market(slug_prefix: str, *, status: str, closes_at, admin_id):
    """A market with the minimum a backlog query needs.

    Built inline the way `conftest.test_market` builds one, because the suite has
    no market factory and inventing a second way to create the same row is how
    fixtures drift apart.
    """
    from app.models.market import Market

    return Market(
        slug=f"{slug_prefix}-{uuid.uuid4().hex[:8]}",
        question="Will it rain tomorrow?",
        description="Backlog test market",
        category="weather",
        status=status,
        created_by=admin_id,
        closes_at=closes_at,
        total_liquidity="100.00",
        total_volume="50.00",
    )




@pytest.mark.asyncio
async def test_backlog_counts_markets_awaiting_resolution(db_session, admin_user):
    """`closed` and `resolving` are both "past close, outcome not final".

    Counting only one of them would under-report exactly the stuck case: a market
    that entered `resolving` and stalled there is worse than one still waiting,
    and it is the one that looks least like a backlog from the outside.
    """
    from datetime import UTC, datetime, timedelta

    from app.models.market import STATUS_ACTIVE, STATUS_CLOSED, STATUS_RESOLVING
    from app.services.ops_signals import unresolved_backlog

    past = datetime.now(UTC) - timedelta(hours=2)
    future = datetime.now(UTC) + timedelta(days=2)

    db_session.add_all(
        [
            _market("closed", status=STATUS_CLOSED, closes_at=past, admin_id=admin_user.id),
            _market("resolving", status=STATUS_RESOLVING, closes_at=past, admin_id=admin_user.id),
            _market("still-open", status=STATUS_ACTIVE, closes_at=past, admin_id=admin_user.id),
            _market("future", status=STATUS_ACTIVE, closes_at=future, admin_id=admin_user.id),
        ]
    )
    await db_session.commit()

    count, age = await unresolved_backlog(db_session)

    assert count == 2, "only one of the two awaiting-resolution states was counted"
    assert age > 3600, f"oldest unresolved market reported as {age:.0f}s old"


@pytest.mark.asyncio
async def test_an_empty_backlog_is_zero_not_an_error(db_session):
    """No backlog is the normal case and must read as a clean zero.

    A gauge that is absent because nothing has ever set it reads as "not
    collected", which is the opposite of "nothing is wrong" - and a check that
    errors when healthy is a check that gets muted.
    """
    from app.services.ops_signals import unresolved_backlog

    count, age = await unresolved_backlog(db_session)

    assert count == 0
    assert age == 0.0


@pytest.mark.asyncio
async def test_backlog_age_is_what_makes_a_count_actionable(db_session, admin_user):
    """Two markets is normal. Two markets where the oldest is six hours old is not.

    A count alone cannot tell those apart, which is why the age is exported
    alongside it - "14 unresolved" is a shrug, and "14 unresolved, oldest six
    hours" is a page.
    """
    from datetime import UTC, datetime, timedelta

    from app.models.market import STATUS_CLOSED
    from app.services.ops_signals import unresolved_backlog

    db_session.add(
        _market(
            "just-closed",
            status=STATUS_CLOSED,
            closes_at=datetime.now(UTC) - timedelta(seconds=30),
            admin_id=admin_user.id,
        )
    )
    await db_session.commit()

    count, age = await unresolved_backlog(db_session)

    assert count == 1
    assert 0 <= age < 300, f"a market closed 30s ago reported as {age:.0f}s old"


@pytest.mark.asyncio
async def test_refresh_publishes_the_gauges():
    """The refresh must set the gauges, not merely compute the numbers.

    A prometheus Gauge is only exported once something has called `.set()` on it,
    so a declared-but-never-refreshed gauge is absent from a scrape - which reads
    as "not collected" rather than "nothing wrong". This is the difference between
    a metric and a declaration of intent.
    """
    from app.middleware import metrics as m
    from app.services import ops_signals

    workers, count, age = await ops_signals.refresh_once()

    assert isinstance(workers, int)
    assert isinstance(count, int)
    assert age >= 0.0

    # Read the gauges back: declared is not exported. A prometheus Gauge only
    # appears in a scrape once something has called `.set()`, so this is the
    # difference between a metric and a declaration of intent.
    assert m.CELERY_WORKERS_ALIVE._value.get() == workers
    assert m.MARKETS_UNRESOLVED._value.get() == count
    assert m.MARKETS_UNRESOLVED_OLDEST_AGE._value.get() == age