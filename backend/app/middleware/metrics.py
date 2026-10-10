"""
Prometheus HTTP metrics.

Gunicorn-safe: when PROMETHEUS_MULTIPROC_DIR is set (see docker-compose),
per-worker values are aggregated across processes via MultiProcessCollector.
Without it, metrics work in single-process mode (local dev, tests).
"""

import logging
import os
import time
from collections.abc import Callable

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("PredictX")

REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "route", "status"],
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
)

# ── WebSocket / realtime ───────────────────────────────────────────────────────
#
# Without these there is no way to answer "how close to capacity are we?", which
# makes the 50k-connection design a claim rather than a measurement. Live gauges
# are set from ConnectionManager (in-process state, so `.inc()/.dec()` on
# connect/disconnect is exact); the counters are monotonic event totals.
#
# `ws_connections` is PER PROCESS • the connection caps are per process too (see
# `ConnectionManager` docstring), so fleet-wide totals are the sum across workers.
WS_CONNECTIONS = Gauge(
    "ws_connections",
    "Currently open WebSocket connections held by this worker",
)
WS_SUBSCRIPTIONS = Gauge(
    "ws_subscriptions",
    "Current market subscriptions held by this worker",
)
WS_CONNECTS_TOTAL = Counter(
    "ws_connects_total",
    "WebSocket connection attempts by outcome",
    ["outcome"],  # accepted | rejected_ip | rejected_user
)
WS_DISCONNECTS_TOTAL = Counter(
    "ws_disconnects_total",
    "WebSocket disconnects by cause",
    ["cause"],  # client | limit | send_failed | heartbeat | shutdown
)
WS_SENDS_TOTAL = Counter(
    "ws_sends_total",
    "Frames handed to the socket, by result",
    ["result"],  # ok | failed | timeout
)
WS_MESSAGES_FANNED_OUT = Counter(
    "ws_messages_fanned_out_total",
    "Realtime frames fanned out to local sockets, by channel class",
    ["channel"],  # market | user | global
)
# A publish that never reached Redis. Previously every publisher ended in
# `except redis.RedisError: pass`, so a Redis outage deleted trades, price
# frames AND the `dirty:markets` marker that drives the limit-order executor,
# with nothing in logs and nothing to alert on. This makes silence visible.
WS_PUBLISH_FAILURES = Counter(
    "ws_publish_failures_total",
    "Realtime frames that failed to publish to Redis, by frame type",
    ["frame"],  # price_update | trade | order_fill | notification | user_event
    #            | market_event | global_trade
)


def _route_template(request: Request) -> str:
    # scope["route"] is populated by the router downstream; read AFTER call_next.
    # Fall back to the raw path (may carry IDs • acceptable for unmapped paths).
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template or request.url.path


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)

        # Labels need the route template, known only after routing ran.
        # Track in-progress under method only, then relabel precisely.
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            template = _route_template(request)
            REQUESTS_TOTAL.labels(request.method, template, "500").inc()
            raise
        latency = time.perf_counter() - start
        template = _route_template(request)
        REQUESTS_TOTAL.labels(request.method, template, str(response.status_code)).inc()
        REQUEST_DURATION.labels(request.method, template).observe(latency)
        return response


def metrics_response() -> Response:
    """Render metrics, aggregating across gunicorn workers when configured."""
    multiprocess_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if multiprocess_dir:
        from prometheus_client import CollectorRegistry, multiprocess
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        data = generate_latest(registry)
    else:
        data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


def clean_multiproc_dir() -> None:
    """Remove stale per-worker metric files from a previous run.

    Called once at worker startup (lifespan). Safe under races: removing an
    already-removed file is a no-op.
    """
    multiprocess_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not multiprocess_dir:
        return
    import glob

    for path in glob.glob(os.path.join(multiprocess_dir, "*.db")):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"Could not clean metric file {path}: {e}")
