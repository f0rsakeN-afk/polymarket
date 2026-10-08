FROM python:3.13-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.13-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1001 appuser \
    && useradd -u 1001 -g 1001 -M -s /usr/sbin/nologin appuser

COPY --from=builder /app/.venv /app/.venv

# --chown in the COPY itself: a separate `chown -R` would duplicate the whole
# tree in its own layer, roughly doubling the image.
COPY --chown=appuser:appuser . .

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s CMD curl -f http://localhost:8000/health/ready || exit 1

USER appuser

EXPOSE 8000

CMD ["gunicorn", "--config", "gunicorn.conf.py", "app.app:app"]
