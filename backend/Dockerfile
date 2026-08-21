FROM python:3.13-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set Python vars
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/app/.venv/bin:$PATH"

# Install Python deps
COPY pyproject.toml uv.lock* ./
RUN pip install uv && uv sync --frozen --no-dev

# Copy app
COPY . .

# Run: single worker (Docker compose deploy.replicas handles horizontal scaling)
CMD ["uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "8000"]

