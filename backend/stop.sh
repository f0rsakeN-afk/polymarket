#!/bin/bash
# ─── PredictX Backend Stop Script ────────────────────────────────────────────
# Stops FastAPI + Celery. Does NOT stop Docker (postgres/redis).

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$BASE_DIR/logs"

echo "[stop] Shutting down PredictX services..."

# Kill by PID files
for pidfile in "$LOG_DIR"/api.pid "$LOG_DIR"/worker.pid "$LOG_DIR"/beat.pid; do
  if [ -f "$pidfile" ]; then
    kill -9 "$(cat "$pidfile")" 2>/dev/null && echo "[stop] Stopped $(basename $pidfile)" || true
    rm -f "$pidfile"
  fi
done

# Kill any remaining uvicorn/celery processes
pkill -9 -f "uvicorn app.main:app" 2>/dev/null && echo "[stop] Stopped uvicorn" || true
pkill -9 -f "celery.*worker" 2>/dev/null && echo "[stop] Stopped celery worker" || true
pkill -9 -f "celery.*beat" 2>/dev/null && echo "[stop] Stopped celery beat" || true

echo "[stop] Done. Docker services (postgres/redis) are still running."
