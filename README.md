# Polymarket — Prediction Market Platform

A Polymarket-style exchange for event outcomes: an order book plus an automated market maker, with
wallets, positions, settlement at $1 per correct share, and realtime prices over WebSockets.

> **All project documentation lives in [`docs/`](docs/README.md)** — start there.

## Documentation

| I want to… | Read |
|---|---|
| Understand the product with no jargon | [`docs/concepts.md`](docs/concepts.md) |
| Rehearse for a viva / defence | [`docs/viva-questions.md`](docs/viva-questions.md) (319 questions + answers) |
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

**Backend** (full commands in [`backend/README.md`](backend/README.md)):

```bash
cd backend
cp .env.example .env          # fill in DB_PASSWORD, JWT_SECRET, TOTP_ENCRYPTION_KEY
docker compose -f docker-compose.dev.yml up -d   # postgres :5433, redis :6380
uv run alembic upgrade head
./start.sh                    # API :8000 + celery worker + beat
curl localhost:8000/health
```

**Frontend** (separate terminal):

```bash
cd frontend
bun install
bun run dev                   # http://localhost:3000
```

**Tests:**

```bash
docker start pm-postgres pm-redis     # test infra on ports 5433 / 6380
cd backend && .venv/bin/pytest -q     # 384 tests, DB rebuilt from migrations each run
.venv/bin/ruff check app/ tests/
```

## Production

```bash
cd backend
cp .env.example .env          # generate real secrets — see docs/deployment.md
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

WebSockets are served by the FastAPI process itself — there is no separate gateway service. All 8
workers subscribe to Redis pub/sub so any instance can push to its own connected clients.

## Ports

| Service | Dev (host) | Notes |
|---|---|---|
| Frontend | `:3000` | `cd frontend && bun run dev` |
| Backend API | `:8000` | `./start.sh` — REST **and** `/ws` |
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
