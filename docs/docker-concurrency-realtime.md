# Docker, Concurrency Control & Realtime Architecture

> Three questions that usually come together in a viva:
> 1. What Docker concepts does this project actually use?
> 2. Two users hit "Buy" on the same market at the same instant • what happens?
> 3. How do live prices/orderbook/trades reach the screen?

---

# PART A • Docker concepts used

## A1. Repository layout

```
backend/    Dockerfile            Dockerfile.dev
            docker-compose.dev.yml  docker-compose.prod.yml
            .dockerignore  gunicorn.conf.py  deploy/nginx/
frontend/   Dockerfile            Dockerfile.dev
            docker-compose.dev.yml  docker-compose.prod.yml
            .dockerignore  deploy/nginx/
```

Two independent compose projects (`name: PredictX-backend` and the frontend stack) joined by an
**external** network so the frontend's nginx can reach the backend.

## A2. Multi-stage builds

### Backend • 2 stages (`backend/Dockerfile`)

```dockerfile
FROM python:3.13-slim AS builder      # compilers: build-essential, libpq-dev, uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project   # deps only → cached layer

FROM python:3.13-slim AS runner       # only libpq5 + curl (runtime libs)
COPY --from=builder /app/.venv /app/.venv
COPY --chown=appuser:appuser . .      # app code last (changes most often)
USER appuser                          # uid 1001, non-root
HEALTHCHECK ... curl -f .../health/ready
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app.app:app"]
```

### Frontend • 3 stages (`frontend/Dockerfile`)

| Stage | Base | Purpose |
|---|---|---|
| `deps` | `oven/bun:1.4-slim` | copies only the 6 `package.json`s + `bun.lock` + `turbo.json` → `bun install --frozen-lockfile` |
| `builder` | `oven/bun:1.4-slim` | `bunx turbo build --filter=web` with `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` build args |
| `runner` | `oven/bun:1.4-slim` | only `.next/standalone` + `.next/static` + `public`, `USER nextjs`, `CMD ["node","server.js"]` |

## A3. The concepts, and where each one appears

### Layer caching & cache invalidation
Dependencies are copied **before** source code in both Dockerfiles, so editing Python/TS doesn't
re-run `uv sync` / `bun install` • only the layer containing the changed files rebuilds. That's
why `pyproject.toml`+`uv.lock` and the six `package.json`s are copied first, in their own `RUN`.

### `.dockerignore`
Present in both `backend/` and `frontend/` • keeps `.venv`, `node_modules`, `.next`, tests, git
metadata out of the build context (smaller context, no layer pollution, no secret leakage).

### `--chown` instead of `chown -R`
`COPY --chown=appuser:appuser . .` • the comment in the Dockerfile is explicit: a separate
`chown -R` would write a *second full copy* of the tree into its own layer, roughly doubling image
size.

### Non-root users
`appuser` (uid/gid 1001) for the API, `nextjs` (uid 1001, created via `/etc/passwd` line in the
runner stage) for Next. A container escape then lands in an unprivileged account.

### `HEALTHCHECK` + `depends_on: condition: service_healthy`
This is the project's **startup ordering** mechanism • far stronger than plain `depends_on`:

- `postgres` → `pg_isready -U ...` (15s/5s/5 retries, `start_period: 20s`)
- `redis` → `redis-cli -a $REDIS_PASSWORD ping | grep -q PONG`
- `app` → `curl -f http://localhost:8000/health/ready` (30s/10s/5, `start_period: 30s`)
- `celery_worker` → `celery inspect ping`
- `nginx` → `wget -qO- http://localhost/health/ready` (waits on `app`)
- frontend `web` → `wget -qO- http://localhost:3000/`, `nginx` waits on `web`

`app` only starts once Postgres **and** Redis are healthy; nginx only after the app is healthy.
Note this only gates *initial* `up` • which is exactly why `lifespan()` **also** has its own
`_wait_for_postgres(60s)` / `_wait_for_redis(60s)` retry loop for later restarts.

### Health endpoints
`/health` (liveness, trivial) vs `/health/ready` (readiness: real `SELECT 1` + `redis.ping()`,
reports latency per dependency, returns **200 or 503**). Used by compose, Docker `HEALTHCHECK`,
nginx upstream, and the CI deploy loop.

### Read-only root filesystem + tmpfs
```yaml
read_only: true
tmpfs: - /tmp:size=64m        # web: /tmp:size=100M
```
The container can't write anywhere except `/tmp`. That's also where
`PROMETHEUS_MULTIPROC_DIR=/tmp` points • per-worker Prometheus files must be wiped on every
restart anyway, so tmpfs is ideal (no `mkdir`, always clean). `celery_beat` gets a named volume
`beatdata` for `celerybeat-schedule` because the schedule file must survive restarts.

### `security_opt: no-new-privileges:true`
Even if a process tricks `setuid`, it can't gain privileges via the kernel.

### Resource limits & reservations
Every service has `deploy.resources.limits` (cpus/memory) and `reservations`. Rough budget:
postgres 1 CPU/1G, redis 0.5/768M, nginx 1/256M, app 2/2G, celery_worker 1/1G, beat 0.5/256M.
Also protects the host from one service starving the others.

### Named volumes vs bind mounts
`pgdata`, `redisdata`, `beatdata`, `nginx-logs`, `nginx-cache` are **named volumes** • Docker
manages the path, data survives `down`, and Postgres/Redis data isn't tied to a host directory.
Config (`./deploy/nginx/conf.d`) is a **bind mount, `:ro`** • you edit nginx config without
rebuilding the image.

### Networks
```yaml
backend:  driver: bridge                       # private backend LAN
frontend: networks: [frontend, backend]        # backend declared `external: true`
```
`web` (Next.js) sits on **both** networks so it can reach the backend API directly, while
`postgres`/`redis`/`celery` are **never published to the host** • they use `expose:` only. The
single published port is nginx's `${BACKEND_PORT:-8000}:80` / `${NGINX_PORT:-80}:80`.

### `expose` vs `ports`
`app: expose: ["8000"]` documents an internal-only port; only nginx binds a host port. Network
segmentation ⇒ DB/Redis are unreachable from outside the compose project.

### Environment handling
- `env_file: .env` for app secrets
- `environment:` overrides for wiring (e.g. `DATABASE_URL=...@postgres:5432/...` using the
  compose **service name as hostname**)
- `${REDIS_PASSWORD:?POSTGRES_PASSWORD must be set in .env}` • the `:?` form **fails the build/parse
  immediately** if a required secret is missing, instead of silently starting with an empty password
- `${VAR:-default}` for optional ports

### `restart: unless-stopped`
Crash/backoff resilience • survives daemon reboots but doesn't fight a manual `stop`.

### Reverse proxy / TLS termination
Both stacks run `nginx:1.27-alpine` in front: adds security headers, terminates TLS (in real
deployment), serves `/_next/static` with `immutable` caching, and passes WebSockets through with
`proxy_http_version 1.1`, `Upgrade`/`Connection` from a `map`, `proxy_read_timeout 86400s`,
`proxy_buffering off`. Backend nginx also sets `X-Real-IP`/`X-Forwarded-For`/`X-Forwarded-Proto` •
which is *only* trusted when `TRUSTED_PROXY_IPS` is configured.

### Process model inside the container
`gunicorn.conf.py`: `workers = 8` (one event loop + one Redis pub/sub listener **each**),
`worker_class = uvicorn.workers.UvicornWorker`, `keepalive = 120`, `timeout = 120`
(**must be ≥ keepalive or gunicorn kills idle WebSocket connections** • flagged as the "M4 fix"),
`graceful_timeout = 30`, `max_requests = 10000` + `jitter = 1000` (recycles workers to bound
memory leaks), and **`preload_app = False`** • async engines and Redis pools must be created
*per worker after fork*, never before (fork-safety).

### Development vs production images
`Dockerfile.dev` + `docker-compose.dev.yml` (hot reload, `--concurrency=2`, redis with
`--appendonly yes --requirepass`) vs `docker-compose.prod.yml` (hardened, resource-limited,
healthcheck-gated).

## A4. CI with containers
`.github/workflows/` (repo root • GitHub ignores any `.github` that is not the root one):
- **`ci.yml`**, three jobs:
  - `backend` • Python 3.14, postgres:16 + redis:7 as service containers, `uv sync --frozen`,
    `ruff check app tests`, then `pytest --cov=app` with **`--cov-fail-under=65`**. The test suite
    builds its schema from `alembic upgrade head`, so a broken migration fails the build.
  - `frontend` • bun, `bun install --frozen-lockfile`, `bun run lint` (0 errors allowed) and
    `bun run typecheck` in `frontend/apps/web`.
  - `security-scan` • Trivy filesystem + config scans, SARIF uploaded **report-only**
    (`continue-on-error`), so findings are visible without blocking anything.
- There is **no `deploy.yml`** • it was removed because nothing deploys from GitHub; production
  bring-up is `docker compose -f docker-compose.prod.yml up -d`, documented in `deployment.md`.

> **Viva trap (and how it was caught):** GitHub only reads workflows from the **repo root**
> `.github/`. Both backend workflows used to sit under `backend/.github/workflows/`, so they had
> been silently never executed • the suites passed locally and CI meant nothing. Moving them was
> the fix. Two related honest gaps: the frontend still has no test runner (no vitest/jest/playwright),
> and its ESLint config *used to* install `eslint-plugin-only-warn`, demoting every error to a
> warning so `lint` could never fail • the plugin is gone now; only four heuristic `react-hooks`
> rules remain `warn` (chart packages), everything else fails the build.

---

# PART B • Concurrency: "two people buy at the same time"

The rule everywhere: **lock first, read inside the lock, decide inside the lock, write inside the
lock, commit once.** Never read → think → write on unlocked rows.

## B1. The serialization point (`OrderService.execute_order`, `order_service.py:166`)

```python
# Step 1 • Lock Market + Pool + Wallet (serialization point)
SELECT ... FROM markets       WHERE id = :m FOR UPDATE
SELECT ... FROM liquidity_pools WHERE market_id = :m FOR UPDATE
SELECT ... FROM wallets       WHERE user_id = :u FOR UPDATE
```

Three `FOR UPDATE` locks taken in a **documented global order**:

> **Market → Pool → Wallet → Position → LPShare → Order**
> (`liquidity_service.py:167` states the canonical order)

Consequences:

- Two users buying in the **same market** contend on the *market row* ⇒ their whole transactions
  serialize. Second one waits, then sees the first one's committed pool state → correct price.
- Two users in **different markets** touch different market rows ⇒ no contention at all.
- Because *every* money path acquires locks in the same global order, no cycle of waiters can
  form ⇒ **no deadlock** by construction.

**Why lock order alone isn't enough** for peer-to-peer matches: `execute_match` locks two wallets
that have no global order relative to each other (maker/taker are arbitrary), so it forces one:

```python
# matching_engine.py:84
user_ids = sorted([maker.user_id, taker_user_id], key=str)
for uid in user_ids:
    ... select(Wallet).where(Wallet.user_id == uid).with_for_update()
```
Deterministic sort ⇒ user A-then-B in every transaction ⇒ lock-order inversion impossible.

## B2. The exact race: two users buy the same market simultaneously

| t | Request A | Request B |
|---|---|---|
| 1 | `SELECT ... markets WHERE id=M FOR UPDATE` ✅ gets lock | `SELECT ... FOR UPDATE` → **blocks** |
| 2 | locks pool, wallet; reads `yes=5000/no=5000` → price 0.50; matches book; AMM fill; updates pool/wallet/position | still blocked (Postgres FIFO on the row lock) |
| 3 | `COMMIT` → locks released | acquires lock, reads **now-updated** pool → price 0.51; executes against post-A state |
| 4 | response | `COMMIT` → response |

B is not "rejected" • it is **delayed and then evaluated against fresh state**. So B can't buy at
a stale price, can't double-spend, can't see A's uncommitted row (Postgres MVCC isolation: each
transaction sees the last committed snapshot).

Key point: **the read of the balance/pool happens *inside* the lock, not before it.** If you read
first and lock later (check-then-act), you have a classic TOCTOU bug.

## B3. `FOR UPDATE` vs `FOR UPDATE SKIP LOCKED` • the deliberate split

| Purpose | Lock mode | Why |
|---|---|---|
| Market/Pool/Wallet/Position correctness | `FOR UPDATE` (blocking) | correctness requires waiting • you must see the true committed state |
| Scanning the **order book** for matches | `FOR UPDATE SKIP LOCKED` (`matching_engine.py:65`) | if another matcher already grabbed order #7, don't block • **skip it and take the next**. Throughput without correctness loss, because the other matcher *is* doing the work |
| Batch sweeps (`expire_stale_orders`, `check_limit_order_execution`, 500-row batches) | `SKIP LOCKED` | same: workers cooperate instead of queueing |

## B4. Preventing over-matching / "minting shares from thin air"

`find_matches()` may read a seller's order, and *before* `execute_match` runs another fill may
have consumed that seller's shares. So `execute_match` re-checks under lock:

```python
# matching_engine.py:114 • "Seller guard: verify cover BEFORE mutating"
seller_pos = SELECT ... FOR UPDATE
if seller_held < match_shares:
    return {"skipped": True, ...}      # caller continues to the NEXT maker
```
Comment in the code: *"races skip the match instead of corrupting supply."*
It never writes a negative position • it declines.

**Buyer guard** (same function, line 103): taker buys have no upfront balance validation, so
this is the check that prevents a negative balance:
```python
buyer_available = buyer_wallet.balance - buyer_wallet.locked_balance
if buyer_available < usdc_value:
    raise InsufficientBalanceError(...)   # fail the trade, never silently skip
```
Because both wallets are locked, this read is **deterministic** • no race between check and debit.

## B5. Locking is not the only layer • the DB enforces invariants itself

Even if application code were wrong, Postgres rejects the write:

| Constraint | Table | Meaning |
|---|---|---|
| `ck_wallets_balance_nonneg` | wallets | balance can never go below 0 |
| `ck_wallets_locked_nonneg` | wallets | locked can't go negative |
| `ck_wallets_locked_lte_balance` | wallets | `locked_balance <= balance` |
| `ck_positions_shares_held_non_negative` | positions | shares can't go negative |
| `price >= 0 AND price <= 1`, `amount > 0` | orders | sane prices (prediction shares ∈ [0,1]) |
| `Unique(user_id, market_id, outcome_id)` | positions | **one position row per user per outcome** |
| `Unique(user_id, client_order_id)` | orders | duplicate client id ⇒ constraint violation, not a second order |
| `Unique(pool_id, user_id)` | lp_shares | one LP holding per pool |
| `Unique("singleton")` + `balance >= 0` | treasury | exactly one treasury row |

Comments in the models call this "no application trust" • the last line of defence is the schema,
not the service layer.

## B6. Concurrency proof: the test suite

`backend/tests/test_concurrency.py` (5 tests) deliberately **does not** override `get_db` • it uses
one real HTTP client per request, so requests genuinely interleave at the DB:

- two users place simultaneous orders → final balances match what each response reported, and are never negative
- same `client_order_id` submitted concurrently → **exactly 1 order row**; one response `filled`, one `duplicate`
- same user, two concurrent orders → no lost update; final balance == min(reported)
- two LPs deposit simultaneously → LP token supply delta == shares delta (conservation)
- two admins resolve the same market → exactly one 200, one 400/409, `apply_async` called **once**

---

# PART C • How duplication is prevented (the "idempotency" answer)

The honest headline: **there is no single "dedup" mechanism • there are five different ones, each
chosen for where the duplicate can come from.**

## C1. Client-generated `client_order_id` → idempotent order placement

The frontend generates a uuid per logical order attempt and sends it as `client_order_id`.
`uq_orders_user_client_order` is a **UNIQUE constraint**, and the service does the check
**inside the market/pool/wallet lock** (`order_service.py:202`, comment: *"Idempotency check
(inside lock • no race)"*):

```python
existing = SELECT ... WHERE user_id=:u AND client_order_id=:c FOR UPDATE
if existing:
    return OrderResult(order_id=existing.id, status="duplicate", shares=..., price=..., ...)
```

Why **inside** the lock: two concurrent identical requests would both miss an unlocked
SELECT-then-INSERT (classic TOCTOU). Inside the lock they serialize; the second sees row #1 and
returns it instead of inserting. And even if both somehow reached INSERT, the **unique index**
would reject the second • `IntegrityError` handler → `integrity_error_handler` → 409. Belt and
braces: pre-check *and* constraint.

Effect: a **double-click, a network retry, or a browser re-POST charges the user once.**

## C2. Quotes → short-lived, user-bound, single-use pricing

`compute_quote()` stores the quote in Redis as `quote:{user_id}:{quote_id}` with `QUOTE_TTL = 5`
seconds. `execute_order` Step 3 validates, with a distinct `error_code` for each failure:
`QUOTE_UNAVAILABLE` / `QUOTE_NOT_FOUND` / `QUOTE_CORRUPTED` / `QUOTE_EXPIRED` /
**`QUOTE_FORBIDDEN`** (`quote.user_id != current user` • you can't replay someone else's quote).
So a price the user agreed to can't be silently re-executed later or by another account.

## C3. Stripe deposits → three independent layers

`payment_intent.succeeded` (`webhooks.py`) can be delivered by Stripe **more than once**, and
retries are normal:

1. **Pre-check**: `SELECT ... WHERE reference_id = :payment_intent_id AND type = 'deposit'` →
   already processed → return `already_processed` (200, so Stripe stops retrying).
2. **Row lock**: `SELECT wallets ... FOR UPDATE` • two simultaneous deliveries of the *same*
   webhook serialize; the second one's pre-check now finds the row.
3. **DB constraint**: partial unique index from migration `25165f81480b`
   ```sql
   CREATE UNIQUE INDEX uq_transactions_deposit_ref
     ON transactions (reference_id) WHERE type = 'deposit' AND reference_id IS NOT NULL;
   ```
   If the race is still lost, `commit()` raises `IntegrityError` → rollback → re-read → if the row
   exists, return `already_processed`, else 500 so **Stripe retries later**.

Plus `verify_stripe_signature()` **fails closed**: empty or bad `STRIPE_WEBHOOK_SECRET` ⇒ 401,
and `STRIPE_TOLERANCE = 300` rejects stale timestamps (replay window) and tampered payloads.

## C4. Withdrawals → idempotency key + unique index

`WalletService.withdraw(db, user, amount, idempotency_key)`:
1. pre-check `reference_id == key AND type='withdrawal'` → `IdempotencyError`
2. lock wallet `FOR UPDATE`, check `balance - locked_balance >= amount`
3. insert `Transaction(type='withdrawal', reference_id=key)` → `commit()` catches
   `IntegrityError` → rollback → `IdempotencyError("Withdrawal already processed")`

Same three-layer pattern; the partial unique index `uq_transactions_withdrawal_ref` is the
backstop that makes the race **unlosable**.

## C5. Settlement / claim → the `settled_at` flag

Double-paying winners is the worst possible bug, so it's guarded three ways in
`workers/tasks.py:717 resolve_market`:

1. **Redis lock** `resolve_lock:{market_id}` = `SET NX EX 7200` (plus `resolve_api_lock` 300 s on
   the API and `resolve_enqueue` 3600 s dedup) • only one worker even starts.
2. **Status gate**: set `status='resolving'` + `flush()` **before any write** • a second worker
   sees `resolving` and bails.
3. **Row lock + flag**: lock every `Position WHERE settled_at IS NULL FOR UPDATE`, then set
   `pos.settled_at = Decimal(str(int(timestamp)))`. A re-run finds zero rows to pay.

`POST /{slug}/claim` uses the same gate:
`SELECT ... WHERE shares_held>0 AND settled_at IS NULL FOR UPDATE` → pays → zeroes
`shares_held` → sets `settled_at`. Second claim finds nothing, pays nothing. Proven by
`test_markets.py::..._idempotent_claim`.

## C6. Position upserts → `ON CONFLICT DO UPDATE`

Four copies of the same atomic statement (`matching_engine`, `order_service`, `tasks`,
`split_merge`):
```sql
INSERT INTO positions (...) VALUES (gen_random_uuid(), :user_id, :market_id, :outcome_id, ...)
ON CONFLICT (user_id, market_id, outcome_id)
DO UPDATE SET shares_held = positions.shares_held + EXCLUDED.shares_held,
              average_price = (avg*held + EXCL.avg*EXCL.held) / (held + EXCL.held)
```
Never "SELECT position, add, UPDATE" on an unlocked row • that's exactly where a lost update
lives. The database computes the new value atomically from the current committed row.

## C7. Rate limiting / OTP / resolve → Redis `SET NX` and atomic Lua

- **`SET NX EX`** = "acquire lock or fail": `resolve_api_lock` (300 s), `resolve_enqueue`
  (3600 s), `resolve_lock` (7200 s), cache-stampede `lock:market:{id}` (30 s). `NX` makes the
  acquire atomic • two callers race, exactly one gets `OK`.
- **Lua scripts** make multi-step check-and-increment atomic so concurrent requests can't both
  slip past: the sliding-window limiter (`ZREMRANGEBYSCORE`+`ZCARD`+`ZADD` in one script), the
  OTP send/attempt counters (`INCR`+`EXPIRE`+compare in one script), progressive friction.
  Without Lua, `INCR` then `EXPIRE` is a window where a crash leaves a key with no TTL, and two
  callers can both read `count=4` and both proceed.
- **OTP single-use**: `DELETE` on success, `invalidate()` on resend → a code can't be replayed.

## C8. Frontend-side duplication prevention

- `client.ts` **GET dedup**: `pendingRequests: Map<"METHOD:path:body", Promise>` • N components
  mounting simultaneously with the same query share **one** in-flight request.
- **Single-flight refresh**: `isRefreshing` + `refreshSubscribers[]` • twenty concurrent 401s
  trigger exactly one `POST /auth/refresh`, then all retry.
- `fetchWithRetry` retries only 5xx/429 (never a non-idempotent failure blindly), honouring
  `Retry-After`.
- React Query prevents refetch storms via `staleTime` tiers and `refetchOnWindowFocus: false`.

## C9. Summary table • "how do you prevent duplication?"

| Duplicate | Source | Mechanism |
|---|---|---|
| Same order placed twice | double-click / retry / timeout-retry | `client_order_id` checked **inside** the lock + `UNIQUE(user, client_order_id)` → returns `status:"duplicate"` |
| Same order matched twice | concurrent matchers | `FOR UPDATE` (blocking) on wallet/position + `SKIP LOCKED` on book scan |
| Same Stripe deposit credited twice | webhook retry | pre-check + wallet `FOR UPDATE` + partial `UNIQUE(reference_id) WHERE type='deposit'` + `IntegrityError` recovery |
| Same withdrawal executed twice | client retry | idempotency key + wallet `FOR UPDATE` + partial `UNIQUE(reference_id) WHERE type='withdrawal'` |
| Market resolved twice | 2 admins / 2 workers | Redis `SET NX EX` locks + status gate `active→resolving→resolved` + `settled_at IS NULL FOR UPDATE` |
| Winner paid twice | re-run of the settlement task | `Position.settled_at` flag + `shares_held` zeroed under lock |
| Same position row created twice | concurrent fills | `UNIQUE(user, market, outcome)` + `INSERT ... ON CONFLICT DO UPDATE` |
| Same rate-limit/OTP attempt counted twice | concurrent requests | atomic Lua scripts (`INCR`+`EXPIRE`+compare in one eval) |
| Same market cached/limit-scanned twice | task retries | per-minute dedup in `snapshot_price_history`, `SET NX` stampede lock |
| Same GET fired N times by the UI | N components mounting | frontend `pendingRequests` promise dedup + React Query cache |

---

# PART D • Realtime architecture

## D1. The problem

The app runs **8 gunicorn workers** (each its own event loop), plus **Celery worker** and
**Celery beat** processes. A price change might be produced inside the Celery worker, while the
browser's WebSocket is held by worker #3. Processes can't share Python objects → you need a
**broker to fan messages across processes**. That broker is **Redis Pub/Sub**.

## D2. End-to-end flow of one price update

```
┌─ WRITE SIDE ──────────────────────────────────────────────────────────────┐
│  POST /orders → OrderService.execute_order()                             │
│     1. lock Market/Pool/Wallet, match, AMM fill, upsert positions        │
│     2. await db.commit()                     ← data is durable FIRST     │
│     3. AFTER commit, best-effort fan-out:                                │
│        redis_pubsub.publish_price_update(market_id, yes, no, volume)     │
│        redis_pubsub.publish_market_event(market_id, "trade:new", {...})  │
│        redis_pubsub.publish_global_trade(trade)                          │
│        build_orderbook() → cache_set_orderbook(ttl=60)                   │
│        cache_invalidate_market_lists()                                   │
│        check_price_alerts.delay(...)              ← Celery, async        │
└──────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
        ONE Redis pipeline (single round-trip, manager.py:428):
        ┌────────────────────────────────────────────────────────────┐
        │ HSET  market:{id}:price  yes/no/volume/updated_at   (cache)│
        │ EXPIRE market:{id}:price  300                             │
        │ PUBLISH market:{id}:price  {"type":"market:price_update"}  │
        │ SADD  dirty:markets {id}        (drives limit-order worker)│
        └────────────────────────────────────────────────────────────┘
                                     │
        Redis Pub/Sub is fire-and-forget fan-out to every subscriber
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
  gunicorn worker 0            worker 3                      worker 7
  RedisPubSub.listen()         listen()                      listen()
        │                            │                            │
        └─ parses channel prefix "market:{id}" ───────────────────┤
                     asyncio.create_task(                         │
                       _bounded_broadcast(                        │
                         manager.broadcast_to_market(id, data)))  │
                                  │                               │
        per-market asyncio.Lock → iterate sockets subscribed to {id}
        → per-socket send task, semaphore 200, 2s timeout
                                  │
                                  ▼
                        Browser WebSocket
```

Key structural point: **every** worker subscribes and **every** worker only forwards to *its own*
connected sockets. Worker 7 publishes; worker 3 delivers to the browser it holds. That's why
Redis is mandatory.

## D3. Channel scheme (`manager.py`)

| Redis channel | Producer | Consumer |
|---|---|---|
| `market:{id}:price` | `publish_price_update` | `market:{id}` WS sockets |
| `market:{id}:events` | `publish_market_event` (`orderbook:update`, `trade:new`, `market:resolved`, `liquidity:add`) | `market:{id}` WS sockets |
| `user:{uid}:fills` | `publish_order_fill` | that user's `/ws/notifications/{uid}` |
| `user:{uid}:notifications` | `publish_notification` | that user's socket |
| `global:trades` | `publish_global_trade` | `/ws/trades` sockets |

`listen()` dispatches purely from the channel name: `parts[0] == "market"` → market broadcast,
`"user"` → user broadcast, `global:trades` → global.

## D4. Scale design in `ConnectionManager` (the "50k concurrent" story)

From the module docstring (`manager.py:1`):

1. **Per-market `asyncio.Lock`** • `MarketLockTable._get_lock()` uses `dict.setdefault`, atomic,
   one lock per market. Broadcasting market A never blocks market B. (A single global lock would
   serialize every broadcast.)
2. **Per-socket lock** • concurrent `subscribe`/`unsubscribe` on the same socket can't corrupt
   its registry.
3. **Fire-and-forget send** • each socket send is its own `asyncio task`; **one slow/stalled
   client can't block the broadcast loop**.
4. **`_broadcast_sem = asyncio.Semaphore(200)`** • bounds concurrent broadcast tasks ("H9 fix",
   avoids OOM at 5k msg/s).
5. **`SEND_TIMEOUT_S = 2.0`** • a send that doesn't complete in 2 s marks the socket dead; cleanup
   is `asyncio.create_task(self._disconnect_many(...))` → **reaped asynchronously, never on the
   broadcast path**.
6. **Connection caps**: `MAX_CONNECTIONS_PER_IP = 50`, `MAX_CONNECTIONS_PER_USER = 5`,
   `MAX_SUBSCRIPTIONS_PER_SOCKET = 50` → prevents file-descriptor exhaustion and memory
   exhaustion from malicious clients. Close code `1008 "Connection limit exceeded"`.

   > **These caps are per *process*, so the effective ceiling is per-IP × workers • with
   > 8 gunicorn workers that is up to 400 connections from one IP, not 50.** State it that way;
   > "50 per IP" on its own is wrong and a panel reading the config will catch it. The
   > per-process choice is deliberate: a global counter needs a Redis round-trip on every
   > connect *and* disconnect, and a counter that leaks when a node dies locks users out.
   > `ws_connections` (a per-worker gauge) now makes the true fleet-wide number observable
   > rather than something you have to derive • see §D10. Making the cap genuinely global
   > would need a Redis-backed counter with a TTL so it self-heals; that's the change I'd
   > make if abuse ever became real, and it is deliberately not done on speculation.

7. **Server-side filtering** • each socket has a subscription registry; the server only sends
   what you actually subscribed to. A client can't receive another market's data.

## D5. WebSocket endpoints & auth (`websocket/routes.py`)

- `/ws/markets/{market_id}` • multiplexed: connect to one market, then send
  `{"type":"subscribe","market_id":...}` / `unsubscribe` / `ping`. **Public.**
- `/ws/trades` • global trade feed. **Public.**
- `/ws/notifications/{user_id}` • **private**: token's uid must match the path uid (IDOR guard).
- **Why the split is by data, not by convenience.** Everything on the market channel
  (`orderbook:update`, `trade:new`, `market:price_update`, `comment:*`, `split`/`merge`,
  `liquidity:*`, `order:expired`) is already served anonymously by
  `GET /markets/{slug}/orderbook`, `GET /markets/{slug}/trades`, `GET /markets/{slug}/comments`
  and `GET /trades`. Requiring a token to watch prices gated public information behind a login, and
  the client • which reconnects with backoff • turned that into a log full of identical handshake
  rejections. Private frames (`notification`, `alert:triggered`, `order:fill`) never touch a market
  channel: they ride `user:{uid}:notifications` and `user:{uid}:fills`, which only
  `/ws/notifications/{user_id}` subscribes to.
- **Optional auth, strictly validated** (`authenticate_ws_token` → `(user_id, token_presented)`).
  The cookie is host-scoped, not port-scoped, so `localhost:3000 → localhost:8000` works and the
  browser sends it unprompted. "No token" and "bad token" are deliberately different answers:
  - `(None, False)` • anonymous; allowed on the public feeds.
  - `(user_id, True)` • valid; the user connection cap applies.
  - `(None, True)` • a token **was** presented and failed ⇒ **reject**. Collapsing this into the
    anonymous case would mean a revoked or logged-out session quietly continued as anonymous, so
    revoking a session would stop meaning anything on these sockets.

  Validation is `deps.authenticate_token()` • the same chain HTTP uses: signature +
  `type == "access"` + `jti` blacklist + `user.is_active` + `sid` session binding • and any
  failure, including a database error, is reported as invalid, so auth fails closed.
- A `?token=` query param is honoured **only** when `WS_ALLOW_QUERY_TOKEN=true` (default false: a
  token in a URL lands in proxy logs, history and `Referer`). With it off, a query token is simply
  ignored • so on a public socket the caller is anonymous, and on the private one, refused.
- **What bounds an anonymous socket:** `MAX_CONNECTIONS_PER_IP = 50` (keyed on IP, always
  available), `MAX_SUBSCRIPTIONS_PER_SOCKET = 50`, and `MAX_WS_PAYLOAD_SIZE = 64 KB` per frame.
  `MAX_CONNECTIONS_PER_USER` is written `if user_id and …`, so it simply does not apply to a
  signed-out caller.

## D6. Background processes feeding realtime

**Celery beat schedule** (`celery_app.py`):

| Task | Interval | Realtime role |
|---|---|---|
| `expire-stale-orders` | 30 s | frees `locked_balance`, publishes `order:expired`, invalidates orderbook |
| `check-limit-order-execution` | 30 s | fills resting limit orders when price crosses → order-fill WS + notifications |
| `sync-amm-prices` | 60 s | writes price hashes; publishes `price_update` **only if \|Δ\| > 0.0001** (no spam) |
| `check-market-resolution` | every 5 min | `active` + `closes_at <= now` → `closed` |
| `snapshot-price-history` | 300 s | chart history (per-minute dedup so retries are safe) |
| `cleanup-expired-sessions` | daily 03:00 | purges expired refresh tokens/sessions |
| `distribute-protocol-fees` | daily 03:30 | `pool.protocol_fees` → treasury |

**The `dirty:markets` dirty-set optimisation** • this is the clever bit worth explaining:
- `publish_price_update` does `SADD dirty:markets {id}` in the same pipeline (no extra round trip).
- `check_limit_order_execution` does `SPOP dirty:markets 10000`. Empty set ⇒ *"No price moves
  since last check"* → **it does no DB work at all**.
- Non-empty ⇒ only those markets are scanned for resting limit orders, with `SKIP LOCKED`, one
  lock per market group, and per-market fault isolation (a failure rolls back only that group).
- Without it you'd run a full-table `FOR UPDATE` sweep every 30 seconds forever.

**Alert engine**: price moves → `check_price_alerts.delay()` → 4 Redis ZSETs
(`alerts:{market}:{yes|no}:{above|below}`) → claim due alerts → mark triggered → WS
`alert:triggered` + in-app notification. On exception it **rebuilds the index from Postgres**
(`reindex_market_alerts`) so a crash between `ZREM` and commit can't orphan an alert.

## D7. Frontend side of realtime

**Two sockets, deliberately:**

1. **`use-market-socket.tsx`** • a **module-level singleton**: exactly **one WebSocket per browser
   tab**, shared by `MarketSocketProvider` and every `useMarketSocket` consumer. Extra markets are
   multiplexed with `subscribe`/`unsubscribe` frames.

   **Why one socket instead of one per market • the arithmetic that decides it.** A socket per
   subscription looks reasonable until you count what the homepage actually renders:

   | On `/` | Count | Source |
   |---|---|---|
   | "Trending" carousel cards, each subscribing | 8 | `home-page-content.tsx:43,58` |
   | "Closing soon" carousel cards, each subscribing | 8 | `home-page-content.tsx:71` |
   | Live trade ticker | 1 | `live-trade-ticker.tsx` |
   | **Socket-per-market total** | **17** | |

   Three of those consequences are hard failures, not inefficiencies:

   1. **The per-IP cap is 50** (`MAX_CONNECTIONS_PER_IP`, `manager.py:90`). 17 sockets per tab
      means **three users sharing one IP exhausts the cap**, and the fourth is refused with
      `1008 Connection limit exceeded`. An office, a university, or a mobile carrier's CGNAT puts
      dozens of real users on one address • this design would break for them specifically. Multiplexed,
      each user holds **one** socket and 50 users fit comfortably.
   2. **Browsers cap concurrent connections per origin.** HTTP/1.1 allows ~6; the app is HTTP/2, but
      each WebSocket still consumes a connection, and every market card also fetches REST through
      the same origin. Per-card sockets would compete with those requests and queue them.
   3. **Cost per connection.** A socket is a kernel file descriptor, a buffer, a keepalive timer,
      and a TLS handshake on connect. 17 handshakes to show a list page is pure waste.

   The server side is *designed* for multiplexing, which is the tell that it was the intended
   shape: `MAX_SUBSCRIPTIONS_PER_SOCKET = 50` (one socket comfortably carries the homepage's 16
   market subscriptions), the registry is keyed market→sockets for O(subscribers-to-this-market)
   fan-out, and the URL is market-scoped (`/ws/markets/{id}`) so the *handshake* picks a default
   market while `subscribe` frames add the rest.

   **The mental model to say out loud:** *one socket per browser tab, many markets multiplexed
   over it.* The server is a broadcast bus per market; the socket is the client's single
   subscription to that bus. Subscription is a reference-counted entry in a `Map`, so the last
   subscriber to leave is what tears the connection down.
   - Reconnect: exponential `min(1000 * 2^retries, 30_000)`, retries reset on open.
   - **No auth gate.** The feed is public (see D5), so a logged-out visitor gets live prices just
     like they get them over REST. The `access_token` cookie rides along automatically when there
     is a session; the server uses it only for the per-user connection cap.
   - **Reconnect gives up after 8 consecutive failures** (~2 min of backoff) instead of retrying
     for the lifetime of the tab, which is what filled the API log with identical handshake
     rejections. It recovers on `online` or tab focus • a laptop resuming from sleep drops the
     socket silently and that is the only signal the browser gives.
   - On open it **re-sends `subscribe` for all server-side subs** • because Redis pub/sub has no
     replay, everything after a disconnect is re-fetched instead.
   - **Stale-message guard**: each sub has a `seq` incremented on re-subscribe; the dispatch loop
     aborts if `seq` changed mid-iteration → messages queued before a resubscribe can't be applied
     to the new subscription.
   - Handler `try/catch` per consumer → one throwing component can't kill the socket.
   - Sub registry cleanup deletes the sub **and its `subLocks` entry** (documented Map-leak fix),
     and closes the whole WS when `subs.size === 0` • **deferred by one tick**. React Strict Mode is
     on by default with the app router (Next 13.5.1+), so in dev every component unmounts and
     remounts; a registry that briefly empties would otherwise close the socket and immediately
     reopen it on every page. Anything that re-subscribes on the next tick keeps it.
   - **A superseded socket must not touch shared state.** `close()` is asynchronous, so a socket
     that has already been replaced fires `onclose` *after* its successor is live. Nulling
     `conn.ws` unconditionally made the live socket untracked, so the next `subscribe` opened a
     second one • two sockets both receiving, flapping on every subscribe/unsubscribe cycle. The
     handler therefore returns early unless `conn.ws === ws`, and the "closed on purpose" marker is
     the **socket identity**, not a shared boolean (a boolean is reset by the successor and read
     back by the predecessor's late event).
   - Status is broadcast as synthetic `{type:"__ws_status__", status}` frames.

2. **`use-user-socket.ts`** • `/ws/notifications/{userId}`, cookie-authenticated (no token in the
   URL), exponential backoff, `enabled:false` closes immediately, unmount clears the timer, and the
   same 8-attempt reconnect cap. Consumed by `notification-bell.tsx`.

**The public socket needs no session; the private one and its queries do.** Auth rides on
`HttpOnly` cookies, so a logged-out visitor's 401s are *expected*, not a fault to retry • the app
has to know the difference or it turns one page view into a storm.

Every hook that reads user-private data gates through **`useAuthGate()`** (`hooks/api/use-auth-gate.ts`)
rather than at each call site: `useWallet`, `useTransactions`, `usePositions`, `useOrders`,
`useAlerts`, `useNotifications`. The gate lives in the hook so a new component cannot reintroduce
the bug by forgetting it, and `useLoadingWithGate` keeps `isLoading` true while `/auth/me` is still
in flight so an authed page does not flash its empty state. This was not hypothetical:
`trade-form.tsx` sits on the **public** market page, so its ungated wallet fetch produced a
`No access token provided` on every anonymous page view.

`client.ts` additionally keeps a tri-state session (`unknown` / `active` / `none`) so a 401 is only
allowed to trigger `/auth/refresh` once, single-flighted • a definitive 401/403 from refresh caches
"no session" for the tab, and an inconclusive one (429/5xx/offline) only starts a 30 s cooldown.
Without it a page load produced one refresh per 401 until the endpoint's cap answered 429. The one
401 that remains by design is `GET /auth/me`: you cannot ask "who am I?" without being told
"nobody".

**How the UI consumes events** (`market-detail.tsx`):

| Message | Action |
|---|---|
| `market:price_update` | live chart/price update |
| `orderbook:update` | **`qc.setQueryData(queryKeys.orderBook(slug), payload)`** • the only `setQueryData` in the app; WS writes straight into the React Query cache |
| `trade:new` | prepend to trade feed |
| `market:resolved` | toast + invalidate `market(slug)` / `positions()` |
| `notification` (with `alert_id`) | price-alert toast; `notification-bell` also prepends locally *and* invalidates `["notifications"]` (local overlay so the badge updates before the refetch lands) |
| `comment:new/updated/deleted` | invalidate `["comments", slug]` |

**Delivery guarantee: at-most-once, no persistence.** Redis Pub/Sub discards messages with no
subscriber; nothing is replayed. That's why the design pairs WS with **query invalidation** • a
missed frame is healed by the next refetch, and `staleTime` tiers (orderbook 5 s, wallet 10 s,
markets 30 s, price history 300 s + `refetchInterval`) bound staleness even if the socket dies.

## D8. Why not just poll? Why not push from the API process?

- **Polling** (N clients × HTTP every second) puts constant load on Postgres and returns mostly
  unchanged data; `sync_amm_prices`' `> 0.0001` delta check is the same idea server-side • publish
  only real changes.
- **Pushing directly from the API process** would only reach sockets held by *that* worker • the
  other 7 workers and the Celery worker couldn't deliver their events. Redis Pub/Sub is the
  cross-process bus that makes "whoever produced the event" irrelevant to "whoever holds the
  socket".
- **Why not Redis Streams / Kafka?** Would add replay & durability, but the system explicitly
  chooses "state is in Postgres + React Query refetches" over "event log replay" • simpler, and
  correct for a UI whose source of truth is a queryable snapshot.

---

## D9. One-paragraph summary (for reading aloud)

**Docker:** both apps are multi-stage builds (backend `builder`→`runner` with `uv sync --frozen`,
frontend `deps`→`builder`→`runner` with `bun` + Turborepo + Next `standalone`), run as non-root
users on a read-only root filesystem with tmpfs, no-new-privileges, CPU/memory limits, named
volumes for state, `expose`-only internal ports with nginx as the sole published entrypoint, and
`HEALTHCHECK` + `depends_on: service_healthy` for startup ordering • backed by an in-app
`_wait_for_postgres/_wait_for_redis` loop because healthchecks only gate the initial `up`.
Gunicorn runs 8 `UvicornWorker`s with `preload_app=False` (fork safety) and
`timeout ≥ keepalive` so long-lived WebSockets survive.

**Concurrency:** correctness comes from a documented global lock order
(Market → Pool → Wallet → Position → LPShare → Order) taken with `SELECT ... FOR UPDATE` *before*
any read that informs a decision, plus deterministic wallet ordering in peer matches to rule out
deadlocks, `SKIP LOCKED` for the order-book scan so matchers cooperate instead of queueing, and
explicit re-checks under lock (buyer's available balance, seller's share cover) so a race can only
skip a match • never mint shares or go negative. Postgres CHECK and UNIQUE constraints are the
last line of defence, and `test_concurrency.py` proves it with genuinely interleaved requests.

**Duplication:** five mechanisms • `client_order_id` checked inside the lock + UNIQUE order index;
three-layer webhook idempotency (pre-check → wallet lock → partial unique index → `IntegrityError`
recovery); withdrawal idempotency keys; `SET NX EX` Redis locks + a `active→resolving→resolved`
status gate + `settled_at IS NULL FOR UPDATE` for settlement; and atomic Lua for rate/OTP counters.
Client-side, a GET-promise dedup map and single-flight token refresh stop the browser from
creating duplicates in the first place.

**Realtime:** after every commit the API fires a single Redis pipeline that writes the price
cache, **PUBLISHes** the event, and marks the market dirty. Each of the 8 workers runs its own
`RedisPubSub.listen()` task that parses the channel name and fans the message out under a
per-market lock to its own sockets • per-socket send tasks bounded by a 200-slot semaphore with a
2 s timeout and asynchronous dead-socket reaping. Browsers hold **one multiplexed WebSocket per
tab** with exponential-backoff reconnect and automatic re-subscribe (Redis Pub/Sub has no replay),
stale-message `seq` guards, and handlers that either `setQueryData` straight into the React Query
cache or invalidate queries • so delivery is at-most-once and the query cache is the durable
source of truth.

---

## D10. Keeping sockets alive, and knowing how many you have

Two things this section covers were **missing and are now fixed** • both were found by auditing
the implementation rather than by reading the design.

### The half-open socket leak

`ConnectionManager._cleanup_dead` pings sockets and disconnects the unresponsive ones. It shipped
as **dead code**: the docstring said *"kept for periodic sweeps only"* and nothing ever scheduled a
sweep. Grep found only the definition and no caller.

That matters more than dead code usually does, because the fallback detection is unreliable:

- A TCP connection can die **without a FIN reaching us** • laptop lid closed, NAT timeout, killed
  container. The socket then looks open forever.
- `send_json` to a half-open socket **succeeds**, because it only fails once the kernel buffer
  finally overflows. So "the send succeeded" is not evidence the client is alive.
- Broadcast-failure detection therefore only reaps sockets on markets that **actually trade**. A
  socket watching a quiet market leaks indefinitely • and each leak holds a file descriptor, memory,
  and a slot in that IP's connection counter, which slowly locks real users out.

The fix is a real scheduled sweep, not more callers of the old method:

```python
async def heartbeat_loop(self, interval_s: float = 30.0) -> None:
    while True:
        await asyncio.sleep(interval_s)
        await self.heartbeat_once()      # ping every local socket, reap what doesn't answer
```

started in the app lifespan and cancelled on shutdown. Three details that matter:

1. **`CancelledError` is re-raised, not swallowed.** Swallowing it would make the task immune to
   cancellation and the process would hang on shutdown.
2. **A blanket `except Exception` keeps the sweep alive.** A single unparseable socket must not kill
   the loop that reaps sockets.
3. **Pinging is a *send*, so it's bounded by `SEND_TIMEOUT_S` like everything else** • one wedged
   socket costs 2 s of one sweep pass, not the loop.

`heartbeat_once()` returns how many it reaped, so a spike is visible in the log rather than silent.

### Three bugs in the first version of the sweep

Wiring up a working-but-unused method is not the same as shipping a working sweep. The first version
had three defects, each of which the obvious tests missed:

1. **It only swept market sockets.** Notification sockets live in a separate
   `UserConnectionManager`, so `all_sockets()` • which walks `_market_subs` • never saw them. Those
   are the long-lived per-user sockets, i.e. exactly the ones most likely to be half-open after a
   laptop sleeps, so the leak persisted for precisely the case the heartbeat was added to fix.
   `heartbeat_once()` now composes both registries.
2. **It pinged sequentially.** `for ws in sockets: await wait_for(send)` at `SEND_TIMEOUT_S = 2.0`
   means fifty wedged sockets take **100 s** against a 30 s interval • sweeps pile up, and fifty
   thousand *healthy* sockets would take minutes. Both managers now ping under a bounded semaphore
   with `asyncio.gather`, matching what `_bounded_send` already did correctly for real frames.
3. **A test that passed for the wrong reason.** Calling `user_manager.heartbeat_once()` directly
   proves the *user* sweep works, but says nothing about whether the *composition* invokes it •
   delete that line and the test still passes. The regression is the dropped line, so that is what
   is now asserted.

Both fixes are pinned by tests that were each verified by **sabotage**, not assumption:

| Sabotage | Test that caught it |
|---|---|
| Notification sweep removed from the composition | `test_heartbeat_once_composes_both_registries` |
| `SEND_CONCURRENCY` forced to 1 (sequential) | `test_heartbeat_is_concurrent_not_sequential` |
| `heartbeat_loop()` call replaced with a no-op | `test_heartbeat_loop_is_started_by_the_app_lifespan` |

Plus two behavioural tests • a hanging send is reaped with cause `heartbeat`, and a responsive socket
is **not** (a reaper that reaps everything is worse than none).

> The lesson worth stating in a defence: all three bugs were found by *asking what the code does
> when it runs*, not by reading it. A method that works, is covered by tests, and is never called is
> the failure mode unit tests are worst at catching • the tests pass, and the feature is absent.

### Metrics: the realtime layer was invisible

There were exactly two Prometheus collectors, both HTTP. Nothing about WebSockets was measurable,
which made "how close to 50k connections are we?" unanswerable • the headline capacity claim had no
evidence behind it. Now:

| Metric | Type | Labels | Answers |
|---|---|---|---|
| `ws_connections` | Gauge | • | How many sockets am I holding *right now*? |
| `ws_subscriptions` | Gauge | • | Total market subscriptions held |
| `ws_connects_total` | Counter | `outcome` (`accepted`/`rejected_ip`/`rejected_user`) | Are we rejecting people, and why? |
| `ws_disconnects_total` | Counter | `cause` (`client`/`error`/`send_failed`/`heartbeat`) | Are clients or the server dropping them? |
| `ws_sends_total` | Counter | `result` (`ok`/`timeout`/`failed`) | Timeout ≠ failed: timeout means a **wedged** client (full buffer), failed means dead |
| `ws_messages_fanned_out_total` | Counter | `channel` (`market`/`user`/`global`) | Fan-out volume per channel class |

Two implementation details that are easy to get wrong:

- **The gauges are decremented only for sockets this worker actually counted.** A socket can reach
  `disconnect()` that was never counted (rejected before `accept()`, already reaped). Registration
  is captured *before* the registry is popped, because decrementing for an uncounted socket drives
  the metric **negative** • which is worse than having no metric, since a negative gauge is read as
  "we have capacity" when the opposite is true.
- **Notification sockets are counted too.** They're tracked by a separate `UserConnectionManager`,
  so wiring only the market manager would have made `ws_connections` silently under-report every
  logged-in user's socket • precisely the load you'd most want to see.

`ws_connections` is a **per-worker gauge**; fleet-wide totals are the sum across workers, which is
exactly consistent with the per-process caps in §D4.
