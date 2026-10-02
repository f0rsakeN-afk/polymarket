# Production Migration Guide

> Moved here from `backend/MIGRATION.md` — all project documentation lives in `/docs`.
> Run every command below from the **`backend/`** directory (`cd backend` first), where
> `alembic.ini`, `pyproject.toml` and the compose files live.

## Pre-Deployment Checklist

### Required Environment Variables

Generate secure values before deploying:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

| Variable | Generated | Description |
|---|---|---|
| `JWT_SECRET` | ✅ required | JWT signing key — must be stable across restarts |
| `SECRET_KEY` | ✅ required | General app secret |
| `TOTP_ENCRYPTION_KEY` | ✅ required | 2FA secret encryption key |
| `TRUSTED_PROXY_IPS` | ⚠️ recommended | Proxy CIDRs (e.g. `10.0.0.0/8,172.16.0.0/12`) |
| `REDIS_SENTINEL_URLS` | ⚠️ for HA | Sentinel node URLs for Redis failover |
| `STRIPE_SECRET_KEY` | ⚠️ for payments | Stripe API key |
| `STRIPE_WEBHOOK_SECRET` | ⚠️ for payments | Stripe webhook signing secret |

### Database Migrations

**5 migrations exist** (initial squashed schema + 4 follow-ups) — always use Alembic in production:
```bash
# Dry run first
alembic upgrade --sql

# Apply in order (run once, not on every deploy)
alembic upgrade head

# Verify
alembic current
alembic history --enum_size=medium
```

The app no longer auto-creates tables on startup. **Always run migrations before starting the API** — on first boot and after every schema change. Never rely on auto-creation for schema changes.

### Migration Strategy

```bash
# 1. Backup DB — timestamped custom-format dump, verified with pg_restore --list,
#    pruned only after a good dump exists (script: backend/scripts/backup_db.sh)
PGHOST=db.prod PGPORT=5432 PGUSER=app PGDATABASE=app \
  ./scripts/backup_db.sh                 # keep 14 days (RETENTION_DAYS=30 to change)

# 2. Run migrations (run in a transaction, lock the migration table)
alembic upgrade head

# 3. Rollback plan (always have one)
alembic downgrade -1
```

Connection settings come from `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`, falling back
to the dev stack, so the same script is used locally and in production — export the variables in
the cron job that runs it:

```cron
# nightly 02:15, keep 30 days, pointing at production
15 2 * * * PGHOST=db.prod PGPORT=5432 PGUSER=app PGDATABASE=app PGPASSWORD=... \
  /opt/polymarket/backend/scripts/backup_db.sh >> /var/log/polymarket-backup.log 2>&1
```

Restores are deliberately manual: `./scripts/backup_db.sh --restore latest` (or a filename in
`BACKUP_DIR`, default `~/backups/polymarket`). The script exits non-zero rather than pruning when
a dump fails verification, and prints the count of dumps retained.

### First Production Boot

The app will **fail to start** if these placeholders are still set:
- `totp_encryption_key = "change-me-in-production"` → RuntimeError
- `jwt_secret = "change-me-in-production"` → RuntimeError
- `secret_key = "change-me-in-production"` → RuntimeError

Set all three before starting the container.

---

## Docker Compose Production Stack

See `backend/docker-compose.prod.yml` for the full stack:
- **nginx** — reverse proxy, SSL termination, rate limiting
- **FastAPI app** — gunicorn (8 UvicornWorkers, one event loop each)
- **Celery worker** — async task processing
- **Celery beat** — scheduled tasks
- **PostgreSQL** — external (not in compose)
- **Redis** — external (not in compose, use Sentinel for HA)

### Deploy

Deploys are manual on purpose — there is **no deploy workflow in CI** (an earlier
`.github/workflows/deploy.yml` was removed because nothing was deploying from GitHub):

```bash
cd backend
docker compose -f docker-compose.prod.yml up -d
```

What CI *does* run on every push (`.github/workflows/ci.yml`, at the repo root — GitHub only
picks workflows up from the root `.github/`, which is why they moved out of `backend/.github/`):

| Job | What it gates on |
|---|---|
| `backend` | postgres:16 + redis:7 services, `uv run ruff check app tests`, `uv run pytest --cov=app --cov-fail-under=65` |
| `frontend` | `bun install --frozen-lockfile`, `bun run lint` (0 errors), `bun run typecheck` in `apps/web` |
| `security-scan` | Trivy filesystem + config scans, SARIF uploaded **report-only** (`continue-on-error`) — findings are visible without blocking a deploy nobody runs |

The test suite builds its own schema from `alembic upgrade head`, so CI needs no migration step.

---

## Health Checks

```bash
# Liveness (is app alive?)
GET /health
→ {"status": "ok"}

# Readiness (is app ready to serve traffic?)
GET /health/ready
→ {"status": "ok", "checks": {"db": {"status": "ok", "latency_ms": 2.1}, "redis": {"status": "ok", "latency_ms": 0.8}}, "version": "1.0.0"}
```

Use `/health/ready` for k8s readiness probes and load balancer health checks.

---

## Redis Sentinel (HA)

If `REDIS_SENTINEL_URLS` is set, the app connects via Sentinel automatically:
```
REDIS_SENTINEL_URLS=redis://sentinel-1:26379,redis://sentinel-2:26379
REDIS_SENTINEL_SERVICE_NAME=mymaster
```
If Sentinel URLs are not set, app falls back to `REDIS_URL`.

**Minimum Sentinel deployment:** 3 sentinel processes across 3 nodes. 1 can fail and the cluster remains available.

---

## Trusted Proxies

If behind a reverse proxy (nginx, Caddy, Cloudflare, LB):
```bash
TRUSTED_PROXY_IPS=10.0.0.0/8,172.16.0.0/12
```
Without this, `X-Forwarded-For` is ignored and all clients appear as the proxy IP.

---

## Celery Tasks

All background tasks log structured JSON with `task_id`, `task_name`, `duration_ms`:
```
{"event": "task_start", "task_id": "...", "task_name": "app.workers.tasks.sync_amm_prices"}
{"event": "task_complete", "task_id": "...", "task_name": "app.workers.tasks.sync_amm_prices", "duration_ms": 142.3}
```

Key scheduled tasks (cadence from `app/workers/celery_app.py`):
- `expire_stale_orders` — frees locked funds on expired orders (every 30 s)
- `check_limit_order_execution` — re-tests resting limit orders against the AMM price (every 30 s)
- `sync_amm_prices` — re-announces prices, only when |Δ| > 0.0001 (every 60 s)
- `check_markets_ready_to_resolve` — auto-resolves markets past close date (every 5 min)
- `snapshot_price_history` — OHLCV candles for price charts (every 5 min)
- `cleanup_expired_sessions` — purges old revoked sessions (daily, 03:00)
- `distribute_protocol_fees` — sweeps `pool.protocol_fees` to the treasury (daily, 03:30)

Event-driven, not scheduled: `check_price_alerts` fires from `sync_amm_prices` whenever a price
actually moves.

---

## Structured Logs

Non-debug mode emits JSON logs:
```json
{"timestamp": "2026-08-22T14:30:01", "level": "INFO", "logger": "polymarket", "message": "...", "request_id": "...", "trace_id": "...", "method": "POST", "path": "/api/v1/orders/", "status_code": 200, "latency_ms": 14.2, "client_ip": "1.2.3.4"}
```

Ship logs to your aggregator (Datadog, Loki, ELK) via stdout → log shipper (filebeat, fluentd, vector).

---

## Security Notes

- **Docs disabled in prod** — `/docs`, `/redoc`, `/openapi.json` are only available when `DEBUG=true`
- **CSP headers** — Content-Security-Policy set via Next.js `next.config.ts` on the frontend
- **Refresh token hashing** — tokens stored as SHA-256 hashes in DB, not plaintext
- **OTP rate limiting** — 5 codes per 5 min per email+purpose
- **Token blacklist fails closed in production** — if Redis is down, revoked tokens are *rejected*
  rather than accepted (deny-by-default). Development fails open so a Redis restart doesn't break
  the dev loop. The blacklist *write* fails closed everywhere: a logout that can't be recorded is
  refused instead of silently succeeding.
