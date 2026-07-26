# Backend

FastAPI + asyncpg + SQLAlchemy asyncio + Redis + Celery

## Quick Start

```bash
# 1. Install dependencies
uv sync

# 2. Run migrations
uv run alembic upgrade head

# 3. Start server
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 4. (Separate terminal) Start Celery worker
uv run celery -A app.workers.celery_app worker --loglevel=info

# 5. (Separate terminal) Start Celery beat (scheduler)
uv run celery -A app.workers.celery_app beat
```

## API Docs

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

## Environment Variables

Copy `.env` and fill in values:

```env
# App
SECRET_KEY=change-me-in-production
DEBUG=false
CORS_ORIGINS=*

# Database
DATABASE_URL=postgresql+asyncpg://myuser:mypassword@localhost:5435/mydatabase
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10

# Redis
REDIS_URL=redis://localhost:6382/0
REDIS_MAX_CONNECTIONS=50

# JWT
JWT_SECRET=change-me-in-production
JWT_ACCESS_EXPIRE=900
JWT_REFRESH_EXPIRE=604800

# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Celery
CELERY_BROKER_URL=redis://localhost:6382/1
```

## API Endpoints

### Auth
```
POST /api/v1/auth/register     {"email", "username", "password"} → user
POST /api/v1/auth/login        {"email", "password"} → sets HTTP-only cookies
POST /api/v1/auth/logout       → clears cookies
POST /api/v1/auth/refresh      → rotate access token
GET  /api/v1/auth/me           → current user
```

### Markets
```
GET  /api/v1/markets/              ?category=&status=&page=&page_size= → paginated list
GET  /api/v1/markets/{slug}        → market detail with outcomes + prices
POST /api/v1/markets/              {"slug", "question", "category", "closes_at", "initial_liquidity"} → admin only
PATCH /api/v1/markets/{id}/resolve  {"winning_outcome_id"} → admin only, triggers settlement
```

### Orders
```
POST /api/v1/orders/               {"market_id", "outcome", "side", "order_type", "amount", "client_order_id"} → market orders only
GET  /api/v1/orders/               ?page=&page_size= → paginated order list
GET  /api/v1/orders/{order_id}     → order detail
DELETE /api/v1/orders/{order_id}  → cancel pending order
```

### Positions
```
GET /api/v1/positions/             → active positions with realized + unrealized P&L
```

### Wallet
```
GET  /api/v1/wallet/              → balance, locked_balance, available_balance
POST /api/v1/wallet/deposit       {"amount"} → returns Stripe PaymentIntent client_secret
POST /api/v1/wallet/withdraw     {"amount"}
GET  /api/v1/wallet/transactions  ?page=&page_size=
```

### Webhooks
```
POST /api/v1/webhooks/stripe      Stripe webhook endpoint (idempotent)
```

### WebSocket
```
WS /ws/markets/{market_id}        Real-time price updates
```

## Architecture

```
app/
├── main.py              FastAPI entry, lifespan, middleware
├── config.py            Pydantic settings (all from env)
├── database.py          SQLAlchemy async engine + session
├── redis.py             Redis connection pool
├── deps.py              Auth dependencies (get_current_user)
├── api/
│   ├── auth.py          /auth/*
│   ├── markets.py       /markets/*
│   ├── orders.py        /orders/*
│   ├── positions.py     /positions/*
│   ├── wallet.py        /wallet/*
│   ├── webhooks.py      /webhooks/stripe
│   ├── exceptions.py    Custom HTTP exceptions
│   ├── handlers.py      Global exception handlers
│   ├── responses.py      ApiResponse wrapper
│   └── middleware.py     Request logging
├── models/               SQLAlchemy async models
├── schemas/              Pydantic request/response DTOs
├── amm/
│   └── engine.py        BinaryAMM (constant product: x*y=k)
├── workers/
│   ├── celery_app.py    Celery config + beat schedule
│   └── tasks.py         Background tasks
└── websocket/
    ├── manager.py       ConnectionManager + RedisPubSub
    └── routes.py        WS /ws/markets/{id}
```

## Database Migrations

```bash
# Generate migration (after model changes)
uv run alembic revision --autogenerate -m "description"

# Apply
uv run alembic upgrade head

# Rollback
uv run alembic downgrade -1

# Status
uv run alembic current
```

## Testing APIs

```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@test.com","username":"user","password":"password123"}'

# Login (gets cookies)
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@test.com","password":"password123"}' \
  -c cookies.txt

# Create market (admin required — set is_admin=true in DB directly for now)
curl -X POST http://localhost:8000/api/v1/markets/ \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"slug":"btc-100k","question":"Will BTC reach $100k?","category":"crypto","closes_at":"2027-01-01T00:00:00","initial_liquidity":1000}'

# Simulate Stripe deposit (after PaymentIntent succeeds)
curl -X POST http://localhost:8000/api/v1/webhooks/stripe \
  -H "Content-Type: application/json" \
  -d '{"type":"payment_intent.succeeded","data":{"object":{"id":"pi_xxx","amount":50000,"currency":"usd","metadata":{"user_id":"<USER_ID>"}}}}'

# Place order
curl -X POST http://localhost:8000/api/v1/orders/ \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"market_id":"<MARKET_ID>","outcome":"yes","side":"buy","order_type":"market","amount":100,"client_order_id":"order-1"}'
```

## Celery Tasks

| Task | Schedule | Purpose |
|------|----------|---------|
| `expire_stale_orders` | 30s | Cancel expired limit orders and release locked collateral |
| `sync_amm_prices` | 60s | Write AMM prices to Redis cache |
| `check_market_resolution` | 5min | Find closed-but-unresolved markets |
| `resolve_market` | on-demand | Settle winners and LPs after market resolution |
| `process_stripe_deposit` | on-demand | Credit wallet idempotently from Stripe webhook |

## Stripe Webhook Setup

1. Get webhook secret from Stripe dashboard
2. Set `STRIPE_WEBHOOK_SECRET` in `.env`
3. Point Stripe to `https://yourdomain.com/api/v1/webhooks/stripe`
4. Events required:
   - `payment_intent.succeeded`
   - `payment_intent.payment_failed`

For local dev, use Stripe CLI:
```bash
stripe listen --forward-to localhost:8000/api/v1/webhooks/stripe
```

## WebSocket

Connect to `/ws/markets/{market_id}` for real-time updates:

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/markets/<market_id>");
ws.onmessage = (e) => {
  const data = JSON.parse(e.data);
  // data.type: "market:price_update", "order:fill", etc.
};
```

## Key Design Notes

- **AMM**: Constant product (x*y=k) with 2% fee. All math in `Decimal`, shares rounded DOWN.
- **Orders**: Only `market` order type is supported. `limit` and `fill_or_kill` return validation errors.
- **Admin**: Markets can only be created/resolved by admin users (`is_admin=true` in DB).
- **Idempotency**: Orders are idempotent via `client_order_id` unique constraint per user.
- **Settlement**: Triggered automatically when a market is resolved — winners credited $1/share, LPs redeemed proportionally.
