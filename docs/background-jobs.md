# Background Jobs, Caching, Rate Limits & Observability

The parts of the backend that run *outside* a request: Celery and its beat schedule, the escrow
audit, Redis caching, the rate limiter, the Redis client and its circuit breaker, metrics, health
checks, and the startup/shutdown sequence.

> Written from `backend/app/workers/{celery_app,tasks}.py`, `backend/app/services/{cache_service,
> rate_limit_service,escrow_audit}.py`, `backend/app/{redis,app,config}.py`,
> `backend/app/api/middleware.py`, `backend/app/middleware/{metrics,request_id}.py`.

---

## 0. The shape of the answer

Every design decision here answers one of four questions:

1. **What happens if this task runs twice?** → idempotency guard, always.
2. **What happens if Redis is down?** → per site, and *deliberately different* per site.
3. **What happens if the worker dies mid-task?** → `acks_late` + `reject_on_worker_lost`, or an
   atomic claim in Redis.
4. **How would I know it broke?** → structured JSON logs, Prometheus metrics, readiness probe.

---

## 1. Celery configuration (`app/workers/celery_app.py`)

### 1.1 The app

```python
celery_app = Celery("PredictX", broker=settings.celery_broker_url,
                    include=["app.workers.tasks"])
```
Tasks are registered via `include=`, not `autodiscover_tasks` • one module, `app.workers.tasks`.
Serializers are JSON-only (no pickle • a deserialisation attack surface you simply don't offer),
timezone UTC with `enable_utc=True`.

### 1.2 The four reliability settings that matter

| Setting | Value | Why |
|---|---|---|
| `task_acks_late` | `True` | Acknowledge **after** the task runs, not when it's received. If a worker dies mid-task, the message returns to the queue. |
| `task_reject_on_worker_lost` | `True` | Without this, Celery *acks* a task whose worker vanished, and it's lost forever. Together with `acks_late` this gives at-least-once delivery. |
| `worker_prefetch_multiplier` | `1` | Fetch one message at a time. With the default prefetch, one slow task hoards the queue and short tasks starve behind it. |
| `worker_concurrency` | `4` | *"cap to avoid overwhelming the DB; separate processes = separate connection pools."* |

**The combination that matters:** `acks_late` + `reject_on_worker_lost` = at-least-once. Which is
only safe if every task is idempotent. That's not optional politeness • it's why `settle_market` has
a `resolve_done:{market_id}` Redis marker and `snapshot_price_history` has a minute-window dedup.

There is **no result backend configured** • tasks return strings used only for logging. Nothing
polls for results, so persisting them would be pure overhead.

### 1.3 The DLX configuration is inert • and the code says so

```python
task_queues={"celery": {..., "arguments": {"x-dead-letter-exchange": "celery.dlx", ...}}},
broker_transport_options={"master_name": "rabbitmq-master", "visibility_timeout": 7200},
# Fallback: Redis broker doesn't support DLX natively • this is a no-op there,
# but docker-compose / production should use RabbitMQ with the dlx arguments above.
```

Dead-lettering and `visibility_timeout` are **RabbitMQ features**. The deployed stack
(`docker-compose.prod.yml:89,132,171`) sets `CELERY_BROKER_URL=redis://…/1`, so:
- rejected / max-retries-exceeded tasks are **not** routed to a DLQ, and
- `visibility_timeout` has no effect on the Redis transport.

**Honest answer:** *"the DLQ is configured and ready but not active, because production runs Redis
as the broker. Moving `CELERY_BROKER_URL` to RabbitMQ activates it with no code change."* That's a
better answer than either pretending it works or hiding it.

### 1.4 The beat schedule • all eight tasks

| Key | Task | Schedule | What it does |
|---|---|---|---|
| `expire-stale-orders` | `expire_stale_orders` | **30s** | cancel timed-out limit orders, free locked funds |
| `check-limit-order-execution` | `check_limit_order_execution` | **30s** | the resting-limit-order sweeper |
| `sync-amm-prices` | `sync_amm_prices` | **60s** | mirror prices to Redis, publish if moved > 1e-4 |
| `check-market-resolution` | `check_markets_ready_to_resolve` | `*/5` min | flip `active → closed` when past `closes_at` |
| `snapshot-price-history` | `snapshot_price_history` | **300s** | chart time-series rows |
| `cleanup-expired-sessions` | `cleanup_expired_sessions` | 03:00 daily | bulk-delete expired tokens/sessions |
| `distribute-protocol-fees` | `distribute_protocol_fees` | 03:30 daily | sweep `pool.protocol_fees` → system wallet |
| `audit-escrow-invariants` | `audit_escrow_invariants` | **04:00 daily** | re-verify every pool's escrow |

**Why the nightly ordering is deliberate** • the comment at `:76-78` explains it: the audit runs at
4am *"after the fee sweep"*, so the fee movement has already happened and the audit checks the
*post-sweep* state. Auditing before the sweep would check numbers that are about to change.

Also note the two 30-second tasks: sub-minute responsiveness for money, and beat's granularity is
seconds so that's achievable.

### 1.5 How async code runs inside a sync worker

Celery tasks are sync functions; the codebase is async. The bridge is a **thread-local event loop**,
created per Celery thread and reused across tasks:

```python
def celery_run(coro):   # tasks.py:44-55
    # thread-local loop, created once, reused
```
and `get_session()` (`:58-67`) calls `app.database.async_session()` • the *function*, not the
maker. Its docstring warns about exactly that trap, because `async_session_maker` is exposed
separately as the *getter*: calling the wrong one gives you a sessionmaker instead of a session.

Every task is `@bind=True` and logs `task_start` / `task_complete` with `duration_ms` around a
nested `async def _run()`.

---

## 2. The tasks that matter

### 2.1 `check_limit_order_execution` • the ~350-line sweeper (`tasks.py:153-507`)

This is the heart of the "resting limit order" story and the best concurrency answer in the project.

**Step 1 • skip markets that haven't moved.** `pop_dirty_markets()`. Empty list → early return *"No
price moves since last check"*. `None` (Redis down) → **full scan**. `sync_amm_prices` does the
`SADD dirty:markets` for free in the same Redis pipeline it already runs.

**Step 2 • lock in a fixed order.** Market → pool → wallet → order → position, all `FOR UPDATE`. Then
each candidate order is **re-locked by id** after grouping, and its status re-checked • so an order
already filled by another path is skipped. That's the anti-over-match guard: `status not in
(pending, partial) → continue`.

**Step 3 • fault isolation per market.** Orders are grouped by market and each group is wrapped in
`try/except` that does `db.rollback(); continue` (`:207-214, 461-464`). One bad market cannot abort
the whole run. A commit at each group boundary releases locks promptly.

**Step 4 • the fill.** AMM leg: rebuild `BinaryAMM` from the locked pool; fill when
`buy: current_price <= limit`, `sell: current_price >= limit`.
- Buy: check `wallet.balance - wallet.locked_balance < remaining` → **reject**, otherwise
  `balance -= remaining`, `pool.credit_collateral(remaining)`, weighted-average `average_price`,
  or `INSERT … ON CONFLICT DO UPDATE` on `positions`.
- Sell: require `pos.shares_held >= remaining`; `realized_pnl = proceeds − cost_basis`;
  `pool.debit_collateral(proceeds)` • **strict**, so a shortfall rolls the fill back.
- Both: `pool.protocol_fees += remaining × price × protocol_fee_rate`, a `Trade` row, and a
  `Transaction` with **Decimal, not float**.

**Step 5 • notify, all inside one `try/except: pass`** (`:418-455`): price publish,
`check_price_alerts.delay(...)`, `order:fill` to the user channel, in-app notification,
`position:update`. The bare `except` is right here • a failed notification must not roll back a
fill that already committed.

**Step 6 • cascade.** After a market with fills: rebuild + cache the orderbook, publish
`orderbook:update`, then `_enqueue_limit_sweep_now()` to re-arm. That helper is
`SET limit_check:enqueued1 NX EX 1` (`order_service.py:43-62`) • **collapsing a burst of fills into
at most one enqueue per second**. Without it, 50 fills in a tick would enqueue 50 sweeps.

### 2.2 `expire_stale_orders` (`tasks.py:70-150`)

Cancels `limit`/`fill_or_kill` orders with `status IN ('pending','partial') AND expires_at <= now`,
in **batches of 500** with `FOR UPDATE SKIP LOCKED`, looping until empty and committing per batch.
The rationale: one giant sweep would lock every expirable row at once.

**Only `side == 'buy'` orders move money** • `wallet.locked_balance -= remaining_amount` under
`Wallet … FOR UPDATE`, floored at 0. That's the correct behaviour: a resting buy reserved USDC;
a resting sell reserved *shares*, which were already removed from the position.

**The idempotency guard is the predicate itself**: re-running matches nothing, because the rows are
now `expired`.

Side effects after commit: `publish_market_event(…, "order:expired")` concurrently via
`asyncio.gather`, then `cache_invalidate_orderbook` per market.

### 2.3 `settle_market` (`tasks.py:732-1024`) • the money path

Module-level coroutine, not a task, *"so async tests can `await` it directly without a Celery
thread"* • and `test_ledger.py:23` does exactly that.

**Four layers of protection:**

1. **`resolve_done:{market_id}` Redis marker**, checked first (`:752`) and written **only after the
   commit** (`:1023`, TTL 30 days). The comment records the old bug: enqueue callers set
   `resolving`/`resolved` *before* the worker ran, so a status-based guard skipped every
   settlement. *The marker must be written after, not before.*
2. **Outcome-match check** • refuses if `market.winning_outcome_id != winning_outcome_id`, logging
   `settlement_outcome_mismatch`. This drops stale deliveries from the dispute flow.
3. **Seven `FOR UPDATE` locks**: market, pool, system user, system wallet, unsettled positions,
   batched wallets, LP shares with `lp_tokens > 0`.
4. **Per-position `settled_at IS NOT NULL` re-check inside the loop** (`:877-879`) • defence in
   depth against `claim_winnings`.

**The pre-flight is the important part** (`:834-873`), before any wallet is touched:
```python
winner_total = Σ shares_held where outcome == winner
required     = winner_total + pool.protocol_fees
if required > pool.collateral:
    log ERROR settlement_escrow_shortfall
    raise   # whole settlement aborted
```
> The old code paid winners one at a time, so a late shortfall meant the last winner got leftovers
> while **every** position was stamped settled • the remainder was owed to nobody and reachable by
> nobody.

Then, in order: pay winners (`debit_collateral`, `settled_at = epoch`, `realized_pnl += payout`,
`Transaction(settlement_win|settlement_loss)`) → sweep protocol fees to the system wallet → pay LPs
the residual:
```python
lp_payout_per_token = pool.collateral / pool.lp_token_supply
```
with a drift guard • if `Σ lp_tokens > lp_token_supply`, log `lp_token_supply_drift` and raise.

Finish: `status = "resolved"`, `resolved_at` set once, commit, **then** write the marker.

### 2.4 `resolve_market` (`tasks.py:1026-1091`) • the enqueue wrapper

```python
@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
```
Acquires a **Redis** lock with `SET resolve_lock:{id} nx=True ex=7200`; if not acquired, returns
*"already running"*. Released in a `finally` on **every** exit path • and the comment records why
that matters: the old code never released it, so a crash held the lock for 2 hours, every retry hit
*"already running"*, got acked, and **the market never settled**.

The code is explicit that this lock is an *optimisation*, not the correctness guarantee:
*"the real correctness guarantee is DB-side (row lock + idempotent data); this lock only collapses
duplicate work."* That's the right framing • a Redis lock with no DB backstop is a cache, not a
guarantee.

### 2.5 The rest, briefly

| Task | Behaviour |
|---|---|
| `sync_amm_prices` (60s) | `Market ⋈ Pool` where active; price = `yes/(yes+no)` else 0.5; `HSET market:{id}:price` + `EXPIRE 300`; **publishes only if the delta > 1e-4** |
| `snapshot_price_history` (300s) | active markets only; **minute-window dedup** so retries are safe; binary = real prices, multi-outcome = uniform `1/n` |
| `check_markets_ready_to_resolve` (*/5) | `active AND closes_at <= now AND winning_outcome_id IS NULL → closed`. Only closes; never resolves |
| `check_price_alerts` | claim → if empty **reindex and retry once** → mark triggered; on exception rollback + reindex + re-raise |
| `cleanup_expired_sessions` (03:00) | three bulk `DELETE`s + one commit: expired tokens, expired sessions, and revoked sessions older than 30d |
| `audit_escrow_invariants` (04:00) | `escrow_audit.audit_and_report(db)`; **`autoretry_for=(Exception,)`, `max_retries=2`** |
| `send_email` | `max_retries=3`, `delay=60`; SMTP if `smtp_host` set, else Resend |
| `send_auth_email` | `max_retries=3`, `delay=30`; then `send_email.delay(...)` • two-stage fan-out |
| `enqueue_otp` | 8-digit `secrets.randbelow(10**8).zfill(8)`; secret = `sha256(jwt_secret:email:purpose)[:32]`; stores **HMAC only**, `setex(600)` |

**`check_markets_ready_to_resolve` filters `status == "active"`** • so a market stuck in
`dispute_window` past its `closes_at` is **never auto-closed**. Worth knowing.

---

## 3. The escrow audit (`services/escrow_audit.py`)

### 3.1 Report-only, never repair

> *"A repair written by something that doesn't fully understand the drift is how a rounding bug turns
> into a loss."*

It logs and returns. And `test_escrow_audit.py` includes a **"a healthy pool reports no violations"**
test specifically so the audit can't cry wolf.

### 3.2 Three queries regardless of market count

1. `Σ Position.shares_held` grouped by `(market_id, outcome_id)`, filtered `settled_at IS NULL`.
2. `Σ LPShare.lp_tokens WHERE lp_tokens > 0` grouped by `pool_id`.
3. `SELECT LiquidityPool, Market.slug` full join • **deliberately unfiltered**. The comment explains
   why: a market nobody has traded is all LP rows and no claims, and that is exactly the case an
   earlier filtered version skipped.

**Aggregation in SQL, interpretation in Python** • that's what makes the cost independent of how
many markets exist.

### 3.3 The five invariants

| kind | condition |
|---|---|
| `pool_missing` | a market has claims but no pool row at all |
| `escrow_below_obligations` | `max(sides) + protocol_fees > collateral` |
| `fees_exceed_escrow` | `protocol_fees > collateral` |
| `lp_supply_drift` | `Σ lp_tokens rows > pool.lp_token_supply` |
| `negative_collateral` | `collateral < 0` |

**`max(sides)`, not the sum** • and this is the single most important line to understand. At
resolution only **one** side is paid $1/share, so the worst case the escrow must cover is the
**larger** open side plus fees. Summing both sides would demand escrow that was never required (and
would false-positive on every healthy market). This mirrors `settle_market`'s pre-flight exactly •
*the audit and the settlement use the same arithmetic*, which is what makes a clean audit meaningful.

`EscrowViolation.as_log()` emits `{"event": "escrow_invariant_violation", …}` • **machine-parseable
structured logging**, so you can alert on the event name rather than regex-matching prose.

---

## 4. Caching (`services/cache_service.py`)

### 4.1 Cache-aside with tag sets

Two key families: data keys `cache:<name>` and index keys `cache:ct:<tag>` (a Redis SET of member key
names). Invalidation = `SMEMBERS` the tag set, then pipeline `DEL` the members + the tag set.

| Cached | Key | TTL | Tag set |
|---|---|---|---|
| Market detail | `cache:cm:market:{id}` | 300s | `cache:ct:market:{id}` |
| Market list | `cache:ml:{filter_key}` | 60s | `cache:ct:market_lists` |
| Orderbook | `cache:cm:ob:{id}` | 60s | `cache:ct:ob:{id}` |

**Tag sets are the interesting part.** Without them, "invalidate every cached market list" means
tracking a set of keys somewhere • which is the same problem one level down. A tag set makes
invalidation O(members) with no bookkeeping elsewhere. The TTL is `ttl + 10` so the index outlives
its members (`:33, 77, 122`) • otherwise a member could outlive the index that would have invalidated
it.

Every invalidation is wrapped in `try/except: pass  # non-critical` • a failed cache delete must not
fail the trade that triggered it.

### 4.2 `build_orderbook` and the unit normalisation

```sql
SELECT outcome_id, side, price, SUM(remaining_amount) ...
WHERE status='pending' AND order_type IN ('limit','fill_or_kill')
GROUP BY outcome_id, side, price ORDER BY ... price DESC
```

Then the crucial line (`:185-190`): **bid remainders are USDC budgets, ask remainders are shares** •
so bids are **divided by their price**, making both sides quote size in shares.

That asymmetry exists because `orders.amount` is documented as "quantity of shares" but
`remaining_amount` for a **buy** holds the money still to be spent. Mixing them in one chart produces
bids that look enormous. This is the same units trap as `trading-engine.md` §1 • worth linking.

### 4.3 What is **not** here • two admissions

1. **No stampede protection.** There is no per-key `SET NX` mutex and no Lua unlock-verifying-owner.
   If a hot key expires under load, every concurrent request misses simultaneously and all recompute.
   The `ttl + 10` tag grace is the only defence. (The dedupe that *does* exist lives elsewhere:
   `_enqueue_limit_sweep_now`'s `SET … NX EX 1` and the snapshot minute-window dedup.)
2. **Placement rebuilds eagerly; invalidation is the backstop** • see the `cache_invalidate_orderbook`
   docstring (`:134-139`). The fast path is a write, not a delete-and-wait.

Also: `cache_invalidate_user` (`:203-222`) exists for user-scoped keys but **no `cache_set_user` is
defined**, so nothing populates them.

Every Redis call goes through `redis_cb.call(...)` • the circuit breaker (§6).

---

## 5. Rate limiting (`services/rate_limit_service.py`)

### 5.1 Exact sliding window, executed as Lua

A Redis **sorted set** of timestamps, trimmed and counted atomically:

```
ZREMRANGEBYSCORE key -inf (now - window)   -- drop old entries
ZCARD key                                  -- count what's left
if count >= limit then return {1, 0}       -- deny, plus retry_after
ZADD key now (now..':'..random)            -- record this hit (random member = unique)
EXPIRE key window + 1
return {0, limit - count - 1}
```

**Why Lua and not a pipeline:** trim → count → insert must be atomic. In a pipeline a concurrent
request could read the count before your insert landed, and two requests could both see
`count == limit - 1` and both be admitted. Redis executes a script atomically, so the check and the
insert are one indivisible step.

**Why a sorted set and not `INCR` + `EXPIRE`:** a fixed window lets a client send 2× the limit across
a window boundary (60 in the last second of minute 1, 60 in the first second of minute 2). A sliding
window doesn't have that edge.

The random ZSET member (`now..':'..math.random()`) matters: two requests in the same millisecond must
be two members, or the second overwrites the first and the count is wrong.

### 5.2 Progressive friction on auth

A Redis hash `{attempts, unlock_at}`. The lockout check happens **before** the increment
(`attempts >= max_attempts`), and the delay is exponential:
```python
delay = min(2 ** (attempts - max_attempts), 16)   # seconds, capped at 16
```
So attempts 1–5 pass through, then each further failure doubles the wait up to 16s. **Exponential
backoff against a specific identity** is much better against a scripted attacker than a flat 429 •
and far kinder to a human who fat-fingered their password twice.

### 5.3 The limit table

| Bucket | Limit / window | Keyed by |
|---|---|---|
| `GENERAL` | 60 / 60s | per IP |
| `AUTH_DECISION` | **5 / 60s** | per **email@IP** |
| `AUTH_FAST` | **3 / 60s** | per **email@IP** |
| `AUTH_REFRESH` | 30 / 60s | per IP |
| `STRICT` | 10 / 60s | per IP (non-GET) |

Path → bucket (`api/middleware.py:63-85`): `/auth/refresh` → `AUTH_REFRESH`; login / verify-email /
verify-magic / reset-password → `AUTH_DECISION`; any other `/api/v1/auth*` → `AUTH_FAST`;
non-GET/HEAD/OPTIONS → `STRICT`; else `GENERAL`.

**Keying auth attempts by `email@ip`** is the important one: keying by IP alone lets one attacker
lock out an entire office/NAT; keying by email alone lets one attacker DoS a specific victim. The
pair is both.

### 5.4 IPv6 normalisation • a real subtlety

`_normalize_ip` (`:135-150`) collapses an IPv6 address to its **/64 prefix**. A single subscriber
routinely gets a whole `/64`, so without this, one host could rotate through billions of addresses
and never hit its own bucket. Level of detail that shows real thought.

### 5.5 Fail-open vs fail-closed is deliberately inconsistent

| Site | On Redis error | Why |
|---|---|---|
| `check()` | **fails CLOSED** (`allowed=False, retry_after=60`) | a limiter that fails open isn't a limiter |
| `check_with_friction()` | **fails OPEN** (`allowed=True`) | don't lock every user out because Redis blipped |

Each site documents its own reasoning. The general principle: **fail closed on security decisions,
fail open on convenience**, and be explicit about which is which.

### 5.6 The dead settings

`config.py:71-72` declares `rate_limit_per_ip = 60` and `rate_limit_per_email_ip = 5` • and
**neither is referenced anywhere in the codebase.** The effective numbers are the hardcoded `_LIMITS`
dict. Changing those env vars does nothing.

That's a genuine, verifiable inconsistency. Admit it.

---

## 6. Redis client & circuit breaker (`app/redis.py`)

### 6.1 Loop-identity is what makes a module-global client safe

```python
_redis_client = None
_redis_client_loop = None

def get_redis():
    global _redis_client, _redis_client_loop
    loop = asyncio.get_running_loop()
    if _redis_client is None or _redis_client_loop is not loop:
        # create new client for this loop
```
> Recreates the client if the running event loop changed, `aclose()`ing the old one.

An async connection pool is bound to the loop that created it. With `uvicorn` workers, `pytest`, and
Celery's per-thread loops all in one process, reusing a global client across loops produces
*"Future attached to a different loop"* errors. Comparing loop identity is the fix.

There are **two** clients: `get_redis()` for async, `get_redis_sync()` for Celery/non-async, with
separate pool budgets (`redis_max_connections=100` vs `celery_worker_redis_max_connections=20`).

### 6.2 Sentinel support • implemented but not deployed

If `redis_sentinel_urls` is set, it builds a `redis.asyncio.sentinel.Sentinel` and calls
`master_for(service_name, ...)` • *"Master-for-read gives us the current primary; Sentinel manages
failover."* Otherwise plain `Redis.from_url`.

**No Sentinel service exists in either compose file.** Same for the DB replica
(`database_replica_url` is empty by default). So: *"HA and read-scaling are implemented and
configuration-gated; turning them on is an env var and a compose service, not a code change."*

`decode_responses=True` everywhere, so services receive `str` not `bytes` • which is why defensive
`.decode()` branches appear in a few places.

### 6.3 `RedisCircuitBreaker` (`redis_cb`) • the best-designed class in the codebase

States: `closed → open → half_open`. Opens after **5 consecutive failures**, recovery timeout **30s**.

Two details worth the airtime:

1. **The lock is never held across the I/O.** It takes an `asyncio.Lock` *only to inspect or mutate
   state*, releases it, then performs the operation (`:115-116`). Holding a lock during a network
   call would serialise every Redis user behind one slow call • which is exactly the problem a
   circuit breaker exists to mitigate.
2. **The exception is re-raised *after* persisting state** (`:144-146`), so a second caller in the
   same event-loop iteration already sees the breaker open. A naive implementation that records the
   failure *after* returning would let a whole burst through.

Half-open admits **exactly one probe** via `asyncio.Semaphore(1)`, released in `finally`.

Every Redis call in the codebase goes through `redis_cb.call(...)`, so a Redis outage degrades
caching, fan-out and rate limiting **without touching the trading path** • because the trading path's
source of truth is PostgreSQL.

---

## 7. Observability

### 7.1 Metrics (`app/middleware/metrics.py`)

Two Prometheus collectors, both **module-level** so names stay stable across workers:

| Metric | Type | Labels |
|---|---|---|
| `http_requests_total` | Counter | `method`, `route`, `status` |
| `http_request_duration_seconds` | Histogram | `method`, `route` |

- `/metrics` skips itself (no self-counting).
- `_route_template` reads `request.scope["route"].path` **after** `call_next`, because the router
  only populates the route downstream. **That's what keeps ids out of the label values** • labelling
  by raw path would create unbounded cardinality and blow up the metrics store.
- On an exception it counts `status="500"` and re-raises.

Multiprocess mode via `PROMETHEUS_MULTIPROC_DIR` (a tmpfs in the container), and
`clean_multiproc_dir()` on startup deletes stale worker files.

### 7.2 Structured logging

Production installs an inline `JSONFormatter` (timestamp/level/logger/message); development uses
`asctime | level | name | message`. Every request emits **one** JSON line with `request_id`,
`user_id`, `method`, `path`, `status_code`, `latency_ms`, `client_ip` (`api/middleware.py:138-159`).

Two deliberate choices:
- **Headers are never logged** • the trailing comment reads *"Scrub raw headers to prevent PII
  leakage"*. Most header dumps leak `Authorization` and `Cookie`.
- **`X-Request-ID` is validated** against `^[A-Za-z0-9\-_]{1,64}$` before being trusted
  (`middleware/request_id.py:13`). Without a charset and length cap, a caller could inject newlines
  or megabytes into your logs. The value is echoed back so a user can quote their request id in a
  support ticket.

### 7.3 The three health endpoints

| Endpoint | Checks | Use |
|---|---|---|
| `GET /health` | **nothing** • `{"status":"ok"}` | liveness: is the process alive? |
| `GET /health/ready` | Postgres `SELECT 1` + Redis `ping`, each with `latency_ms`; **200 ok / 503 degraded** | readiness: should it receive traffic? |
| `GET /metrics` | • | Prometheus; `include_in_schema=False` |

The `error` string is included **only when `app_env != "production"`** (`app.py:292-338`).

**Why liveness must not check dependencies:** if liveness fails when Postgres is down, the orchestrator
restarts every API process, and the outage gets *worse* • you lose your warm connection pools and
add restart churn to an already-broken system. Liveness asks "is this process wedged?"; readiness asks
"can it serve?"; only readiness should gate traffic.

---

## 8. Startup & shutdown (`app/app.py` lifespan, `:84-209`)

In execution order:

1. Configure logging.
2. `clean_multiproc_dir()` • delete stale Prometheus worker files.
3. Optional Sentry init with `send_default_pii=False`.
4. **Fail-fast secret check** • `RuntimeError` if `totp_encryption_key`, `jwt_secret` or
   `secret_key` still equals `"change-me-in-production"` (`:107-121`).
   *The app refuses to boot with a known-public secret.* That's a strong, quotable control.
5. **Warnings**: production + missing `TRUSTED_PROXY_IPS` → warn that all proxied traffic shares one
   rate-limit bucket; non-production → warn that token-blacklist checks **fail open** when Redis is
   unreachable.
6. `_wait_for_postgres(60s)` / `_wait_for_redis(60s)` • poll every 2s, raise `RuntimeError` on
   timeout. The rationale (`:151`): Compose `depends_on` only covers *initial* startup, not a
   dependency that dies later.
7. Schema presence check • warns if empty, otherwise logs *"migrations own the schema (no auto
   create_all)"*.
8. `redis_pubsub.connect()` + `start_listener()` • **failure is a warning, not fatal**, so the API
   still serves REST without realtime.

Shutdown: `redis_pubsub.close()`, dispose the primary engine, dispose the replica engine (`:206-209`).

**Picking which startup failures are fatal is a real design decision.** Secrets are fatal (booting
with a public secret is worse than not booting). Redis pub/sub is not (degraded realtime beats no
service). Say that reasoning out loud.

### 8.1 Middleware order • and why Starlette inverts your declaration

`add_middleware` **inserts at index 0**, so the **last one added is the outermost**. Actual execution
order:

| # | Middleware | Declared | Must come first because |
|---|---|---|---|
| 1 | `RateLimitMiddleware` | `:248` | reject oversized bodies (413) and cross-origin writes (403) **before** any DB/JWT work |
| 2 | `RequestIDMiddleware` | `:247` | set `request.state.request_id` so rate-limit identifiers, logs and metrics can cite it |
| 3 | `RequestLoggingMiddleware` | `:246` | needs `request_id` **and** `user_id`; reads the final status, so it must wrap the handlers |
| 4 | `MetricsMiddleware` | `:245` | times the request **including** the layers above • so rejected requests are still counted |
| 5 | `SecurityHeadersMiddleware` | `:244` | inside rate-limit/logging so its headers reach 413/429 responses too |
| 6 | `CORSMiddleware` | `:232` | **innermost**, so anything above can return a bare `JSONResponse` without CORS middleware mangling it |

**An ordering bug here is invisible in code review and only shows up in production.** The rule to
articulate: *correlation id first, then throttling, then logging, then metrics, then headers, with
CORS innermost.*

**And why `RateLimitMiddleware` returns `JSONResponse` instead of raising:** the catch-all
`Exception` handler belongs to `ServerErrorMiddleware`, the **outermost** layer in Starlette • outside
all user middleware. `HTTPException` and friends are served by `ExceptionMiddleware`, which sits
*inside* the whole user stack. So an exception raised from the outermost user layer would bypass the
inner exception handlers entirely and produce an un-enveloped response. Returning a ready-made
response avoids that entirely.

---

## 9. Gaps to admit

1. **DLX / dead-letter queue is configured but inert** • production runs a Redis broker (§1.3).
2. **No frontend observability** • no error reporting SDK, no client-side logging. Sentry is
   backend-only and off unless `SENTRY_DSN` is set.
3. **The escrow audit only logs.** Nothing alerts on it, nothing watches it. A violation is detected
   nightly and then... sits in a log file.
4. **`cache_service` has no stampede protection** (§4.3).
5. **`rate_limit_per_ip` / `rate_limit_per_email_ip` are dead settings** (§5.6).
6. **Sentinel and read-replica support exist but aren't deployed** (§6.2).
7. **No distributed lock on `beat`**. Run two beat instances and every periodic task fires twice. The
   *tasks* are idempotent (that's the defence), but there's no leader election • this is exactly the
   "beat distributed lock `SET NX`" item in `TODO.md`.
8. **No task-level time limits.** A wedged task holds `acks_late` until it dies.
9. **`task_track_started=True` is set but no result backend**, so task events are emitted and then
   discarded.

---

## 10. One-paragraph summary, for reading aloud

> Celery runs on Redis with eight beat tasks • two at 30 seconds for money-critical sweeps, the rest
> minute-to-daily, with the nightly fee sweep deliberately ordered *before* the 4am escrow audit so
> the audit checks post-sweep state. Reliability comes from `task_acks_late` plus
> `task_reject_on_worker_lost` for at-least-once delivery, `prefetch_multiplier=1` so one slow task
> can't starve the queue, and concurrency capped at 4 because separate processes mean separate database
> pools. Because delivery is at-least-once, every task carries an idempotency guard • a Redis
> `resolve_done` marker, a minute-window dedup, or a status predicate that matches nothing on re-run •
> and settlement is additionally protected by a seven-lock `FOR UPDATE` sequence and an escrow
> pre-flight that aborts the *whole* payout rather than paying one winner partially. The limit sweeper
> is the best example: it skips markets that haven't moved (a Redis dirty set that returns `None` on
> error, which triggers a full scan instead of a silent skip), locks in a fixed
> market→pool→wallet→order→position order, re-locks and re-checks each order to prevent
> over-matching, isolates each market in its own try/except, and collapses a burst of fills into one
> re-arm per second with `SET NX EX 1`. Rate limiting is an exact sliding window in a sorted set
> executed as Lua so trim-count-insert is atomic, keyed `email@IP` on auth endpoints so one attacker
> can't lock out a whole office, with exponential friction and IPv6 collapsed to /64 so a subscriber
> can't fragment its own bucket. Fail-open versus fail-closed is inconsistent **on purpose** and
> documented per site • closed for the limiter, open for auth friction. Redis access goes through a
> circuit breaker that never holds its lock across I/O and records failure state before re-raising.
> And the honest gaps are that the dead-letter queue is configured but inert on a Redis broker,
> there's no beat leader election, no stampede protection on the cache, and the escrow audit only
> logs • nothing alerts on it.