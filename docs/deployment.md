# Production Migration Guide

> Moved here from `backend/MIGRATION.md` • all project documentation lives in `/docs`.
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
| `JWT_SECRET` | ✅ required | JWT signing key • must be stable across restarts |
| `SECRET_KEY` | ✅ required | General app secret |
| `TOTP_ENCRYPTION_KEY` | ✅ required | 2FA secret encryption key |
| `TRUSTED_PROXY_IPS` | ⚠️ recommended | Proxy CIDRs (e.g. `10.0.0.0/8,172.16.0.0/12`) |
| `REDIS_SENTINEL_URLS` | ⚠️ for HA | Sentinel node URLs for Redis failover |
| `STRIPE_SECRET_KEY` | ⚠️ for payments | Stripe API key |
| `STRIPE_WEBHOOK_SECRET` | ⚠️ for payments | Stripe webhook signing secret |

### Database Migrations

**5 migrations exist** (initial squashed schema + 4 follow-ups) • always use Alembic in production:
```bash
# Dry run first
alembic upgrade --sql

# Apply in order (run once, not on every deploy)
alembic upgrade head

# Verify
alembic current
alembic history --enum_size=medium
```

The app no longer auto-creates tables on startup. **Always run migrations before starting the API** • on first boot and after every schema change. Never rely on auto-creation for schema changes.

### Migration Strategy

```bash
# 1. Backup DB • timestamped custom-format dump, verified with pg_restore --list,
#    pruned only after a good dump exists (script: backend/scripts/backup_db.sh)
PGHOST=db.prod PGPORT=5432 PGUSER=app PGDATABASE=app \
  ./scripts/backup_db.sh                 # keep 14 days (RETENTION_DAYS=30 to change)

# 2. Run migrations (run in a transaction, lock the migration table)
alembic upgrade head

# 3. Rollback plan (always have one)
alembic downgrade -1
```

Connection settings come from `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`, falling back
to the dev stack, so the same script is used locally and in production • export the variables in
the cron job that runs it:

```cron
# nightly 02:15, keep 30 days, pointing at production
15 2 * * * PGHOST=db.prod PGPORT=5432 PGUSER=app PGDATABASE=app PGPASSWORD=... \
  /opt/PredictX/backend/scripts/backup_db.sh >> /var/log/PredictX-backup.log 2>&1
```

Restores are deliberately manual: `./scripts/backup_db.sh --restore latest` (or a filename in
`BACKUP_DIR`, default `~/backups/PredictX`). The script exits non-zero rather than pruning when
a dump fails verification, and prints the count of dumps retained.

### Escrow invariant audit

`settle_market` refuses to run if a pool's escrow cannot cover what it owes, which is correct but
only tells you at resolution. A nightly Celery task (`audit-escrow-invariants`, 4am, after the fee
sweep) re-checks every pool: `collateral >= max(open YES, open NO) + protocol_fees`, fees backed
by collateral, LP share rows not exceeding `lp_token_supply`, no negative escrow, and no positions
owed on a market with no pool. Violations are logged as structured `ERROR`s with the market id.

Run it on demand • exit code 1 means "violations found", so it drops straight into a cron or a
monitoring check:

```bash
cd backend
./scripts/audit_escrow.py                    # everything, human-readable
./scripts/audit_escrow.py --market <uuid>    # one market, while investigating
./scripts/audit_escrow.py --json             # machine-readable
```

It only reports; it never repairs a ledger, because a repair written by something that doesn't
understand the drift is how a rounding bug becomes a loss. Wire the exit code into whatever
alerts you have • an audit nobody is paged for is the current weakest link.

### First Production Boot

The app will **fail to start** if these placeholders are still set:
- `totp_encryption_key = "change-me-in-production"` → RuntimeError
- `jwt_secret = "change-me-in-production"` → RuntimeError
- `secret_key = "change-me-in-production"` → RuntimeError

Set all three before starting the container.

---

## Docker Compose Production Stack

See `backend/docker-compose.prod.yml` for the full stack:
- **nginx** • reverse proxy, SSL termination, rate limiting
- **FastAPI app** • gunicorn (8 UvicornWorkers, one event loop each)
- **Celery worker** • async task processing
- **Celery beat** • scheduled tasks
- **PostgreSQL** • external (not in compose)
- **Redis** • external (not in compose, use Sentinel for HA)

### Deploy

Deploys are manual on purpose • there is **no deploy workflow in CI** (an earlier
`.github/workflows/deploy.yml` was removed because nothing was deploying from GitHub):

```bash
cd backend
docker compose -f docker-compose.prod.yml up -d
```

### The frontend stack

`frontend/docker-compose.prod.yml` runs **two** applications from **one** image:

| Service | Port (internal) | What it is |
|---|---|---|
| `web` | 3000 | The storefront |
| `admin` | 3001 | The operator tool |
| `nginx` | 80 | Reverse proxy, routes both |

One image because the build is the expensive part and the two apps are always
released together. Two services because the runtime is scaled, restarted and taken
down independently — an operator tool on a box that is out of memory should take
the operator tool down, not the site. `admin` is `expose`d and not published, so
the only thing that can reach it is nginx.

**`ADMIN_SERVER_NAME` must be set** to the admin hostname (for example
`admin.example.com`). It is what nginx matches on, and it defaults to `_` so an
unset value leaves the storefront as the default vhost rather than breaking
startup. The admin app's routes are `/users`, `/disputes`, `/markets`, `/treasury`,
`/audit` and `/login` — not under an `/admin` prefix — which is why this is
host-based routing and not a path.

### `COOKIE_SAMESITE` — read this before deploying the admin app

The auth cookies' `SameSite` is deployment topology, not an application setting:

| Deployment | `COOKIE_SAMESITE` |
|---|---|
| One site (API and front ends on one hostname) | `lax` |
| Admin on a separate hostname (`admin.example.com` vs `api.example.com`) | `none`, with `APP_ENV=production` |

Two failure modes, both silent, both producing an operator who is permanently
signed out with nothing in any log:

- **`lax` across sites.** The browser never sends the cookie. Login returns 200,
  `Set-Cookie` arrives, `/auth/me` 401s forever.
- **`none` without HTTPS.** Browsers *discard* a `SameSite=None` cookie that is
  not `Secure`. Same symptom, opposite cause.

The API refuses to start on that second pair rather than warning about it, because
a warning is not actionable against a symptom that looks like an unrelated bug.

Why none of it reproduces locally: **SameSite ignores ports**, so `localhost:3000`,
`:3001` and `:8000` are one site and `lax` is correct. The bug only exists once the
hostnames differ.

What CI *does* run on every push (`.github/workflows/ci.yml`, at the repo root • GitHub only
picks workflows up from the root `.github/`, which is why they moved out of `backend/.github/`):

| Job | What it gates on |
|---|---|
| `backend` | postgres:16 + redis:7 services, `uv run ruff check app tests`, `uv run pytest --cov=app --cov-fail-under=65` |
| `frontend` | `bun install --frozen-lockfile`, `bun run lint` (0 errors), `bun run typecheck` in `apps/web` |
| `security-scan` | Trivy filesystem + config scans, SARIF uploaded **report-only** (`continue-on-error`) • findings are visible without blocking a deploy nobody runs |

The test suite builds its own schema from `alembic upgrade head`, so CI needs no migration step.
`celery beat` also schedules `audit-escrow-invariants` at 4am • the beat schedule lives in
`app/workers/celery_app.py`, so a worker without beat running will quietly skip it (as it skips the
order sweeper).

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
- `expire_stale_orders` • frees locked funds on expired orders (every 30 s)
- `check_limit_order_execution` • re-tests resting limit orders against the AMM price (every 30 s)
- `sync_amm_prices` • re-announces prices, only when |Δ| > 0.0001 (every 60 s)
- `check_markets_ready_to_resolve` • auto-resolves markets past close date (every 5 min)
- `snapshot_price_history` • OHLCV candles for price charts (every 5 min)
- `cleanup_expired_sessions` • purges old revoked sessions (daily, 03:00)
- `distribute_protocol_fees` • sweeps `pool.protocol_fees` to the treasury (daily, 03:30)

Event-driven, not scheduled: `check_price_alerts` fires from `sync_amm_prices` whenever a price
actually moves.

---

## Structured Logs

Non-debug mode emits JSON logs:
```json
{"timestamp": "2026-08-22T14:30:01", "level": "INFO", "logger": "PredictX", "message": "...", "request_id": "...", "trace_id": "...", "method": "POST", "path": "/api/v1/orders/", "status_code": 200, "latency_ms": 14.2, "client_ip": "1.2.3.4"}
```

Ship logs to your aggregator (Datadog, Loki, ELK) via stdout → log shipper (filebeat, fluentd, vector).

---

## Security Notes

- **Docs disabled in prod** • `/docs`, `/redoc`, `/openapi.json` are only available when `DEBUG=true`
- **CSP headers** • Content-Security-Policy set via Next.js `next.config.ts` on the frontend
- **Refresh token hashing** • tokens stored as SHA-256 hashes in DB, not plaintext
- **OTP rate limiting** • 5 codes per 5 min per email+purpose
- **Token blacklist fails closed in production** • if Redis is down, revoked tokens are *rejected*
  rather than accepted (deny-by-default). Development fails open so a Redis restart doesn't break
  the dev loop. The blacklist *write* fails closed everywhere: a logout that can't be recorded is
  refused instead of silently succeeding.

### If an image is built from packages nobody declared

The builder stage copies the workspace install **after** the source, on purpose.
The other order looks tidier and is a trap: `COPY apps/web/ ./apps/web/` merges
the build context into a tree that already holds the installed `node_modules`, and
where a developer's `node_modules` reaches the context the context wins.

The tell is a `node_modules/.bin/next` symlink pointing at a version the image
does not contain — the build then fails with `next: command not found`, or worse,
succeeds and ships an image from whatever that machine had installed.

`.dockerignore` is supposed to prevent this. Do not rely on it alone: the copy
order is the actual control. Check with:

```bash
docker run --rm --entrypoint sh <image> -c 'readlink apps/web/node_modules/next'
```

### Regenerating `bun.lock`

Two rules, both learned the hard way, and both with the same failure: the lockfile
ends up bumped by a minor version of everything while the diff reads as incidental.

1. **Never mount the repo read-write into a container that runs `bun install`.**
   `docker run -v "$PWD":/app oven/bun bun install` resolves against whatever is
   newest on the registry and writes `bun.lock` **and every `package.json`** back
   into the host tree. Reverting only the lockfile leaves `package.json` demanding
   `next@16.4.2` against a lockfile pinning `16.3.3`, and the next frozen install
   fails — which looks like a stale lockfile rather than a dirty working tree.

2. **Use the version the repo declares.** `package.json`'s `packageManager` is the
   source of truth and CI installs exactly that. Bun versions disagree about
   lockfile format, so resolving with a different one re-resolves every semver
   range. To regenerate:

   ```bash
   # copy the tree, install in the copy, then copy the lockfile back
   cp -r frontend /tmp/lockgen && cd /tmp/lockgen
   docker run --rm -v "$PWD":/app oven/bun:1.3.14-slim bun install
   ```

   Then read the diff before committing it. A correct regeneration moves a handful
   of lines; one that touches every `@next/swc-*` entry is a resolution, not a
   repair.

### Running the dev containers as your own user

The dev image runs as the image's `bun` user (uid 1000), not root, so a dev server
cannot write root-owned files into the repository. For the bind mount to be
writable from inside the container, that uid has to match yours:

```bash
export DOCKER_UID=$(id -u) DOCKER_GID=$(id -g)
cd frontend && docker compose -f docker-compose.dev.yml up
```

Put those two in your shell profile and they stop being a thing to remember. The
default of `1000:1000` matches the official Node and Bun images, so most people
never need to set them — but "most people" is not a property a build should depend
on, and the failure is a permission error partway through a first compile, which
reads as anything except a uid mismatch.
