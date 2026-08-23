# Stage 1: builder
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock* ./
RUN pip install uv && uv sync --frozen --no-dev --no-install-project

# Stage 2: production image
FROM python:3.12-slim

RUN groupadd --gid 1000 appgroup && useradd --uid 1000 --gid appgroup appuser

WORKDIR /app

# Install runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/app/.venv/bin:$PATH"

# Copy venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy app source
COPY . .

# Switch to non-root user
USER appuser

EXPOSE 8000

CMD ["gunicorn", "app.app:app", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "120"]
