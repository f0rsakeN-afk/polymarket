#!/bin/bash
# ─── Start all Celery workers ─────────────────────────────────────────────────
# Run from backend/ directory: ./start-workers.sh

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$BASE_DIR/logs"
mkdir -p "$LOG_DIR"

cd "$BASE_DIR"

echo "[workers] Starting Celery worker + beat..."
uv run celery -A app.workers.celery_app worker --loglevel=info > "$LOG_DIR/worker.log" 2>&1 &
echo $! > "$LOG_DIR/worker.pid"
echo "[workers] Worker started (PID $(cat "$LOG_DIR/worker.pid"))"

uv run celery -A app.workers.celery_app beat --loglevel=info > "$LOG_DIR/beat.log" 2>&1 &
echo $! > "$LOG_DIR/beat.pid"
echo "[workers] Beat started (PID $(cat "$LOG_DIR/beat.pid"))"

echo "[workers] Both running. Logs: $LOG_DIR/{worker,beat}.log"
