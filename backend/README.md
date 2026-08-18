# Polymarket Backend

FastAPI + asyncpg + SQLAlchemy asyncio + Redis + Celery — a prediction market backend with an AMM-based trading engine, real-time WebSocket updates, and Stripe deposit integration.

---

## Commands & Scripts

### Local Development

```bash
# 1. Install dependencies
uv sync

# 2. Start PostgreSQL + Redis (Docker)
docker run -d -p 5435:5432 --name postgres -e POSTGRES_USER=myuser -e POSTGRES_PASSWORD=mypassword -e POSTGRES_DB=mydatabase postgres:16-alpine
docker run -d -p 6382:6379 --name redis redis:7-alpine

# 3. Run migrations
uv run alembic upgrade head

# 4. Start API + Celery (3 terminals)
./start.sh              # Terminal 1: API (8 workers) + auto-starts celery worker + beat
./start-workers.sh      # Terminal 2: Celery worker + beat (if not started by start.sh)
```

### Docker Compose (Production-ready)

```bash
# Start everything (API × 4 replicas, celery × 2 workers, postgres, redis, nginx)
cp .env.example .env    # fill in secrets
docker compose up --build -d

# Watch logs
docker compose logs -f api
docker compose logs -f celery_worker

# Stop everything
docker compose down

# Restart after code changes
docker compose up --build -d
```

### Load Testing

```bash
# Install locust
pip install locust websocket-client

# Web UI
locust -f scripts/locustfile.py --host=http://localhost:8000

# Headless — 50k users, 100/sec ramp, 60s
locust -f scripts/locustfile.py --host=http://localhost:8000 \
    --users=50000 --spawn-rate=100 --run-time=60s --headless

# REST API only — 10k users
locust -f scripts/locustfile.py --host=http://localhost:8000 \
    --users=10000 --spawn-rate=200 --run-time=60s --headless \
    --class-picker RestAPIUser

# WebSocket only — 50k connections
locust -f scripts/locustfile.py --host=http://localhost:8000 \
    --users=50000 --spawn-rate=500 --run-time=30s --headless \
    --class-picker WebSocketUser
```

### Database

```bash
# Run migrations
uv run alembic upgrade head

# Create migration (after model changes)
uv run alembic revision --autogenerate -m "describe change"

# Rollback
uv run alembic downgrade -1

# Drop and recreate (dev only)
uv run alembic downgrade base && uv run alembic upgrade head
```

### Celery

```bash
# Worker only
uv run celery -A app.workers.celery_app worker --loglevel=info --concurrency=8

# Beat scheduler only
uv run celery -A app.workers.celery_app beat --loglevel=info

# Inspect tasks (while running)
uv run celery -A app.workers.celery_app inspect active
uv run celery -A app.workers.celery_app inspect scheduled
uv run celery -A app.workers.celery_app inspect stats
```

### Code Quality

```bash
# Lint
uv run ruff check app/ tests/ --fix

# Type check
uv run pyright app/

# Format
uv run ruff format app/ tests/
```

### Environment

```bash
# Copy env and edit
cp .env.example .env

# For Docker deployment, update these in .env:
# DATABASE_URL=postgresql+asyncpg://myuser:mypassword@postgres:5432/mydatabase
# REDIS_URL=redis://redis:6379/0
# CELERY_BROKER_URL=redis://redis:6379/1
```

---

---

## Quick Start
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

Swagger UI: http://localhost:8000/docs

---

## Docker Production Stack

### Architecture

```
                    ┌─────────────────────────────────────────┐
                    │              nginx :8000                │
                    │         (load balancer / reverse proxy)   │
                    └─────────────────┬───────────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
         ┌────┴────┐           ┌────┴────┐           ┌────┴────┐
         │  api1   │           │  api2   │           │  api3   │
         │ (4 wks) │           │ (4 wks) │           │ (4 wks) │
         └────┬────┘           └────┬────┘           └────┬────┘
              │                       │                       │
              └───────────────────────┼───────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
               ┌────┴────┐      ┌────┴────┐      ┌────┴────┐
               │postgres │      │  redis  │      │ celery  │
               │   :5432 │      │  :6379  │      │ workers │
               └─────────┘      └─────────┘      └─────────┘
```

### Services

| Service | Replicas | Workers Each | Total WS Capacity |
|---------|----------|--------------|-------------------|
| `api` | 4 | 4 | 50k WebSocket connections |
| `celery_worker` | 2 | 8 concurrency | — |
| `celery_beat` | 1 | — | — |
| `postgres` | 1 | — | — |
| `redis` | 1 | — | — |
| `nginx` | 1 | — | — |

### Resource Limits (per container)

| Service | Memory | File Descriptors |
|---------|--------|-----------------|
| `api` | 2GB max / 512MB reserved | 65536 |
| `celery_worker` | 1GB | 65536 |
| `postgres` | 1GB | — |
| `redis` | 768MB | — |
| `nginx` | — | 65536 |

### Files

```
backend/
├── Dockerfile              # API image (uvicorn 4 workers)
├── Dockerfile.worker       # Celery worker image
├── docker-compose.yml      # Full stack
├── nginx/nginx.conf       # Load balancer config
└── scripts/postgres.conf  # PostgreSQL tuning
```

### Deploy

```bash
# 1. Copy and fill env
cp .env.example .env
# Edit .env — set all *change-me* secrets

# 2. Build and start
docker compose up --build -d

# 3. Watch
docker compose logs -f api
docker compose logs -f celery_worker

# 4. Stop
docker compose down

# 5. Scale API (requires more RAM/CPU)
docker compose up -d --scale api=8
```

### Nginx Config Highlights

- **Load balancing**: `least_conn` — routes to the least busy worker
- **WebSocket**: `Upgrade` + `Connection: upgrade` headers forwarded
- **WS keepalive**: 7-day timeout for long-lived connections
- **Rate limiting**: 60 req/min per IP on `/`, 5 req/min on `/auth/**`
- **No buffering**: `proxy_buffering off` on WS — critical for real-time

### Redis Pub/Sub with Multiple Workers

Each `api` container runs its own Redis pub/sub listener (started in FastAPI lifespan). When a trade executes on any worker, `redis.publish()` fans out to all workers' listeners, which broadcast to their local WebSocket clients. This ensures WS clients receive events regardless of which API container handles the trade.

---

## Architecture Overview

```
                    ┌─────────────┐
                    │   Client    │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
         REST API     WebSocket    Stripe WH
              │            │            │
              ▼            │            ▼
         ┌────────┐       │       ┌──────────┐
         │FastAPI │◄──────┘       │ Stripe   │
         │(uvicorn)│              │ Webhooks  │
         └───┬────┘              └──────────┘
             │
    ┌────────┼─────────┬──────────────┐
    │        │         │              │
    ▼        ▼         ▼              ▼
┌──────┐ ┌──────┐ ┌──────┐     ┌─────────┐
│Primary│ │Replica│ │Redis │     │ Celery  │
│PostgreSQL│ │(optional)│ │Cache+PubSub│  │ Workers  │
└──────┘ └──────┘ └──┬───┘     └─────────┘
                      │
                      ▼
               WebSocket Clients
              (via Redis Pub/Sub)
```

**Key design patterns:**

- **Read/Write Splitting**: Writes to primary, reads from replica (with automatic fallback to primary in dev)
- **Pessimistic Locking**: All write operations use `SELECT ... FOR UPDATE` with strict lock ordering (market → pool → wallet) to prevent deadlocks
- **Distributed Singleflight**: Redis `SETNX` lock prevents thundering herd on market price reads across all workers
- **Circuit Breaker**: Redis operations protected by a state machine (closed → open → half-open) with 5-failure threshold and 30s recovery
- **Decimal Math**: All financial calculations use Python `Decimal` — never floating point for money
- **Idempotency**: Orders via `client_order_id` unique constraint; Stripe deposits via `reference_id` check

---

## AMM Engine — Constant Product Market Maker

The core of the trading system is a **BinaryAMM** implementing the constant product formula `x * y = k` for binary (YES/NO) markets.

### The Math

```
Pool State:
  x = YES shares in the pool
  y = NO shares in the pool
  k = x * y  (constant product)

Pricing:
  Price(YES) = y / (x + y)
  Price(NO)  = x / (x + y)

Note: Price(YES) + Price(NO) = 1 always.
```

### How It Works

The AMM always maintains the invariant `x * y = k`. When you buy shares of one outcome, you add collateral to its side of the pool, which increases that side's share count. The constant product `k` stays the same, so the other side's share count must decrease proportionally. The decrease in the other side represents the shares you receive.

#### Buy Flow (depositing collateral to receive shares)

```
Buying YES with $100 collateral (2% fee = $2):
  1. Fee deducted: collateral_after_fee = $98
  2. New YES pool: x' = x + 98
  3. New NO pool:  y' = k / x'  (k is unchanged)
  4. Shares received: y - y' (the decrease in NO pool)

Buying NO with $100 collateral (2% fee = $2):
  1. Fee deducted: collateral_after_fee = $98
  2. New NO pool:  y' = y + 98
  3. New YES pool: x' = k / y'  (k is unchanged)
  4. Shares received: x - x' (the decrease in YES pool)
```

#### Sell Flow (returning shares to receive collateral)

```
Selling YES shares:
  1. New YES pool: x' = x - shares_sold
  2. New NO pool:  y' = k / x'
  3. Collateral received (before fee): y - y'
  4. Fee deducted: collateral_out = (y - y') * (1 - fee_rate)

Selling NO shares:
  1. New NO pool:  y' = y - shares_sold
  2. New YES pool: x' = k / y'
  3. Collateral received (before fee): x - x'
  4. Fee deducted: collateral_out = (x - x') * (1 - fee_rate)
```

#### Price Impact Example

Starting pool: x=5000 YES, y=5000 NO, k=25,000,000
- Price(YES) = 5000/10000 = 0.50
- Price(NO) = 5000/10000 = 0.50

Buy $1000 YES (2% fee = $20, after fee = $980):
- x' = 5000 + 980 = 5980
- y' = 25,000,000 / 5980 = 4180.60
- Shares received = 5000 - 4180.60 = 819.40 shares
- Effective price per share = 980 / 819.40 = $1.196 (YES price moved from 0.50 to 0.59)

### Fee Structure

| Fee | Rate | Purpose |
|-----|------|---------|
| **Trading fee** | 2% of collateral | Stays in the pool (accrues to LP providers) |
| **Protocol fee** | 1% of trade value | Extracted to treasury at settlement |

Trading fee is deducted from the collateral before the trade executes. Protocol fee is computed from the total trade value and accumulated in `pool.protocol_fees`, then swept to the treasury during market resolution.

### AMM State Mutation

The `apply_trade()` method executes a buy and then mutates the pool state atomically:

```python
def apply_trade(self, outcome, collateral):
    quote = self.buy(outcome, collateral)
    k = self.yes_shares * self.no_shares  # save k BEFORE mutation

    if outcome == "yes":
        self.yes_shares += collateral - quote.fee
        self.no_shares = k / self.yes_shares  # recompute using saved k
    else:
        self.no_shares += collateral - quote.fee
        self.yes_shares = k / self.no_shares   # recompute using saved k

    return quote
```

---

## Order Types & Execution

### Supported Order Types

| Type | Behavior |
|------|----------|
| **Market** | Executes immediately against the AMM at the current price. No price limit. |
| **Limit** | Places a pending order at a specified price. Executes only when the AMM price reaches the limit. Locked collateral is released if cancelled/expired. |
| **Fill-or-Kill (FOK)** | Executes immediately AND fully at the limit price, or fails entirely. |

### Order Execution Flow (POST /api/v1/orders/)

```
1. Idempotency Check
   - If client_order_id provided, check (user_id, client_order_id) unique constraint
   - Prevents duplicate submissions on network retry

2. Validation & Locking (all FOR UPDATE, in order)
   - Lock Market record  ───┐  Deadlock prevention:
   - Lock LiquidityPool  ───┤  Always acquire locks
   - Lock Wallet         ───┤  in the same order:
   - Lock Position       ───┘  market → pool → wallet → position

3. Market Validation
   - Market exists and status = "active"
   - Market.closes_at is in the future
   - Outcome is valid for this market

4. Slippage / Post-Only Checks
   - For BUY:  current_price must be >= limit_price  (you want to buy at or below limit)
   - For SELL: current_price must be <= limit_price  (you want to sell at or above limit)
   - Post-only orders are rejected if they would execute immediately
   - FOK orders fail if the price condition isn't met

5. Wallet Checks
   - BUY:  wallet.balance - wallet.locked_balance >= amount
   - SELL: position.shares_held >= amount

6. AMM Execution (for market/FOK orders that pass price check)
   - Create BinaryAMM instance from pool state (yes_shares, no_shares, fee_rate)
   - Call amm.apply_trade(outcome, amount)
   - Compute shares_out, fee, execution price from AMMQuote

7. Protocol Fee
   - protocol_fee = trade_value * 0.01
   - Accumulated in pool.protocol_fees (swept to treasury at settlement)

8. State Updates
   - Pool: Update yes_shares, no_shares from AMM state
   - Position: Create or update with weighted average price
   - Order: Create with status="filled"
   - Trade: Create public trade record
   - Transaction: Create wallet transaction record
   - Market: Increment total_volume, num_trades

9. Referral Reward (first trade only)
   - If user was referred and hasn't traded before, credit referrer $1
   - Mark referral as "completed"

10. Event Publication
    - Redis pub/sub: publish_price_update (market prices + volume)
    - Redis pub/sub: publish_market_event ("trade:new")
    - Celery task: check_price_alerts.delay()
```

### Limit Order Lifecycle

```
1. ORDER PLACED (status="pending")
   │
   ├──> Price condition met immediately?
   │       ├── YES → Execute as market order (status="filled")
   │       └── NO  → Lock collateral, store pending order
   │
   ├──> Celery Beat (every 30s): expire_stale_orders
   │       └── Check if expires_at <= now
   │               ├── YES → status="expired", release locked collateral
   │               │         Publish "order:expired" event
   │               └── NO  → Leave pending
   │
   ├──> Limit Order Checker (on-demand):
   │       └── Check current AMM price vs limit price
   │               ├── Fillable? → Execute full order
   │               └── Not fillable → Leave pending
   │
   └──> User cancels (DELETE /api/v1/orders/{id})
           └── Only pending orders → status="cancelled", release locked collateral
```

### Cancel Order Flow

```
1. Verify order belongs to user
2. Verify order.status == "pending"
3. Set status = "cancelled"
4. For BUY orders: release locked collateral back to available balance
5. Publish "order:expired" event
```

---

## Orderbook

The orderbook is implemented as a **live aggregation query** over pending limit orders, not a separate matching engine. There is no central limit order book (CLOB) — the AMM is the counterparty to every trade.

### How It Works

```
GET /api/v1/markets/{slug}/orderbook
```

1. Query all pending limit orders for the market, grouped by `(outcome_id, price)`
2. Aggregate `SUM(remaining_amount)` at each price level
3. Split into **bids** (buy orders) and **asks** (sell orders)
4. Sort by price descending

```sql
-- Logical equivalent:
SELECT o.outcome_id, o.price, SUM(o.remaining_amount) as total_size
FROM orders o
JOIN markets m ON m.id = o.market_id
WHERE m.slug = :slug
  AND o.status = 'pending'
  AND o.order_type IN ('limit', 'fill_or_kill')
GROUP BY o.outcome_id, o.price
ORDER BY o.price DESC
```

### Bids vs Asks

| Side | Direction | For outcome |
|------|-----------|-------------|
| **Bid** | User wants to BUY shares | YES |
| **Ask** | User wants to SELL shares | NO |

### Response Structure

```json
{
  "bids": [
    {"outcome_id": "...", "outcome": "yes", "price": 0.45, "size": 500},
    {"outcome_id": "...", "outcome": "yes", "price": 0.40, "size": 300}
  ],
  "asks": [
    {"outcome_id": "...", "outcome": "no", "price": 0.60, "size": 200},
    {"outcome_id": "...", "outcome": "no", "price": 0.65, "size": 150}
  ]
}
```

---

## Liquidity Provision

Liquidity providers (LPs) deposit USDC into a market pool and receive LP tokens proportional to their contribution. These tokens represent their share of the pool and can be redeemed at any time.

### Adding Liquidity

```
POST /api/v1/markets/{market_id}/liquidity?amount=1000
```

1. **Lock** market → pool → wallet (in that order, FOR UPDATE)
2. **Validate** market is active
3. **Compute LP tokens to mint:**

```
If LP token supply already exists:
  lp_tokens_minted = amount * lp_token_supply / (yes_shares + no_shares)

If first liquidity deposit (initial state):
  lp_tokens_minted = amount * 2
```

4. **Add equal amounts to both pool sides** (maintains 50/50 balance):

```
yes_shares += amount / current_yes_price
no_shares  += amount / current_no_price
```

Wait — the actual implementation adds equal collateral to both sides:

```
yes_shares += amount
no_shares  += amount
collateral += amount
```

This is the initial equal-split approach. Each unit of collateral is split 50/50 between YES and NO.

5. **Update LPShare** record (create or merge with existing)
6. **Increment** `lp_token_supply`
7. **Deduct** amount from wallet balance
8. **Record** Transaction (type="liquidity_add")

### Removing Liquidity

```
DELETE /api/v1/markets/{market_id}/liquidity?lp_tokens=500
```

1. **Validate** user owns the LP tokens
2. **Compute proportional redemption:**

```
lp_fraction      = lp_tokens / pool.lp_token_supply
yes_redeemed     = pool.yes_shares * lp_fraction
no_redeemed      = pool.no_shares * lp_fraction
collateral_back  = pool.collateral * lp_fraction
```

3. **Update pool:** subtract redeemed amounts
4. **Burn LP tokens** (decrement user's LPShare, potentially delete record)
5. **Credit** wallet
6. **Record** Transaction (type="liquidity_remove")

### LP Token Economics

- LP tokens represent pro-rata ownership of the entire pool (both YES and NO sides)
- When you redeem, you get back a proportional slice of whatever is left in the pool
- If the pool has grown (due to trading fees), your LP tokens are worth more
- If the pool has shrunk (due to adverse price movements), your LP tokens are worth less

---

## Wallet & Transactions

### Wallet Model

Each user has exactly one wallet (enforced by `user_id` unique constraint). The wallet tracks:

| Field | Type | Description |
|-------|------|-------------|
| `balance` | Decimal(20,8) | Total USDC balance |
| `locked_balance` | Decimal(20,8) | Collateral locked for pending limit buy orders |
| `currency` | String | "USDC" |

**Available balance for trading:** `balance - locked_balance`

### Transaction History

All wallet movements are recorded as Transaction records with types:

| Type | Direction | Description |
|------|-----------|-------------|
| `deposit` | + | Fiat/USDC deposited via Stripe |
| `withdrawal` | - | User withdrew to external wallet |
| `trade_buy` | - | Collateral spent on buying shares |
| `trade_sell` | + | Collateral received from selling shares |
| `fee` | - | Trading/protocol fees |
| `liquidity_add` | - | Collateral deposited into AMM pool |
| `liquidity_remove` | + | Collateral withdrawn from AMM pool |
| `settlement_win` | + | Payout from winning market resolution |
| `settlement_loss` | - | Loss on losing market resolution |
| `refund` | + | Collateral returned (e.g., cancelled limit order) |
| `referral_reward` | + | Reward for referring a new user |
| `protocol_fee` | - | Protocol fee extracted to treasury |

### Deposit Flow

```
Client                  Backend                  Stripe
  │                        │                        │
  │  POST /wallet/deposit  │                        │
  │──────────────────────► │                        │
  │                        │  Create PaymentIntent  │
  │                        │──────────────────────► │
  │  ◄── client_secret ────│                        │
  │                        │                        │
  │  [Frontend completes payment via Stripe Elements]
  │                        │                        │
  │                        │  POST /webhooks/stripe │
  │                        │◄────────────────────── │
  │                        │  (payment_intent.succeeded)
  │                        │                        │
  │                        │  Idempotency check     │
  │                        │  Credit wallet         │
  │                        │  Create Transaction    │
```

**Note:** The deposit endpoint is currently **mocked** — it generates `pi_<uuid>_secret` as the client_secret without actually calling Stripe. In production, you would integrate with `stripe.PaymentIntent.create()`.

### Withdrawal Flow

```
POST /api/v1/wallet/withdraw {"amount": 500}
  → Validate amount > 0
  → Check available balance (balance - locked_balance >= amount)
  → Deduct from balance
  → Create Transaction (type="withdrawal", status="pending")
  → Return withdrawal_id
```

---

## Market Resolution & Settlement

### Resolution (Admin Action)

```
PATCH /api/v1/markets/{market_id}/resolve?winning_outcome_id=...
```

1. Validate market exists and status is "active"
2. Validate winning_outcome belongs to this market
3. Set `status = "resolved"`, `winning_outcome_id = ...`, `resolved_at = now`
4. Publish `market:resolved` event
5. Dispatch Celery task: `resolve_market.delay(market_id, winning_outcome_id)`

### Settlement (Celery Task: `resolve_market`)

The settlement process runs in a background Celery task with retry (3x, exponential backoff):

```
1. Lock market (FOR UPDATE)
   Verify not already resolved

2. Find/Create Treasury User
   Look for user with is_system=True
   Create if not exists (used for protocol fee collection)

3. Settle User Positions
   For each position on this market:
     - If position.outcome_id == winning_outcome_id:
         payout = shares_held * 1.0  (each winning share = $1)
         Create Transaction (settlement_win)
         Credit wallet
     - If position.outcome_id != winning_outcome_id:
         Create Transaction (settlement_loss)
         (shares expire worthless)

4. Extract Protocol Fees
   protocol_fees = pool.protocol_fees
   Credit treasury wallet with protocol_fees
   Create Transaction (protocol_fee)

5. Settle LP Shares
   For each LP holder:
     - lp_payout_per_token = pool.winning_side_shares / lp_token_supply
       (where winning_side = YES if YES won, NO if NO won)
     - lp_payout = user_lp_tokens * lp_payout_per_token
     - Credit LP holder's wallet
     - Burn LP tokens (delete LPShare record)
```

### What Happens to LPs at Settlement

When a market resolves:
- The **winning side** of the pool is distributed pro-rata to LP token holders
- The **losing side** is used to pay out winning position holders
- LPs earn the trading fees accumulated during the market's lifetime

Example:
```
Pool before resolution: YES=8000, NO=2000 (k=16,000,000)
Market resolves: YES wins

Payout to YES position holders: 8000 shares = $8000 (from YES pool)
LP payout: The NO pool (2000) is distributed to LP token holders
           each LP gets: LP_tokens * (2000 / total_LP_supply)
```

---

## WebSocket & Real-Time Updates

### Connection

```
WebSocket: ws://host:port/ws/markets/{market_id}
```

### Protocol

**Client → Server messages:**

```json
{"type": "ping"}                    // Health check
{"type": "subscribe", "market_id": "..."}  // Switch to a different market
```

**Server → Client messages:**

```json
{"type": "pong"}                    // Ping response
// Plus any forwarded Redis pub/sub events (see below)
```

### Event Types Forwarded to Clients

The WebSocket receives these event types from Redis pub/sub and forwards them to all subscribers of the relevant market:

| Event Type | Triggered By | Payload |
|------------|-------------|---------|
| `market:price_update` | Any trade | `{market_id, yes_price, no_price, volume}` |
| `market:resolved` | Admin resolution | `{market_id, winning_outcome_id}` |
| `market:closed` | Admin close | `{market_id}` |
| `trade:new` | Order execution | `{market_id, outcome, side, price, amount, executed_at}` |
| `comment:new` | New comment | `{market_id, comment_id, username, content}` |
| `order:expired` | Celery expiry | `{market_id, order_id}` |
| `order:fill` | Order execution | Full order data |
| `alert:triggered` | Price alert hit | `{market_id, alert_id, condition, trigger_price}` |

### Connection Manager Internals

The `ConnectionManager` class manages WebSocket subscriptions:

```
ConnectionManager
├── _market_subs: Dict[str, Set[WebSocket]]
│     Maps market_id → set of connected WebSocket clients
│
├── _ws_to_market: Dict[WebSocket, str]
│     Reverse lookup: WebSocket → market_id
│
├── connect(ws, market_id)
│     → Accepts the WebSocket
│     → Adds to _market_subs[market_id]
│     → Records in _ws_to_market
│
├── disconnect(ws)
│     → Removes from _ws_to_market
│     → Removes from _market_subs
│     → Cleans up empty market sets
│
├── broadcast_to_market(market_id, event)
│     → Sends JSON to all subscribers of a market
│     → Removes dead connections on send failure
│
└── broadcast_global(event)
      → Sends JSON to ALL connected clients (across all markets)
```

All operations are protected by `asyncio.Lock` to prevent race conditions between concurrent connect/disconnect/broadcast calls.

---

## Redis Pub/Sub System

Redis serves three roles in this system:
1. **Cache** — Market prices stored as hashes with TTL
2. **Pub/Sub** — Real-time event distribution across workers
3. **Celery Broker** — Task queue for background jobs

### Channel Architecture

```
Redis Pub/Sub Channels:

market:{id}:price     →  Price updates (published on every trade)
market:{id}:events    →  Market events (resolution, close, new comment, new trade)
user:{id}:fills       →  Order fill notifications (user-specific)
```

### Event Flow

```
                 ┌──────────────────────┐
                 │   API Handler        │
                 │   (Worker 1)         │
                 └─────────┬────────────┘
                           │
                    redis.publish(channel, msg)
                           │
                           ▼
                 ┌──────────────────────┐
                 │       Redis          │
                 │   (Pub/Sub Engine)   │
                 └─────────┬────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                 │
          ▼                ▼                 ▼
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │ PubSub.listen │ │ PubSub.listen│ │ PubSub.listen│
  │ (Worker 1)   │ │ (Worker 2)   │ │ (Worker 3)   │
  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
         │                │                 │
         ▼                ▼                 ▼
  ConnectionManager.broadcast_to_market(market_id, data)
         │                │                 │
         ▼                ▼                 ▼
  WebSocket.send_json() to local clients
```

### Why Redis Pub/Sub Instead of Direct WebSocket Broadcast

1. **Multi-worker support**: If you run multiple FastAPI workers (vertical or horizontal), a trade on worker 1 needs to notify clients connected to worker 2. Redis pub/sub bridges this gap.
2. **Decoupling**: API handlers don't need to know about WebSocket connections. They just publish to Redis.
3. **Resilience**: If a WebSocket worker crashes and restarts, it reconnects to Redis pub/sub and continues receiving events.

### Circuit Breaker

The `RedisCircuitBreaker` protects against Redis failures:

```
States:
  CLOSED    → Normal operation, all Redis calls pass through
  OPEN      → After 5 consecutive failures, all Redis calls are rejected
              (fail fast, don't block trading)
  HALF_OPEN → After 30s recovery timeout, one test call is allowed
              → If it succeeds: back to CLOSED
              → If it fails: back to OPEN
```

### Price Cache with Distributed Singleflight

Market prices are cached in Redis hashes with 5-minute TTL:

```
Key: market:{id}:price
Fields:
  yes_price:  "0.62"
  no_price:   "0.38"
  volume:     "5600000"
  updated_at: "1734567890.123"   (unix timestamp)
```

To prevent the thundering herd problem when cache expires and multiple concurrent requests hit the DB:

```
Request A comes in → cache miss
  → SETNX lock:market:{id} (5s TTL)
  → Acquired? YES → Hit DB, write cache, delete lock
  → Response with DB data

Request B comes in (same time) → cache miss
  → SETNX lock:market:{id}  (5s TTL)
  → Acquired? NO → Poll Redis cache every 100ms for up to 5s
  → Cache populated by Request A → Return cached data
  → Timeout (5s) → Fall through to DB directly
```

---

## Celery Workers

### Configuration (`celery_app.py`)

- **Broker**: Redis (configurable, typically DB 1)
- **Serializer**: JSON
- **Concurrency**: 4 workers
- **Task acknowledgments**: Late (`task_acks_late=True`) — tasks are re-delivered if the worker crashes

### Scheduled Tasks (Celery Beat)

| Interval | Task | What It Does |
|----------|------|-------------|
| Every 30s | `expire_stale_orders` | Finds limit/FOK orders with `expires_at <= now`, marks them expired, releases locked collateral, publishes `order:expired` event |
| Every 60s | `sync_amm_prices` | Reads all active markets with their pools, writes `yes_price`/`no_price`/`updated_at` to Redis hashes (5min TTL). Acts as a fallback cache warmer if price updates are missed. |
| Every 5min | `check_market_resolution` | Finds active markets where `closes_at <= now`. Currently just logs a warning — resolution requires manual admin action. |

### On-Demand Tasks

| Task | Triggered By | What It Does |
|------|-------------|-------------|
| `resolve_market` | Admin market resolution | Settles all positions, LPs, and protocol fees |
| `process_stripe_deposit` | Stripe webhook | Idempotently credits wallet for completed deposits |
| `check_price_alerts` | After every trade | Checks all untriggered alerts for the traded market, marks triggered alerts |
| `check_limit_order_execution` | (External/custom) | Checks pending limit/FOK orders against current AMM price; executes fillable orders |

---

## Authentication & JWT

### Credential Types

| Method | Source | Priority |
|--------|--------|----------|
| Access token cookie | `request.cookies["access_token"]` | 1st (checked first) |
| Bearer header | `request.headers["Authorization"]` | 2nd |

### Token Format

```json
// JWT Payload (HS256)
{
  "sub": "<user_id>",
  "exp": <unix_timestamp>,
  "type": "access"  // or "refresh"
}
```

### Session Flow

```
Registration:
  → bcrypt(password) → store password_hash
  → Create wallet (balance=0, USDC)
  → If referral_code provided, create Referral record

Login:
  → Verify password with bcrypt.checkpw()
  → Create access_token (JWT, 15 min default)
  → Create refresh_token (UUID v4)
  → Store RefreshToken in DB (plain UUID as "hash")
  → Set HTTP-only, SameSite=lax cookies

Token Refresh:
  → Read refresh_token cookie
  → Find DB record: matching token_hash, NOT revoked, NOT expired
  → Revoke old RefreshToken
  → Issue new access_token + new refresh_token (rotation)
  → Set new cookies

Logout:
  → Revoke refresh token (set revoked=True)
  → Clear cookies
```

### Auth Dependencies

```python
# Requires authentication — returns 401 if missing/invalid
async def get_current_user(request, db) -> User

# Optional authentication — returns None if missing
async def get_optional_user(request, db) -> User | None
```

---

## Stripe Deposit Flow

### Endpoint

```
POST /api/v1/webhooks/stripe
Content-Type: application/json
Stripe-Signature: <webhook_signature>
```

### Handled Events

| Event | Action |
|-------|--------|
| `payment_intent.succeeded` | Credit user's wallet, create deposit Transaction |
| `payment_intent.payment_failed` | Log warning, no state change |

### Idempotency

Deposits are idempotent via `reference_id` check:

```python
existing_tx = await db.execute(
    select(Transaction).where(
        Transaction.reference_id == payment_intent_id,
        Transaction.reference_type == "stripe_deposit"
    )
)
if existing_tx:
    return {"status": "already_processed"}
```

### Stripe to Wallet Mapping

The Stripe PaymentIntent's `metadata.user_id` field is used to identify which Polymarket user to credit. The amount is converted from cents to dollars (`amount_cents / 100`).

---

## Referral System

### How It Works

1. Each user has a unique `referral_code` (auto-generated on registration — first 8 chars of a UUID4, uppercased)
2. A referrer shares their code
3. New user registers with `referral_code` in the request body
4. A Referral record is created with `status="pending"`
5. When the referred user completes their **first trade**, the referral is marked `status="completed"` and the referrer is credited with the configured reward (`REFERRAL_REWARD_AMOUNT`, default $1)

### Endpoints

```
GET /api/v1/referrals/code
  → Returns user's referral code (auto-generates if missing)

GET /api/v1/referrals/stats
  → Returns:
    - total_referrals (count)
    - successful_referrals (count where status=completed)
    - rewards_earned (sum of reward_amount)
    - referrals[] (list with username, status, reward, date)
```

---

## Price Alerts

Users can set price alerts on markets. When the market price crosses the trigger threshold, the alert fires and an event is published.

### Alert Conditions

| Condition | Meaning |
|-----------|---------|
| `above` | Trigger when price goes ABOVE trigger_price |
| `below` | Trigger when price goes BELOW trigger_price |

### Check Flow (after every trade)

```
check_price_alerts(market_id, outcome, current_price):
  → Load all untriggered alerts for this market
  → For each alert:
    - If alert.outcome matches (or is None = either outcome)
    - If condition == "above" AND current_price > trigger_price → TRIGGERED
    - If condition == "below" AND current_price < trigger_price → TRIGGERED
  → Set triggered=True, triggered_at=now
  → Publish "alert:triggered" event via Redis pub/sub
  → WebSocket broadcasts to connected clients
```

---

## API Endpoints Reference

### Auth (`/api/v1/auth`)

| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| POST | `/register` | No | `{email, username, password, referral_code?}` | `{success, data: {id, email, username}}` |
| POST | `/login` | No | `{email, password}` | Sets cookies, returns user data |
| POST | `/logout` | Cookie | - | Clears cookies |
| POST | `/refresh` | Refresh cookie | - | Rotates tokens, sets new cookies |
| GET | `/me` | Required | - | `{success, data: {id, email, username, is_verified, referral_code}}` |

### Markets (`/api/v1/markets`)

| Method | Path | Auth | Query/Body | Response |
|--------|------|------|------------|----------|
| GET | `/` | No | `q?, category?, status?, page?, page_size?` | `{success, data: Market[], page, page_size, has_more}` |
| GET | `/{slug}` | No | - | `MarketDetailResponse` (prices, outcomes, spread) |
| POST | `/` | Admin | `CreateMarketRequest` | Created market |
| PATCH | `/{id}/resolve` | Admin | `{winning_outcome_id}` | Updated market |
| PATCH | `/{id}/close` | Admin | - | Updated market (status=closed) |
| GET | `/{slug}/orderbook` | No | - | `{bids: [], asks: []}` |
| GET | `/{slug}/faqs` | No | - | `FAQResponse[]` |
| GET | `/{slug}/related` | No | - | `MarketResponse[]` (same category) |

### Orders (`/api/v1/orders`)

| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| POST | `/` | Required | `OrderRequest` | Order result (filled shares, price, etc.) |
| GET | `/` | Required | `page?, page_size?` | Paginated order list |
| GET | `/{order_id}` | Required | - | Order detail |
| DELETE | `/{order_id}` | Required | - | Cancel (only pending) |

### Positions (`/api/v1/positions`)

| Method | Path | Auth | Response |
|--------|------|------|----------|
| GET | `/` | Required | `{positions: PositionResponse[]}` with realized + unrealized PnL |

### Wallet (`/api/v1/wallet`)

| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| GET | `/` | Required | - | Balance, locked, available, currency |
| POST | `/deposit` | Required | `{amount}` | `{client_secret, amount, currency}` |
| POST | `/withdraw` | Required | `{amount}` | `{withdrawal_id, amount, status}` |
| GET | `/transactions` | Required | `page?, page_size?` | Paginated transaction list |

### Liquidity (`/api/v1/markets/{market_id}`)

| Method | Path | Auth | Query | Response |
|--------|------|------|-------|----------|
| POST | `/liquidity` | Required | `amount` | LP tokens minted |
| DELETE | `/liquidity` | Required | `lp_tokens` | Collateral returned |
| GET | `/liquidity` | Required | - | LP position details |

### Trades (`/api/v1`)

| Method | Path | Auth | Query | Response |
|--------|------|------|-------|----------|
| GET | `/trades` | No | `market_slug?, page?, page_size?` | Global trade feed |
| GET | `/markets/{slug}/trades` | No | `page?, page_size?` | Market-specific trade feed |

### Comments (`/api/v1/markets/{slug}/comments`)

| Method | Path | Auth | Body/Query | Response |
|--------|------|------|-----------|----------|
| POST | `/` | Required | `{content, parent_id?}` | Created comment |
| GET | `/` | No | `page?, page_size?` | Top-level comments with reply_count |
| GET | `/{id}/replies` | No | `page?, page_size?` | Replies to a comment |
| PATCH | `/{id}` | Required | `{content}` | Updated comment |
| DELETE | `/{id}` | Required | - | Soft-deleted comment |

### Alerts (`/api/v1/alerts`)

| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| POST | `/` | Required | `{market_id, outcome?, condition, trigger_price}` | Created alert |
| GET | `/` | Required | - | Non-triggered alerts |
| DELETE | `/{alert_id}` | Required | - | Deleted alert |

### Referrals (`/api/v1/referrals`)

| Method | Path | Auth | Response |
|--------|------|------|----------|
| GET | `/code` | Required | `{referral_code}` |
| GET | `/stats` | Required | Referral stats + list |

### Market Activity (`/api/v1/markets/{slug}/activity`)

| Method | Path | Auth | Response |
|--------|------|------|----------|
| GET | `/{slug}/activity` | No | `{market_stats, top_holders_by_outcome[], recent_trades[], recent_comments[]}` |

### Webhooks (`/api/v1/webhooks`)

| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| POST | `/stripe` | Signature | Stripe event JSON | `{received: true}` |

### WebSocket

| Path | Description |
|------|-------------|
| `ws://host/ws/markets/{market_id}` | Real-time price updates and market events |

---

## Database Models & Relationships

### Entity Relationship Diagram

```
users ──┬── wallets (1:1)
        ├── refresh_tokens (1:N)
        ├── sessions (1:N)
        ├── orders (1:N)
        ├── positions (1:N)
        ├── trades (1:N)
        ├── alerts (1:N)
        ├── comments (1:N)
        ├── referrals_made (1:N via referrer_id)
        ├── referrals_received (1:N via referred_id)
        └── lp_shares (1:N)

markets ──┬── outcomes (1:N)
          ├── liquidity_pools (1:1)
          ├── orders (1:N)
          ├── positions (1:N)
          ├── trades (1:N)
          ├── comments (1:N)
          ├── alerts (1:N)
          └── market_faqs (1:N)

liquidity_pools ──┬── lp_shares (1:N)
                  └── market (1:1)

orders ── players: user, market, outcome

wallets ──┬── transactions (1:N)
          └── user (1:1)

comments ── self-referential (parent_id → comments.id)
```

### Key Relationships

```
Market (1) ────────────── (1) LiquidityPool
Market (1) ────────────── (N) Outcome      (2 rows: YES, NO for binary)
Market (1) ────────────── (N) Order
Market (1) ────────────── (N) Position
Market (1) ────────────── (N) Trade
Market (1) ────────────── (N) Comment
Market (1) ────────────── (N) Alert
Market (1) ────────────── (N) MarketFAQ

User (1) ─────────────── (1) Wallet
User (1) ─────────────── (N) Transaction   (via wallet)
User (1) ─────────────── (N) Order
User (1) ─────────────── (N) Position
User (1) ─────────────── (N) Comment
User (1) ─────────────── (N) Alert
User (1) ─────────────── (N) LPShare       (via liquidity_pools)

LiquidityPool (1) ─────── (N) LPShare

Comment (1) ──────────── (N) Comment       (self-ref: replies)
```

---

## Data Flow Diagrams

### Full Trade Lifecycle

```
               ┌──────────────┐
               │  Client POST │
               │  /api/v1/orders/ │
               └──────┬───────┘
                      │
                      ▼
          ┌───────────────────────┐
          │  1. Idempotency Check │
          │  2. Lock Market (FK)  │
          │  3. Lock Pool (FK)    │
          │  4. Lock Wallet (FK)  │────────── Order matters for deadlock prevention
          │  5. Lock Position(FK) │
          └───────────────────────┘
                      │
                      ▼
          ┌───────────────────────┐
          │  6. Validate market   │── Market exists? Active? Not expired?
          │  7. Validate balance  │── Sufficient funds/shares?
          │  8. AMM.apply_trade()│── Compute shares_out, fee, prices
          └───────────────────────┘
                      │
                      ▼
          ┌───────────────────────┐
          │  9. Write state:      │
          │     ├─ Update pool    │
          │     ├─ Update position│────────── Weighted avg price
          │     ├─ Create Order   │────────── status=filled
          │     ├─ Create Trade   │────────── Public trade feed
          │     ├─ Create Tx      │────────── Wallet history
          │     └─ Update market  │────────── total_volume += amount
          └───────────────────────┘
                      │
                      ▼
          ┌───────────────────────┐
          │ 10. After commit:     │
          │     ├─ Referral check │────────── First trade → reward referrer
          │     ├─ Redis pub/sub  │────────── Price update + trade event
          │     └─ Celery task    │────────── check_price_alerts.delay()
          └───────────────────────┘
```

### WebSocket Event Flow

```
Trade executes on Worker 1 (handling API request)
  │
  ├─► redis.publish("market:{id}:price", price_update_json)
  ├─► redis.publish("market:{id}:events", trade_event_json)
  │
  ▼
Redis distributes to ALL subscribed workers
  │
  ├─► Worker 1: PubSub listener → ConnectionManager → WS clients on Worker 1
  ├─► Worker 2: PubSub listener → ConnectionManager → WS clients on Worker 2
  └─► Worker 3: PubSub listener → ConnectionManager → WS clients on Worker 3
```

### Limit Order Lifecycle

```
             ┌───────────────────┐
             │ Limit Order Placed│
             │ status="pending"  │
             └────────┬──────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
        ▼             ▼             ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐
   │Celery:   │ │Celery:   │ │User      │
   │expire(30s)│ │check(ondemand)│ │cancel   │
   └─────┬────┘ └─────┬────┘ └─────┬────┘
         │            │            │
         ▼            ▼            ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐
   │Expired → │ │Fillable? │ │Cancelled │
   │Release   │ │  YES→Fill│ │Release   │
   │collateral│ │  NO→Wait │ │collateral│
   └──────────┘ └──────────┘ └──────────┘
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `change-me-in-production` | Application secret |
| `DEBUG` | `false` | Enable debug mode |
| `CORS_ORIGINS` | `*` | Comma-separated CORS origins |
| `DATABASE_URL` | `postgresql+asyncpg://...:5435/mydatabase` | Primary database |
| `DATABASE_REPLICA_URL` | (empty) | Read replica (falls back to primary) |
| `DB_POOL_SIZE` | `50` | Connection pool size |
| `DB_MAX_OVERFLOW` | `30` | Max overflow connections |
| `DB_POOL_TIMEOUT` | `30` | Pool timeout in seconds |
| `REDIS_URL` | `redis://localhost:6382/0` | Redis URL |
| `REDIS_MAX_CONNECTIONS` | `100` | Redis max connections |
| `JWT_SECRET` | `change-me-in-production` | JWT signing key |
| `JWT_ACCESS_EXPIRE` | `900` | Access token TTL (seconds, 15 min) |
| `JWT_REFRESH_EXPIRE` | `604800` | Refresh token TTL (seconds, 7 days) |
| `STRIPE_SECRET_KEY` | (empty) | Stripe API key |
| `STRIPE_WEBHOOK_SECRET` | (empty) | Stripe webhook signing secret |
| `CELERY_BROKER_URL` | `redis://localhost:6382/1` | Celery broker (Redis DB 1) |
| `RESEND_API_KEY` | (empty) | Resend email API key |
| `REFERRAL_REWARD_AMOUNT` | `1.0` | Reward for successful referral |

---

## Testing APIs with cURL

```bash
# Register a new user
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@test.com","username":"trader1","password":"password123"}'

# Login (save cookies)
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@test.com","password":"password123"}' \
  -c cookies.txt

# List markets
curl http://localhost:8000/api/v1/markets/ \
  -b cookies.txt | jq

# Get market detail
curl http://localhost:8000/api/v1/markets/btc-100k \
  -b cookies.txt | jq

# Get orderbook
curl http://localhost:8000/api/v1/markets/btc-100k/orderbook \
  -b cookies.txt | jq

# Place a market order (buy YES)
curl -X POST http://localhost:8000/api/v1/orders/ \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"market_id":"<MARKET_ID>","outcome":"yes","side":"buy","order_type":"market","amount":100,"client_order_id":"order-1"}'

# Place a limit order
curl -X POST http://localhost:8000/api/v1/orders/ \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"market_id":"<MARKET_ID>","outcome":"yes","side":"buy","order_type":"limit","amount":500,"price":0.45,"client_order_id":"limit-1"}'

# Add liquidity
curl -X POST "http://localhost:8000/api/v1/markets/<MARKET_ID>/liquidity?amount=1000" \
  -b cookies.txt

# Check wallet
curl http://localhost:8000/api/v1/wallet/ \
  -b cookies.txt | jq

# List transactions
curl http://localhost:8000/api/v1/wallet/transactions \
  -b cookies.txt | jq

# Create a price alert
curl -X POST http://localhost:8000/api/v1/alerts/ \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"market_id":"<MARKET_ID>","outcome":"yes","condition":"above","trigger_price":0.75}'

# Get referral code
curl http://localhost:8000/api/v1/referrals/code \
  -b cookies.txt

# Get referral stats
curl http://localhost:8000/api/v1/referrals/stats \
  -b cookies.txt

# Simulate a Stripe webhook (deposit $500)
curl -X POST http://localhost:8000/api/v1/webhooks/stripe \
  -H "Content-Type: application/json" \
  -d '{"type":"payment_intent.succeeded","data":{"object":{"id":"pi_test_123","amount":50000,"currency":"usd","metadata":{"user_id":"<USER_ID>"}}}}'

# Cancel a pending order
curl -X DELETE http://localhost:8000/api/v1/orders/<ORDER_ID> \
  -b cookies.txt

# Get market activity feed
curl http://localhost:8000/api/v1/markets/btc-100k/activity \
  -b cookies.txt | jq

# WebSocket connection (via wscat)
wscat -c ws://localhost:8000/ws/markets/<MARKET_ID>
```

---

## Troubleshooting

### WebSocket connections timing out

- Nginx default keepalive is 65s — WS routes use `proxy_read_timeout 7d` to handle long connections
- If using Docker, make sure `nginx` container has `nofile` limit raised (set in docker-compose.yml)

### "Connection limit exceeded" errors on WebSocket

- `ConnectionManager` enforces max 10 connections per IP, 5 per authenticated user
- Check logs: `WS rejected: too many connections from IP <ip>`

### Celery tasks not running

```bash
# Verify workers are up
uv run celery -A app.workers.celery_app inspect active

# Check scheduled tasks (beat)
uv run celery -A app.workers.celery_app inspect scheduled

# Verify beat is writing to schedule
cat celerybeat-schedule
```

### Redis connection errors

- Circuit breaker opens after 5 consecutive Redis failures — auto-recovers after 30s
- Check Redis is running: `redis-cli -p 6382 ping`

### PostgreSQL connection pool exhausted

- Symptoms: `QueuePool limit exceeded` errors
- Fix: increase `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` in `.env`
- For 50k users: pool_size=100, max_overflow=50

### Tests hanging on `pytest`

- The `conftest.py` tries to connect to PostgreSQL at collection time
- Run specific tests directly: `.venv/bin/python -c "from app.amm.engine import BinaryAMM; .."`
- Or use a test database: `DATABASE_URL=postgresql+asyncpg://... pytest tests/`

---

## Scaling to 50k Concurrent Users

### What was done

| Component | Fix | Effect |
|-----------|-----|--------|
| WebSocket manager | Per-market locks, fire-and-forget broadcasts | 50k connections don't block each other |
| WebSocket routes | IP/user connection limits (10/IP, 5/user) | Prevents FD exhaustion |
| Redis client | Shared singleton per worker (was: new client per call) | No more FD leaks |
| DB pool | 50 → 100, overflow 30 → 50 | Handles more concurrent DB ops |
| Redis pub/sub listener | Non-blocking (fire-and-forget) | Listener never stalls |
| API workers | 1 → 8 uvicorn workers (8 total) | 8× throughput |
| PostgreSQL | Tuned `max_connections=500`, shared_buffers, `effective_io_concurrency=200` | Handles 50k connections |
| Celery | 2 workers × 8 concurrency = 16 task handlers | Background job throughput |

### What you still need

| Item | When Required | How |
|------|--------------|-----|
| Redis Sentinel/Cluster | >10k WS connections per Redis instance | Add 1 replica, promote to master on failure |
| PostgreSQL read replica | >5k read-heavy queries/sec | Set `DATABASE_REPLICA_URL` in `.env` |
| CDN (Cloudflare/Fastly) | Static assets, orderbook snapshots | Point at nginx, cache at edge |
| Vertical scaling (more RAM/CPU) | Bottleneck on single box | Scale API containers horizontally first |
| Separate Celery queues | Different task SLAs | Split `check_markets_ready_to_resolve` into its own queue |

