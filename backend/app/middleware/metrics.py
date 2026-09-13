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
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("polymarket")

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


def _route_template(request: Request) -> str:
    # scope["route"] is populated by the router downstream; read AFTER call_next.
    # Fall back to the raw path (may carry IDs — acceptable for unmapped paths).
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
