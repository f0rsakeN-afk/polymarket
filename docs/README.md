# Docs

Everything you need to explain, defend or work on this project lives in **this folder** — nothing
project-specific is kept anywhere else in the repo (repo-level files like `README.md`,
`AGENTS.md` and `TODO.md` are entry points / working files, not documentation).

Written from the code — if the code and these documents disagree, one of them needs fixing, and it
is usually the document.

## The documents

| Doc | What's in it | Read it when |
|---|---|---|
| [`concepts.md`](concepts.md) | **Plain English, zero jargon.** Order book, liquidity jar, how prices start, buy/sell, split/merge, settlement, disputes, and why this isn't 1xBet | You're new, or you need to explain the product to a non-engineer |
| [`data-model.md`](data-model.md) | **All 24 tables**, column by column: entities, constraints, indexes, `Numeric` scales, what the **database** enforces vs what only the application does, and a **verified drift** between the models and the migrations | Asked "where is X stored?", "what does your schema look like?", "what does Postgres actually guarantee?" |
| [`trading-engine.md`](trading-engine.md) | Order routing (book → AMM), matching rules, AMM maths and the no-arbitrage fix, split/merge, settlement, honest accounting limitations, and **why this isn't 1xBet** | The core technical questions come up |
| [`platform-features.md`](platform-features.md) | Everything that isn't trading: threaded comments, price alerts (and the exactly-once Lua claim), notifications + preferences, referrals, market flags, the **48h dispute process**, moderation, the treasury and the real fee flow, activity feed, trade tape, positions, audit trail, and the shared error contract | Asked about moderation, trust, governance, or "what else does the app do?" |
| [`auth-and-security.md`](auth-and-security.md) | Auth model (JWT + session binding, refresh rotation, 2FA, OTP, rate limits), audit trail, SQLi / XSS / CSRF reasoning, token revocation, and the status of every known gap | The security questions come up |
| [`docker-concurrency-realtime.md`](docker-concurrency-realtime.md) | **A** Docker concepts in use · **B** concurrency ("two users buy at once") · **C** duplication prevention · **D** realtime architecture (Redis pub/sub fan-out) | The "how does it stay correct?" questions come up |
| [`background-jobs.md`](background-jobs.md) | Celery config + the **8-task beat schedule**, the idempotency guard on every task, the **nightly escrow audit**, cache-aside with tag sets, the rate limiter (sliding window in Lua, progressive friction), Redis Sentinel + circuit breaker, Prometheus metrics, health probes, and the **middleware ordering** | Asked "what runs in the background?", "how do you know it works?", "how do you monitor it?" |
| [`frontend.md`](frontend.md) | Next.js 16 / React 19 / Turborepo / Bun: routing and route groups, server vs client components, the three-layer data client, React Query tuning, the **WebSocket singleton**, cookie-only auth, the chart system, bundle splitting, and an honest list of dead code and content bugs | Asked anything about the client |
| [`architecture.md`](architecture.md) | System shape, request/response envelope, endpoint groups, order flows, Celery and WebSocket overview, Stripe, Decimal rules | You need the 5-minute map |
| [`testing-and-ci.md`](testing-and-ci.md) | **384 tests and what each file proves**, the fixtures that make them trustworthy, the 3 tests worth demoing live, the CI pipeline and its coverage gaps, the Locust harness, and the honest limits | Asked "how do you know it works?", or you're running the demo |
| [`deployment.md`](deployment.md) | Production checklist: env vars, Alembic migration strategy, compose stack, health checks, Redis Sentinel, trusted proxies, beat schedule, log shipping | You're deploying or operating it |
| [`demo-script.md`](demo-script.md) | **The runbook for the live demo** — start-up order, a 7-phase demo script with what to say, live-code targets, what to do when it breaks, and the final checklist | The day of the defence |
| [`viva-questions.md`](viva-questions.md) | **319 questions across A–R, each with a full spoken-word answer** a non-programmer can deliver, plus a glossary and a numbers cheat sheet | Rehearsing — this is the drill sheet |

### Suggested reading order for a viva

**Stage 1 — get the story straight**
1. `concepts.md` — explain the product in plain English before any code.

**Stage 2 — know where things live**
2. `architecture.md` — the shape of the system.
3. `data-model.md` §3–§5 — the schema and what's actually enforced.

**Stage 3 — the questions that separate a project from a system**
4. `docker-concurrency-realtime.md` §B + §C — *"two users buy at once"* and *"how do you stop
   duplicates"*. These two carry the most marks.
5. `trading-engine.md` §2 (how an order actually executes) and §7 (why it isn't gambling).
6. `background-jobs.md` §1–§3 — what runs in the background and how you know it worked.

**Stage 4 — breadth, so nothing can catch you out**
7. `platform-features.md` — moderation, disputes, fees, errors.
8. `frontend.md` §10–§11 — the gaps and the dead code. Naming them first is the whole game.
9. `auth-and-security.md` §7–§9 (SQLi/XSS/CSRF) and §12 (gap status).

**Stage 5 — prove it, then rehearse**
9. `testing-and-ci.md` §4–§5 — what each test file proves, and the **three worth running live**.
10. `demo-script.md` — the 7-phase demo, and its §4 for what to do when it breaks.
11. `viva-questions.md` §A–§C (shape), then §O–§R, §M (reflective) and §N (curveballs), then the
    cheat sheet. Answer **out loud** — a spoken answer is the thing being assessed.

### The questions that actually decide it

If you only prepare three answers, prepare these. They are the questions that separate "I built
something" from "I understand what I built".

1. **"Two people buy the same market at the same instant — what actually stops you creating money
   from nothing?"** → `docker-concurrency-realtime.md` §B. The one-serialisation-point design, the
   fixed lock order, `FOR UPDATE` vs `SKIP LOCKED`, and the seller-cover check.
2. **"What does your database *guarantee*, and what does your code guarantee?"** →
   `data-model.md` §5. The honest split — including the five CHECK constraints that exist in the
   models but **not** in the provisioned schema.
3. **"What happens when a background job runs twice?"** → `background-jobs.md` §1.4 + §2.1.
   At-least-once delivery, and therefore an idempotency guard on every single task.

### Known gaps we admit rather than hide

Naming what was wrong *and* how it was closed is the answer that scores. Closed: the single-entry
escrow ledger, LPs exposed to the outcome, decorative `pool.collateral`, protocol fee recorded
rather than escrowed (`trading-engine.md` §6); register-form email enumeration, the uncapped refresh
chain, the `?token=` WebSocket handshake, CI moved to the repository root
(`auth-and-security.md` §12).

**Still open — say these before you're asked:**

| Gap | Where |
|---|---|
| **No frontend test suite at all** (0 files, 0 runners, 0 `test` script) | `frontend.md` §10 |
| 5 CHECK constraints in the models but absent from the migrations | `data-model.md` §8.2 |
| 3 of 15+ "enums" are unconstrained strings — there are **no** database enums at all | `data-model.md` §1.3 |
| The escrow audit **only logs** — nothing alerts on it, nothing watches it | `background-jobs.md` §9 |
| Dead-letter queue configured but **inert** (Redis broker, DLX is a RabbitMQ feature) | `background-jobs.md` §1.3 |
| No **beat leader election** — two beat instances fire every task twice | `background-jobs.md` §9 |
| No **cache stampede protection** | `background-jobs.md` §4.3 |
| `rate_limit_per_ip` / `rate_limit_per_email_ip` are **dead settings** | `background-jobs.md` §5.6 |
| Redis Sentinel and DB read-replica support exist but **aren't deployed** | `background-jobs.md` §6.2 |
| **No admin audit trail** beyond ban/unban, and the actor is in JSON the API doesn't return | `platform-features.md` §13.4 |
| **No kill switch / global pause** anywhere in the API | `platform-features.md` §7.2 |
| `treasury` is disconnected from the real fee flow (which runs through the `is_system` wallet) | `platform-features.md` §8.6 |
| Multi-outcome price history is **synthetic and flat** (`1/len(outcomes)`) | `platform-features.md` §9.4 |
| Multi-outcome **position PnL is incorrect** (prices every non-YES as `1 − yes`) | `platform-features.md` §11 |
| Server-component fetch **doesn't forward cookies**, so the homepage SSR is anonymous | `frontend.md` §3.2 |
| Market detail page **server-renders no data**; per-market SEO metadata absent | `frontend.md` §3.2 |
| **160 of 164 chart files unused**; leftover `predictx.io` branding; FAQ describes a wallet-connect product this isn't | `frontend.md` §11 |
| Thin AMM (one pool per market) | `trading-engine.md` §6 "Still true" |

### Related tests

Backend: **22 files, 384 test functions**, in `backend/tests/`. Run with:

```bash
docker start pm-postgres pm-redis     # test infra (ports 5433 / 6380)
cd backend && .venv/bin/pytest -q
```

The DB is **dropped and rebuilt from migrations on every run** (`conftest.py:80-135`) — a stale schema
must never mask a failure.

| Test file | What it proves |
|---|---|
| `test_amm.py` | AMM pricing, price impact, round-trips returning only fees, min-shares-out enforcement |
| `test_ledger.py` | The escrow invariant suite: split/merge accounting, settlement pays everyone, settlement is idempotent, and it **refuses rather than underpaying** |
| `test_escrow_audit.py` | Every invariant in `escrow_audit.py`, plus "a healthy pool reports no violations" |
| `test_concurrency.py` | Two users ordering at once, same `client_order_id` concurrently, two LPs on one pool, two admins resolving one market |
| `test_orders.py` | Order units, book matching, protocol-fee crediting, price/amount boundaries |
| `test_resting_orders.py` | A resting limit order is actually **committed** — the branch that rolled it back |
| `test_auth.py` | Including the refresh-chain cap and the non-enumerable register form |
| `test_security_fixes.py` | Nine named historical breaks: WS auth, XFF, OTP storage, Origin allowlist, trade rows |
| `test_websocket.py` / `test_websocket_multinode.py` | Realtime, and cross-node fan-out through real Redis pub/sub |
| `test_task_integration.py` | The Celery tasks driven directly, no broker — including the Redis-down full-scan fallback |
| `test_disputes.py` / `test_admin.py` / `test_flags.py` / `test_notifications.py` | The platform subsystems |
| `test_market_activity.py` / `test_referrals.py` / `test_wallet.py` / `test_webhooks.py` / `test_trades_comments_alerts.py` | Read models, payments, activity feed |

**Frontend: zero tests.** See `frontend.md` §10 — say it yourself.