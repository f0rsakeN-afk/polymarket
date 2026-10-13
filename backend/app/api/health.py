"""Health endpoints, with the four questions actually being different questions.

Most services expose one `/health` that everything points at, and it ends up
answering something nobody asked. A load balancer asking "should I send traffic
here?" and an orchestrator asking "is this process wedged?" need opposite
answers, and so does an operator asking "what is this system currently failing
at?".

So there are four, and conflating them is how a dependency blip becomes an
outage:

* `/health/live` - is this process running? Checks nothing external, because
  restarting the process does not fix Postgres. Depends on nothing, so it cannot
  be taken down by a dependency it does not control.
* `/health/startup` - has it finished booting? Stays failing during startup so a
  slow boot is not mistaken for a crash and the container is restarted mid-init.
* `/health/ready` - can it serve traffic? Checks what serving actually requires:
  the database and Redis. **Not** Celery workers - see `app/services/ops_signals.py`
  for why pulling a working API out of rotation because a different service is
  down turns a partial outage into a total one.
* `/health/details` - the full picture including work the system still owes.
  Admin-only, because it reports market backlogs and worker counts.

`/health` is retained as an alias of `/health/live`, because `docker-compose.dev.yml`
and the production nginx healthcheck already point at these paths and silently
breaking a healthcheck is worse than any tidiness gained.

## Two properties that matter more than they look

**Per-check timeouts.** A health endpoint that hangs is worse than one that is
wrong. Probes come from an external balancer, so during an incident they arrive
just as the pool is exhausted, and a blocking check turns that into a pile-up
that outlives the incident. Every dependency is bounded.

**A short result cache.** Probes run every few seconds per instance. Without a
cache each one is a real query, and during an outage the checks become part of
the load that caused it. Cached for `CACHE_TTL_S` - long enough to collapse a
burst of probes, short enough that recovery is visible immediately.
"""

import asyncio
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import _get_engine, get_db
from app.services.ops_signals import backlog_snapshot

router = APIRouter(tags=["health"])

# Bounded so a wedged dependency cannot hold a probe open. Short because a probe
# that answers slowly is already a problem, and because the orchestrator will
# have given up by the time a generous timeout returns.
DEPENDENCY_TIMEOUT_S = 2.0

# Collapses a burst of probes into one set of queries. Long enough to be
# effective, short enough that a recovered dependency is reported at once.
CACHE_TTL_S = 2.0

# Set once the lifespan has finished starting, so `/health/startup` can answer.
_STARTED = False


def mark_started() -> None:
    global _STARTED
    _STARTED = True


_cached: tuple[float, dict] | None = None


async def _check_db() -> dict:
    t0 = time.perf_counter()
    async with _get_engine().begin() as conn:
        await conn.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
    }


async def _check_redis() -> dict:
    from app.redis import get_redis

    t0 = time.perf_counter()
    redis = await get_redis()
    await redis.ping()
    return {
        "status": "ok",
        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
    }


async def _bounded(name: str, coro) -> dict:
    """Run one dependency check with a hard timeout, never raising."""
    try:
        result = await asyncio.wait_for(coro, timeout=DEPENDENCY_TIMEOUT_S)
        return result
    except TimeoutError:
        return {"status": "error", "latency_ms": None, "error": f"timeout after {DEPENDENCY_TIMEOUT_S}s"}
    except Exception as exc:
        result = {"status": "error", "latency_ms": None}
        # The exception text can carry connection strings and hostnames. Shown in
        # development because that is where it is useful, withheld in production
        # because that is where it is a leak.
        if settings.app_env != "production":
            result["error"] = str(exc)
        return result


async def _readiness() -> dict:
    global _cached
    now = time.monotonic()
    if _cached is not None and now - _cached[0] < CACHE_TTL_S:
        return _cached[1]

    checks: dict[str, dict] = {}
    # Sequential rather than concurrent: these are two cheap round trips, and
    # firing them together would double the load on exactly the dependency pool
    # that is most likely to be the thing in trouble.
    checks["db"] = await _bounded("db", _check_db())
    checks["redis"] = await _bounded("redis", _check_redis())

    # Only the dependencies this process genuinely cannot serve traffic without.
    # Worker liveness is deliberately absent - see the module docstring.
    ready = all(c["status"] == "ok" for c in checks.values())
    payload = {
        "status": "ok" if ready else "unavailable",
        "checks": checks,
    }
    _cached = (now, payload)
    return payload


@router.get("/health", include_in_schema=False)
@router.get("/health/live", summary="Liveness")
async def liveness() -> dict:
    """Is this process running? Deliberately checks nothing external.

    Restarting does not fix Postgres, so a process that cannot reach the database
    is not the thing that needs restarting. If liveness consulted dependencies,
    every database blip would restart every API process - turning a recoverable
    outage into a crash loop that outlives the blip.
    """
    return {"status": "ok", "checks": {}}


@router.get("/health/startup", summary="Startup probe")
async def startup() -> JSONResponse:
    """Has the process finished booting?

    Without this, an orchestrator's liveness probe can fire during a slow start
    and kill a container that was about to become healthy.
    """
    if _STARTED:
        return JSONResponse(status_code=200, content={"status": "ok"})
    return JSONResponse(status_code=503, content={"status": "starting"})


@router.get("/health/ready", summary="Readiness")
async def readiness() -> JSONResponse:
    """Can this process serve traffic? Checks only what serving requires."""
    payload = await _readiness()
    code = 200 if payload["status"] == "ok" else 503
    return JSONResponse(status_code=code, content=payload)


async def _get_admin_user(request: Request, db: AsyncSession = Depends(get_db)):
    """Return the admin user, or `None`.

    Returning `None` rather than raising is deliberate. A 403 here would tell any
    unauthenticated caller that this path exists and is protected, and would make
    a plain `curl` against it look like an outage. A monitoring tool without
    credentials should get readiness back - which is useful, and reveals nothing.
    """
    from app.deps import get_current_user

    try:
        user = await get_current_user(request, db)
    except Exception:
        return None
    return user if getattr(user, "is_admin", False) else None


@router.get("/health/details", summary="Full health detail (admin)")
async def details(
    admin=Depends(_get_admin_user),
) -> JSONResponse:
    """Everything, including work the system still owes. Admin-only.

    Separate from readiness on purpose: it reports *debt* - markets past close
    and unresolved, live worker count - which is the thing an operator needs and
    the thing a public endpoint has no business exposing. The numbers describe
    how much money is sitting against markets that should have settled, which is
    more than a competitor needs to know.
    """
    payload = await _readiness()
    body: dict = {"status": payload["status"], "checks": payload["checks"]}

    # Non-admins get readiness and nothing more - already assembled in `body`.
    if admin is None:
        return JSONResponse(status_code=200, content=body)

    workers, unresolved, oldest_age = await backlog_snapshot()
    body["workers"] = {
        "celery_workers_alive": workers,
        "markets_unresolved": unresolved,
        "markets_unresolved_oldest_age_s": round(oldest_age, 1),
    }
    return JSONResponse(status_code=200, content=body)