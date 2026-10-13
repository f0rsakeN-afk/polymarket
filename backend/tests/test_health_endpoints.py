"""The health surface, and the scrape endpoint it sits next to.

`test_metrics_endpoint_exists` is first because it pins a mistake actually made
while building this: `/metrics` sits between `/health` and `/health/ready` in
`app.py`, and a refactor that removed the two health endpoints as one block took
the Prometheus scrape endpoint with it. Nothing failed - the app booted, every
route resolved, every test that did not happen to ask still passed - and the
effect was that **every metric in the application silently stopped being
exported**. Monitoring does not fail when it stops receiving data; it just goes
quiet, which is the worst possible way for a monitoring system to break.

So the endpoint is asserted to exist and to serve exposition text. Cheap, and it
would have caught it in seconds.

The rest of this file covers the distinctions the endpoints exist to make, which
are easy to erase by accident because "one health endpoint" is simpler.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_metrics_endpoint_exists(client: AsyncClient):
    """The scrape endpoint must be there and must serve exposition text.

    If this fails after a refactor, the first thing to check is whether a block
    of routes was removed by range rather than by name.
    """
    resp = await client.get("/metrics")

    assert resp.status_code == 200, "the Prometheus scrape endpoint is missing"
    body = resp.text
    assert "ws_connects_total" in body or "# HELP" in body, (
        "metrics served no exposition text - an empty scrape looks identical to a "
        "healthy system that has simply stopped reporting"
    )


@pytest.mark.asyncio
async def test_ops_gauges_are_exported(client: AsyncClient):
    """The operational-debt gauges must actually appear in a scrape.

    A prometheus Gauge is only exported once something has set it, so declaring
    one and never refreshing it yields a metric that is absent rather than zero -
    and absent reads as "not collected" rather than "nothing is wrong".
    """
    resp = await client.get("/metrics")
    body = resp.text

    # Set them so the assertion is about the refresh, not about luck.
    from app.middleware.metrics import (
        CELERY_WORKERS_ALIVE,
        MARKETS_UNRESOLVED,
        MARKETS_UNRESOLVED_OLDEST_AGE,
    )

    CELERY_WORKERS_ALIVE.set(0)
    MARKETS_UNRESOLVED.set(0)
    MARKETS_UNRESOLVED_OLDEST_AGE.set(0)
    body = (await client.get("/metrics")).text

    for name in (
        "celery_workers_alive",
        "markets_unresolved",
        "markets_unresolved_oldest_age_seconds",
    ):
        assert name in body, f"{name} is declared but never exported"


# ── The four questions are different questions ────────────────────────────────


@pytest.mark.asyncio
async def test_liveness_answers_without_touching_a_dependency(client: AsyncClient):
    """Liveness must not consult Postgres.

    Restarting the process does not fix Postgres. If liveness consulted the
    database, every database blip would restart every API process - turning a
    recoverable outage into a crash loop that outlives the blip. This asserts the
    separation rather than trusting it.
    """
    resp = await client.get("/health/live")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["checks"] == {}, "liveness consulted a dependency"


@pytest.mark.asyncio
async def test_health_alias_is_liveness(client: AsyncClient):
    """`/health` must keep answering, because compose and nginx point at it.

    `docker-compose.dev.yml` probes `/health` and `docker-compose.prod.yml`
    probes `/health/ready`. Silently breaking a healthcheck is worse than any
    tidiness gained by moving the route.
    """
    for path in ("/health", "/health/live"):
        resp = await client.get(path)
        assert resp.status_code == 200, f"{path} no longer answers"
        assert resp.json()["status"] == "ok", path


@pytest.mark.asyncio
async def test_startup_reports_503_until_the_lifespan_has_finished(client: AsyncClient):
    """Startup must fail while booting, so a slow boot is not read as a crash."""
    from app.api import health

    health.mark_started()
    assert (await client.get("/health/startup")).status_code == 200

    # Simulate a process that has not finished coming up.
    original = health._STARTED
    try:
        health._STARTED = False
        resp = await client.get("/health/startup")
        assert resp.status_code == 503, (
            "startup reported ready before the lifespan finished - an "
            "orchestrator's liveness probe could kill a slow-booting container"
        )
    finally:
        health._STARTED = original


@pytest.mark.asyncio
async def test_readiness_reports_each_dependency_separately(client: AsyncClient):
    """The payload must say *which* dependency failed, not just that one did.

    An operator reading a health endpoint at 3am needs to know whether to look at
    the database or at Redis. "unavailable" with no detail sends them looking in
    both directions.
    """
    from app.api import health

    health._cached = None
    resp = await client.get("/health/ready")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body["checks"]) == {"db", "redis"}, (
        "readiness checks must be reported individually - and must not include "
        "Celery workers, which are not something serving traffic requires"
    )
    for name, check in body["checks"].items():
        assert "status" in check, name
        assert check["latency_ms"] is not None, (
            f"{name} failed to report a latency - an operator cannot tell a slow "
            f"dependency from a dead one"
        )


@pytest.mark.asyncio
async def test_readiness_goes_503_when_a_dependency_is_down(client: AsyncClient, monkeypatch):
    from app.api import health

    async def _dead():
        raise RuntimeError("connection refused")

    health._cached = None
    monkeypatch.setattr(health, "_check_redis", _dead)

    resp = await client.get("/health/ready")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["redis"]["status"] == "error"
    # The other dependency is still evaluated and reported, so the failure is
    # attributable rather than "something is wrong somewhere".
    assert "db" in body["checks"], (
        "the payload only reported the dependency that failed - an operator "
        "cannot tell which of two is at fault"
    )


@pytest.mark.asyncio
async def test_a_dependency_check_cannot_hang_the_endpoint(client: AsyncClient, monkeypatch):
    """A health endpoint that hangs is worse than one that is wrong.

    Probes arrive from an external balancer, so during an incident they land just
    as the connection pool is exhausted. An unbounded check turns that into a
    pile-up that outlives the incident it was reporting on.
    """
    import asyncio

    from app.api import health

    async def _wedged():
        await asyncio.sleep(3600)

    health._cached = None
    monkeypatch.setattr(health, "_check_db", _wedged)

    resp = await client.get("/health/ready")

    assert resp.status_code == 503
    assert "timeout" in resp.json()["checks"]["db"].get("error", "").lower()


@pytest.mark.asyncio
async def test_readiness_results_are_cached(client: AsyncClient):
    """Probes run every few seconds; each one should not be a fresh query.

    Without a cache every probe is a real DB and Redis round trip, and during an
    outage the checks become part of the load that caused it.
    """
    from app.api import health

    health._cached = None
    await client.get("/health/ready")
    cached_at, payload = health._cached
    assert payload["status"] == "ok"

    # A second call inside the TTL must reuse the cached result.
    await client.get("/health/ready")
    assert health._cached is not None
    assert health._cached[0] == cached_at, "readiness was recomputed inside the cache TTL"


# ── Details: the operator's view, and not the public's ────────────────────────


@pytest.mark.asyncio
async def test_details_withholds_operational_debt_from_anonymous_callers(client: AsyncClient):
    """Backlog and worker counts are not public information.

    They say how much money is sitting against markets that should have settled.
    An unauthenticated caller gets readiness and nothing more.
    """
    from app.api import health

    health._cached = None
    resp = await client.get("/health/details")

    assert resp.status_code == 200
    body = resp.json()
    assert "checks" in body
    assert "workers" not in body, (
        "an anonymous caller was shown the operational backlog - that is market "
        "and settlement information with no business being public"
    )


@pytest.mark.asyncio
async def test_details_includes_the_backlog_for_an_admin(client: AsyncClient, admin_user):
    from conftest import token_for

    from app.api import health

    health._cached = None
    client.cookies.set("access_token", token_for(admin_user.id))

    resp = await client.get("/health/details")

    assert resp.status_code == 200
    workers = resp.json()["workers"]
    assert "celery_workers_alive" in workers
    assert "markets_unresolved" in workers
    assert "markets_unresolved_oldest_age_s" in workers


# ── The rate limiter must not throttle infrastructure ────────────────────────


@pytest.mark.asyncio
async def test_health_paths_are_not_rate_limited(monkeypatch):
    """Every `/health*` path is exempt, not a hand-listed few.

    The exemption was an exact-match list of `/health` and `/health/ready`, so the
    liveness, startup and details paths added later silently fell *into* rate
    limiting - an orchestrator polling liveness would eventually get 429 and
    restart a healthy container, and the failure would look like an application
    problem rather than a missing list entry.

    Asserted by counting what actually reaches the limiter rather than by
    inspecting a list of paths, because a hand-listed set of paths is precisely
    the thing that drifts.
    """
    from fastapi.responses import JSONResponse
    from starlette.requests import Request

    from app.api import middleware as mw
    from app.services.rate_limit_service import RateLimitResult

    calls: list[str] = []

    async def _counted(_limit_type, _identifier, _ip=None):
        calls.append("checked")
        return RateLimitResult(
            allowed=True, limit=0, remaining=0, retry_after=None, is_slowdown=False
        )

    # Patched on the real class, not by replacing it, so `_normalize_ip` - which
    # client-IP resolution also uses - keeps working.
    monkeypatch.setattr(mw.RateLimitService, "check", _counted)

    async def _responder(*_args, **_kwargs):
        return JSONResponse({"status": "ok"})

    def _request(method: str, path: str) -> Request:
        # A real Request, so the middleware sees the attribute surface it
        # actually reads - client, scope, state, headers. A hand-rolled stand-in
        # fails in ways that say nothing about the behaviour under test.
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "scheme": "http",
            "headers": [],
            "client": ("203.0.113.9", 51234),
            "server": ("test", 80),
        }
        return Request(scope)

    middleware = mw.RateLimitMiddleware(app=_responder, enabled=True)

    for path in ("/health", "/health/live", "/health/startup", "/health/ready", "/health/details"):
        await middleware.dispatch(_request("GET", path), _responder)

    assert calls == [], (
        f"health paths reached the rate limiter: {len(calls)} call(s) - a probe "
        f"that gets 429 restarts a healthy container"
    )

    # And the exemption is not a blanket one. A POST, because GET is exempt on
    # every path - asserting with a GET would pass even if the limiter were off.
    await middleware.dispatch(_request("POST", "/api/v1/auth/login"), _responder)

    assert calls == ["checked"], (
        "a real request bypassed the rate limiter - the health exemption has "
        "become a general one"
    )
