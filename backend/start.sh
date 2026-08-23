#!/bin/bash
# ─── PredictX Backend Start Script ────────────────────────────────────────────
# Starts all local services. Postgres/Redis are expected to be in Docker.
# Usage: ./start.sh

set -e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$BASE_DIR/logs"
mkdir -p "$LOG_DIR"

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; RESET='\033[0m'

log()  { echo -e "${GREEN}[start]${RESET} $1"; }
warn() { echo -e "${YELLOW}[warn]${RESET} $1"; }
info() { echo -e "${CYAN}[info]${RESET} $1"; }

# ─── Helpers ─────────────────────────────────────────────────────────────────
cleanup() {
  log "Shutting down..."
  jobs -p | xargs kill -9 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM

# ─── Docker Services ─────────────────────────────────────────────────────────
start_docker_services() {
  if docker ps --format '{{.Names}}' | grep -q 'postgres\|postgresql'; then
    info "PostgreSQL container already running"
  else
    warn "PostgreSQL not running — make sure Docker is up"
  fi

  if docker ps --format '{{.Names}}' | grep -q 'redis'; then
    info "Redis container already running"
  else
    warn "Redis not in Docker — make sure it's running"
  fi
}

# ─── FastAPI ──────────────────────────────────────────────────────────────────
start_api() {
  log "Starting FastAPI (8 uvicorn workers)..."
  cd "$BASE_DIR"
  # 8 workers, each with its own event loop + Redis pub/sub listener
  uv run uvicorn app.app:app --host 0.0.0.0 --port 8000 --workers 8 \
    > "$LOG_DIR/api.log" 2>&1 &
  echo $! > "$LOG_DIR/api.pid"
  info "API running at http://localhost:8000"
  info "API docs at http://localhost:8000/docs"
}

# ─── Celery Worker ─────────────────────────────────────────────────────────────
start_worker() {
  log "Starting Celery worker..."
  cd "$BASE_DIR"
  uv run celery -A app.workers.celery_app worker \
    --loglevel=info \
    --hostname=worker1@%h \
    > "$LOG_DIR/worker.log" 2>&1 &
  echo $! > "$LOG_DIR/worker.pid"
  info "Celery worker started"
}

# ─── Celery Beat ──────────────────────────────────────────────────────────────
start_beat() {
  log "Starting Celery beat (scheduler)..."
  cd "$BASE_DIR"
  uv run celery -A app.workers.celery_app beat \
    --loglevel=info \
    > "$LOG_DIR/beat.log" 2>&1 &
  echo $! > "$LOG_DIR/beat.pid"
  info "Celery beat started"
}

# ─── Main ─────────────────────────────────────────────────────────────────────
log "PredictX backend starting..."
start_docker_services
start_api
sleep 3
start_worker
start_beat

echo ""
log "All services started!"
echo ""
echo -e "  ${CYAN}API${RESET}    http://localhost:8000"
echo -e "  ${CYAN}Docs${RESET}   http://localhost:8000/docs"
echo -e "  ${CYAN}Redis${RESET}  Docker (port 6382)"
echo -e "  ${CYAN}PG${RESET}     Docker (port 5432)"
echo -e "  ${CYAN}Logs${RESET}   $LOG_DIR/{api,worker,beat}.log"
echo ""
info "Press Ctrl+C to stop API + workers"

tail -q -f "$LOG_DIR/api.log" "$LOG_DIR/worker.log" "$LOG_DIR/beat.log" &
wait
