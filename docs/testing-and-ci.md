# Testing, CI & Load Testing • What Proves What

How correctness is actually demonstrated: the test suite and what each file *proves*, the fixtures
that make it trustworthy, the CI pipeline, the load-test harness, and the honest limits.

> Written from `backend/tests/`, `backend/pytest.ini`, `.github/workflows/ci.yml`,
> `backend/scripts/{locustfile.py,audit_escrow.py,backup_db.sh}`.
>
> **Current state: 511 backend tests across 30 files, plus 118 frontend tests across
> 11 files.** See `frontend.md` §10.

---

## 1. The number that matters, and the one that doesn't

| | Count | Worth quoting? |
|---|---|---|
| Backend tests | **511** across **30** files | Yes • with the *why*, see below |
| Test files | 30 backend, 11 frontend | Yes, if asked what's covered |
| Frontend tests | **118** across **11** files | Yes • the client gap is closing, and the shape matters more than the count |

**Never quote a raw count alone.** The panel's next question is always "do they actually test the
interesting parts?" So the answer is the *shape*: 20 tests in `test_ledger.py` pin the escrow
invariant, `test_concurrency.py` fires parallel orders at one market, `test_escrow_audit.py` asserts
every invariant *and* that a healthy pool reports zero violations, and `test_task_integration.py`
drives the Celery tasks with no broker at all.

That's a defence. "511 tests" is a number.

---

## 2. The design decision that makes the suite trustworthy

```python
# tests/conftest.py:80-135
DROP DATABASE mydatabase_test WITH (FORCE)
CREATE DATABASE mydatabase_test
alembic upgrade head
```

**The test database is dropped and recreated from the Alembic migrations before every run.**

Three consequences worth stating:

1. **A stale schema can never make a failing test pass.** If a column or index is missing, the run
   fails loudly instead of silently testing against whatever was left over.
2. **The migrations are exercised by the test suite itself.** Every run proves `alembic upgrade head`
   works from empty • which is exactly what production deploys will do.
3. It is why the run takes a couple of minutes. That's the price.

The rationale is in the code: *"a stale schema must never mask a failure."*

---

## 3. Fixtures, and what each one proves (`conftest.py`, 421 lines)

| Fixture / helper | What it does | Why it matters |
|---|---|---|
| env setup (`:14-56`) | Forces `DATABASE_URL` → `mydatabase_test`, Redis → **DB 15**, `RATE_LIMIT_ENABLED=false`, `WS_ALLOW_QUERY_TOKEN=true` | Isolates tests from real config; Redis 15 so a `flushdb` can't touch dev data |
| `_bootstrap_test_database` | drop + create + `alembic upgrade head` | §2 above |
| session patching (`:140-148`) | Swaps both session makers for a `NullPool` factory, clears all four `lru_cache`d getters | Tests never share a connection pool |
| `_fresh_db` (autouse) | `TRUNCATE … CASCADE` over **19 tables** before every test | Prevents leakage between tests |
| `_reset_redis` (autouse) | Nulls the Redis client globals, resets the circuit-breaker state, `flushdb()` on DB 15 | Cached market lists have 60–300 s TTLs keyed by filter • they'd serve another test's rows |
| `client` | Overrides `get_db` with one shared session, `ASGITransport` | Fast in-process HTTP |
| `create_login_session` / `token_for` | Builds a real `RefreshToken` + `Session` pair and mints a `sid`-bound access token, exactly like `_issue_tokens` | **Tests exercise the real auth chain** |
| `admin_user` / `test_user` | User + funded wallet + session; admin has 10000, user 1000 | Money tests can actually trade |
| `test_market` | Market + Yes/No outcomes + `LiquidityPool(50/50, collateral=100, lp_token_supply=200)` | A pool with real reserves and real escrow |

Two details that show the tests are written carefully:

- **`token_for` raises if no session exists** • "a token without a `sid` claim is rejected", which no
  real login produces. So the tests can't accidentally bypass session binding.
- **`_reset_redis` calls `flushdb()`** *because* market-list caches persist across tests with 60–300 s
  TTLs. That's a real bug class caught and handled.

---

## 4. What each test file proves

| File | Tests | The claim it defends |
|---|---|---|
| `test_amm.py` | 32 | Price from reserves, price impact, **round trips return only fees**, min-shares-out and min-collateral enforced, insufficient shares rejected. Also hosts the password-strength and TOTP unit tests. |
| **`test_ledger.py`** | **20** | **The escrow invariant suite.** `credit`/`debit_collateral` refuse negatives, refuse to underpay, zero is a no-op. End-to-end: split/merge accounting, AMM buy-credits/sell-debits, LP exit funding, settlement pays everyone out of escrow, **settlement is idempotent**, refuses a stale outcome, **refuses rather than underpaying**, never mints when the pool row is missing, and `claim_winnings` debits and refuses an unfunded escrow. Imports `settle_market` directly. |
| `test_escrow_audit.py` | 12 | One test per invariant in `escrow_audit.py`, **plus "a healthy pool reports no violations"** • so the audit can't cry wolf. Includes the exactly-funded boundary and that the nightly task actually runs. |
| `test_markets.py` | 46 | CRUD, filters, sorting, pagination bounds, pending-review visibility + access control + non-tradability, admin approve/reject, resolve, claim winnings (incl. idempotent), FAQ, price history, orderbook |
| `test_trades_comments_alerts.py` | 46 | Trade feeds, comment CRUD with ownership, soft-delete, **cross-market parent injection**, nested replies and the depth limit; alerts CRUD; notification prefs; referral code; market flagging; disputes; **treasury endpoints are admin-only** |
| `test_orders.py` | 31 | Quotes, market/limit placement, insufficient balance, closed market, sell-without-holding, duplicate `client_order_id`, price/amount boundary validation (0, 1, out-of-range), and the book-match cases |
| `test_wallet.py` | 28 | Deposit via Stripe, withdrawal limits, transactions, add/remove liquidity, LP analytics, **split/merge happy path plus every failure mode**, positions |
| `test_auth.py` | 25 | Registration guards, **duplicate email not enumerable**, login variants, 2FA setup/wrong code, `/me`, sessions, logout-all (+ token actually revoked), change-password, and the **two refresh-chain tests** |
| `test_admin.py` | 21 | User listing, search, **banning an admin is forbidden**, audit-event listing, protocol-fee distribution admin-only + the empty case |
| `test_disputes.py` | 12 | Full dispute lifecycle: resolved-market-only, active rejected, admin-only proposal/adjudication, upheld/dismissed, invalid ruling |
| `test_websocket.py` | 20 | Connect/ping/pong, reconnect subscribes a different market, **market and trades feeds are public**, invalid token still rejected, notification socket rejects anonymous/wrong user/invalid token, **plus the heartbeat sweep: a hanging send is reaped with cause `heartbeat`, a responsive socket is not, and the lifespan actually schedules the loop** |
| `test_webhooks.py` | 14 | **Stripe signature verification as the primary subject**: invalid signature, missing header, **stale timestamp**, tampered payload, **unconfigured secret fails closed**, invalid JSON; plus idempotent delivery |
| `test_task_integration.py` | 14 | Runs Celery task bodies via `asyncio.to_thread(task.run)` • **no broker needed**. Sweeper fills a resting buy once the price crosses, leaves unreachable orders alone, expires and frees funds, no-ops when nothing moved, only touches marked markets, **falls back to a full scan when Redis is gone**. Also the fee sweep including the **shortfall carried forward** case. |
| `test_security_fixes.py` | 12 | Regression suite for **nine named historical breaks** (the header lists all nine): revoked-session/blacklisted-token WS rejection, `?token=` gated off, XFF ignored without a trusted proxy, **OTP plaintext never in Redis**, origin allowlist outside production, refresh has its own bucket, cookies accepted by a standard jar, dummy bcrypt hash cached, AMM buy writes a Trade row |
| `test_notifications.py` | 10 | Preferences get/update, list + pagination, mark-read, mark-all-read, 401 for each |
| `test_flags.py` | 10 | Flag a market (duplicate rejected), admin-only list and resolve, already-resolved |
| `test_websocket_multinode.py` | 9 | **The multi-node property through real Redis pub/sub**: a price on node A reaches a socket on node B; registries stay local; per-process caps enforced *and released*; counters don't leak; **a wedged socket is dropped without blocking the broadcast** |
| `test_resting_orders.py` | 6 | A resting limit order must actually be **committed** • every assertion reads from a **second session**, because the endpoint's own session can see its own uncommitted writes |
| `test_concurrency.py` | 5 | Under the fixed lock order: two users ordering at once, the **same `client_order_id` concurrently**, one user with two orders, two LPs on one pool, two admins resolving one market |
| `test_market_activity.py` | 6 | Activity feed, limit bounds, 404, empty market, resolved shape |
| `test_safety_limits.py` | 4 | LP exit can't take escrow open positions still need; split/merge move AMM reserves with the shares; **a fill immediately enqueues the limit sweep** |
| `test_referrals.py` | 4 | Referral code and stats, each with its unauthenticated counterpart |

---

## 5. Three tests that are worth demonstrating live

If a panel says *"prove it"*, these three are the most convincing per second spent.

### 5.1 `test_concurrency.py` • the money question
Fires parallel orders at one market and asserts the invariants. Builds **its own client per
request** so the handlers genuinely interleave.

> The shared `client` fixture uses one session, which *serialises* requests. This file deliberately
> avoids it • otherwise every race it exists to test would be hidden by the fixture. That decision is
> itself worth explaining.

```bash
cd backend && uv run pytest tests/test_concurrency.py -q
```

### 5.2 `test_ledger.py` • "what stops you paying a winner partially?"
Contains the test that settlement **refuses rather than underpaying**, and that it aborts the entire
payout leaving positions claimable.

```bash
cd backend && uv run pytest tests/test_ledger.py -q
```

### 5.3 `test_websocket.py -k heartbeat` • the test that guards dead code

Three tests that exist because `_cleanup_dead` shipped as dead code: the method worked, and nothing
ever called it. The third test asserts the *wiring* rather than the behaviour •
`inspect.getsource(app)` must contain `heartbeat_loop()` and `heartbeat_task.cancel()`.

**That assertion was verified by sabotage**, not by assumption: I temporarily replaced the lifespan's
`heartbeat_loop()` call with a no-op, confirmed the test failed, then restored the file and
confirmed `diff` showed no residual change. A test that has never been observed failing is not
evidence.

The other two are behavioural and deliberately paired, because a heartbeat that reaps everything is
worse than none: a hanging send must be reaped, and a responsive socket must **not** be. Both use a
stand-in socket that either never resolves or returns immediately, and both fake `disconnect` so
they assert the *decision* rather than the counter bookkeeping.

### 5.4 `test_resting_orders.py` • "tell me about a bug you found"
Resting limit orders used to **return before the commit**, so the order and its locked funds rolled
back • resting orders did not actually exist.

**Why it survived:** the API session could read its own uncommitted writes. The test's fix was to read
from a *second* session and use a **rollback as the discriminator**. Using the request session would
never have caught it.

That's a genuinely good answer to *"what was the hardest bug?"* and it's better than the AMM exploit
story, because it's about *how you find* bugs, not just that you fixed one.

---

## 6. The test-execution detail that surprises people

```python
# tests/test_task_integration.py:34-36
await asyncio.to_thread(task.run)
```

Celery task bodies are driven **directly**, with no broker. Combined with the thread-local event loop
in `tasks.celery_run`, this means the whole background layer is testable synchronously.

Consequences: no Redis-broker dependency in tests, deterministic ordering, and the sweep's Redis
dependency can be removed on demand to test the **full-scan fallback**. That's why
`test_task_integration.py` can assert behaviour that would otherwise need a broker outage to
reproduce.

**Also worth knowing:** `e2e_api_test.py` (81 KB) is a standalone script for a *live* stack and is
explicitly excluded via `pytest.ini` `addopts = --ignore=e2e_api_test.py` • its tests fail without a
running server on `localhost:8000`.

---

## 7. CI (`.github/workflows/ci.yml`)

### 7.1 Why it lives at the repository root

The header comment records the bug:

> *"These workflows used to live in `backend/.github/workflows/`, where GitHub never looked at them •
> so CI had never actually run. They now live at the repository root, which is the only place Actions
> reads from."*

**A file in the wrong directory is the same as no CI at all.** If you're asked *"how do you know your
CI runs?"*, this is the honest, specific answer.

Triggers: `pull_request`, and `push` to `main` and `dev`.

### 7.2 The three jobs

| Job | Does | Notes |
|---|---|---|
| `backend` | ruff + pytest on **Python 3.14** | Postgres 16-alpine on 5433, Redis 7-alpine on 6380, both with health checks and `options:` waits |
| `frontend` | eslint + `tsc --noEmit` | Bun 1.3.14, `--frozen-lockfile` |
| `security-scan` | Trivy filesystem + config | **`continue-on-error: true`** • reports, doesn't block |

### 7.3 Three details worth quoting

**1. `uv sync --frozen`** • *"fail if `pyproject.toml` and `uv.lock` disagree, so a dependency edit
that was never locked can't reach main."* Lockfile drift is a real failure mode and this fails loudly.

**2. `uv run pytest -q --cov=app --cov-fail-under=65`** • with the comment:

> *"`--cov-fail-under` is the measured baseline (72.5% at time of writing); **ratchet it up, never
> down.**"*

That's the right instinct and a good thing to say: the floor is a guard against regression, not a
target to be satisfied.

**3. Frontend type-check is scoped to `apps/web`:**

> *"the shared `@workspace/ui` package still has type errors in the chart internals (see
> `docs/README.md` gap list) and is not part of the gate yet."*

**A CI gate scoped around a known-broken area, with the reason written down, is far better than
either no gate or a gate everyone ignores.** That's your answer for *"how do you handle tech debt?"*.

### 7.4 The coverage gap in CI, honestly

There is **no frontend test step** • only lint and typecheck, because there are no tests to run. CI
passing on the frontend means "it compiles and lints", **not** "it works". Say that plainly rather than
leting "CI is green" imply more than it does.

Also note `security-scan` is advisory only (`continue-on-error`), so a CRITICAL Trivy finding does not
block a merge. It uploads SARIF to the Security tab, which needs GitHub Advanced Security on private
repos • hence the best-effort uploads.

---

## 8. Load testing (`scripts/locustfile.py`)

A Locust harness covering **all** API endpoints plus WebSockets.

```bash
cd backend
locust -f scripts/locustfile.py --host=http://localhost:8000

# 500 users, 60s, headless:
locust -f scripts/locustfile.py --host=http://localhost:8000 \
  --users=500 --spawn-rate=50 --run-time=60s --headless

# REST only:
locust -f scripts/locustfile.py --host=http://localhost:8000 \
  --users=500 --spawn-rate=50 --run-time=60s --headless --class-picker RestAPIUser

# WebSocket only:
locust -f scripts/locustfile.py --host=http://localhost:8000 \
  --users=1000 --spawn-rate=100 --run-time=30s --headless --class-picker WebSocketUser
```

It uses `FastHttpUser` (not the default `HttpUser`) for throughput, and shares one authenticated
test user behind a `threading.Lock` so the login cost isn't measured as endpoint latency.

**Be honest about the limits of this harness**, because a panel will probe:

- It exists and runs, but **no published results** • no committed report, no baseline, no
  before/after numbers.
- It shares one account, so it measures *throughput*, not multi-user contention.
- **Scale claims in the docs are design reasoning, not measurements**: the 50k-connection story in
  `docker-concurrency-realtime.md` §D4 rests on per-process caps (50/IP, 5/user, 50 subscriptions per
  socket) plus a bounded send with a 2 s timeout • not on a load test at that scale.

That last point is the single most important honesty item on this topic. Claiming measured scale you
haven't measured is the fastest way to lose a technical panel.

---

## 9. Operational scripts

| Script | Purpose |
|---|---|
| `scripts/audit_escrow.py` | The same invariants as the 4am Celery job, on demand, human-readable. `./audit_escrow.py`, `--market <uuid>`, `--json`. **Reports only, never repairs.** Exit codes: 0 clean, 1 violations, 2 bad usage |
| `scripts/backup_db.sh` | Timestamped custom-format `pg_dump`, verified with `pg_restore --list`, pruned only after a good dump exists |
| `scripts/locustfile.py` | Load harness (§8) |
| `scripts/seed.py` | `python -m scripts.seed` • 20 tables of demo data (§demo-script.md §1.4) |
| `scripts/postgres.conf` | Tuned Postgres config (referenced by TODO #44 pool-exhaustion work) |

`audit_escrow.py` is the best of these to show live • it's the operational face of the invariant
work, and it exits non-zero on violations, so it can be wired into a cron or a deploy gate later.
Today it isn't; that's a gap.

---

## 10. Gaps

1. **No frontend tests** • the headline. 0 files, 0 runners, 0 `test` script, 0 turbo `test` task.
2. **No published load-test baseline** • results aren't committed, so the scale story is
   design-reasoned only (§8).
3. **No alerting on the escrow audit.** Detection works and logs structured events; nothing watches.
   `audit_escrow.py` exists and exits non-zero, but nothing runs it on a schedule.
   *(Same story now applies to `ws_connections`: the gauge exists and nothing alerts on a
   saturation trend. A metric you never graph or alert on is inventory, not observability.)*
4. **`security-scan` is advisory** • a CRITICAL finding doesn't block a merge.
5. **CI doesn't gate `packages/ui` typecheck** • scoped out because of known chart-internal errors.
6. **`@workspace/ui`'s 164 chart files are effectively untested and mostly unused** • CI lints them,
   nothing exercises them (`frontend.md` §7.3).
7. **No mutation testing / property-based tests** on the AMM maths. Round-trip tests cover the
   important invariant, but the fee/impact surface is only unit-tested.
8. **The coverage floor is 65%** against a measured 72.5% • comfortable, and could be ratcheted.

---

## 11. One-paragraph summary, for reading aloud

> Correctness is demonstrated with 511 tests across 30 files, and the design decision behind them is
> that the test database is dropped and rebuilt from the Alembic migrations before every run • so a
> stale schema can never make a failing test pass, and the migrations are exercised on every run too.
> The tests authenticate through the real refresh-token and session-binding path rather than a test
> shortcut, and Redis is flushed between tests because cached market lists carry 60 to 300-second
> TTLs that would otherwise leak between them. Three files are worth calling out: the concurrency
> suite builds a separate client per request so the requests genuinely interleave; the ledger suite
> pins the escrow invariant, including that settlement refuses rather than underpaying; and the
> resting-orders suite reads from a second session, because the original bug • resting orders
> returning before their commit • was invisible from the endpoint's own session, which could see its
> own uncommitted writes. Background tasks are driven directly through the thread body with no broker,
> which is why the sweep's Redis-down full-scan fallback is testable at all. CI runs ruff and pytest
> on Python 3.14 with `--frozen` dependency installs and a coverage floor that only ratchets upward,
> plus eslint and a typecheck scoped to the app because the UI package still has known chart-internal
> errors • and it lives at the repository root because it used to sit in a directory GitHub never
> read, so it had never actually run. The honest gaps: zero frontend tests, no committed load-test
> baseline, and the escrow audit logs its findings but nothing alerts on them.
