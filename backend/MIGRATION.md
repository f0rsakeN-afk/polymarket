# Production Migration Guide

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

**22 migrations exist** — always use Alembic in production:
```bash
# Dry run first
alembic upgrade --sql

# Apply in order (run once, not on every deploy)
alembic upgrade head

# Verify
alembic current
alembic history --enum_size=medium
```

The app's `lifespan` auto-creates tables on startup only if no tables exist (first boot). After first boot, **always use migrations** — never rely on `lifespan` for schema changes.

### Migration Strategy

```bash
# 1. Backup DB
pg_dump -Fc mydatabase > backup_$(date +%Y%m%d).dump

# 2. Run migrations (run in a transaction, lock the migration table)
alembic upgrade head

# 3. Rollback plan (always have one)
alembic downgrade -1
```

### First Production Boot

The app will **fail to start** if these placeholders are still set:
- `totp_encryption_key = "change-me-in-production"` → RuntimeError
- `jwt_secret = "change-me-in-production"` → RuntimeError
- `secret_key = "change-me-in-production"` → RuntimeError

Set all three before starting the container.

---

## Docker Compose Production Stack

See `deploy/docker-compose.prod.yml` for the full stack:
- **nginx** — reverse proxy, SSL termination, rate limiting
- **FastAPI app** — gunicorn (4 workers, uvicorn)
- **Celery worker** — async task processing
- **Celery beat** — scheduled tasks
- **PostgreSQL** — external (not in compose)
- **Redis** — external (not in compose, use Sentinel for HA)

### Deploy
```bash
docker compose -f deploy/docker-compose.prod.yml up -d
```

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

Key scheduled tasks:
- `sync_amm_prices` — keeps AMM prices in Redis (every 30s via Celery beat)
- `snapshot_price_history` — OHLCV candles for price charts (every 5min via beat)
- `check_limit_order_execution` — executes limit orders when price crosses threshold (every 1min)
- `check_markets_ready_to_resolve` — auto-resolves markets past close date (every 5min)
- `check_price_alerts` — fires price alert notifications (every 1min)
- `cleanup_expired_sessions` — purges old revoked sessions (daily)

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
- **Token blacklist fail-open** — if Redis is down, revoked tokens work until natural expiry (15 min). Redis Sentinel HA eliminates this window.
