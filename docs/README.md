# Docs

Everything you need to explain, defend or work on this project lives in **this folder** — nothing
project-specific is kept anywhere else in the repo (repo-level files like `README.md`,
`AGENTS.md` and `TODO.md` are entry points / working files, not documentation).

Written from the code — if the code and these documents disagree, one of them needs fixing, and it
is usually the document.

| Doc | What's in it | Read it when |
|---|---|---|
| [`concepts.md`](concepts.md) | **Plain English, zero jargon.** Order book, liquidity jar, how prices start, buy/sell, split/merge, settlement, disputes, and why this isn't 1xBet | You're new, or you need to explain the product to a non-engineer |
| [`architecture.md`](architecture.md) | System shape, database models, endpoints, AMM engine, order types, auth, Celery, websockets, Stripe, idempotency, Redis usage | You need to point at a file for "where is that implemented?" |
| [`auth-and-security.md`](auth-and-security.md) | Auth model (JWT + session binding, refresh rotation, 2FA, OTP, rate limits), audit trail, SQLi / XSS / CSRF reasoning, token revocation, and the status of every known gap | The security questions come up |
| [`docker-concurrency-realtime.md`](docker-concurrency-realtime.md) | **A** Docker concepts in use · **B** concurrency ("two users buy at once") · **C** duplication prevention · **D** realtime architecture (Redis pub/sub fan-out) | The "how does it stay correct?" questions come up |
| [`trading-engine.md`](trading-engine.md) | Order routing (book → AMM), matching rules, AMM maths and the no-arbitrage fix, split/merge, settlement, honest accounting limitations, and **why this isn't 1xBet** | The core technical questions come up |
| [`deployment.md`](deployment.md) | Production checklist: env vars, Alembic migration strategy, compose stack, health checks, Redis Sentinel, trusted proxies, beat schedule, log shipping (was `backend/MIGRATION.md`) | You're deploying or operating it |
| [`viva-questions.md`](viva-questions.md) | **227 questions across A–N, each with a full spoken-word answer** a non-programmer can deliver, plus a glossary and a numbers cheat sheet | Rehearsing — this is the drill sheet |

### Read in this order for a viva

1. `concepts.md` — get the story straight in your own words first.
2. `viva-questions.md` §A–§C (shape of the system) → answer out loud, then uncover.
3. `docker-concurrency-realtime.md` §B + §C — the two questions that separate a project from a
   system ("two users at once" and "how do you stop duplicates").
4. `trading-engine.md` §2 (how an order actually executes) and §7 (why it isn't gambling).
5. `auth-and-security.md` §7–§9 (SQLi/XSS/CSRF) and §12 (gap status — name the remaining ones
   before you're asked).
6. `viva-questions.md` §M + §N — the reflective and curveball answers, plus the cheat sheet.

### Known gaps we admit rather than hide

Six of the gaps we listed have since been closed — the details of *how* live in
`trading-engine.md` §6 (single-entry ledger, LPs exposed to the outcome, decorative
`pool.collateral`, protocol fee recorded rather than escrowed) and `auth-and-security.md` §12
(register-form email enumeration, uncapped refresh chain, `?token=` WebSocket handshake,
CI workflow parked in `backend/.github/` where GitHub never runs it). Naming what was wrong *and*
how it was closed is the answer that scores.

Still open, deliberately: **no frontend test suite** (needs network access to install a test
runner in CI — D1), plus the honest limits in `trading-engine.md` §6 "Still true" (thin AMM) and
the fact that the nightly invariant audit only *logs* its findings — nothing watches them yet.

### Related tests

Behaviour described here is pinned by `backend/tests/`: `test_amm.py` (pricing + no-arbitrage),
`test_security_fixes.py` (websocket auth, XFF, OTP storage, Origin allowlist, trade rows),
`test_concurrency.py` (parallel orders), `test_websocket.py` (realtime), `test_orders.py`
(order units, book matching, protocol-fee crediting), `test_ledger.py` (escrow in/out, settlement
payout table, claim shortfalls, and the refusal to settle an underfunded market rather than pay a
winner partially), `test_safety_limits.py` (LP-exit escrow floor, split/merge reserve sync,
immediate limit-order sweep), `test_resting_orders.py` (a resting limit order must be
committed, locked, cancellable — the branch that rolled it back), `test_task_integration.py`
(the Celery tasks driven directly, no broker), `test_websocket_multinode.py` (cross-node
fan-out), `test_escrow_audit.py` (every pool invariant, plus the beat task
itself so the 4am job can't silently stop working), `test_auth.py` (including the refresh-chain cap and the
non-enumerable register form).

Run them with:

```bash
docker start pm-postgres pm-redis     # test infra (ports 5433 / 6380)
cd backend && .venv/bin/pytest -q
```
