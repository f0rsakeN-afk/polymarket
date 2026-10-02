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

Listed in `trading-engine.md` §6 and `auth-and-security.md` §12: single-entry ledger, AMM-leg
protocol fee recorded rather than escrowed, register-form email enumeration, no absolute cap on the
refresh chain, CI workflow sitting in `backend/.github/` where GitHub won't run it, and no frontend
tests. Each has a fix sketch.

### Related tests

Behaviour described here is pinned by `backend/tests/`: `test_amm.py` (pricing + no-arbitrage),
`test_security_fixes.py` (websocket auth, XFF, OTP storage, Origin allowlist, trade rows),
`test_concurrency.py` (parallel orders), `test_websocket.py` (realtime), `test_orders.py`
(order units, book matching, protocol-fee crediting).

Run them with:

```bash
docker start pm-postgres pm-redis     # test infra (ports 5433 / 6380)
cd backend && .venv/bin/pytest -q
```
