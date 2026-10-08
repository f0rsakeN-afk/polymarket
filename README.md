# PredictX • Prediction Market Platform

A PredictX-style exchange for event outcomes: an order book plus an automated market maker, with
wallets, positions, settlement at $1 per correct share, and realtime prices over WebSockets.

> **All project documentation lives in [`docs/`](docs/README.md)** • start there.

## Documentation

| I want to… | Read |
|---|---|
| Understand the product with no jargon | [`docs/concepts.md`](docs/concepts.md) |
| Rehearse for a viva / defence | [`docs/viva-questions.md`](docs/viva-questions.md) (322 questions + answers) |
| Run the live demo | [`docs/demo-script.md`](docs/demo-script.md) (7-phase script + troubleshooting) |
| Understand testing & CI | [`docs/testing-and-ci.md`](docs/testing-and-ci.md) |
| Know what the database actually stores and guarantees | [`docs/data-model.md`](docs/data-model.md) |
| Understand matching, AMM maths, split/merge, "is this gambling?" | [`docs/trading-engine.md`](docs/trading-engine.md) |
| Understand moderation, disputes, alerts, fees, errors | [`docs/platform-features.md`](docs/platform-features.md) |
| Understand auth and security | [`docs/auth-and-security.md`](docs/auth-and-security.md) |
| Understand Docker, concurrency and realtime | [`docs/docker-concurrency-realtime.md`](docs/docker-concurrency-realtime.md) |
| Understand background jobs, caching, rate limits, monitoring | [`docs/background-jobs.md`](docs/background-jobs.md) |
| Understand the frontend (Next 16 / React 19) | [`docs/frontend.md`](docs/frontend.md) |
| See how the system is built | [`docs/architecture.md`](docs/architecture.md) |
| Deploy to production | [`docs/deployment.md`](docs/deployment.md) |
| Find the index / reading order | [`docs/README.md`](docs/README.md) |

## Repository layout

```
backend/    FastAPI + async SQLAlchemy/Postgres + Redis + Celery, Dockerfiles, compose files
frontend/   Bun + Turborepo monorepo: apps/web (Next.js 16 / React 19), packages/ui
docs/       All project documentation (this is the only place docs live)
```

## Dev setup

Prerequisites: Docker, Python 3.14+ with [uv](https://docs.astral.sh/uv/), Bun 1.3+.

**One-time setup**

```bash
cd backend
cp .env.example .env          # fill in DB_PASSWORD, JWT_SECRET, TOTP_ENCRYPTION_KEY
uv sync                       # install Python dependencies
cd ../frontend && bun install # install JS dependencies
```

**Infrastructure** — Postgres on `:5433`, Redis on `:6380`:

```bash
cd backend
docker compose -f docker-compose.dev.yml up -d
```

**Create the schema and fill it with demo data**

```bash
cd backend
uv run alembic upgrade head    # apply migrations
PYTHONPATH=. uv run python scripts/seed.py   # 17 markets, 20 accounts, trades, charts
```

The seed is idempotent — it skips anything already present, so re-running it tops
up rather than duplicating.

**Demo accounts**

| Email | Password | Role | Use it to show |
|---|---|---|---|
| `admin@predictx.io` | `testpass123` | admin | market approval, moderation, disputes, resolution |
| `demo@predictx.io` | `testpass123` | trader | wallet, portfolio, positions, order placement |

Override the password with `SEED_PASSWORD=... python scripts/seed.py` before
seeding. Both accounts have `is_email_verified=True`, so there is no confirmation
step in the way.

The seed also creates 18 background accounts (`alice@predictx.io` and so on, same
password). They are **not** login accounts — they exist so the trade feed, comment
threads and leaderboards are not all attributed to the demo user, which reads as
fabricated. The two above are the documented way in.

**What gets seeded**

| | |
|---|---|
| Markets | 17 — 15 binary, 2 parimutuel (an 8-way football winner, a 6-way NBA championship) |
| Resolved markets | 5, with winners, and charts that settle at $1.00 / $0.00, so settlement and claims are demoable |
| Trades | ~2,500, each priced against its own outcome's live price |
| Price history | ~48 points per outcome over ~30 days, ending exactly at the current price |
| Positions | every market has holders, every trader has a portfolio |
| Resting orders | ~136, all with `remaining ≤ amount` |
| Comments | every market has a thread, with replies |
| Also | wallets, transactions, LP shares, alerts, notifications, disputes, flags, referrals, treasury |

**Run it** — three terminals:

```bash
cd backend && ./start.sh                       # API :8000 + celery worker + beat
cd frontend && bun run dev                      # http://localhost:3000
```

`start.sh` runs Postgres/Redis check, then API, worker and beat together, logging
to `backend/logs/{api,worker,beat}.log`. To run them separately instead:

```bash
cd backend
uv run uvicorn app.app:app --host 0.0.0.0 --port 8000 --workers 8
uv run celery -A app.workers.celery_app worker --loglevel=info
uv run celery -A app.workers.celery_app beat   --loglevel=info
```

Then check it is alive:

```bash
curl localhost:8000/health     # {"status":"ok", ...}
open http://localhost:3000
```

**Reset the database** — drops everything and rebuilds from migrations. Needed
after any schema change:

```bash
cd backend
docker compose -f docker-compose.dev.yml down -v    # also drops the volumes
docker compose -f docker-compose.dev.yml up -d
uv run alembic upgrade head
PYTHONPATH=. uv run python scripts/seed.py
```

**Tests** — the backend rebuilds its database from migrations on every run, so it
needs Postgres and Redis up but nothing else:

```bash
cd backend && uv run pytest -q                  # 511 tests
uv run ruff check app tests scripts

cd frontend/apps/web && bun run test            # 118 tests
cd frontend && bun run typecheck && bun run lint
```

Note: there is no `test` script at the `frontend/` root — it must be run from
`frontend/apps/web`.

**No email key? Nothing breaks.** Leave `RESEND_API_KEY` and `SMTP_HOST` empty and
email is skipped with one warning line per send instead of retrying. Only set one
if you want mail actually delivered.

## Production

```bash
cd backend
cp .env.example .env          # generate real secrets • see docs/deployment.md
docker compose -f docker-compose.prod.yml up --build -d
```

Frontend: `cd frontend && docker compose -f docker-compose.prod.yml up --build -d` (built image is
served by nginx, which also proxies `/api` and `/ws` to the backend).

## Architecture

```
Browser ── HTTP/REST ──► Next.js :3000 ──► nginx ──► FastAPI (gunicorn, 8 UvicornWorkers)
   │                                                    ├──► PostgreSQL (source of truth)
   └──── WebSocket ─────────────────────────────────────┤
                                                        └──► Redis (cache · rate limits · pub/sub)
                                                                    ▲
                                          Celery worker + beat ─────┘
                                          (settlement, order expiry, price snapshots)
```

WebSockets are served by the FastAPI process itself • there is no separate gateway service. All 8
workers subscribe to Redis pub/sub so any instance can push to its own connected clients.

## Ports

| Service | Dev (host) | Notes |
|---|---|---|
| Frontend | `:3000` | `cd frontend && bun run dev` |
| Backend API | `:8000` | `./start.sh` • REST **and** `/ws` |
| Postgres | `:5433` | container `pm-postgres` / `docker-compose.dev.yml` |
| Redis | `:6380` | container `pm-redis` / `docker-compose.dev.yml` |

## Generate secrets

```bash
# JWT secret
openssl rand -base64 64
# TOTP encryption key
openssl rand -base64 32
```

The app refuses to boot while any of `JWT_SECRET`, `SECRET_KEY` or `TOTP_ENCRYPTION_KEY` is still
`change-me-in-production`.
