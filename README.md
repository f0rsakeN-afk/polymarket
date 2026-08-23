# PredictX — Prediction Market Platform

## Dev Setup (hot reload)

```bash
# 1. Copy env — fill in DB_PASSWORD, JWT_SECRET, TOTP_ENCRYPTION_KEY
cp .env.example .env
nano .env

# 2. Start backend + ws + postgres + redis (all hot reload)
make dev

# 3. Frontend (separate terminal)
cd frontend && bun run dev
```

Dev stack: postgres · redis · api · ws1

## Prod Setup

```bash
# Build and start everything
make prod

# Or build images separately then start
make prod-build && make prod
```

## Tear Down

```bash
make down          # stop containers, keep data volumes
make clean         # stop + wipe data volumes
```

## What Gets Built

### Services

| Service | Dev Port | Prod Port | Notes |
|---------|----------|-----------|-------|
| Frontend | `:3000` | — | Run separately: `cd frontend && bun run dev` |
| API | `:8000` | via nginx `:8000` | Hot reload in dev |
| WS Gateway | `:7080` | via nginx `:8000/ws/` | Hot reload in dev |
| Postgres | `:5435` | docker only | |
| Redis | `:6382` | docker only | |

### Architecture

```
Browser
  │
  ├─ HTTP/REST ──► Nginx (:8000) ──► FastAPI (4 replicas)
  │                              └─► PostgreSQL
  │                              └─► Redis (pub/sub + cache)
  │
  └─ WebSocket ──► Nginx (:8000/ws/) ──► WS Gateway (3 Bun instances)
                                          └─► Redis
```

Celery Workers ──► Redis (broker) ──► PostgreSQL

## Docker Commands

```bash
# Dev: hot reload services only
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# Dev: just infra
docker compose -f docker-compose.yml -f docker-compose.dev.yml up postgres redis

# Prod: everything
docker compose up

# Prod: rebuild
docker compose build && docker compose up

# Logs
docker compose logs -f api
docker compose logs -f ws1

# Health
make health
```

## Generate Secrets

```bash
# Database password
openssl rand -base64 32

# JWT secret
openssl rand -base64 64

# TOTP encryption key
openssl rand -base64 32
```

## Frontend (without Docker)

```bash
cd frontend
cp .env.local.example .env.local 2>/dev/null || true
bun install
bun run dev
```

## Backend Migrations

```bash
make migrate
```
